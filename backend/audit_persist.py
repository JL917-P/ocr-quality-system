"""Persistencia de bitácora: archivo en DATA_DIR + pestaña Google Sheets BITACORA.

Sin esto, al reiniciar Render (SQLite efímero) se pierden los eventos del día.
Se conserva solo la ventana de retención (30 días).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from auth_service import (
    AUDIT_RETENTION_DAYS,
    audit_retention_cutoff_dt,
    get_app_tz,
    parse_app_datetime,
    purge_old_audit_logs,
)
from google_sheets import (
    get_spreadsheet,
    read_sheet_rows,
    run_sync_after_create,
    upsert_row_by_id,
)

logger = logging.getLogger(__name__)

TAB_BITACORA = os.getenv("GOOGLE_SHEET_TAB_BITACORA", "BITACORA")
HEADERS_BITACORA = (
    "id",
    "created_at",
    "user_id",
    "username",
    "action",
    "entity",
    "entity_id",
    "detail",
)


def default_data_dir() -> Path:
    env = os.getenv("DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


def audit_backup_path(data_dir: Path) -> Path:
    return Path(data_dir) / "audit_log_backup.json"


def _fetch_retained_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    purge_old_audit_logs(conn)
    cutoff = audit_retention_cutoff_dt()
    rows = conn.execute(
        """
        SELECT id, created_at, user_id, username, action, entity, entity_id, detail
        FROM audit_log
        ORDER BY id
        """
    ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        dt = parse_app_datetime(row[1])
        if dt is not None and dt.astimezone(get_app_tz()) < cutoff:
            continue
        events.append(
            {
                "id": row[0],
                "created_at": row[1],
                "user_id": row[2],
                "username": row[3],
                "action": row[4],
                "entity": row[5] or "",
                "entity_id": row[6] or "",
                "detail": row[7] or "",
            }
        )
    return events


def save_audit_backup_file(conn: sqlite3.Connection, data_dir: Path) -> Path:
    path = audit_backup_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    events = _fetch_retained_events(conn)
    path.write_text(
        json.dumps(
            {"retention_days": AUDIT_RETENTION_DAYS, "events": events},
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("[AUDIT] Backup local: %s eventos → %s", len(events), path)
    return path


def _ensure_bitacora_worksheet() -> None:
    from google_sheets import _worksheet_cache

    if TAB_BITACORA in _worksheet_cache:
        return
    spreadsheet = get_spreadsheet()
    if spreadsheet is None:
        return
    try:
        ws = spreadsheet.worksheet(TAB_BITACORA)
        _worksheet_cache[TAB_BITACORA] = ws
        return
    except Exception:
        pass
    try:
        ws = spreadsheet.add_worksheet(title=TAB_BITACORA, rows=5000, cols=len(HEADERS_BITACORA))
        ws.update([list(HEADERS_BITACORA)], range_name="A1", value_input_option="RAW")
        _worksheet_cache[TAB_BITACORA] = ws
        logger.warning("[AUDIT] Pestaña %s creada en Google Sheets", TAB_BITACORA)
    except Exception:
        logger.exception("[AUDIT] No se pudo crear pestaña %s", TAB_BITACORA)


def sync_audit_event_to_sheets(event: dict[str, Any]) -> bool:
    _ensure_bitacora_worksheet()
    return upsert_row_by_id(
        TAB_BITACORA,
        HEADERS_BITACORA,
        (
            event.get("id"),
            event.get("created_at"),
            event.get("user_id"),
            event.get("username"),
            event.get("action"),
            event.get("entity"),
            event.get("entity_id"),
            event.get("detail"),
        ),
    )


def persist_audit_event(conn: sqlite3.Connection, data_dir: Path, event_id: int) -> None:
    """Tras insertar un evento: backup local + sync a Sheets (sin bloquear HTTP)."""
    try:
        save_audit_backup_file(conn, data_dir)
    except Exception:
        logger.exception("[AUDIT] No se pudo guardar backup local")
    row = conn.execute(
        """
        SELECT id, created_at, user_id, username, action, entity, entity_id, detail
        FROM audit_log WHERE id = ?
        """,
        (event_id,),
    ).fetchone()
    if not row:
        return
    event = {
        "id": row[0],
        "created_at": row[1],
        "user_id": row[2],
        "username": row[3],
        "action": row[4],
        "entity": row[5] or "",
        "entity_id": row[6] or "",
        "detail": row[7] or "",
    }
    run_sync_after_create(
        TAB_BITACORA,
        event_id,
        lambda e=event: sync_audit_event_to_sheets(e),
    )


def _insert_event_if_missing(conn: sqlite3.Connection, data: dict[str, Any]) -> bool:
    try:
        eid = int(data.get("id"))
    except (TypeError, ValueError):
        return False
    if not data.get("created_at") or not data.get("action"):
        return False
    exists = conn.execute("SELECT 1 FROM audit_log WHERE id = ?", (eid,)).fetchone()
    if exists:
        return False
    conn.execute(
        """
        INSERT INTO audit_log (
            id, created_at, user_id, username, action, entity, entity_id, detail
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            eid,
            data.get("created_at"),
            data.get("user_id"),
            (data.get("username") or "sistema"),
            data.get("action"),
            data.get("entity") or None,
            data.get("entity_id") or None,
            data.get("detail") or None,
        ),
    )
    return True


