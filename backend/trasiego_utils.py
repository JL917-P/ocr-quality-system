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
    rec = {
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
    if len(row) > 12:
        rec["constancia_id"] = row[12]
    return rec


def trasiego_extra_has_data(extra: dict[str, Any] | None) -> bool:
    if not extra or not isinstance(extra, dict):
        return False
    for key in ("mp", "f_ingreso_cd", "estado", "f_fumigacion", "f_liberacion"):
        if _str(extra.get(key)):
            return True
    return False


def build_trasiego_payloads_from_constancia(
    issue_date: str | None,
    items: list[dict[str, Any]],
    extra: dict[str, Any],
) -> list[dict[str, Any]]:
    fecha = _str(issue_date) or None
    mp = _str(extra.get("mp")) or None
    f_ingreso = _str(extra.get("f_ingreso_cd")) or None
    estado = _str(extra.get("estado")) or None
    payloads: list[dict[str, Any]] = []
    for item in items:
        product = _str(item.get("product"))
        if not product:
            continue
        qty = item.get("quantity")
        cantidad = None
        if qty is not None and qty != "":
            cantidad = _str(qty)
        payloads.append(
            {
                "fecha": fecha,
                "mp": mp,
                "f_ingreso": f_ingreso,
                "estado": estado,
                "p_final": product,
                "lote": _str(item.get("lot")) or None,
                "f_p": _str(item.get("production_text")) or None,
                "f_v": _str(item.get("expiration_text")) or None,
                "cantidad": cantidad,
            }
        )
    return payloads


def replace_trasiegos_for_constancia(
    conn: sqlite3.Connection,
    constancia_id: int,
    issue_date: str | None,
    items: list[dict[str, Any]],
    extra: dict[str, Any] | None,
    *,
    now: str,
) -> tuple[list[int], list[int]]:
    """Reemplaza filas de trasiego ligadas a una constancia. Retorna (nuevos_ids, eliminados_ids)."""
    deleted_ids = [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM trasiegos WHERE constancia_id = ?",
            (constancia_id,),
        ).fetchall()
    ]
    if deleted_ids:
        conn.execute("DELETE FROM trasiegos WHERE constancia_id = ?", (constancia_id,))

    if not trasiego_extra_has_data(extra):
        return [], deleted_ids

    new_ids: list[int] = []
    for payload in build_trasiego_payloads_from_constancia(issue_date, items, extra or {}):
        cursor = conn.execute(
            """
            INSERT INTO trasiegos (
                fecha, mp, f_ingreso, estado, p_final, lote, f_p, f_v, cantidad,
                created_at, updated_at, constancia_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["fecha"],
                payload["mp"],
                payload["f_ingreso"],
                payload["estado"],
                payload["p_final"],
                payload["lote"],
                payload["f_p"],
                payload["f_v"],
                payload["cantidad"],
                now,
                now,
                constancia_id,
            ),
        )
        new_ids.append(int(cursor.lastrowid))
    return new_ids, deleted_ids


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
