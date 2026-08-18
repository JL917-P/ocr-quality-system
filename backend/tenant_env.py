"""Entornos aislados por usuario (owner_user_id).

El admin conserva el entorno maestro (datos actuales).
Cada operador puede tener catálogo/constancias propias.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from auth_service import get_user_by_id, utc_now_iso

ENV_OWNER_HEADER = "X-QC-Env-Owner"

OWNER_TABLES = (
    "clients",
    "products",
    "transports",
    "constancias",
    "trasiegos",
    "constancia_history",
    "sync_deletions",
    "ocr_results",
)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def ensure_owner_columns(conn: sqlite3.Connection) -> None:
    for table in OWNER_TABLES:
        cols = _table_columns(conn, table)
        if not cols:
            continue
        if "owner_user_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN owner_user_id INTEGER")


def get_master_admin_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        """
        SELECT id FROM app_users
        WHERE is_admin = 1 AND active = 1
        ORDER BY CASE WHEN lower(username) = 'admin' THEN 0 ELSE 1 END, id ASC
        LIMIT 1
        """
    ).fetchone()
    if row:
        return int(row[0])
    row = conn.execute("SELECT id FROM app_users ORDER BY id ASC LIMIT 1").fetchone()
    return int(row[0]) if row else None


def migrate_existing_rows_to_admin(conn: sqlite3.Connection) -> dict[str, int]:
    """Asigna filas sin owner al admin. No toca filas que ya tienen owner."""
    admin_id = get_master_admin_id(conn)
    updated: dict[str, int] = {}
    if admin_id is None:
        return updated
    for table in OWNER_TABLES:
        cols = _table_columns(conn, table)
        if "owner_user_id" not in cols:
            continue
        cur = conn.execute(
            f"UPDATE {table} SET owner_user_id = ? WHERE owner_user_id IS NULL",
            (admin_id,),
        )
        updated[table] = int(cur.rowcount or 0)
    return updated


def resolve_env_owner_id(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    header_value: str | None,
) -> int:
    """Entorno activo: por defecto el del usuario. Solo admin puede impersonar vía header."""
    own_id = int(user["id"])
    raw = (header_value or "").strip()
    if not raw:
        return own_id
    if not user.get("is_admin"):
        return own_id
    try:
        target_id = int(raw)
    except (TypeError, ValueError):
        return own_id
    if target_id == own_id:
        return own_id
    target = get_user_by_id(conn, target_id)
    if not target or not target.get("active"):
        return own_id
    return target_id


def env_counts(conn: sqlite3.Connection, owner_user_id: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in ("clients", "products", "transports", "constancias", "trasiegos"):
        cols = _table_columns(conn, table)
        if "owner_user_id" not in cols:
            out[table] = 0
            continue
        row = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE owner_user_id = ?",
            (owner_user_id,),
        ).fetchone()
        out[table] = int(row[0] if row else 0)
    return out


def clone_catalog(
    conn: sqlite3.Connection,
    *,
    source_owner_id: int,
    dest_owner_id: int,
    force: bool = False,
) -> dict[str, Any]:
    """Copia clientes/productos/transportes del origen al destino (nuevos IDs).

    No copia constancias ni trasiegos. Si el destino ya tiene catálogo y force=False, no duplica.
    """
    if source_owner_id == dest_owner_id:
        return {"ok": False, "error": "Origen y destino son el mismo entorno.", "copied": {}}

    dest_counts = env_counts(conn, dest_owner_id)
    catalog_total = dest_counts["clients"] + dest_counts["products"] + dest_counts["transports"]
    if catalog_total > 0 and not force:
        return {
            "ok": True,
            "skipped": True,
            "message": "El entorno ya tiene catálogo. No se volvió a copiar.",
            "copied": {"clients": 0, "products": 0, "transports": 0},
            "counts": dest_counts,
        }

    now = utc_now_iso()
    copied = {"clients": 0, "products": 0, "transports": 0}

    client_rows = conn.execute(
        """
        SELECT name, ruc, created_at FROM clients
        WHERE owner_user_id = ?
        ORDER BY id
        """,
        (source_owner_id,),
    ).fetchall()
    for name, ruc, created_at in client_rows:
        conn.execute(
            """
            INSERT INTO clients (name, ruc, created_at, owner_user_id)
            VALUES (?, ?, ?, ?)
            """,
            (name, ruc, created_at or now, dest_owner_id),
        )
        copied["clients"] += 1

    product_rows = conn.execute(
        """
        SELECT name, code, origin, um, active, lot, production_text, expiration_text,
               humidity, broken_grains, chalky_1, chalky_2, damaged_grains, whiteness, created_at
        FROM products
        WHERE owner_user_id = ?
        ORDER BY id
        """,
        (source_owner_id,),
    ).fetchall()
    for row in product_rows:
        conn.execute(
            """
            INSERT INTO products (
                name, code, origin, um, active, lot, production_text, expiration_text,
                humidity, broken_grains, chalky_1, chalky_2, damaged_grains, whiteness,
                created_at, owner_user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*row, dest_owner_id),
        )
        copied["products"] += 1

    transport_rows = conn.execute(
        """
        SELECT plate, created_at FROM transports
        WHERE owner_user_id = ?
        ORDER BY id
        """,
        (source_owner_id,),
    ).fetchall()
    for plate, created_at in transport_rows:
        conn.execute(
            """
            INSERT INTO transports (plate, created_at, owner_user_id)
            VALUES (?, ?, ?)
            """,
            (plate, created_at or now, dest_owner_id),
        )
        copied["transports"] += 1

    return {
        "ok": True,
        "skipped": False,
        "copied": copied,
        "counts": env_counts(conn, dest_owner_id),
        "message": (
            f"Catálogo copiado: {copied['clients']} clientes, "
            f"{copied['products']} productos, {copied['transports']} transportes."
        ),
    }


