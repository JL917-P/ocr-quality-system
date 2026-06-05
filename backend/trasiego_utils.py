"""Detección y reparación de filas TRASIEGOS con columnas desplazadas (legacy p_final)."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

LOT_PATTERN = re.compile(r"^[A-Z]{2,3}-\d+", re.IGNORECASE)
DATE_SHORT = re.compile(
    r"^(ene|feb|mar|abr|may|jun|jul|ago|sep|set|oct|nov|dic)\d{2}$",
    re.IGNORECASE,
)


def _str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def is_shifted_trasiego(rec: dict[str, Any]) -> bool:
    """True si los valores parecen desplazados (p_final vacío y cantidad parece fecha)."""
    p_final = _str(rec.get("p_final"))
    lote = _str(rec.get("lote"))
    cantidad = _str(rec.get("cantidad"))
    f_v = _str(rec.get("f_v"))
    if p_final:
        return False
    if not lote:
        return False
    if LOT_PATTERN.match(lote):
        return False
    if DATE_SHORT.match(cantidad) or DATE_SHORT.match(f_v):
        return True
    if len(lote) > 12 and not LOT_PATTERN.match(lote):
        return True
    return False


def repair_shifted_trasiego(rec: dict[str, Any]) -> dict[str, Any]:
    if not is_shifted_trasiego(rec):
        return rec
    return {
        **rec,
        "p_final": _str(rec.get("lote")),
        "lote": _str(rec.get("f_p")),
        "f_p": _str(rec.get("f_v")),
        "f_v": _str(rec.get("cantidad")),
        "cantidad": "",
    }


def trasiego_row_dict(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0],
        "fecha": row[1] or "",
        "mp": row[2] or "",
        "f_ingreso": row[3] or "",
        "estado": row[4] or "",
        "p_final": row[5] or "",
        "lote": row[6] or "",
        "f_p": row[7] or "",
        "f_v": row[8] or "",
        "cantidad": row[9] or "",
        "created_at": row[10],
        "updated_at": row[11],
    }


def repair_trasiego_in_sqlite(conn: sqlite3.Connection, trasiego_id: int) -> bool:
    row = conn.execute(
        """
        SELECT id, fecha, mp, f_ingreso, estado, p_final, lote, f_p, f_v, cantidad, created_at, updated_at
        FROM trasiegos WHERE id = ?
        """,
        (trasiego_id,),
    ).fetchone()
    if not row:
        return False
    rec = trasiego_row_dict(row)
    fixed = repair_shifted_trasiego(rec)
    if fixed == rec:
        return False
    conn.execute(
        """
        UPDATE trasiegos
        SET p_final = ?, lote = ?, f_p = ?, f_v = ?, cantidad = ?
        WHERE id = ?
        """,
        (
            fixed.get("p_final") or None,
            fixed.get("lote") or None,
            fixed.get("f_p") or None,
            fixed.get("f_v") or None,
            fixed.get("cantidad") or None,
            trasiego_id,
        ),
    )
    return True


def repair_all_trasiegos_in_sqlite(conn: sqlite3.Connection) -> int:
    ids = [int(r[0]) for r in conn.execute("SELECT id FROM trasiegos").fetchall()]
    repaired = 0
    for row_id in ids:
        if repair_trasiego_in_sqlite(conn, row_id):
            repaired += 1
    return repaired
