from __future__ import annotations

import io
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import List

import cv2
import numpy as np
import pytesseract
try:
    import easyocr
except Exception:  # pragma: no cover - optional dependency
    easyocr = None
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pytesseract import Output

APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(APP_ROOT / "data")))
DB_PATH = Path(os.getenv("DATABASE_PATH", str(APP_ROOT / "results.db")))
PRODUCTS_PATH = DATA_DIR / "products.txt"
FRONTEND_DIR = APP_ROOT.parent / "frontend"

app = FastAPI(title="Mobile OCR Admin")
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ocr_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                lines_json TEXT NOT NULL,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                label_text TEXT NOT NULL DEFAULT ''
            )
            """
        )
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(ocr_results)").fetchall()
        }
        if "warnings_json" not in columns:
            conn.execute(
                "ALTER TABLE ocr_results ADD COLUMN warnings_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "label_text" not in columns:
            conn.execute(
                "ALTER TABLE ocr_results ADD COLUMN label_text TEXT NOT NULL DEFAULT ''"
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                code TEXT,
                origin TEXT,
                um TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                lot TEXT,
                production_text TEXT,
                expiration_text TEXT,
                humidity REAL,
                broken_grains REAL,
                chalky_1 REAL,
                chalky_2 REAL,
                damaged_grains REAL,
                whiteness REAL,
                created_at TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(products)").fetchall()}
        if "origin" not in columns:
            conn.execute("ALTER TABLE products ADD COLUMN origin TEXT")
        if "um" not in columns:
            conn.execute("ALTER TABLE products ADD COLUMN um TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ruc TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trasiegos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT,
                mp TEXT,
                f_ingreso TEXT,
                estado TEXT,
                lote TEXT,
                f_p TEXT,
                f_v TEXT,
                cantidad TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS constancias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT,
                issue_date TEXT,
                client_name TEXT,
                transport_plate TEXT,
                fumigacion INTEGER NOT NULL DEFAULT 1,
                calidad INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL,
                items_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(constancias)").fetchall()}
        if "fumigacion" not in columns:
            conn.execute("ALTER TABLE constancias ADD COLUMN fumigacion INTEGER NOT NULL DEFAULT 1")
        if "calidad" not in columns:
            conn.execute("ALTER TABLE constancias ADD COLUMN calidad INTEGER NOT NULL DEFAULT 1")
        conn.commit()


def load_product_catalog() -> List[str]:
    if not PRODUCTS_PATH.exists():
        return []
    lines = []
    for raw in PRODUCTS_PATH.read_text(encoding="utf-8").splitlines():
        item = raw.strip()
        if not item or item.startswith("#"):
            continue
        lines.append(item.upper())
    return lines


def _resolve_tesseract_cmd() -> str | None:
    env_cmd = (os.getenv("TESSERACT_CMD") or "").strip()
    if env_cmd and os.path.isfile(env_cmd):
        return env_cmd
    win_default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    win_user = os.path.expandvars(
        r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"
    )
    for candidate in (win_default, win_user):
        if candidate and os.path.isfile(candidate):
            return candidate
    return shutil.which("tesseract")


resolved_cmd = _resolve_tesseract_cmd()
if resolved_cmd:
    pytesseract.pytesseract.tesseract_cmd = resolved_cmd
    tessdata_dir = os.path.join(os.path.dirname(resolved_cmd), "tessdata")
    if os.path.isdir(tessdata_dir):
        os.environ.setdefault("TESSDATA_PREFIX", tessdata_dir)

PRODUCT_CATALOG = load_product_catalog()
EASYOCR_READER = None


def order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def warp_perspective(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    rect = order_points(pts)
    (tl, tr, br, bl) = rect
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    max_width = int(max(width_a, width_b))
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_height = int(max(height_a, height_b))
    dst = np.array(
        [[0, 0], [max_width - 1, 0], [max_width - 1, max_height - 1], [0, max_height - 1]],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, matrix, (max_width, max_height))


def detect_document(image: np.ndarray) -> np.ndarray | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 75, 200)
    contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
    image_area = image.shape[0] * image.shape[1]
    for contour in contours:
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) == 4:
            area = cv2.contourArea(contour)
            if area < image_area * 0.6:
                continue
            return approx.reshape(4, 2)
    return None


def preprocess_image(
    image_bytes: bytes,
) -> tuple[np.ndarray, list[str], np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

    warnings = []
    height, width = img.shape[:2]
    if min(height, width) < 1600:
        warnings.append("Resolucion baja: intenta mas cerca o mayor calidad.")
        scale = 2.0
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        height, width = img.shape[:2]
    if min(height, width) < 2400:
        scale = 1.5
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    focus_measure = cv2.Laplacian(gray, cv2.CV_64F).var()
    if focus_measure < 80:
        warnings.append("Imagen borrosa: toma la foto mas estable.")

    doc_pts = detect_document(img)
    if doc_pts is not None:
        img = warp_perspective(img, doc_pts)
    else:
        warnings.append("No se detecto el borde del documento.")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    gray_base = gray.copy()

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    sharpen = cv2.addWeighted(gray, 1.6, cv2.GaussianBlur(gray, (0, 0), 3), -0.6, 0)
    enhanced = cv2.normalize(sharpen, None, 0, 255, cv2.NORM_MINMAX)

    thresh = cv2.adaptiveThreshold(
        enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )
    _, otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    coords = np.column_stack(np.where(thresh < 255))
    if len(coords) > 0:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        if abs(angle) <= 15:
            (h, w) = thresh.shape[:2]
            center = (w // 2, h // 2)
            matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            thresh = cv2.warpAffine(
                thresh, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
            )

    # Limpia líneas horizontales para mejorar el OCR global
    inv = 255 - thresh
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (80, 1))
    horiz_lines = cv2.morphologyEx(inv, cv2.MORPH_OPEN, horiz_kernel)
    text_only = cv2.subtract(inv, horiz_lines)
    clean_text = 255 - text_only
    clean_text = cv2.morphologyEx(clean_text, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))

    return thresh, warnings, gray_base, otsu, enhanced, clean_text, img


def normalize_line(line: str) -> str:
    text = line.upper()
    text = re.sub(r"[|]", "I", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\bX\s*(\d)", r"X \1", text)
    text = re.sub(r"(\d)\s*KG\b", r"\1 KG", text)
    return text


def catalog_best(line: str) -> tuple[str, float]:
    if not PRODUCT_CATALOG:
        return line, 0.0
    best = line
    best_score = 0.0
    for item in PRODUCT_CATALOG:
        score = SequenceMatcher(a=line, b=item).ratio()
        if score > best_score:
            best_score = score
            best = item
    return best, best_score


def best_catalog_match(line: str) -> str:
    best, score = catalog_best(line)
    if score >= 0.86:
        return best
    return line


def deduplicate_lines(lines: List[str]) -> List[str]:
    seen = set()
    unique: List[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        unique.append(line)
    return unique


def add_to_catalog(lines: List[str]) -> None:
    if not lines:
        return
    normalized = [normalize_line(line) for line in lines if line.strip()]
    if not normalized:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = set(load_product_catalog())
    additions = [line for line in normalized if line not in existing]
    if not additions:
        return
    with PRODUCTS_PATH.open("a", encoding="utf-8") as handle:
        for line in additions:
            handle.write(f"{line}\n")
    existing.update(additions)
    global PRODUCT_CATALOG
    PRODUCT_CATALOG = list(existing)


def extract_lines(image: np.ndarray, lang: str, psm: str) -> List[str]:
    whitelist = "ABCDEFGHIJKLMNOPQRSTUVWXYZÑ0123456789XKG"
    config = (
        f"--oem 1 --psm {psm} -c preserve_interword_spaces=1 "
        f"-c tessedit_char_whitelist={whitelist} "
        "-c load_system_dawg=0 -c load_freq_dawg=0"
    )
    data = pytesseract.image_to_data(image, output_type=Output.DICT, lang=lang, config=config)

    line_map = {}
    for i, text in enumerate(data.get("text", [])):
        word = (text or "").strip()
        if not word:
            continue
        try:
            conf = int(float(data.get("conf", ["-1"])[i]))
        except (ValueError, TypeError, IndexError):
            conf = -1
        if conf >= 0 and conf < 40:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        line_map.setdefault(key, []).append(word)

    lines = []
    for key in sorted(line_map.keys()):
        line = " ".join(line_map[key])
        line = normalize_line(line)
        line = best_catalog_match(line)
        if line:
            lines.append(line)
    return lines


def extract_lines_by_projection(image: np.ndarray, lang: str) -> List[str]:
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    _, bin_img = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    text_mask = (bin_img < 128).astype(np.uint8) * 255

    # Remove horizontal table lines (robust to breaks)
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (60, 1))
    horiz_lines = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, horiz_kernel)
    horiz_lines = cv2.morphologyEx(horiz_lines, cv2.MORPH_OPEN, horiz_kernel)
    text_mask = cv2.subtract(text_mask, horiz_lines)

    # Prefer row segments between horizontal lines (table rows)
    line_rows = (horiz_lines > 0).sum(axis=1)
    line_threshold = max(2, int(text_mask.shape[1] * 0.1))
    line_indices = np.where(line_rows > line_threshold)[0]
    line_bands = []
    if len(line_indices) > 0:
        band_start = line_indices[0]
        prev = line_indices[0]
        for idx in line_indices[1:]:
            if idx == prev + 1:
                prev = idx
                continue
            line_bands.append((band_start, prev))
            band_start = idx
            prev = idx
        line_bands.append((band_start, prev))

    segments = []
    if len(line_bands) >= 2:
        for i in range(len(line_bands) - 1):
            y1 = line_bands[i][1] + 1
            y2 = line_bands[i + 1][0] - 1
            if y2 - y1 >= 8:
                segments.append((y1, y2))
    else:
        rows_sum = (text_mask > 0).sum(axis=1)
        threshold = max(2, int(text_mask.shape[1] * 0.005))
        in_text = False
        start = 0
        for i, value in enumerate(rows_sum):
            if value > threshold and not in_text:
                in_text = True
                start = i
            elif value <= threshold and in_text:
                end = i
                if end - start >= 8:
                    segments.append((start, end))
                in_text = False
        if in_text:
            end = len(rows_sum) - 1
            if end - start >= 8:
                segments.append((start, end))

    def clean_line_image(crop_gray: np.ndarray) -> np.ndarray:
        # Binariza y elimina líneas horizontales para mejorar el OCR por fila
        crop_blur = cv2.medianBlur(crop_gray, 3)
        _, bin_img = cv2.threshold(crop_blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        inv = 255 - bin_img
        horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        horiz_lines = cv2.morphologyEx(inv, cv2.MORPH_OPEN, horiz_kernel)
        inv = cv2.subtract(inv, horiz_lines)
        clean = 255 - inv
        clean = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
        clean = cv2.erode(clean, np.ones((2, 2), np.uint8), iterations=1)
        return clean

    lines = []
    whitelist = "ABCDEFGHIJKLMNOPQRSTUVWXYZÑ0123456789XKG"
    config = (
        "--oem 1 --psm 7 -c preserve_interword_spaces=1 "
        f"-c tessedit_char_whitelist={whitelist} "
        "-c load_system_dawg=0 -c load_freq_dawg=0"
    )
    for start, end in segments:
        pad = 4
        y1 = max(0, start - pad)
        y2 = min(gray.shape[0], end + pad)
        crop = gray[y1:y2, :]
        clean_crop = clean_line_image(crop)
        text = pytesseract.image_to_string(clean_crop, lang=lang, config=config).strip()
        if not text:
            continue
        text = normalize_line(text)
        if PRODUCT_CATALOG:
            best, score = catalog_best(text)
            alpha_count = sum(ch.isalpha() for ch in text)
            if alpha_count >= 4 and score >= 0.78:
                lines.append(best)
            elif alpha_count >= 4:
                # Si no coincide con el catálogo, conserva el texto detectado
                lines.append(text)
        else:
            text = best_catalog_match(text)
            if text:
                lines.append(text)
    return lines


def extract_full_lines(images: List[np.ndarray], lang: str) -> List[str]:
    configs = [
        "--oem 1 --psm 6 -c preserve_interword_spaces=1 -c user_defined_dpi=300",
        "--oem 1 --psm 4 -c preserve_interword_spaces=1 -c user_defined_dpi=300",
        "--oem 1 --psm 11 -c preserve_interword_spaces=1 -c user_defined_dpi=300",
    ]
    best_lines: List[str] = []
    best_score = -1
    for image in images:
        img = image
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        for config in configs:
            text = pytesseract.image_to_string(img, lang=lang, config=config)
            candidates = []
            for raw in text.splitlines():
                cleaned = normalize_line(raw)
                if not cleaned:
                    continue
                alpha_count = sum(ch.isalpha() for ch in cleaned)
                if alpha_count < 6:
                    continue
                alpha_ratio = alpha_count / max(1, len(cleaned))
                if alpha_ratio < 0.5:
                    continue
                if (
                    "ARROZ" in cleaned
                    or "KG" in cleaned
                    or " X " in cleaned
                    or ("X " in cleaned and "KG" in cleaned)
                ):
                    candidates.append(cleaned)
                elif len(cleaned) >= 12:
                    vowel_count = sum(ch in "AEIOU" for ch in cleaned)
                    if vowel_count >= 3:
                        candidates.append(cleaned)
            candidates = deduplicate_lines(candidates)
            score = len(candidates)
            score += sum(2 for line in candidates if "ARROZ" in line)
            score += sum(1 for line in candidates if "KG" in line)
            if score > best_score:
                best_score = score
                best_lines = candidates
    return best_lines


def is_low_quality(lines: List[str]) -> bool:
    if not lines:
        return True
    keyword_hits = sum(1 for line in lines if ("ARROZ" in line or "KG" in line or " X " in line))
    avg_alpha_ratio = 0.0
    for line in lines:
        if not line:
            continue
        alpha = sum(ch.isalpha() for ch in line)
        avg_alpha_ratio += alpha / max(1, len(line))
    avg_alpha_ratio = avg_alpha_ratio / max(1, len(lines))
    return keyword_hits == 0 and avg_alpha_ratio < 0.5


def extract_lines_from_data(image: np.ndarray, lang: str) -> List[str]:
    config = "--oem 1 --psm 6 -c preserve_interword_spaces=1 -c user_defined_dpi=300"
    data = pytesseract.image_to_data(image, output_type=Output.DICT, lang=lang, config=config)
    line_map: dict[tuple[int, int, int], list[str]] = {}
    for i, text in enumerate(data.get("text", [])):
        word = (text or "").strip()
        if not word:
            continue
        try:
            conf = int(float(data.get("conf", ["-1"])[i]))
        except (ValueError, TypeError, IndexError):
            conf = -1
        if conf >= 0 and conf < 50:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        line_map.setdefault(key, []).append(word)
    lines: List[str] = []
    for key in sorted(line_map.keys()):
        line = normalize_line(" ".join(line_map[key]))
        alpha_count = sum(ch.isalpha() for ch in line)
        if alpha_count < 4:
            continue
        lines.append(line)
    return lines


def crop_text_region(image: np.ndarray, pad: int = 8) -> np.ndarray:
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    _, bin_img = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = bin_img < 200
    coords = np.column_stack(np.where(mask))
    if coords.size == 0:
        return image
    y1, x1 = coords.min(axis=0)
    y2, x2 = coords.max(axis=0)
    y1 = max(0, y1 - pad)
    x1 = max(0, x1 - pad)
    y2 = min(gray.shape[0] - 1, y2 + pad)
    x2 = min(gray.shape[1] - 1, x2 + pad)
    if y2 <= y1 or x2 <= x1:
        return image
    return image[y1 : y2 + 1, x1 : x2 + 1]


def crop_center_regions(image: np.ndarray, margins: tuple[float, ...] = (0.08,)) -> List[np.ndarray]:
    h, w = image.shape[:2]
    crops: List[np.ndarray] = []
    for margin in margins:
        x1 = int(w * margin)
        x2 = int(w * (1 - margin))
        y1 = int(h * 0.02)
        y2 = int(h * 0.98)
        if x2 > x1 and y2 > y1:
            crops.append(image[y1:y2, x1:x2])
    return crops


def get_tessdata_dir() -> str | None:
    prefix = os.environ.get("TESSDATA_PREFIX")
    if prefix:
        if os.path.basename(prefix).lower() == "tessdata":
            return prefix
        return os.path.join(prefix, "tessdata")
    cmd = pytesseract.pytesseract.tesseract_cmd
    if cmd and os.path.exists(cmd):
        return os.path.join(os.path.dirname(cmd), "tessdata")
    return None


def lang_available(lang: str) -> bool | None:
    tessdata_dir = get_tessdata_dir()
    if not tessdata_dir:
        return None
    return os.path.exists(os.path.join(tessdata_dir, f"{lang}.traineddata"))


def get_ocr_lang() -> str:
    spa_ok = lang_available("spa")
    eng_ok = lang_available("eng")
    if spa_ok and eng_ok:
        return "spa+eng"
    if spa_ok:
        return "spa"
    if eng_ok:
        return "eng"
    return "spa"


def get_easyocr_reader():
    global EASYOCR_READER
    if easyocr is None:
        return None
    if EASYOCR_READER is None:
        EASYOCR_READER = easyocr.Reader(["es", "en"], gpu=False)
    return EASYOCR_READER


def easyocr_lines(image: np.ndarray) -> List[str]:
    reader = get_easyocr_reader()
    if reader is None:
        return []
    if len(image.shape) == 3:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    else:
        rgb = image
    allowlist = "ABCDEFGHIJKLMNOPQRSTUVWXYZÑ0123456789XKG"
    results = reader.readtext(
        rgb,
        detail=1,
        paragraph=False,
        text_threshold=0.5,
        low_text=0.3,
        link_threshold=0.4,
        contrast_ths=0.3,
        adjust_contrast=0.7,
        decoder="beamsearch",
        allowlist=allowlist,
    )
    items = []
    for bbox, text, conf in results:
        if conf is not None and conf < 0.25:
            continue
        cleaned = normalize_line(text)
        if not cleaned:
            continue
        alpha_count = sum(ch.isalpha() for ch in cleaned)
        if alpha_count < 4:
            continue
        alpha_ratio = alpha_count / max(1, len(cleaned))
        if alpha_ratio < 0.45:
            continue
        if PRODUCT_CATALOG:
            best, score = catalog_best(cleaned)
            if score >= 0.72:
                cleaned = best
        y_center = sum(p[1] for p in bbox) / len(bbox)
        items.append((y_center, cleaned))
    items.sort(key=lambda x: x[0])
    lines = [item[1] for item in items]
    return deduplicate_lines(lines)


def score_lines(lines: List[str]) -> int:
    text = "".join(lines)
    return sum(ch.isalnum() for ch in text)


def catalog_score(lines: List[str]) -> tuple[int, float]:
    if not PRODUCT_CATALOG or not lines:
        return (0, 0.0)
    matched = 0
    total_ratio = 0.0
    for line in lines:
        best_ratio = 0.0
        for item in PRODUCT_CATALOG:
            ratio = SequenceMatcher(a=line, b=item).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
        if best_ratio >= 0.75:
            matched += 1
        total_ratio += best_ratio
    return (matched, total_ratio)


def score_key(lines: List[str]) -> tuple[int, float, int, int]:
    matched, total_ratio = catalog_score(lines)
    return (matched, total_ratio, len(lines), score_lines(lines))


def run_ocr_variants(images: List[np.ndarray], lang: str) -> List[str]:
    best_lines: List[str] = []
    best_key = (-1, -1.0, -1, -1)
    for img in images:
        for psm in ("6", "4", "11"):
            lines = deduplicate_lines(extract_lines(img, lang, psm))
            key = score_key(lines)
            if key > best_key:
                best_key = key
                best_lines = lines
        proj_lines = deduplicate_lines(extract_lines_by_projection(img, lang))
        key = score_key(proj_lines)
        if key > best_key:
            best_key = key
            best_lines = proj_lines
    return best_lines


def run_ocr_with_fallback(images: List[np.ndarray]) -> tuple[List[str], List[str]]:
    warnings = []
    spa_ok = lang_available("spa")
    eng_ok = lang_available("eng")
    lang = get_ocr_lang()

    if spa_ok is False and eng_ok:
        warnings.append("No se encontro el idioma spa. Se uso eng como respaldo.")
        return run_ocr_variants(images, "eng"), warnings

    if spa_ok is False and eng_ok is False:
        raise RuntimeError("No hay idiomas instalados (spa/eng) en Tesseract.")

    try:
        # EasyOCR primero: mejor para texto impreso en tablas
        for img in images:
            easy_lines = easyocr_lines(img)
            if easy_lines and not is_low_quality(easy_lines):
                return easy_lines, warnings

        if PRODUCT_CATALOG:
            best_lines: List[str] = []
            best_key = (-1, -1.0, -1, -1)
            for img in images:
                proj_lines = extract_lines_by_projection(img, lang)
                key = score_key(proj_lines)
                if key > best_key:
                    best_key = key
                    best_lines = proj_lines
            if not best_lines:
                best_lines = run_ocr_variants(images, lang)
            if is_low_quality(best_lines):
                fallback = extract_full_lines(images, lang)
                if fallback:
                    return fallback, warnings
                data_lines = []
                for img in images:
                    data_lines = extract_lines_from_data(img, lang)
                    if data_lines and not is_low_quality(data_lines):
                        return data_lines, warnings
            return best_lines, warnings

        lines = run_ocr_variants(images, lang)
        if not lines or is_low_quality(lines):
            fallback = extract_full_lines(images, lang)
            if fallback:
                lines = fallback
            else:
                for img in images:
                    data_lines = extract_lines_from_data(img, lang)
                    if data_lines and not is_low_quality(data_lines):
                        lines = data_lines
                        break
        return lines, warnings
    except pytesseract.pytesseract.TesseractError as exc:
        msg = str(exc)
        if ("Failed loading language 'spa'" in msg or "spa.traineddata" in msg) and eng_ok:
            warnings.append("No se encontro el idioma spa. Se uso eng como respaldo.")
            return run_ocr_variants(images, "eng"), warnings
        raise RuntimeError("Tesseract no pudo cargar idiomas. Instala spa/eng.") from exc


def save_result(lines: List[str], warnings: List[str], label_text: str) -> None:
    payload = json.dumps(lines, ensure_ascii=True)
    warnings_payload = json.dumps(warnings, ensure_ascii=True)
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO ocr_results (created_at, lines_json, warnings_json, label_text) VALUES (?, ?, ?, ?)",
            (created_at, payload, warnings_payload, label_text),
        )
        conn.commit()


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True, "tesseract": bool(resolved_cmd)})


@app.get("/", response_class=RedirectResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/admin")


@app.get("/capture", response_class=HTMLResponse)
def capture_page() -> HTMLResponse:
    html_path = FRONTEND_DIR / "capture.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/admin", response_class=HTMLResponse)
def admin_page() -> HTMLResponse:
    html_path = FRONTEND_DIR / "admin.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/constancia-view", response_class=HTMLResponse)
def constancia_view_page(constancia_id: int = Query(..., alias="id")) -> HTMLResponse:
    html = f"""
    <!doctype html>
    <html lang="es">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Constancia</title>
      </head>
      <body>
        <div style="font-family: Arial, sans-serif; padding: 16px;">Cargando constancia...</div>
        <script>
          async function loadConstancia() {{
            try {{
              if (!window.opener || typeof window.opener.buildConstanciaHtml !== "function") {{
                document.body.innerHTML = '<div style="font-family: Arial, sans-serif; padding: 16px;">No se encontró la página principal para renderizar.</div>';
                return;
              }}
              const res = await fetch('/api/constancias/{constancia_id}');
              const data = await res.json();
              if (!res.ok) throw new Error();
              const prodRes = await fetch('/api/products');
              const prodData = await prodRes.json();
              const catalog = prodData.products || [];
              const clientRes = await fetch('/api/clients');
              const clientData = await clientRes.json();
              const clients = clientData.clients || [];
              const html = window.opener.buildConstanciaHtml(data, catalog, clients);
              document.open();
              document.write(html);
              document.close();
            }} catch (err) {{
              document.body.innerHTML = '<div style="font-family: Arial, sans-serif; padding: 16px;">No se pudo cargar la constancia.</div>';
            }}
          }}
          loadConstancia();
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/api/ocr_preview")
async def ocr_preview(file: UploadFile = File(...)) -> JSONResponse:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid image file")
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    processed, warnings, gray_base, otsu, enhanced, clean_text, original = preprocess_image(image_bytes)
    try:
        base_variants = [clean_text, enhanced, original]
        variants = []
        for img in base_variants:
            variants.append(img)
            cropped = crop_text_region(img)
            if cropped.shape != img.shape:
                variants.append(cropped)
            variants.extend(crop_center_regions(img, margins=(0.08,)))
        lines, ocr_warnings = run_ocr_with_fallback(variants)
    except pytesseract.pytesseract.TesseractNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail="Tesseract no esta instalado o no esta en PATH.",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    warnings.extend(ocr_warnings)
    return JSONResponse({"lines": lines, "warnings": warnings})