def ensure_user_environment(
    conn: sqlite3.Connection,
    *,
    dest_user_id: int,
    source_owner_id: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    dest = get_user_by_id(conn, dest_user_id)
    if not dest:
        return {"ok": False, "error": "Usuario destino no encontrado."}
    source_id = source_owner_id if source_owner_id is not None else get_master_admin_id(conn)
    if source_id is None:
        return {"ok": False, "error": "No hay entorno origen (admin) disponible."}
    result = clone_catalog(
        conn,
        source_owner_id=int(source_id),
        dest_owner_id=int(dest_user_id),
        force=force,
    )
    result["dest_user_id"] = int(dest_user_id)
    result["source_owner_id"] = int(source_id)
    return result


def ensure_catalog_if_empty(conn: sqlite3.Connection, owner_user_id: int) -> dict[str, Any] | None:
    """Si un operador no tiene catálogo, copia clientes/productos/transportes del admin (sin constancias)."""
    target = get_user_by_id(conn, int(owner_user_id))
    if not target or target.get("is_admin"):
        return None
    counts = env_counts(conn, int(owner_user_id))
    catalog_total = counts["clients"] + counts["products"] + counts["transports"]
    if catalog_total > 0:
        return None
    admin_id = get_master_admin_id(conn)
    if admin_id is None or int(admin_id) == int(owner_user_id):
        return None
    return ensure_user_environment(
        conn,
        dest_user_id=int(owner_user_id),
        source_owner_id=int(admin_id),
        force=False,
    )


def row_belongs_to_owner(conn: sqlite3.Connection, table: str, record_id: int, owner_user_id: int) -> bool:
    cols = _table_columns(conn, table)
    if "owner_user_id" not in cols:
        return True
    row = conn.execute(
        f"SELECT 1 FROM {table} WHERE id = ? AND owner_user_id = ?",
        (record_id, owner_user_id),
    ).fetchone()
    return bool(row)


def _ensure_app_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT
        )
        """
    )


def _meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    _ensure_app_meta(conn)
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row else None


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    _ensure_app_meta(conn)
    conn.execute(
        """
        INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, utc_now_iso()),
    )


def reclaim_operator_constancias_to_admin_once(conn: sqlite3.Connection) -> dict[str, Any]:
    """Una sola vez: devuelve al admin las constancias/trasiegos de operadores.

    Los catálogos (clientes/productos/transportes) de cada operador se conservan.
    Así user01/02/… quedan en 0 constancias y pueden crear las suyas en su entorno.
    """
    flag = "reclaim_operator_constancias_v1"
    if _meta_get(conn, flag) == "done":
        return {"ok": True, "skipped": True, "moved_constancias": 0, "moved_trasiegos": 0}

    admin_id = get_master_admin_id(conn)
    if admin_id is None:
        return {"ok": False, "error": "No hay admin", "moved_constancias": 0, "moved_trasiegos": 0}

    op_ids = [
        int(r[0])
        for r in conn.execute(
            "SELECT id FROM app_users WHERE COALESCE(is_admin, 0) = 0"
        ).fetchall()
    ]
    moved_c = 0
    moved_t = 0
    for oid in op_ids:
        cur = conn.execute(
            "UPDATE constancias SET owner_user_id = ? WHERE owner_user_id = ?",
            (admin_id, oid),
        )
        moved_c += int(cur.rowcount or 0)
        cur = conn.execute(
            "UPDATE trasiegos SET owner_user_id = ? WHERE owner_user_id = ?",
            (admin_id, oid),
        )
        moved_t += int(cur.rowcount or 0)

    # Quitar duplicados del admin (mismo número+cliente) tras reunificar.
    try:
        from constancia_utils import consolidate_constancia_duplicates

        groups = conn.execute(
            """
            SELECT trim(coalesce(number, '')), lower(trim(coalesce(client_name, ''))),
                   MIN(id), COUNT(*)
            FROM constancias
            WHERE owner_user_id = ?
              AND trim(coalesce(number, '')) != ''
            GROUP BY 1, 2
            HAVING COUNT(*) > 1
            """,
            (admin_id,),
        ).fetchall()
        for _num, _client, keep_id, _cnt in groups:
            row = conn.execute(
                "SELECT number, client_name FROM constancias WHERE id = ?",
                (keep_id,),
            ).fetchone()
            if row:
                consolidate_constancia_duplicates(
                    conn,
                    int(keep_id),
                    row[0] or "",
                    row[1] or "",
                    owner_user_id=admin_id,
                )
    except Exception:
        pass

    _meta_set(conn, flag, "done")
    return {
        "ok": True,
        "skipped": False,
        "moved_constancias": moved_c,
        "moved_trasiegos": moved_t,
        "admin_id": admin_id,
        "operator_ids": op_ids,
    }
