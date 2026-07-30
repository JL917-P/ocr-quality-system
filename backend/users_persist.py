"""Persistencia de usuarios: archivo en DATA_DIR + pestaña Google Sheets USUARIOS.

Los usuarios no deben perderse al redeploy: se respaldan y se restauran al arrancar.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from google_sheets import (
    _parse_id_cell,
    delete_row_by_id,
    get_spreadsheet,
    read_sheet_rows,
    run_sync_after_create,
    run_sync_after_delete,
    upsert_row_by_id,
)

logger = logging.getLogger(__name__)

TAB_USUARIOS = os.getenv("GOOGLE_SHEET_TAB_USUARIOS", "USUARIOS")
HEADERS_USUARIOS = (
    "id",
    "username",
    "display_name",
    "password_hash",
    "password_salt",
    "active",
    "is_admin",
    "permissions_json",
    "created_at",
    "updated_at",
)


def users_backup_path(data_dir: Path) -> Path:
    return Path(data_dir) / "app_users_backup.json"


def _fetch_all_users(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, username, display_name, password_hash, password_salt,
               active, is_admin, permissions_json, created_at, updated_at
        FROM app_users
        ORDER BY id
        """
    ).fetchall()
    return [
        {
            "id": row[0],
            "username": row[1],
            "display_name": row[2],
            "password_hash": row[3],
            "password_salt": row[4],
            "active": int(row[5] or 0),
            "is_admin": int(row[6] or 0),
            "permissions_json": row[7] or "{}",
            "created_at": row[8],
            "updated_at": row[9],
        }
        for row in rows
    ]


def save_users_backup_file(conn: sqlite3.Connection, data_dir: Path) -> Path:
    path = users_backup_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    users = _fetch_all_users(conn)
    path.write_text(json.dumps({"users": users}, ensure_ascii=True, indent=2), encoding="utf-8")
    logger.info("[USERS] Backup local: %s usuarios → %s", len(users), path)
    return path


def sync_user_upsert_to_sheets(user: dict[str, Any]) -> bool:
    _ensure_usuarios_worksheet()
    return upsert_row_by_id(
        TAB_USUARIOS,
        HEADERS_USUARIOS,
        (
            user.get("id"),
            user.get("username"),
            user.get("display_name"),
            user.get("password_hash"),
            user.get("password_salt"),
            user.get("active"),
            user.get("is_admin"),
            user.get("permissions_json"),
            user.get("created_at"),
            user.get("updated_at"),
        ),
    )


def sync_user_delete_from_sheets(user_id: int) -> bool:
    _ensure_usuarios_worksheet()
    return delete_row_by_id(TAB_USUARIOS, HEADERS_USUARIOS, user_id)


def _ensure_usuarios_worksheet() -> None:
    """Crea la pestaña USUARIOS si no existe."""
    from google_sheets import _worksheet_cache

    if TAB_USUARIOS in _worksheet_cache:
        return
    spreadsheet = get_spreadsheet()
    if spreadsheet is None:
        return
    try:
        ws = spreadsheet.worksheet(TAB_USUARIOS)
        _worksheet_cache[TAB_USUARIOS] = ws
        return
    except Exception:
        pass
    try:
        ws = spreadsheet.add_worksheet(title=TAB_USUARIOS, rows=2000, cols=len(HEADERS_USUARIOS))
        ws.update([list(HEADERS_USUARIOS)], range_name="A1", value_input_option="RAW")
        _worksheet_cache[TAB_USUARIOS] = ws
        logger.warning("[USERS] Pestaña %s creada en Google Sheets", TAB_USUARIOS)
    except Exception:
        logger.exception("[USERS] No se pudo crear pestaña %s", TAB_USUARIOS)


def persist_users_now(conn: sqlite3.Connection, data_dir: Path) -> None:
    """Guarda backup local y encola sync completo de usuarios a Sheets."""
    save_users_backup_file(conn, data_dir)
    users = _fetch_all_users(conn)
    for user in users:
        uid = int(user["id"])
        run_sync_after_create(
            TAB_USUARIOS,
            uid,
            lambda u=user: sync_user_upsert_to_sheets(u),
        )


def persist_user_row(conn: sqlite3.Connection, data_dir: Path, user_id: int) -> None:
    save_users_backup_file(conn, data_dir)
    row = conn.execute(
        """
        SELECT id, username, display_name, password_hash, password_salt,
               active, is_admin, permissions_json, created_at, updated_at
        FROM app_users WHERE id = ?
        """,
        (user_id,),
    ).fetchone()
    if not row:
        return
    user = {
        "id": row[0],
        "username": row[1],
        "display_name": row[2],
        "password_hash": row[3],
        "password_salt": row[4],
        "active": int(row[5] or 0),
        "is_admin": int(row[6] or 0),
        "permissions_json": row[7] or "{}",
        "created_at": row[8],
        "updated_at": row[9],
    }
    run_sync_after_create(
        TAB_USUARIOS,
        user_id,
        lambda: sync_user_upsert_to_sheets(user),
    )


def persist_user_deleted(data_dir: Path, conn: sqlite3.Connection, user_id: int) -> None:
    save_users_backup_file(conn, data_dir)
    run_sync_after_delete(
        TAB_USUARIOS,
        user_id,
        lambda: sync_user_delete_from_sheets(user_id),
    )


