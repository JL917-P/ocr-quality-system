"""Respaldo de fotos de fumigación.

El disco de Render se vacía al reiniciar. Las fotos se copian a un archivo
local y a Google Sheets, y se vuelven a colocar al arrancar.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TAB_FUMIGACIONES = os.getenv("GOOGLE_SHEET_TAB_FUMIGACIONES", "FUMIGACIONES")
CHUNK_CHARS = 45000
CHUNK_COUNT = 24
CHUNK_HEADERS = tuple(f"c{i}" for i in range(1, CHUNK_COUNT + 1))
HEADERS_FUMIGACIONES = (
    "id",
    "created_at",
    "stored_name",
    "original_name",
    "uploaded_by",
    "uploaded_by_id",
    "size_bytes",
    *CHUNK_HEADERS,
)


def backup_path(data_dir: Path) -> Path:
    return Path(data_dir) / "fumigaciones_backup.json"


def _chunks(data: bytes) -> list[str] | None:
    encoded = base64.b64encode(data).decode("ascii")
    parts = [encoded[i : i + CHUNK_CHARS] for i in range(0, len(encoded), CHUNK_CHARS)]
    if len(parts) > CHUNK_COUNT:
        logger.error("[FUMIGACION] La foto no cabe en el respaldo (%s partes)", len(parts))
        return None
    parts.extend([""] * (CHUNK_COUNT - len(parts)))
    return parts


def _decode_chunks(row: dict[str, Any]) -> bytes | None:
    pieces = []
    for key in CHUNK_HEADERS:
        piece = str(row.get(key) or "").strip()
        if piece:
            pieces.append(piece)
    if not pieces:
        image_b64 = str(row.get("image_b64") or "").strip()
        if image_b64:
            pieces = [image_b64]
    if not pieces:
        return None
    try:
        data = base64.b64decode("".join(pieces))
    except Exception:
        return None
    if not data.startswith(b"\xff\xd8"):
        return None
    return data


def _row_from_record(record: dict[str, Any], data: bytes) -> list[Any] | None:
    parts = _chunks(data)
    if parts is None:
        return None
    return [
        int(record["id"]),
        record.get("created_at") or "",
        record.get("stored_name") or "",
        record.get("original_name") or "",
        record.get("uploaded_by") or "",
        record.get("uploaded_by_id") or "",
        len(data),
        *parts,
    ]


def _ensure_worksheet() -> None:
    from google_sheets import _worksheet_cache, get_spreadsheet

    if TAB_FUMIGACIONES in _worksheet_cache:
        return
    spreadsheet = get_spreadsheet()
    if spreadsheet is None:
        return
    try:
        ws = spreadsheet.worksheet(TAB_FUMIGACIONES)
        _worksheet_cache[TAB_FUMIGACIONES] = ws
        return
    except Exception:
        pass
    try:
        ws = spreadsheet.add_worksheet(
            title=TAB_FUMIGACIONES,
            rows=200,
            cols=len(HEADERS_FUMIGACIONES),
        )
        ws.update([list(HEADERS_FUMIGACIONES)], range_name="A1", value_input_option="RAW")
        _worksheet_cache[TAB_FUMIGACIONES] = ws
        logger.warning("[FUMIGACION] Pestaña %s creada en Google Sheets", TAB_FUMIGACIONES)
    except Exception:
        logger.exception("[FUMIGACION] No se pudo crear la pestaña %s", TAB_FUMIGACIONES)


def _sheet_rows() -> list[dict[str, str]]:
    from google_sheets import get_spreadsheet, read_sheet_rows

    if get_spreadsheet() is None:
        return []
    _ensure_worksheet()
    try:
        return read_sheet_rows(TAB_FUMIGACIONES, HEADERS_FUMIGACIONES)
    except Exception:
        logger.exception("[FUMIGACION] No se pudo leer %s", TAB_FUMIGACIONES)
        return []


def push_fumigacion_sheet(record: dict[str, Any], data: bytes) -> bool:
    from google_sheets import upsert_row_by_id

    values = _row_from_record(record, data)
    if values is None:
        return False
    _ensure_worksheet()
    try:
        return bool(upsert_row_by_id(TAB_FUMIGACIONES, HEADERS_FUMIGACIONES, values))
    except Exception:
        logger.exception("[FUMIGACION] No se pudo copiar la foto %s a Sheets", record.get("id"))
        return False


def drop_fumigacion_sheet(record_id: int) -> None:
    from google_sheets import delete_row_by_id, get_spreadsheet

    if get_spreadsheet() is None:
        return
    _ensure_worksheet()
    try:
        delete_row_by_id(TAB_FUMIGACIONES, HEADERS_FUMIGACIONES, int(record_id))
    except Exception:
        logger.exception("[FUMIGACION] No se pudo quitar la foto %s de Sheets", record_id)


def _records_from_db(conn: sqlite3.Connection, photos_dir: Path) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, created_at, stored_name, original_name, uploaded_by, uploaded_by_id, size_bytes
        FROM fumigaciones
        ORDER BY id
        """
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        stored_name = str(row[2] or "")
        path = photos_dir / stored_name
        image_b64 = ""
        if path.is_file():
            raw = path.read_bytes()
            if raw.startswith(b"\xff\xd8"):
                image_b64 = base64.b64encode(raw).decode("ascii")
        items.append(
            {
                "id": int(row[0]),
                "created_at": row[1],
                "stored_name": stored_name,
                "original_name": row[3] or "",
                "uploaded_by": row[4] or "",
                "uploaded_by_id": row[5],
                "size_bytes": int(row[6] or 0),
                "image_b64": image_b64,
            }
        )
    return items


