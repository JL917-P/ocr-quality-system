"""Usuarios, sesiones, permisos y bitácora de auditoría."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Permisos disponibles (admin puede otorgar cada uno)
PERMISSION_KEYS = (
    "section_home",
    "section_clients",
    "section_products",
    "section_transports",
    "section_ocr",
    "section_constancias",
    "section_trazabilidad",
    "section_trasiegos",
    "constancia_create",
    "constancia_edit",
    "constancia_delete",
    "constancia_confirm",
    "clients_write",
    "products_write",
    "transports_write",
    "trasiegos_write",
    "trace_export",
    "users_manage",
    "audit_view",
    "sheets_sync",
)

DEFAULT_OPERATOR_PERMISSIONS: dict[str, bool] = {
    "section_home": True,
    "section_clients": True,
    "section_products": True,
    "section_transports": True,
    "section_ocr": True,
    "section_constancias": True,
    "section_trazabilidad": True,
    "section_trasiegos": True,
    "constancia_create": True,
    "constancia_edit": True,
    "constancia_delete": True,
    "constancia_confirm": True,
    "clients_write": True,
    "products_write": True,
    "transports_write": True,
    "trasiegos_write": True,
    "trace_export": True,
    "users_manage": False,
    "audit_view": False,
    "sheets_sync": True,
}

ADMIN_PERMISSIONS: dict[str, bool] = {key: True for key in PERMISSION_KEYS}

SESSION_DAYS = 14
# Bitácora: conservar al menos 1 mes; descartar solo lo más antiguo
AUDIT_RETENTION_DAYS = 30
PBKDF2_ITERATIONS = 120_000


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit_retention_cutoff_iso(days: int = AUDIT_RETENTION_DAYS) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat()


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt_bytes = secrets.token_bytes(16) if not salt else bytes.fromhex(salt)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        PBKDF2_ITERATIONS,
    )
    return digest.hex(), salt_bytes.hex()


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    try:
        candidate, _ = _hash_password(password, salt)
        return hmac.compare_digest(candidate, password_hash)
    except Exception:
        return False


def normalize_permissions(raw: Any, *, is_admin: bool = False) -> dict[str, bool]:
    if is_admin:
        return dict(ADMIN_PERMISSIONS)
    base = dict(DEFAULT_OPERATOR_PERMISSIONS)
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if isinstance(raw, dict):
        for key in PERMISSION_KEYS:
            if key in raw:
                base[key] = bool(raw[key])
    return base


def permissions_to_json(perms: dict[str, bool]) -> str:
    clean = {key: bool(perms.get(key, False)) for key in PERMISSION_KEYS}
    return json.dumps(clean, ensure_ascii=True)


def user_row_to_dict(row: tuple, *, include_sensitive: bool = False) -> dict[str, Any]:
    is_admin = bool(row[5])
    perms = normalize_permissions(row[6], is_admin=is_admin)
    data = {
        "id": row[0],
        "username": row[1],
        "display_name": row[2] or row[1],
        "active": bool(row[4]),
        "is_admin": is_admin,
        "permissions": perms,
        "created_at": row[7],
        "updated_at": row[8],
    }
    if include_sensitive:
        data["password_hash"] = row[3]
        data["salt"] = row[9] if len(row) > 9 else ""
    return data


def ensure_auth_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            is_admin INTEGER NOT NULL DEFAULT 0,
            permissions_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES app_users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            user_id INTEGER,
            username TEXT NOT NULL,
            action TEXT NOT NULL,
            entity TEXT,
            entity_id TEXT,
            detail TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            requester_user_id INTEGER,
            requester_name TEXT NOT NULL,
            entity TEXT,
            entity_ids_json TEXT NOT NULL DEFAULT '[]',
            detail TEXT,
            resolved_at TEXT,
            resolved_by TEXT
        )
        """
    )
    seed_default_admin(conn)
    purge_old_audit_logs(conn)