def _upsert_user_from_dict(conn: sqlite3.Connection, data: dict[str, Any]) -> bool:
    username = (data.get("username") or "").strip()
    if not username:
        return False
    password_hash = (data.get("password_hash") or "").strip()
    password_salt = (data.get("password_salt") or "").strip()
    if not password_hash or not password_salt:
        return False
    display_name = (data.get("display_name") or username).strip()
    try:
        active = 1 if int(data.get("active") or 0) else 0
    except (TypeError, ValueError):
        active = 1
    try:
        is_admin = 1 if int(data.get("is_admin") or 0) else 0
    except (TypeError, ValueError):
        is_admin = 0
    permissions_json = data.get("permissions_json") or "{}"
    if isinstance(permissions_json, dict):
        permissions_json = json.dumps(permissions_json, ensure_ascii=True)
    created_at = data.get("created_at") or ""
    updated_at = data.get("updated_at") or created_at
    wanted_id = data.get("id")

    existing = conn.execute(
        "SELECT id FROM app_users WHERE lower(username) = lower(?)",
        (username,),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE app_users
            SET display_name = ?, password_hash = ?, password_salt = ?,
                active = ?, is_admin = ?, permissions_json = ?,
                created_at = COALESCE(NULLIF(?, ''), created_at),
                updated_at = COALESCE(NULLIF(?, ''), updated_at)
            WHERE id = ?
            """,
            (
                display_name,
                password_hash,
                password_salt,
                active,
                is_admin,
                permissions_json,
                created_at,
                updated_at,
                existing[0],
            ),
        )
        return True

    # Insertar preservando id si es posible (y no choca)
    if wanted_id is not None:
        try:
            wid = int(wanted_id)
            clash = conn.execute("SELECT id FROM app_users WHERE id = ?", (wid,)).fetchone()
            if not clash:
                conn.execute(
                    """
                    INSERT INTO app_users (
                        id, username, display_name, password_hash, password_salt,
                        active, is_admin, permissions_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        wid,
                        username,
                        display_name,
                        password_hash,
                        password_salt,
                        active,
                        is_admin,
                        permissions_json,
                        created_at,
                        updated_at,
                    ),
                )
                return True
        except (TypeError, ValueError):
            pass

    conn.execute(
        """
        INSERT INTO app_users (
            username, display_name, password_hash, password_salt,
            active, is_admin, permissions_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            username,
            display_name,
            password_hash,
            password_salt,
            active,
            is_admin,
            permissions_json,
            created_at,
            updated_at,
        ),
    )
    return True


def restore_users_from_backup_file(conn: sqlite3.Connection, data_dir: Path) -> int:
    path = users_backup_path(data_dir)
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("[USERS] No se pudo leer backup %s", path)
        return 0
    users = payload.get("users") if isinstance(payload, dict) else None
    if not isinstance(users, list):
        return 0
    restored = 0
    for item in users:
        if isinstance(item, dict) and _upsert_user_from_dict(conn, item):
            restored += 1
    if restored:
        conn.commit()
        logger.warning("[USERS] Restaurados %s usuarios desde backup local", restored)
    return restored


def restore_users_from_sheets(conn: sqlite3.Connection) -> int:
    if get_spreadsheet() is None:
        return 0
    _ensure_usuarios_worksheet()
    try:
        rows = read_sheet_rows(TAB_USUARIOS, HEADERS_USUARIOS)
    except Exception:
        logger.exception("[USERS] No se pudo leer pestaña %s", TAB_USUARIOS)
        return 0
    restored = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        username = (row.get("username") or "").strip()
        if not username:
            continue
        active_raw = str(row.get("active") or "1").strip().lower()
        admin_raw = str(row.get("is_admin") or "0").strip().lower()
        data = {
            "id": _parse_id_cell(str(row.get("id", ""))),
            "username": username,
            "display_name": row.get("display_name") or username,
            "password_hash": (row.get("password_hash") or "").strip(),
            "password_salt": (row.get("password_salt") or "").strip(),
            "active": 0 if active_raw in ("0", "false", "no") else 1,
            "is_admin": 1 if admin_raw in ("1", "true", "yes", "si", "sí") else 0,
            "permissions_json": row.get("permissions_json") or "{}",
            "created_at": row.get("created_at") or "",
            "updated_at": row.get("updated_at") or "",
        }
        if _upsert_user_from_dict(conn, data):
            restored += 1
    if restored:
        conn.commit()
        logger.warning("[USERS] Restaurados %s usuarios desde Google Sheets", restored)
    return restored


def restore_users_on_startup(conn: sqlite3.Connection, data_dir: Path) -> dict[str, int]:
    """Restaura usuarios desde backup local y Sheets; luego reescribe el backup."""
    from_file = restore_users_from_backup_file(conn, data_dir)
    from_sheets = 0
    try:
        from_sheets = restore_users_from_sheets(conn)
    except Exception:
        logger.exception("[USERS] Falló restore desde Sheets")
    # Siempre refrescar backup local con el estado final
    try:
        save_users_backup_file(conn, data_dir)
    except Exception:
        logger.exception("[USERS] No se pudo guardar backup tras restore")
    count = conn.execute("SELECT COUNT(*) FROM app_users").fetchone()[0]
    return {"from_file": from_file, "from_sheets": from_sheets, "total": int(count or 0)}