@app.post("/api/ocr_confirm")
async def ocr_confirm(payload: dict) -> JSONResponse:
    lines = payload.get("lines") or []
    warnings = payload.get("warnings") or []
    if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
        raise HTTPException(status_code=400, detail="Invalid lines payload")
    if not isinstance(warnings, list) or not all(isinstance(x, str) for x in warnings):
        raise HTTPException(status_code=400, detail="Invalid warnings payload")
    label_text = (payload.get("label_text") or "").strip()
    save_result(lines, warnings, label_text)
    add_to_catalog(lines)
    return JSONResponse({"ok": True})


@app.get("/api/results")
def list_results(limit: int = 20) -> JSONResponse:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, lines_json, warnings_json, label_text
            FROM ocr_results
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    results = [
        {
            "id": row[0],
            "created_at": row[1],
            "lines": json.loads(row[2]),
            "warnings": json.loads(row[3]),
            "label_text": row[4] or "",
        }
        for row in rows
    ]
    return JSONResponse({"results": results})


@app.get("/api/products")
def list_products(limit: int = 200) -> JSONResponse:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT id, name, code, origin, um, active, lot, production_text, expiration_text,
                   humidity, broken_grains, chalky_1, chalky_2, damaged_grains, whiteness, created_at
            FROM products
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    products = [
        {
            "id": row[0],
            "name": row[1],
            "code": row[2],
            "origin": row[3],
            "um": row[4],
            "active": bool(row[5]),
            "lot": row[6],
            "production_text": row[7],
            "expiration_text": row[8],
            "humidity": row[9],
            "broken_grains": row[10],
            "chalky_1": row[11],
            "chalky_2": row[12],
            "damaged_grains": row[13],
            "whiteness": row[14],
            "created_at": row[15],
        }
        for row in rows
    ]
    return JSONResponse({"products": products})


