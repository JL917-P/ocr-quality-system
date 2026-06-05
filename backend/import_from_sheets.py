"""
Importación inicial: Google Sheets → SQLite (solo registros faltantes por id).

Uso:
  cd backend
  python import_from_sheets.py

Variables opcionales: DATABASE_PATH, GOOGLE_CREDENTIALS_PATH
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from constancia_utils import find_items_json_for_constancia, import_constancia_status, normalize_constancia_status, parse_items_json
from trasiego_utils import repair_trasiego_in_sqlite
from google_sheets import (
    HEADERS_CLIENTES,
    HEADERS_CONSTANCIAS,
    HEADERS_PRODUCTOS,
    HEADERS_TRASIEGOS,
    HEADERS_TRANSPORTES,
    TAB_CLIENTES,
    TAB_CONSTANCIAS,
    TAB_PRODUCTOS,
    TAB_TRASIEGOS,
    TAB_TRANSPORTES,
    _parse_id_cell,
    get_spreadsheet,
    read_sheet_rows,
    read_trasiegos_sheet_rows,
    reset_connection,
)

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parent
DEFAULT_DB = BACKEND_ROOT / "results.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _str_or_none(value: str) -> Optional[str]:
    text = (value or "").strip()
    return text or None


def _int_flag(value: str, default: int = 1) -> int:
    text = (value or "").strip().lower()
    if not text:
        return default
    if text in ("1", "true", "yes", "si", "sí"):
        return 1
    if text in ("0", "false", "no"):
        return 0
    try:
        return 1 if int(float(text)) else 0
    except (ValueError, TypeError):
        return default


def _float_or_none(value: str) -> Optional[float]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def _existing_ids(conn: sqlite3.Connection, table: str) -> set[int]:
    try:
        return {int(r[0]) for r in conn.execute(f"SELECT id FROM {table}").fetchall()}
    except sqlite3.OperationalError:
        return set()


def _deleted_ids(conn: sqlite3.Connection, entity_table: str) -> set[int]:
    try:
        return {
            int(r[0])
            for r in conn.execute(
                "SELECT record_id FROM sync_deletions WHERE entity_table = ?",
                (entity_table,),
            ).fetchall()
        }
    except sqlite3.OperationalError:
        return set()


def _items_json_is_empty(raw: str) -> bool:
    return len(parse_items_json(raw or "[]")) == 0


def _constancia_id_by_number_client(
    conn: sqlite3.Connection,
    number: Optional[str],
    client_name: Optional[str],
) -> Optional[int]:
    num = (number or "").strip()
    client = (client_name or "").strip().lower()
    if not num:
        return None
    row = conn.execute(
        """
        SELECT id FROM constancias
        WHERE trim(coalesce(number, '')) = ?
          AND lower(trim(coalesce(client_name, ''))) = ?
        LIMIT 1
        """,
        (num, client),
    ).fetchone()
    return int(row[0]) if row else None


def _merge_constancia_from_sheet(
    conn: sqlite3.Connection,
    target_id: int,
    items_json: str,
) -> bool:
    """Fusiona items desde Sheets. Nunca modifica status (solo el usuario lo cambia)."""
    cur = conn.execute(
        "SELECT items_json, number, client_name FROM constancias WHERE id = ?",
        (target_id,),
    ).fetchone()
    if not cur:
        return False
    sqlite_items = cur[0] or "[]"
    if _items_json_is_empty(sqlite_items) and not _items_json_is_empty(items_json):
        conn.execute(
            "UPDATE constancias SET items_json = ? WHERE id = ?",
            (items_json, target_id),
        )
        return True
    if _items_json_is_empty(sqlite_items):
        alt_json = find_items_json_for_constancia(conn, cur[1] or "", cur[2] or "", exclude_id=target_id)
        if alt_json:
            conn.execute(
                "UPDATE constancias SET items_json = ? WHERE id = ?",
                (alt_json, target_id),
            )
            return True
    return False


def _fix_sqlite_sequence(conn: sqlite3.Connection, table: str) -> None:
    row = conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()
    max_id = int(row[0]) if row else 0
    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    if max_id > 0:
        conn.execute(
            "INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)",
            (table, max_id),
        )


def _import_clients(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> int:
    existing = _existing_ids(conn, "clients")
    deleted = _deleted_ids(conn, "clients")
    imported = 0
    for row in rows:
        row_id = _parse_id_cell(row.get("id", ""))
        if row_id is None or row_id in existing or row_id in deleted:
            continue
        name = (row.get("name") or "").strip()
        if not name:
            continue
        created_at = _str_or_none(row.get("created_at", "")) or _utc_now()
        conn.execute(
            "INSERT INTO clients (id, name, ruc, created_at) VALUES (?, ?, ?, ?)",
            (row_id, name, _str_or_none(row.get("ruc", "")), created_at),
        )
        existing.add(row_id)
        imported += 1
    if imported:
        _fix_sqlite_sequence(conn, "clients")
    return imported


def _import_products(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> int:
    existing = _existing_ids(conn, "products")
    deleted = _deleted_ids(conn, "products")
    imported = 0
    for row in rows:
        row_id = _parse_id_cell(row.get("id", ""))
        if row_id is None or row_id in existing or row_id in deleted:
            continue
        name = (row.get("name") or "").strip()
        if not name:
            continue
        created_at = _str_or_none(row.get("created_at", "")) or _utc_now()
        conn.execute(
            """
            INSERT INTO products (
                id, name, code, origin, um, active, lot, production_text, expiration_text,
                humidity, broken_grains, chalky_1, chalky_2, damaged_grains, whiteness, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                name,
                _str_or_none(row.get("code", "")),
                _str_or_none(row.get("origin", "")),
                _str_or_none(row.get("um", "")),
                _int_flag(row.get("active", ""), 1),
                _str_or_none(row.get("lot", "")),
                _str_or_none(row.get("production_text", "")),
                _str_or_none(row.get("expiration_text", "")),
                _float_or_none(row.get("humidity", "")),
                _float_or_none(row.get("broken_grains", "")),
                _float_or_none(row.get("chalky_1", "")),
                _float_or_none(row.get("chalky_2", "")),
                _float_or_none(row.get("damaged_grains", "")),
                _float_or_none(row.get("whiteness", "")),
                created_at,
            ),
        )
        existing.add(row_id)
        imported += 1
    if imported:
        _fix_sqlite_sequence(conn, "products")
    return imported