def seed_default_admin(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT id FROM app_users WHERE username = ?", ("admin",)).fetchone()
    if row:
        return
    now = utc_now_iso()
    password_hash, salt = _hash_password("123456")
    conn.execute(
        """
        INSERT INTO app_users (
            username, display_name, password_hash, password_salt,
            active, is_admin, permissions_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 1, 1, ?, ?, ?)
        """,
        (
            "admin",
            "Administrador",
            password_hash,
            salt,
            permissions_to_json(ADMIN_PERMISSIONS),
            now,
            now,
        ),
    )


def get_user_by_username(conn: sqlite3.Connection, username: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, username, display_name, password_hash, active, is_admin,
               permissions_json, created_at, updated_at, password_salt
        FROM app_users WHERE lower(username) = lower(?)
        """,
        (username.strip(),),
    ).fetchone()
    if not row:
        return None
    return user_row_to_dict(row, include_sensitive=True)


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, username, display_name, password_hash, active, is_admin,
               permissions_json, created_at, updated_at, password_salt
        FROM app_users WHERE id = ?
        """,
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return user_row_to_dict(row, include_sensitive=True)


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "active": user["active"],
        "is_admin": user["is_admin"],
        "permissions": normalize_permissions(user.get("permissions"), is_admin=user.get("is_admin")),
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
    }


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=SESSION_DAYS)
    conn.execute(
        """
        INSERT INTO app_sessions (token, user_id, created_at, expires_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (token, user_id, now.isoformat(), expires.isoformat(), now.isoformat()),
    )
    return token


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM app_sessions WHERE token = ?", (token,))


def resolve_session(conn: sqlite3.Connection, token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    row = conn.execute(
        """
        SELECT s.token, s.user_id, s.expires_at,
               u.id, u.username, u.display_name, u.password_hash, u.active, u.is_admin,
               u.permissions_json, u.created_at, u.updated_at, u.password_salt
        FROM app_sessions s
        JOIN app_users u ON u.id = s.user_id
        WHERE s.token = ?
        """,
        (token,),
    ).fetchone()
    if not row:
        return None
    expires_at = row[2]
    try:
        exp = datetime.fromisoformat(expires_at)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            conn.execute("DELETE FROM app_sessions WHERE token = ?", (token,))
            return None
    except ValueError:
        return None
    if not row[7]:
        return None
    user = user_row_to_dict(
        (row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10], row[11], row[12]),
        include_sensitive=False,
    )
    now = utc_now_iso()
    conn.execute("UPDATE app_sessions SET last_seen_at = ? WHERE token = ?", (now, token))
    return user


def list_users(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, username, display_name, password_hash, active, is_admin,
               permissions_json, created_at, updated_at, password_salt
        FROM app_users
        ORDER BY is_admin DESC, username ASC
        """
    ).fetchall()
    return [public_user(user_row_to_dict(row)) for row in rows]


def create_user(
    conn: sqlite3.Connection,
    *,
    username: str,
    display_name: str,
    password: str,
    is_admin: bool = False,
    permissions: dict[str, bool] | None = None,
    active: bool = True,
) -> dict[str, Any]:
    username = username.strip()
    display_name = (display_name or username).strip()
    if not username or not password:
        raise ValueError("Usuario y contraseña son obligatorios.")
    if len(password) < 4:
        raise ValueError("La contraseña debe tener al menos 4 caracteres.")
    existing = conn.execute(
        "SELECT id FROM app_users WHERE lower(username) = lower(?)",
        (username,),
    ).fetchone()
    if existing:
        raise ValueError("Ese nombre de usuario ya existe.")
    now = utc_now_iso()
    password_hash, salt = _hash_password(password)
    perms = ADMIN_PERMISSIONS if is_admin else normalize_permissions(permissions or DEFAULT_OPERATOR_PERMISSIONS)
    cursor = conn.execute(
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
            salt,
            1 if active else 0,
            1 if is_admin else 0,
            permissions_to_json(perms),
            now,
            now,
        ),
    )
    user = get_user_by_id(conn, int(cursor.lastrowid))
    assert user is not None
    return public_user(user)


