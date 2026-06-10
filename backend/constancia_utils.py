"""Snapshots históricos e historial de cambios para constancias."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

VALID_STATUSES = frozenset({"borrador", "por_confirmar", "confirmada"})


def normalize_constancia_status(value: Any) -> str:
    """Normaliza estados legacy (p. ej. '1' importado desde Sheets)."""
    text = str(value or "").strip().lower()
    if text in ("confirmada", "confirmado", "confirmed", "1", "true", "si", "sí"):
        return "confirmada"
    if text in ("por_confirmar", "por confirmar", "reserva", "pending", "0", "false", "no"):
        return "por_confirmar"
    if text in ("borrador", "draft"):
        return "borrador"
    if not text:
        return "confirmada"
    return text if text in VALID_STATUSES else "por_confirmar"


def import_constancia_status(raw: Any) -> str:
    """Estado al importar filas nuevas: por confirmar si Sheets no trae valor."""
    text = _str(raw)
    if text:
        return normalize_constancia_status(text)
    return "por_confirmar"


QUALITY_SNAPSHOT_MAP = (
    ("humidity", "humidity_snapshot"),
    ("broken_grains", "broken_grains_snapshot"),
    ("chalky_1", "chalky_grains_1_snapshot"),
    ("chalky_2", "chalky_grains_2_snapshot"),
    ("damaged_grains", "damaged_grains_snapshot"),
    ("whiteness", "whiteness_snapshot"),
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def item_field(item: dict[str, Any], *keys: str) -> Any:
    """Lee un campo del ítem priorizando snapshots."""
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return ""


def item_display_product(item: dict[str, Any]) -> str:
    return _str(item_field(item, "product_name_snapshot", "product"))


def item_display_lot(item: dict[str, Any]) -> str:
    return _str(item_field(item, "lote_snapshot", "lot"))


def item_display_production(item: dict[str, Any]) -> str:
    return _str(item_field(item, "production_date_snapshot", "production_text"))


def item_display_expiration(item: dict[str, Any]) -> str:
    return _str(item_field(item, "expiration_date_snapshot", "expiration_text"))


def item_quality_value(
    item: dict[str, Any],
    catalog_key: str,
    snapshot_key: str,
    catalog: Optional[dict[str, Any]] = None,
) -> Any:
    if catalog and catalog.get(catalog_key) is not None:
        return catalog[catalog_key]
    if snapshot_key in item and item[snapshot_key] not in (None, ""):
        return item[snapshot_key]
    legacy = {
        "humidity_snapshot": "humidity",
        "broken_grains_snapshot": "broken_grains",
        "chalky_grains_1_snapshot": "chalky_1",
        "chalky_grains_2_snapshot": "chalky_2",
        "damaged_grains_snapshot": "damaged_grains",
        "whiteness_snapshot": "whiteness",
    }.get(snapshot_key)
    if legacy and legacy in item and item[legacy] not in (None, ""):
        return item[legacy]
    return ""


def find_product_by_name(conn: sqlite3.Connection, name: str) -> Optional[dict[str, Any]]:
    target = _str(name).lower()
    if not target:
        return None
    row = conn.execute(
        """
        SELECT id, name, lot, production_text, expiration_text,
               humidity, broken_grains, chalky_1, chalky_2, damaged_grains, whiteness
        FROM products
        WHERE lower(trim(name)) = ?
        LIMIT 1
        """,
        (target,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "lot": row[2],
        "production_text": row[3],
        "expiration_text": row[4],
        "humidity": row[5],
        "broken_grains": row[6],
        "chalky_1": row[7],
        "chalky_2": row[8],
        "damaged_grains": row[9],
        "whiteness": row[10],
    }


def build_item_snapshot(
    item: dict[str, Any],
    catalog: Optional[dict[str, Any]],
    previous: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Construye snapshot completo; la calidad siempre se toma del catálogo cuando existe."""
    product_name = _str(item.get("product") or item.get("product_name_snapshot"))
    lot = _str(item.get("lot") or item.get("lote_snapshot"))
    production = _str(item.get("production_text") or item.get("production_date_snapshot"))
    expiration = _str(item.get("expiration_text") or item.get("expiration_date_snapshot"))
    quantity = item.get("quantity")

    snap: dict[str, Any] = {
        "product_id": item.get("product_id") or (catalog or {}).get("id") or (previous or {}).get("product_id"),
        "product": product_name,
        "product_name_snapshot": product_name,
        "lot": lot,
        "lote_snapshot": lot,
        "production_text": production,
        "production_date_snapshot": production,
        "expiration_text": expiration,
        "expiration_date_snapshot": expiration,
    }
    if quantity not in (None, ""):
        snap["quantity"] = quantity

    for cat_key, snap_key in QUALITY_SNAPSHOT_MAP:
        if catalog and catalog.get(cat_key) is not None:
            snap[snap_key] = catalog[cat_key]
        elif snap_key in item and item[snap_key] not in (None, ""):
            snap[snap_key] = item[snap_key]
        elif previous and snap_key in previous:
            snap[snap_key] = previous[snap_key]

    return snap