@app.post("/api/products")
async def create_product(payload: dict) -> JSONResponse:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nombre es obligatorio.")
    data = {
        "name": name,
        "code": (payload.get("code") or "").strip() or None,
        "origin": (payload.get("origin") or "").strip() or None,
        "um": (payload.get("um") or "").strip() or None,
        "active": 1 if payload.get("active", True) else 0,
        "lot": (payload.get("lot") or "").strip() or None,
        "production_text": (payload.get("production_text") or "").strip() or None,
        "expiration_text": (payload.get("expiration_text") or "").strip() or None,
        "humidity": payload.get("humidity"),
        "broken_grains": payload.get("broken_grains"),
        "chalky_1": payload.get("chalky_1"),
        "chalky_2": payload.get("chalky_2"),
        "damaged_grains": payload.get("damaged_grains"),
        "whiteness": payload.get("whiteness"),
    }
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT INTO products (
                name, code, origin, um, active, lot, production_text, expiration_text,
                humidity, broken_grains, chalky_1, chalky_2, damaged_grains, whiteness, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["name"],
                data["code"],
                data["origin"],
                data["um"],
                data["active"],
                data["lot"],
                data["production_text"],
                data["expiration_text"],
                data["humidity"],
                data["broken_grains"],
                data["chalky_1"],
                data["chalky_2"],
                data["damaged_grains"],
                data["whiteness"],
                created_at,
            ),
        )
        conn.commit()
        product_id = cursor.lastrowid
    return JSONResponse({"id": product_id})