def _import_transports(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> int:
    existing = _existing_ids(conn, "transports")
    deleted = _deleted_ids(conn, "transports")
    imported = 0
    for row in rows:
        row_id = _parse_id_cell(row.get("id", ""))
        if row_id is None or row_id in existing or row_id in deleted:
            continue
        plate = (row.get("plate") or "").strip()
        if not plate:
            continue
        created_at = _str_or_none(row.get("created_at", "")) or _utc_now()
        conn.execute(
            "INSERT INTO transports (id, plate, created_at) VALUES (?, ?, ?)",
            (row_id, plate, created_at),
        )
        existing.add(row_id)
        imported += 1
    if imported:
        _fix_sqlite_sequence(conn, "transports")
    return imported


def _import_constancias(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> int:
    existing = _existing_ids(conn, "constancias")
    deleted = _deleted_ids(conn, "constancias")
    imported = 0
    repaired = 0
    for row in rows:
        sheet_id = _parse_id_cell(row.get("id", ""))
        if sheet_id is None or sheet_id in deleted:
            continue
        status = import_constancia_status(row.get("status"))
        items_json = (row.get("items_json") or "").strip() or "[]"
        number = _str_or_none(row.get("number", ""))
        client_name = _str_or_none(row.get("client_name", ""))

        target_id: Optional[int] = None
        if sheet_id in existing:
            target_id = sheet_id
        elif number:
            target_id = _constancia_id_by_number_client(conn, number, client_name)

        if target_id is not None:
            if _merge_constancia_from_sheet(conn, target_id, items_json):
                repaired += 1
            continue

        if number and _constancia_id_by_number_client(conn, number, client_name) is not None:
            continue

        if sheet_id in existing:
            continue

        created_at = _str_or_none(row.get("created_at", "")) or _utc_now()
        conn.execute(
            """
            INSERT INTO constancias (
                id, number, issue_date, client_name, transport_plate,
                fumigacion, calidad, status, items_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sheet_id,
                number,
                _str_or_none(row.get("issue_date", "")),
                _str_or_none(row.get("client_name", "")),
                _str_or_none(row.get("transport_plate", "")),
                _int_flag(row.get("fumigacion", ""), 1),
                _int_flag(row.get("calidad", ""), 1),
                status,
                items_json,
                created_at,
            ),
        )
        existing.add(sheet_id)
        imported += 1
    if imported or repaired:
        _fix_sqlite_sequence(conn, "constancias")
    return imported + repaired


def _import_trasiegos(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> int:
    existing = _existing_ids(conn, "trasiegos")
    deleted = _deleted_ids(conn, "trasiegos")
    imported = 0
    repaired = 0
    for row in rows:
        row_id = _parse_id_cell(row.get("id", ""))
        if row_id is None or row_id in deleted:
            continue
        if row_id in existing:
            if repair_trasiego_in_sqlite(conn, row_id):
                repaired += 1
            continue
        now = _utc_now()
        created_at = _str_or_none(row.get("created_at", "")) or now
        updated_at = _str_or_none(row.get("updated_at", "")) or created_at
        conn.execute(
            """
            INSERT INTO trasiegos (
                id, fecha, mp, f_ingreso, estado, p_final, lote, f_p, f_v, cantidad, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                _str_or_none(row.get("fecha", "")),
                _str_or_none(row.get("mp", "")),
                _str_or_none(row.get("f_ingreso", "")),
                _str_or_none(row.get("estado", "")),
                _str_or_none(row.get("p_final", "")),
                _str_or_none(row.get("lote", "")),
                _str_or_none(row.get("f_p", "")),
                _str_or_none(row.get("f_v", "")),
                _str_or_none(row.get("cantidad", "")),
                created_at,
                updated_at,
            ),
        )
        existing.add(row_id)
        imported += 1
    if imported or repaired:
        _fix_sqlite_sequence(conn, "trasiegos")
    return imported + repaired


IMPORT_SPECS: list[tuple[str, Sequence[str], Callable[[sqlite3.Connection, list[dict[str, str]]], int]]] = [
    (TAB_CLIENTES, HEADERS_CLIENTES, _import_clients),
    (TAB_PRODUCTOS, HEADERS_PRODUCTOS, _import_products),
    (TAB_TRANSPORTES, HEADERS_TRANSPORTES, _import_transports),
    (TAB_CONSTANCIAS, HEADERS_CONSTANCIAS, _import_constancias),
    (TAB_TRASIEGOS, HEADERS_TRASIEGOS, _import_trasiegos),
]


def print_import_summary(by_tab: dict[str, int]) -> None:
    for tab in (TAB_CLIENTES, TAB_PRODUCTOS, TAB_TRANSPORTES, TAB_CONSTANCIAS, TAB_TRASIEGOS):
        print(f"{tab}: {by_tab.get(tab, 0)} importados")
    print(f"TOTAL IMPORTADOS: {sum(by_tab.values())}")


def run_import_from_sheets(db_path: Path, *, reset: bool = True) -> dict[str, Any]:
    """Importa a SQLite solo registros cuyo id no exista aún."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if reset:
        reset_connection()

    if get_spreadsheet() is None:
        return {
            "ok": False,
            "error": "No hay conexión a Google Sheets",
            "by_tab": {},
            "total": 0,
            "imported": 0,
        }

    by_tab: dict[str, int] = {}
    with sqlite3.connect(db_path) as conn:
        for tab, headers, importer in IMPORT_SPECS:
            if tab == TAB_TRASIEGOS:
                rows = read_trasiegos_sheet_rows()
            else:
                rows = read_sheet_rows(tab, headers)
            count = importer(conn, rows)
            conn.commit()
            by_tab[tab] = count
            print(f"{tab}: {count} importados")
            logger.info("[IMPORT] %s: %s importados", tab, count)

    total = sum(by_tab.values())
    print(f"TOTAL IMPORTADOS: {total}")
    return {
        "ok": True,
        "message": "Importación completada",
        "by_tab": by_tab,
        "total": total,
        "imported": total,
    }


def main() -> int:
    db_path = Path(os.getenv("DATABASE_PATH", str(DEFAULT_DB)))

    from app import init_db

    init_db()

    print("=== IMPORTACIÓN Google Sheets → SQLite ===")
    print("Base de datos:", db_path.resolve())

    result = run_import_from_sheets(db_path)
    if not result.get("ok"):
        print("ERROR:", result.get("error", "desconocido"))
        return 1

    print("\n--- RESUMEN ---")
    print_import_summary(result.get("by_tab", {}))
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sys.exit(main())