def write_local_backup(conn: sqlite3.Connection, data_dir: Path, photos_dir: Path) -> None:
    path = backup_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    items = _records_from_db(conn, photos_dir)
    path.write_text(
        json.dumps({"items": items}, ensure_ascii=True),
        encoding="utf-8",
    )


def _load_local_backup(data_dir: Path) -> list[dict[str, Any]]:
    path = backup_path(data_dir)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("[FUMIGACION] No se pudo leer %s", path)
        return []
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _item_from_source(row: dict[str, Any], source: str) -> dict[str, Any] | None:
    stored_name = Path(str(row.get("stored_name") or "")).name
    if not stored_name.endswith(".jpg") or stored_name != str(row.get("stored_name") or ""):
        return None
    data = _decode_chunks(row)
    if data is None:
        return None
    try:
        record_id = int(row.get("id"))
    except (TypeError, ValueError):
        return None
    return {
        "id": record_id,
        "created_at": str(row.get("created_at") or ""),
        "stored_name": stored_name,
        "original_name": str(row.get("original_name") or ""),
        "uploaded_by": str(row.get("uploaded_by") or ""),
        "uploaded_by_id": row.get("uploaded_by_id") or None,
        "size_bytes": len(data),
        "data": data,
        "source": source,
    }


def _insert_if_missing(conn: sqlite3.Connection, item: dict[str, Any]) -> bool:
    exists = conn.execute(
        "SELECT 1 FROM fumigaciones WHERE id = ? OR stored_name = ?",
        (int(item["id"]), item["stored_name"]),
    ).fetchone()
    if exists:
        return False
    uploaded_by_id = item.get("uploaded_by_id")
    try:
        uploaded_by_id = int(uploaded_by_id) if uploaded_by_id not in (None, "") else None
    except (TypeError, ValueError):
        uploaded_by_id = None
    conn.execute(
        """
        INSERT INTO fumigaciones (
            id, created_at, stored_name, original_name, uploaded_by, uploaded_by_id, size_bytes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(item["id"]),
            item.get("created_at") or datetime.now(timezone.utc).isoformat(),
            item["stored_name"],
            item.get("original_name") or "",
            item.get("uploaded_by") or "",
            uploaded_by_id,
            int(item.get("size_bytes") or len(item["data"])),
        ),
    )
    return True


def _fix_sequence(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT MAX(id) FROM fumigaciones").fetchone()
    max_id = int(row[0] or 0)
    if max_id <= 0:
        return
    try:
        cur = conn.execute(
            "UPDATE sqlite_sequence SET seq = ? WHERE name = 'fumigaciones'",
            (max_id,),
        )
        if cur.rowcount == 0:
            conn.execute(
                "INSERT OR REPLACE INTO sqlite_sequence(name, seq) VALUES ('fumigaciones', ?)",
                (max_id,),
            )
    except sqlite3.Error:
        pass


def restore_fumigaciones_on_startup(
    conn: sqlite3.Connection,
    data_dir: Path,
    photos_dir: Path,
) -> dict[str, int]:
    photos_dir.mkdir(parents=True, exist_ok=True)
    before = int(conn.execute("SELECT COUNT(*) FROM fumigaciones").fetchone()[0] or 0)
    known_names = {
        str(row[0])
        for row in conn.execute("SELECT stored_name FROM fumigaciones").fetchall()
        if row and row[0]
    }
    from_file = 0
    from_sheets = 0
    merged: dict[str, dict[str, Any]] = {}
    for raw in _load_local_backup(data_dir):
        item = _item_from_source(raw, "file")
        if item:
            merged[item["stored_name"]] = item
    for raw in _sheet_rows():
        item = _item_from_source(raw, "sheets")
        if item:
            merged[item["stored_name"]] = item
    for stored_name, item in merged.items():
        path = photos_dir / stored_name
        if not path.is_file():
            path.write_bytes(item["data"])
        if stored_name in known_names:
            continue
        if _insert_if_missing(conn, item):
            known_names.add(stored_name)
            if item["source"] == "sheets":
                from_sheets += 1
            else:
                from_file += 1
    if from_file or from_sheets:
        _fix_sequence(conn)
    try:
        write_local_backup(conn, data_dir, photos_dir)
    except Exception:
        logger.exception("[FUMIGACION] No se pudo reescribir el respaldo local")
    present_ids = set()
    for raw in _sheet_rows():
        try:
            present_ids.add(int(raw.get("id")))
        except (TypeError, ValueError):
            continue
    for record in _records_from_db(conn, photos_dir):
        if int(record["id"]) in present_ids or not record.get("image_b64"):
            continue
        data = base64.b64decode(record["image_b64"])
        push_fumigacion_sheet(record, data)
    total = int(conn.execute("SELECT COUNT(*) FROM fumigaciones").fetchone()[0] or 0)
    return {
        "before": before,
        "from_file": from_file,
        "from_sheets": from_sheets,
        "total": total,
    }


def sync_fumigacion_backup(
    conn: sqlite3.Connection,
    data_dir: Path,
    photos_dir: Path,
    drop_ids: list[int] | None = None,
    push_id: int | None = None,
) -> None:
    for record_id in drop_ids or []:
        drop_fumigacion_sheet(int(record_id))
    try:
        write_local_backup(conn, data_dir, photos_dir)
    except Exception:
        logger.exception("[FUMIGACION] No se pudo guardar el respaldo local")
    if push_id is None:
        return
    record = next((row for row in _records_from_db(conn, photos_dir) if int(row["id"]) == int(push_id)), None)
    if not record or not record.get("image_b64"):
        return
    push_fumigacion_sheet(record, base64.b64decode(record["image_b64"]))