def _fix_audit_autoincrement(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT MAX(id) FROM audit_log").fetchone()
    max_id = int(row[0] or 0)
    if max_id <= 0:
        return
    try:
        conn.execute(
            "UPDATE sqlite_sequence SET seq = ? WHERE name = 'audit_log'",
            (max_id,),
        )
        if conn.total_changes == 0:
            conn.execute(
                "INSERT OR REPLACE INTO sqlite_sequence(name, seq) VALUES ('audit_log', ?)",
                (max_id,),
            )
    except sqlite3.Error:
        # Tabla sin sqlite_sequence todavía: el próximo INSERT usará max+1 si insertamos sin id
        pass


def restore_audit_from_backup_file(conn: sqlite3.Connection, data_dir: Path) -> int:
    path = audit_backup_path(data_dir)
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("[AUDIT] No se pudo leer backup %s", path)
        return 0
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        return 0
    cutoff = audit_retention_cutoff_dt()
    restored = 0
    for item in events:
        if not isinstance(item, dict):
            continue
        dt = parse_app_datetime(str(item.get("created_at") or ""))
        if dt is not None and dt.astimezone(get_app_tz()) < cutoff:
            continue
        if _insert_event_if_missing(conn, item):
            restored += 1
    if restored:
        _fix_audit_autoincrement(conn)
        logger.warning("[AUDIT] Restaurados %s eventos desde backup local", restored)
    return restored


def restore_audit_from_sheets(conn: sqlite3.Connection) -> int:
    if get_spreadsheet() is None:
        return 0
    _ensure_bitacora_worksheet()
    try:
        rows = read_sheet_rows(TAB_BITACORA, HEADERS_BITACORA)
    except Exception:
        logger.exception("[AUDIT] No se pudo leer pestaña %s", TAB_BITACORA)
        return 0
    cutoff = audit_retention_cutoff_dt()
    restored = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        dt = parse_app_datetime(str(row.get("created_at") or ""))
        if dt is not None and dt.astimezone(get_app_tz()) < cutoff:
            continue
        if _insert_event_if_missing(conn, row):
            restored += 1
    if restored:
        _fix_audit_autoincrement(conn)
        logger.warning("[AUDIT] Restaurados %s eventos desde Google Sheets", restored)
    return restored


def restore_audit_on_startup(conn: sqlite3.Connection, data_dir: Path) -> dict[str, int]:
    """Restaura bitácora tras redeploy (SQLite vacío) y aplica retención de 30 días."""
    purge_old_audit_logs(conn)
    before = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    from_file = restore_audit_from_backup_file(conn, data_dir)
    from_sheets = restore_audit_from_sheets(conn)
    purge_old_audit_logs(conn)
    try:
        save_audit_backup_file(conn, data_dir)
    except Exception:
        logger.exception("[AUDIT] No se pudo reescribir backup tras restore")
    after = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    return {
        "before": int(before or 0),
        "from_file": int(from_file),
        "from_sheets": int(from_sheets),
        "total": int(after or 0),
    }