@app.put("/api/products/{product_id}")
async def update_product(product_id: int, payload: dict) -> JSONResponse:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nombre es obligatorio.")
    data = {
        "name": name,
        "code": (payload.get("code") or "").strip() or None,
        "origin": (payload.get("origin") or "").strip() or None,
        "um": (payload.get("um") or "").strip() or None,
        "active": 1 if payload.get("active", True) else 0,
        "lot": (payload.get("lot") or "").strip() or None,
        "production_text": (payload.get("production_text") or "").strip() or None,
        "expiration_text": (payload.get("expiration_text") or "").strip() or None,
        "humidity": payload.get("humidity"),
        "broken_grains": payload.get("broken_grains"),
        "chalky_1": payload.get("chalky_1"),
        "chalky_2": payload.get("chalky_2"),
        "damaged_grains": payload.get("damaged_grains"),
        "whiteness": payload.get("whiteness"),
    }
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE products
            SET name = ?, code = ?, origin = ?, um = ?, active = ?, lot = ?, production_text = ?, expiration_text = ?,
                humidity = ?, broken_grains = ?, chalky_1 = ?, chalky_2 = ?, damaged_grains = ?, whiteness = ?
            WHERE id = ?
            """,
            (
                data["name"],
                data["code"],
                data["origin"],
                data["um"],
                data["active"],
                data["lot"],
                data["production_text"],
                data["expiration_text"],
                data["humidity"],
                data["broken_grains"],
                data["chalky_1"],
                data["chalky_2"],
                data["damaged_grains"],
                data["whiteness"],
                product_id,
            ),
        )
        conn.commit()
    return JSONResponse({"ok": True})


@app.delete("/api/products/{product_id}")
def delete_product(product_id: int) -> JSONResponse:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()
    return JSONResponse({"ok": True})


@app.get("/api/clients")
def list_clients(limit: int = 200) -> JSONResponse:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, name, ruc, created_at FROM clients ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    clients = [
        {"id": row[0], "name": row[1], "ruc": row[2], "created_at": row[3]}
        for row in rows
    ]
    return JSONResponse({"clients": clients})


@app.post("/api/clients")
async def create_client(payload: dict) -> JSONResponse:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nombre es obligatorio.")
    ruc = (payload.get("ruc") or "").strip() or None
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT INTO clients (name, ruc, created_at) VALUES (?, ?, ?)",
            (name, ruc, created_at),
        )
        conn.commit()
        client_id = cursor.lastrowid
    return JSONResponse({"id": client_id})


@app.delete("/api/clients/{client_id}")
def delete_client(client_id: int) -> JSONResponse:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        conn.commit()
    return JSONResponse({"ok": True})


@app.get("/api/transports")
def list_transports(limit: int = 200) -> JSONResponse:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, plate, created_at FROM transports ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    transports = [{"id": row[0], "plate": row[1], "created_at": row[2]} for row in rows]
    return JSONResponse({"transports": transports})


@app.post("/api/transports")
async def create_transport(payload: dict) -> JSONResponse:
    plate = (payload.get("plate") or "").strip()
    if not plate:
        raise HTTPException(status_code=400, detail="Matrícula es obligatoria.")
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT INTO transports (plate, created_at) VALUES (?, ?)",
            (plate, created_at),
        )
        conn.commit()
        transport_id = cursor.lastrowid
    return JSONResponse({"id": transport_id})


@app.delete("/api/transports/{transport_id}")
def delete_transport(transport_id: int) -> JSONResponse:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM transports WHERE id = ?", (transport_id,))
        conn.commit()
    return JSONResponse({"ok": True})


def _trasiego_row_to_dict(row: tuple) -> dict:
    return {
        "id": row[0],
        "fecha": row[1] or "",
        "mp": row[2] or "",
        "f_ingreso": row[3] or "",
        "estado": row[4] or "",
        "lote": row[5] or "",
        "f_p": row[6] or "",
        "f_v": row[7] or "",
        "cantidad": row[8] or "",
        "created_at": row[9],
        "updated_at": row[10],
    }


@app.get("/api/trasiegos")
def list_trasiegos(limit: int = 500) -> JSONResponse:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT id, fecha, mp, f_ingreso, estado, lote, f_p, f_v, cantidad, created_at, updated_at
            FROM trasiegos
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return JSONResponse({"trasiegos": [_trasiego_row_to_dict(row) for row in rows]})


@app.post("/api/trasiegos")
async def create_trasiego(payload: dict) -> JSONResponse:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT INTO trasiegos (
                fecha, mp, f_ingreso, estado, lote, f_p, f_v, cantidad, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (payload.get("fecha") or "").strip() or None,
                (payload.get("mp") or "").strip() or None,
                (payload.get("f_ingreso") or "").strip() or None,
                (payload.get("estado") or "").strip() or None,
                (payload.get("lote") or "").strip() or None,
                (payload.get("f_p") or "").strip() or None,
                (payload.get("f_v") or "").strip() or None,
                (payload.get("cantidad") or "").strip() or None,
                now,
                now,
            ),
        )
        conn.commit()
        row_id = cursor.lastrowid
    return JSONResponse({"id": row_id})


@app.put("/api/trasiegos/{trasiego_id}")
async def update_trasiego(trasiego_id: int, payload: dict) -> JSONResponse:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE trasiegos
            SET fecha = ?, mp = ?, f_ingreso = ?, estado = ?, lote = ?, f_p = ?, f_v = ?, cantidad = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                (payload.get("fecha") or "").strip() or None,
                (payload.get("mp") or "").strip() or None,
                (payload.get("f_ingreso") or "").strip() or None,
                (payload.get("estado") or "").strip() or None,
                (payload.get("lote") or "").strip() or None,
                (payload.get("f_p") or "").strip() or None,
                (payload.get("f_v") or "").strip() or None,
                (payload.get("cantidad") or "").strip() or None,
                now,
                trasiego_id,
            ),
        )
        conn.commit()
    return JSONResponse({"ok": True})


@app.delete("/api/trasiegos/{trasiego_id}")
def delete_trasiego(trasiego_id: int) -> JSONResponse:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM trasiegos WHERE id = ?", (trasiego_id,))
        conn.commit()
    return JSONResponse({"ok": True})


@app.post("/api/constancias")
async def create_constancia(payload: dict) -> JSONResponse:
    items = payload.get("items") or []
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="Items invalidos.")
    status = payload.get("status") or "confirmada"
    if status not in {"confirmada", "por_confirmar"}:
        raise HTTPException(status_code=400, detail="Estado invalido.")
    fumigacion = 1 if payload.get("fumigacion", True) else 0
    calidad = 1 if payload.get("calidad", True) else 0
    if fumigacion == 0 and calidad == 0:
        raise HTTPException(status_code=400, detail="Selecciona al menos una constancia.")
    number = (payload.get("number") or "").strip() or None
    issue_date = (payload.get("issue_date") or "").strip() or None
    client_name = (payload.get("client_name") or "").strip() or None
    transport_plate = (payload.get("transport_plate") or "").strip() or None
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT INTO constancias (
                number, issue_date, client_name, transport_plate, fumigacion, calidad, status, items_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                number,
                issue_date,
                client_name,
                transport_plate,
                fumigacion,
                calidad,
                status,
                json.dumps(items, ensure_ascii=True),
                created_at,
            ),
        )
        conn.commit()
        constancia_id = cursor.lastrowid
    return JSONResponse({"id": constancia_id})


@app.get("/api/constancias")
def list_constancias(limit: int = 200) -> JSONResponse:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT id, number, issue_date, client_name, transport_plate, fumigacion, calidad, status, items_json, created_at
            FROM constancias
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    constancias = [
        {
            "id": row[0],
            "number": row[1],
            "issue_date": row[2],
            "client_name": row[3],
            "transport_plate": row[4],
            "fumigacion": bool(row[5]),
            "calidad": bool(row[6]),
            "status": row[7],
            "items": json.loads(row[8]),
            "created_at": row[9],
        }
        for row in rows
    ]
    return JSONResponse({"constancias": constancias})


@app.post("/api/constancias/{constancia_id}/confirm")
def confirm_constancia(constancia_id: int) -> JSONResponse:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE constancias SET status = 'confirmada' WHERE id = ?",
            (constancia_id,),
        )
        conn.commit()
    return JSONResponse({"ok": True})


@app.delete("/api/constancias/{constancia_id}")
def delete_constancia(constancia_id: int) -> JSONResponse:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM constancias WHERE id = ?", (constancia_id,))
        conn.commit()
    return JSONResponse({"ok": True})


@app.get("/api/constancias/{constancia_id}")
def get_constancia(constancia_id: int) -> JSONResponse:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT id, number, issue_date, client_name, transport_plate, fumigacion, calidad, status, items_json, created_at
            FROM constancias
            WHERE id = ?
            """,
            (constancia_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Constancia no encontrada.")
    return JSONResponse(
        {
            "id": row[0],
            "number": row[1],
            "issue_date": row[2],
            "client_name": row[3],
            "transport_plate": row[4],
            "fumigacion": bool(row[5]),
            "calidad": bool(row[6]),
            "status": row[7],
            "items": json.loads(row[8]),
            "created_at": row[9],
        }
    )


@app.put("/api/constancias/{constancia_id}")
async def update_constancia(constancia_id: int, payload: dict) -> JSONResponse:
    items = payload.get("items") or []
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="Items invalidos.")
    status = payload.get("status") or "confirmada"
    if status not in {"confirmada", "por_confirmar"}:
        raise HTTPException(status_code=400, detail="Estado invalido.")
    fumigacion = 1 if payload.get("fumigacion", True) else 0
    calidad = 1 if payload.get("calidad", True) else 0
    if fumigacion == 0 and calidad == 0:
        raise HTTPException(status_code=400, detail="Selecciona al menos una constancia.")
    number = (payload.get("number") or "").strip() or None
    issue_date = (payload.get("issue_date") or "").strip() or None
    client_name = (payload.get("client_name") or "").strip() or None
    transport_plate = (payload.get("transport_plate") or "").strip() or None
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE constancias
            SET number = ?, issue_date = ?, client_name = ?, transport_plate = ?, fumigacion = ?, calidad = ?, status = ?, items_json = ?
            WHERE id = ?
            """,
            (
                number,
                issue_date,
                client_name,
                transport_plate,
                fumigacion,
                calidad,
                status,
                json.dumps(items, ensure_ascii=True),
                constancia_id,
            ),
        )
        conn.commit()
    return JSONResponse({"ok": True})