def normalize_items_for_save(
    conn: sqlite3.Connection,
    items: list[dict[str, Any]],
    previous_items: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    prev_list = previous_items or []
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        product_name = _str(raw.get("product") or raw.get("product_name_snapshot"))
        if not product_name:
            continue
        catalog = find_product_by_name(conn, product_name)
        previous = prev_list[idx] if idx < len(prev_list) else None
        normalized.append(build_item_snapshot(raw, catalog, previous))
    return normalized


def constancia_header_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": _str(payload.get("number")) or None,
        "issue_date": _str(payload.get("issue_date")) or None,
        "client_name": _str(payload.get("client_name")) or None,
        "transport_plate": _str(payload.get("transport_plate")) or None,
        "fumigacion": 1 if payload.get("fumigacion", True) else 0,
        "calidad": 1 if payload.get("calidad", True) else 0,
        "status": payload.get("status") or "confirmada",
    }


HEADER_HISTORY_FIELDS = (
    ("number", "número"),
    ("issue_date", "fecha_emisión"),
    ("client_name", "cliente"),
    ("transport_plate", "transporte"),
    ("fumigacion", "fumigación"),
    ("calidad", "calidad"),
    ("status", "estado"),
)

ITEM_HISTORY_FIELDS = (
    ("product_name_snapshot", "producto"),
    ("lote_snapshot", "lote"),
    ("production_date_snapshot", "fecha_producción"),
    ("expiration_date_snapshot", "fecha_vencimiento"),
    ("quantity", "cantidad"),
    ("humidity_snapshot", "humedad"),
    ("broken_grains_snapshot", "quebrados"),
    ("chalky_grains_1_snapshot", "tizados_1"),
    ("chalky_grains_2_snapshot", "tizados_2"),
    ("damaged_grains_snapshot", "dañados"),
    ("whiteness_snapshot", "blancura"),
)


def _fmt_history(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(value)
    return str(value)


def record_constancia_history(
    conn: sqlite3.Connection,
    constancia_id: int,
    old_header: dict[str, Any],
    new_header: dict[str, Any],
    old_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    usuario: str,
) -> None:
    now = utc_now_iso()
    user = _str(usuario) or "admin"

    for field, label in HEADER_HISTORY_FIELDS:
        old_val = _fmt_history(old_header.get(field))
        new_val = _fmt_history(new_header.get(field))
        if old_val != new_val:
            conn.execute(
                """
                INSERT INTO constancia_history
                    (constancia_id, fecha, usuario, campo, valor_anterior, valor_nuevo)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (constancia_id, now, user, label, old_val, new_val),
            )

    max_len = max(len(old_items), len(new_items))
    for idx in range(max_len):
        old_item = old_items[idx] if idx < len(old_items) else {}
        new_item = new_items[idx] if idx < len(new_items) else {}
        prefix = f"item_{idx + 1}"
        for field, label in ITEM_HISTORY_FIELDS:
            old_val = _fmt_history(old_item.get(field, ""))
            new_val = _fmt_history(new_item.get(field, ""))
            if old_val != new_val:
                conn.execute(
                    """
                    INSERT INTO constancia_history
                        (constancia_id, fecha, usuario, campo, valor_anterior, valor_nuevo)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (constancia_id, now, user, f"{prefix}.{label}", old_val, new_val),
                )


def parse_items_json(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def items_json_is_empty(raw: str) -> bool:
    return len(parse_items_json(raw or "[]")) == 0


def constancia_identity_key(number: Any, client_name: Any) -> tuple[str, str]:
    """Clave única operativa: número + cliente (mismo número puede repetirse entre clientes)."""
    return (_str(number).lower(), _str(client_name).lower())


def find_items_json_for_constancia(
    conn: sqlite3.Connection,
    number: str,
    client_name: str,
    exclude_id: Optional[int] = None,
) -> Optional[str]:
    num = _str(number)
    client = _str(client_name).lower()
    if not num:
        return None
    sql = """
        SELECT items_json FROM constancias
        WHERE trim(coalesce(number, '')) = ?
          AND lower(trim(coalesce(client_name, ''))) = ?
          AND items_json IS NOT NULL
          AND trim(items_json) NOT IN ('', '[]')
    """
    params: list[Any] = [num, client]
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)
    sql += " ORDER BY length(items_json) DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def consolidate_constancia_duplicates(
    conn: sqlite3.Connection,
    keep_id: int,
    number: str,
    client_name: str,
) -> list[int]:
    """Elimina otras constancias con el mismo número y cliente."""
    num = _str(number)
    client = _str(client_name).lower()
    if not num:
        return []
    rows = conn.execute(
        """
        SELECT id FROM constancias
        WHERE trim(coalesce(number, '')) = ?
          AND lower(trim(coalesce(client_name, ''))) = ?
          AND id != ?
        """,
        (num, client, keep_id),
    ).fetchall()
    removed: list[int] = []
    for (row_id,) in rows:
        conn.execute("DELETE FROM constancia_history WHERE constancia_id = ?", (row_id,))
        conn.execute("DELETE FROM constancias WHERE id = ?", (row_id,))
        removed.append(int(row_id))
    return removed