def update_user(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    display_name: str | None = None,
    password: str | None = None,
    active: bool | None = None,
    is_admin: bool | None = None,
    permissions: dict[str, bool] | None = None,
) -> dict[str, Any]:
    user = get_user_by_id(conn, user_id)
    if not user:
        raise ValueError("Usuario no encontrado.")
    now = utc_now_iso()
    new_display = (display_name if display_name is not None else user["display_name"]).strip()
    new_active = user["active"] if active is None else bool(active)
    new_admin = user["is_admin"] if is_admin is None else bool(is_admin)
    if new_admin:
        new_perms = ADMIN_PERMISSIONS
    elif permissions is not None:
        new_perms = normalize_permissions(permissions, is_admin=False)
    else:
        new_perms = normalize_permissions(user["permissions"], is_admin=False)

    if password:
        if len(password) < 4:
            raise ValueError("La contraseña debe tener al menos 4 caracteres.")
        password_hash, salt = _hash_password(password)
        conn.execute(
            """
            UPDATE app_users
            SET display_name = ?, active = ?, is_admin = ?, permissions_json = ?,
                password_hash = ?, password_salt = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_display,
                1 if new_active else 0,
                1 if new_admin else 0,
                permissions_to_json(new_perms),
                password_hash,
                salt,
                now,
                user_id,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE app_users
            SET display_name = ?, active = ?, is_admin = ?, permissions_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_display,
                1 if new_active else 0,
                1 if new_admin else 0,
                permissions_to_json(new_perms),
                now,
                user_id,
            ),
        )
    if not new_active:
        conn.execute("DELETE FROM app_sessions WHERE user_id = ?", (user_id,))
    updated = get_user_by_id(conn, user_id)
    assert updated is not None
    return public_user(updated)


def delete_user(conn: sqlite3.Connection, user_id: int, *, actor_id: int) -> None:
    if user_id == actor_id:
        raise ValueError("No puedes eliminar tu propio usuario.")
    user = get_user_by_id(conn, user_id)
    if not user:
        raise ValueError("Usuario no encontrado.")
    if user["username"] == "admin":
        raise ValueError("No se puede eliminar el usuario administrador principal.")
    conn.execute("DELETE FROM app_sessions WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM app_users WHERE id = ?", (user_id,))


def user_has_permission(user: dict[str, Any] | None, permission: str) -> bool:
    if not user:
        return False
    if user.get("is_admin"):
        return True
    perms = normalize_permissions(user.get("permissions"), is_admin=False)
    return bool(perms.get(permission))


def write_audit(
    conn: sqlite3.Connection,
    *,
    user: dict[str, Any] | None,
    action: str,
    entity: str | None = None,
    entity_id: Any = None,
    detail: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO audit_log (created_at, user_id, username, action, entity, entity_id, detail)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            utc_now_iso(),
            user.get("id") if user else None,
            (user.get("display_name") or user.get("username") or "sistema") if user else "sistema",
            action,
            entity,
            str(entity_id) if entity_id is not None else None,
            detail,
        ),
    )
    event_id = int(cursor.lastrowid or 0)
    # Descartar solo eventos con más de 1 mes de antigüedad
    purge_old_audit_logs(conn)
    # Persistir fuera de SQLite (Render borra la BD al reiniciar)
    if event_id:
        try:
            from audit_persist import persist_audit_event, default_data_dir

            persist_audit_event(conn, default_data_dir(), event_id)
        except Exception:
            # No tumbar la operación de negocio si falla el respaldo
            pass
    return event_id


def purge_old_audit_logs(
    conn: sqlite3.Connection,
    *,
    days: int = AUDIT_RETENTION_DAYS,
) -> int:
    """Elimina de la bitácora solo registros anteriores a la ventana de retención."""
    cutoff = audit_retention_cutoff_iso(days)
    cursor = conn.execute("DELETE FROM audit_log WHERE created_at < ?", (cutoff,))
    return int(cursor.rowcount or 0)


def list_audit(
    conn: sqlite3.Connection,
    *,
    limit: int = 2000,
    username: str | None = None,
    days: int = AUDIT_RETENTION_DAYS,
) -> list[dict[str, Any]]:
    purge_old_audit_logs(conn, days=days)
    # Dentro del mes: devolver amplio historial (no un tope artificial bajo)
    limit = max(1, min(int(limit or 2000), 10000))
    cutoff = audit_retention_cutoff_iso(days)
    params: list[Any] = [cutoff]
    where = "created_at >= ?"
    if username:
        where += " AND lower(username) LIKE lower(?)"
        params.append(f"%{username.strip()}%")
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT id, created_at, user_id, username, action, entity, entity_id, detail
        FROM audit_log
        WHERE {where}
        ORDER BY id DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    return [
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
        for row in rows
    ]


def extract_bearer_token(authorization: str | None, cookie_token: str | None = None) -> str | None:
    if authorization:
        parts = authorization.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            return parts[1].strip()
    if cookie_token and cookie_token.strip():
        return cookie_token.strip()
    return None


def _parse_entity_ids(raw: Any) -> list[int]:
    if isinstance(raw, list):
        out: list[int] = []
        for item in raw:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return out
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return _parse_entity_ids(parsed)
        except json.JSONDecodeError:
            return []
    return []


def notification_row_to_dict(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0],
        "created_at": row[1],
        "type": row[2],
        "status": row[3],
        "requester_user_id": row[4],
        "requester_name": row[5] or "",
        "entity": row[6] or "",
        "entity_ids": _parse_entity_ids(row[7]),
        "detail": row[8] or "",
        "resolved_at": row[9],
        "resolved_by": row[10] or "",
    }


def create_notification(
    conn: sqlite3.Connection,
    *,
    user: dict[str, Any] | None,
    type_: str,
    entity: str | None,
    entity_ids: list[int],
    detail: str | None = None,
    target_user_id: int | None = None,
    target_name: str | None = None,
) -> dict[str, Any]:
    now = utc_now_iso()
    requester_name = (target_name or "").strip() or "usuario"
    requester_id = target_user_id
    if requester_id is None and user:
        requester_id = user.get("id")
        requester_name = (user.get("display_name") or user.get("username") or "usuario").strip()
    elif user and not (target_name or "").strip():
        requester_name = (user.get("display_name") or user.get("username") or requester_name).strip()
    cursor = conn.execute(
        """
        INSERT INTO app_notifications (
            created_at, type, status, requester_user_id, requester_name,
            entity, entity_ids_json, detail
        ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)
        """,
        (
            now,
            type_,
            requester_id,
            requester_name,
            entity,
            json.dumps(entity_ids, ensure_ascii=True),
            detail,
        ),
    )
    row = conn.execute(
        """
        SELECT id, created_at, type, status, requester_user_id, requester_name,
               entity, entity_ids_json, detail, resolved_at, resolved_by
        FROM app_notifications WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    assert row is not None
    return notification_row_to_dict(row)


def count_pending_notifications(
    conn: sqlite3.Connection,
    *,
    user: dict[str, Any] | None = None,
    for_admin: bool = False,
) -> int:
    if for_admin or (user and user.get("is_admin")):
        # Admin: solo solicitudes de borrado pendientes de atender
        row = conn.execute(
            """
            SELECT COUNT(*) FROM app_notifications
            WHERE status = 'pending' AND type = 'delete_constancia_request'
            """
        ).fetchone()
        return int(row[0] if row else 0)
    if not user:
        return 0
    # Usuario: confirmaciones / sus solicitudes pendientes dirigidas a él
    row = conn.execute(
        """
        SELECT COUNT(*) FROM app_notifications
        WHERE status = 'pending' AND requester_user_id = ?
        """,
        (user.get("id"),),
    ).fetchone()
    return int(row[0] if row else 0)


def list_notifications(
    conn: sqlite3.Connection,
    *,
    user: dict[str, Any] | None,
    limit: int = 100,
    status: str | None = "pending",
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 100), 500))
    is_admin = bool(user and user.get("is_admin"))
    params: list[Any] = []
    where = []
    if status:
        where.append("status = ?")
        params.append(status)
    if is_admin:
        # Admin ve solicitudes de borrado (no las confirmaciones al operador)
        where.append("type = 'delete_constancia_request'")
    else:
        where.append("requester_user_id = ?")
        params.append(user.get("id") if user else -1)
    sql = """
        SELECT id, created_at, type, status, requester_user_id, requester_name,
               entity, entity_ids_json, detail, resolved_at, resolved_by
        FROM app_notifications
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [notification_row_to_dict(row) for row in rows]


def get_notification(conn: sqlite3.Connection, notification_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, created_at, type, status, requester_user_id, requester_name,
               entity, entity_ids_json, detail, resolved_at, resolved_by
        FROM app_notifications WHERE id = ?
        """,
        (notification_id,),
    ).fetchone()
    if not row:
        return None
    return notification_row_to_dict(row)


def resolve_notification(
    conn: sqlite3.Connection,
    notification_id: int,
    *,
    resolver: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    if status not in ("approved", "rejected", "dismissed"):
        raise ValueError("Estado de resolución inválido.")
    note = get_notification(conn, notification_id)
    if not note:
        raise ValueError("Notificación no encontrada.")
    if note["status"] != "pending":
        raise ValueError("Esta solicitud ya fue atendida.")
    now = utc_now_iso()
    resolver_name = (resolver.get("display_name") or resolver.get("username") or "admin").strip()
    conn.execute(
        """
        UPDATE app_notifications
        SET status = ?, resolved_at = ?, resolved_by = ?
        WHERE id = ?
        """,
        (status, now, resolver_name, notification_id),
    )
    updated = get_notification(conn, notification_id)
    assert updated is not None
    return updated