def issue_date_sort_key(issue_date: Any) -> tuple[int, int, int]:
    """Clave (año, mes, día) para ordenar por fecha de emisión."""
    text = _str(issue_date)
    if not text:
        return (0, 0, 0)
    iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if iso:
        return (int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    slash4 = re.match(r"^(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})$", text)
    if slash4:
        return (int(slash4.group(3)), int(slash4.group(2)), int(slash4.group(1)))
    slash2 = re.match(r"^(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{2})$", text)
    if slash2:
        yy = int(slash2.group(3))
        year = 2000 + yy if yy < 100 else yy
        return (year, int(slash2.group(2)), int(slash2.group(1)))
    return (0, 0, 0)


def sort_constancia_rows_by_issue_date(rows: list[tuple]) -> list[tuple]:
    """Más reciente primero según fecha de emisión (independiente de id o status)."""
    return sorted(rows, key=lambda r: issue_date_sort_key(r[2]), reverse=True)


def dedupe_constancia_rows(rows: list[tuple]) -> list[tuple]:
    """Por número+cliente conserva la fila con más productos (solo duplicados reales)."""
    best_by_key: dict[tuple[str, str], tuple] = {}
    without_number: list[tuple] = []
    for row in rows:
        number = _str(row[1])
        if not number:
            without_number.append(row)
            continue
        key = constancia_identity_key(number, row[3])
        if key not in best_by_key:
            best_by_key[key] = row
            continue
        prev = best_by_key[key]
        if len(parse_items_json(row[8])) > len(parse_items_json(prev[8])):
            best_by_key[key] = row
    merged = list(best_by_key.values()) + without_number
    return sort_constancia_rows_by_issue_date(merged)


def restore_items_from_history(conn: sqlite3.Connection, constancia_id: int) -> list[dict[str, Any]]:
    """Reconstruye items desde el historial (último valor conocido por campo)."""
    label_to_snap = {label: snap for snap, label in ITEM_HISTORY_FIELDS}
    legacy_keys = {
        "producto": "product",
        "lote": "lot",
        "fecha_producción": "production_text",
        "fecha_vencimiento": "expiration_text",
        "cantidad": "quantity",
        "humedad": "humidity",
        "quebrados": "broken_grains",
        "tizados_1": "chalky_1",
        "tizados_2": "chalky_2",
        "dañados": "damaged_grains",
        "blancura": "whiteness",
    }
    rows = conn.execute(
        """
        SELECT campo, valor_nuevo FROM constancia_history
        WHERE constancia_id = ? AND campo LIKE 'item_%'
        ORDER BY id DESC
        """,
        (constancia_id,),
    ).fetchall()
    items_by_idx: dict[int, dict[str, Any]] = {}
    pattern = re.compile(r"^item_(\d+)\.(.+)$")
    for campo, valor_nuevo in rows:
        match = pattern.match(_str(campo))
        if not match:
            continue
        idx = int(match.group(1)) - 1
        label = match.group(2)
        snap_key = label_to_snap.get(label)
        if not snap_key:
            continue
        bucket = items_by_idx.setdefault(idx, {})
        if snap_key in bucket:
            continue
        val = valor_nuevo
        if label == "cantidad":
            try:
                val = float(valor_nuevo) if "." in str(valor_nuevo) else int(valor_nuevo)
            except (ValueError, TypeError):
                val = valor_nuevo
        bucket[snap_key] = val
        legacy = legacy_keys.get(label)
        if legacy:
            bucket[legacy] = val
    return [items_by_idx[i] for i in sorted(items_by_idx)]
