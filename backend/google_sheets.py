"""
Google Sheets como respaldo de SQLite (fuente de verdad).

Optimizado: caché de worksheets, mínimas lecturas, append por lotes, retry 429.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parent
DEFAULT_CREDENTIALS = BACKEND_ROOT.parent / "secrets" / "chatbot-registros-7bc8f90366fd.json"
CREDENTIALS_PATH = Path(os.getenv("GOOGLE_CREDENTIALS_PATH", str(DEFAULT_CREDENTIALS)))
SPREADSHEET_NAME = os.getenv("GOOGLE_SPREADSHEET_NAME", "ocr_control_calidad")

BATCH_APPEND_SIZE = int(os.getenv("GOOGLE_SHEETS_BATCH_SIZE", "50"))
MIGRATE_TAB_PAUSE_SEC = float(os.getenv("GOOGLE_SHEETS_TAB_PAUSE_SEC", "3"))
RETRY_DELAYS_SEC = (2, 5, 10)

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
)

TAB_CLIENTES = os.getenv("GOOGLE_SHEET_TAB_CLIENTES", "CLIENTES")
TAB_PRODUCTOS = os.getenv("GOOGLE_SHEET_TAB_PRODUCTOS", "PRODUCTOS")
TAB_TRANSPORTES = os.getenv("GOOGLE_SHEET_TAB_TRANSPORTES", "TRANSPORTES")
TAB_CONSTANCIAS = os.getenv("GOOGLE_SHEET_TAB_CONSTANCIAS", "CONSTANCIAS")
TAB_TRASIEGOS = os.getenv("GOOGLE_SHEET_TAB_TRASIEGOS", "TRASIEGOS")

REQUIRED_TABS = (
    TAB_CLIENTES,
    TAB_PRODUCTOS,
    TAB_TRANSPORTES,
    TAB_CONSTANCIAS,
    TAB_TRASIEGOS,
)

_client: Optional[gspread.Client] = None
_spreadsheet: Optional[gspread.Spreadsheet] = None
_credentials: Optional[Credentials] = None
_credentials_source: Optional[str] = None  # "env" | "file"
_worksheet_cache: dict[str, gspread.Worksheet] = {}
_tab_state_cache: dict[str, "TabState"] = {}


@dataclass
class SheetMetrics:
    reads: int = 0
    writes: int = 0
    rows_exported: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "reads": self.reads,
            "writes": self.writes,
            "rows_exported": self.rows_exported,
        }


_metrics = SheetMetrics()


def get_metrics() -> SheetMetrics:
    return _metrics


def reset_metrics() -> None:
    global _metrics
    _metrics = SheetMetrics()


@dataclass
class TabState:
    tab: str
    sheet: gspread.Worksheet
    headers: Sequence[str]
    existing_ids: set[int] = field(default_factory=set)
    has_header: bool = False


# —— Conexión y caché ——

def _is_quota_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "429" in text or "quota exceeded" in text


def _with_retry(operation: str, fn: Callable[[], Any]) -> Any:
    last_exc: Optional[BaseException] = None
    for attempt in range(3):
        try:
            return fn()
        except gspread.exceptions.APIError as exc:
            last_exc = exc
            if _is_quota_error(exc) and attempt < 2:
                delay = RETRY_DELAYS_SEC[attempt]
                logger.warning(
                    "[SHEETS] 429 en %s — reintento %s/3 en %ss",
                    operation,
                    attempt + 2,
                    delay,
                )
                time.sleep(delay)
            else:
                raise
        except Exception as exc:
            last_exc = exc
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Operación fallida: {operation}")


def _load_credentials() -> Optional[Credentials]:
    """Carga credenciales: GOOGLE_SERVICE_ACCOUNT_JSON (Render) o archivo local."""
    global _credentials, _credentials_source
    logger.warning(
        "[DEBUG] GOOGLE_SERVICE_ACCOUNT_JSON existe=%s",
        bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")),
    )
    logger.warning(
        "[DEBUG] GOOGLE_CREDENTIALS_PATH=%s",
        os.getenv("GOOGLE_CREDENTIALS_PATH"),
    )
    logger.warning("[DEBUG] VERSION_ENV_SUPPORT_V1")
    if _credentials is not None:
        return _credentials

    env_json = (os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or "").strip()
    if env_json:
        try:
            info = json.loads(env_json)
            _credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
            _credentials_source = "env"
            logger.info("Google Sheets: credenciales cargadas desde ENV")
            return _credentials
        except Exception:
            logger.exception(
                "Google Sheets: error al leer credenciales desde GOOGLE_SERVICE_ACCOUNT_JSON"
            )
            return None

    if not CREDENTIALS_PATH.is_file():
        logger.warning("Google Sheets: credenciales no encontradas en %s", CREDENTIALS_PATH)
        return None
    try:
        _credentials = Credentials.from_service_account_file(str(CREDENTIALS_PATH), scopes=SCOPES)
        _credentials_source = "file"
        logger.info("Google Sheets: credenciales cargadas desde archivo")
        return _credentials
    except Exception:
        logger.exception("Google Sheets: error al leer credenciales desde %s", CREDENTIALS_PATH)
        return None


def get_gspread_client() -> Optional[gspread.Client]:
    global _client
    if _client is not None:
        return _client
    credentials = _load_credentials()
    if credentials is None:
        return None
    try:
        _client = gspread.authorize(credentials)
        return _client
    except Exception:
        logger.exception("Google Sheets: error al autorizar con gspread")
        return None


def get_spreadsheet() -> Optional[gspread.Spreadsheet]:
    global _spreadsheet
    if _spreadsheet is not None:
        return _spreadsheet
    client = get_gspread_client()
    if client is None:
        return None
    try:
        _spreadsheet = _with_retry("open_spreadsheet", lambda: client.open(SPREADSHEET_NAME))
        return _spreadsheet
    except gspread.SpreadsheetNotFound:
        logger.warning("Google Sheets: spreadsheet '%s' no encontrado", SPREADSHEET_NAME)
        return None
    except Exception:
        logger.exception("Google Sheets: error al abrir spreadsheet '%s'", SPREADSHEET_NAME)
        return None


def _get_worksheet_cached(tab_name: str) -> Optional[gspread.Worksheet]:
    if tab_name in _worksheet_cache:
        return _worksheet_cache[tab_name]
    spreadsheet = get_spreadsheet()
    if spreadsheet is None:
        return None
    try:
        ws = _with_retry(f"worksheet({tab_name})", lambda: spreadsheet.worksheet(tab_name))
        _worksheet_cache[tab_name] = ws
        return ws
    except gspread.WorksheetNotFound:
        logger.warning("Google Sheets: pestaña '%s' no existe", tab_name)
        return None
    except Exception:
        logger.exception("Google Sheets: error al abrir pestaña '%s'", tab_name)
        return None


def get_clients_sheet() -> Optional[gspread.Worksheet]:
    return _get_worksheet_cached(TAB_CLIENTES)


def get_products_sheet() -> Optional[gspread.Worksheet]:
    return _get_worksheet_cached(TAB_PRODUCTOS)


def get_transports_sheet() -> Optional[gspread.Worksheet]:
    return _get_worksheet_cached(TAB_TRANSPORTES)


def get_constancias_sheet() -> Optional[gspread.Worksheet]:
    return _get_worksheet_cached(TAB_CONSTANCIAS)


def get_trasiegos_sheet() -> Optional[gspread.Worksheet]:
    return _get_worksheet_cached(TAB_TRASIEGOS)


def reset_connection() -> None:
    global _client, _spreadsheet, _credentials, _credentials_source, _worksheet_cache, _tab_state_cache
    _client = None
    _spreadsheet = None
    _credentials = None
    _credentials_source = None
    _worksheet_cache.clear()
    _tab_state_cache.clear()


# —— Lectura mínima (columna id, una vez por pestaña en caché) ——

def _fmt_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _parse_id_cell(value: str) -> Optional[int]:
    value = (value or "").strip()
    if not value or value.lower() == "id":
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "items_json": ("items_json", "items", "productos_json", "items json"),
}


def read_sheet_rows(tab: str, headers: Sequence[str]) -> list[dict[str, str]]:
    """Lee todas las filas de una pestaña como dicts {header: valor_str}."""
    sheet = _get_worksheet_cached(tab)
    if sheet is None:
        return []

    def _read() -> list[list[str]]:
        return sheet.get_all_values()

    raw = _with_retry(f"get_all_values({tab})", _read)
    global _metrics
    _metrics.reads += 1
    if not raw:
        return []

    header_row = [(c or "").strip().lower() for c in raw[0]]
    col_map: dict[str, int] = {}
    for h in headers:
        alias_keys = COLUMN_ALIASES.get(h, (h,))
        for key in alias_keys:
            lookup = key.lower()
            if lookup in header_row:
                col_map[h] = header_row.index(lookup)
                break

    records: list[dict[str, str]] = []
    for row in raw[1:]:
        if not any((c or "").strip() for c in row):
            continue
        rec: dict[str, str] = {}
        for h in headers:
            idx = col_map.get(h)
            rec[h] = (row[idx] if idx is not None and idx < len(row) else "") or ""
        records.append(rec)
    return records


def _read_id_column(sheet: gspread.Worksheet) -> tuple[set[int], bool]:
    """Una lectura: columna A. Retorna (ids, tiene_fila_util)."""
    global _metrics

    def _read() -> list[str]:
        return sheet.col_values(1)

    col = _with_retry(f"col_values_id({sheet.title})", _read)
    _metrics.reads += 1
    ids: set[int] = set()
    has_header = False
    for i, cell in enumerate(col):
        if i == 0 and (cell or "").strip().lower() == "id":
            has_header = True
            continue
        parsed = _parse_id_cell(cell)
        if parsed is not None:
            ids.add(parsed)
            has_header = True
    return ids, has_header or len(col) > 0


def get_tab_state(tab: str, headers: Sequence[str]) -> Optional[TabState]:
    if tab in _tab_state_cache:
        return _tab_state_cache[tab]
    sheet = _get_worksheet_cached(tab)
    if sheet is None:
        return None
    existing_ids, has_header = _read_id_column(sheet)
    state = TabState(
        tab=tab,
        sheet=sheet,
        headers=headers,
        existing_ids=existing_ids,
        has_header=has_header,
    )
    _tab_state_cache[tab] = state
    return state


def get_existing_ids(sheet: gspread.Worksheet) -> set[int]:
    """Compatibilidad: usa caché TabState si existe, si no lee columna id una vez."""
    for state in _tab_state_cache.values():
        if state.sheet.id == sheet.id:
            return set(state.existing_ids)
    ids, _ = _read_id_column(sheet)
    return ids


# —— Escritura (append / batch, sin get_all_values) ——

def _append_rows_batch(state: TabState, rows: list[list[Any]]) -> int:
    """Append en lotes; actualiza caché de ids. Retorna filas escritas."""
    global _metrics
    if not rows:
        return 0

    new_rows: list[list[Any]] = []
    for row in rows:
        rid = _parse_id_cell(str(row[0]) if row else "")
        if rid is None:
            continue
        if rid in state.existing_ids:
            continue
        new_rows.append([_fmt_cell(v) for v in row])

    if not new_rows:
        return 0

    to_write: list[list[Any]] = []
    if not state.has_header:
        to_write.append(list(state.headers))
        state.has_header = True

    to_write.extend(new_rows)

    for i in range(0, len(to_write), BATCH_APPEND_SIZE):
        chunk = to_write[i : i + BATCH_APPEND_SIZE]

        def _append(chunk_rows: list = chunk) -> None:
            state.sheet.append_rows(chunk_rows, value_input_option="USER_ENTERED")

        _with_retry(f"append_rows({state.tab})", _append)
        _metrics.writes += 1

    for row in new_rows:
        rid = _parse_id_cell(str(row[0]))
        if rid is not None:
            state.existing_ids.add(rid)

    exported = len(new_rows)
    _metrics.rows_exported += exported
    return exported


def _append_single(
    tab: str,
    headers: Sequence[str],
    values: Sequence[Any],
) -> bool:
    state = get_tab_state(tab, headers)
    if state is None:
        return False
    return _append_rows_batch(state, [list(values)]) > 0 or (
        _parse_id_cell(str(values[0])) in state.existing_ids if values else False
    )


def _col_letter(n: int) -> str:
    """Índice de columna 1-based → letra(s) de Excel (A, B, …, AA)."""
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _invalidate_tab_state(tab: str) -> None:
    _tab_state_cache.pop(tab, None)


def _find_row_number_by_id(sheet: gspread.Worksheet, record_id: int) -> Optional[int]:
    """Número de fila 1-based donde aparece record_id en columna A."""
    global _metrics

    def _read() -> list[str]:
        return sheet.col_values(1)

    col = _with_retry(f"col_values_id({sheet.title})", _read)
    _metrics.reads += 1
    for i, cell in enumerate(col):
        if i == 0 and (cell or "").strip().lower() == "id":
            continue
        if _parse_id_cell(cell) == record_id:
            return i + 1
    return None


def delete_row_by_id(tab: str, headers: Sequence[str], record_id: int) -> bool:
    """Elimina la fila con ese id en Google Sheets (no-op si no existe)."""
    state = get_tab_state(tab, headers)
    if state is None:
        return False
    row_num = _find_row_number_by_id(state.sheet, record_id)
    if row_num is None:
        return True

    def _delete() -> None:
        state.sheet.delete_rows(row_num)

    _with_retry(f"delete_row({tab},{record_id})", _delete)
    global _metrics
    _metrics.writes += 1
    state.existing_ids.discard(record_id)
    _invalidate_tab_state(tab)
    return True


def upsert_row_by_id(tab: str, headers: Sequence[str], values: Sequence[Any]) -> bool:
    """Actualiza la fila existente por id o la agrega si no está en Sheets."""
    state = get_tab_state(tab, headers)
    if state is None:
        return False
    record_id = _parse_id_cell(str(values[0]) if values else "")
    if record_id is None:
        return False
    row_values = [_fmt_cell(v) for v in values]
    row_num = _find_row_number_by_id(state.sheet, record_id)
    if row_num is not None:
        end_col = _col_letter(len(headers))
        range_name = f"A{row_num}:{end_col}{row_num}"

        def _update() -> None:
            state.sheet.update(
                [row_values],
                range_name=range_name,
                value_input_option="USER_ENTERED",
            )

        _with_retry(f"update_row({tab},{record_id})", _update)
        global _metrics
        _metrics.writes += 1
        state.existing_ids.add(record_id)
        return True
    return _append_rows_batch(state, [row_values]) > 0


# —— Logs [SYNC] ——

def log_sync_sqlite_ok(entity: str, record_id: Any) -> None:
    logger.info("[SYNC] SQLITE OK | %s | id=%s", entity, record_id)


def log_sync_sheets_ok(entity: str, record_id: Any) -> None:
    logger.info("[SYNC] SHEETS OK | %s | id=%s", entity, record_id)


def log_sync_sheets_error(entity: str, record_id: Any, reason: str = "") -> None:
    msg = f" | {reason}" if reason else ""
    logger.warning("[SYNC] SHEETS ERROR | %s | id=%s%s", entity, record_id, msg)


def run_sync_after_create(entity: str, record_id: Any, sync_fn: Callable[[], bool]) -> None:
    log_sync_sqlite_ok(entity, record_id)
    try:
        if sync_fn():
            log_sync_sheets_ok(entity, record_id)
        else:
            log_sync_sheets_error(entity, record_id)
    except Exception as exc:
        log_sync_sheets_error(entity, record_id, str(exc))
        logger.exception("[SYNC] SHEETS ERROR detalle | %s | id=%s", entity, record_id)


def run_sync_after_delete(entity: str, record_id: Any, sync_fn: Callable[[], bool]) -> None:
    logger.info("[SYNC] DELETE SQLITE OK | %s | id=%s", entity, record_id)
    try:
        if sync_fn():
            logger.info("[SYNC] DELETE SHEETS OK | %s | id=%s", entity, record_id)
        else:
            log_sync_sheets_error(entity, record_id, "delete failed")
    except Exception as exc:
        log_sync_sheets_error(entity, record_id, str(exc))
        logger.exception("[SYNC] DELETE SHEETS ERROR | %s | id=%s", entity, record_id)


def sync_client_created(client_id: int, name: str, ruc: str | None, created_at: str) -> bool:
    return sync_client_upsert(client_id, name, ruc, created_at)


def sync_client_upsert(client_id: int, name: str, ruc: str | None, created_at: str) -> bool:
    return upsert_row_by_id(
        TAB_CLIENTES,
        HEADERS_CLIENTES,
        (client_id, name, ruc, created_at),
    )


def sync_product_created(product_id: int, data: dict[str, Any], created_at: str) -> bool:
    return sync_product_upsert(product_id, data, created_at)


def sync_product_upsert(product_id: int, data: dict[str, Any], created_at: str) -> bool:
    return upsert_row_by_id(
        TAB_PRODUCTOS,
        HEADERS_PRODUCTOS,
        (
            product_id,
            data.get("name"),
            data.get("code"),
            data.get("origin"),
            data.get("um"),
            data.get("active"),
            data.get("lot"),
            data.get("production_text"),
            data.get("expiration_text"),
            data.get("humidity"),
            data.get("broken_grains"),
            data.get("chalky_1"),
            data.get("chalky_2"),
            data.get("damaged_grains"),
            data.get("whiteness"),
            created_at,
        ),
    )


def sync_transport_created(transport_id: int, plate: str, created_at: str) -> bool:
    return sync_transport_upsert(transport_id, plate, created_at)


def sync_transport_upsert(transport_id: int, plate: str, created_at: str) -> bool:
    return upsert_row_by_id(
        TAB_TRANSPORTES,
        HEADERS_TRANSPORTES,
        (transport_id, plate, created_at),
    )


def sync_trasiego_created(
    trasiego_id: int,
    fecha: str | None,
    mp: str | None,
    f_ingreso: str | None,
    estado: str | None,
    p_final: str | None,
    lote: str | None,
    f_p: str | None,
    f_v: str | None,
    cantidad: str | None,
    created_at: str,
    updated_at: str,
) -> bool:
    return sync_trasiego_upsert(
        trasiego_id,
        fecha,
        mp,
        f_ingreso,
        estado,
        p_final,
        lote,
        f_p,
        f_v,
        cantidad,
        created_at,
        updated_at,
    )


def sync_trasiego_upsert(
    trasiego_id: int,
    fecha: str | None,
    mp: str | None,
    f_ingreso: str | None,
    estado: str | None,
    p_final: str | None,
    lote: str | None,
    f_p: str | None,
    f_v: str | None,
    cantidad: str | None,
    created_at: str,
    updated_at: str,
) -> bool:
    return upsert_row_by_id(
        TAB_TRASIEGOS,
        HEADERS_TRASIEGOS,
        (
            trasiego_id, fecha, mp, f_ingreso, estado, p_final, lote,
            f_p, f_v, cantidad, created_at, updated_at,
        ),
    )


def sync_constancia_created(
    constancia_id: int,
    number: str | None,
    issue_date: str | None,
    client_name: str | None,
    transport_plate: str | None,
    fumigacion: int,
    calidad: int,
    status: str,
    items_json: str,
    created_at: str,
) -> bool:
    return upsert_row_by_id(
        TAB_CONSTANCIAS,
        HEADERS_CONSTANCIAS,
        (
            constancia_id, number, issue_date, client_name, transport_plate,
            fumigacion, calidad, status, items_json, created_at,
        ),
    )


def sync_constancia_upsert(
    constancia_id: int,
    number: str | None,
    issue_date: str | None,
    client_name: str | None,
    transport_plate: str | None,
    fumigacion: int,
    calidad: int,
    status: str,
    items_json: str,
    created_at: str,
) -> bool:
    return sync_constancia_created(
        constancia_id,
        number,
        issue_date,
        client_name,
        transport_plate,
        fumigacion,
        calidad,
        status,
        items_json,
        created_at,
    )


# —— Migración / resync por lotes ——

HEADERS_CLIENTES = ("id", "name", "ruc", "created_at")
HEADERS_PRODUCTOS = (
    "id", "name", "code", "origin", "um", "active", "lot",
    "production_text", "expiration_text", "humidity", "broken_grains",
    "chalky_1", "chalky_2", "damaged_grains", "whiteness", "created_at",
)
HEADERS_TRANSPORTES = ("id", "plate", "created_at")
HEADERS_CONSTANCIAS = (
    "id", "number", "issue_date", "client_name", "transport_plate",
    "fumigacion", "calidad", "status", "items_json", "created_at",
)
HEADERS_TRASIEGOS = (
    "id", "fecha", "mp", "f_ingreso", "estado", "p_final", "lote",
    "f_p", "f_v", "cantidad", "created_at", "updated_at",
)

ENTITY_SPECS: list[tuple[str, str, Sequence[str], str]] = [
    (TAB_CLIENTES, "clients", HEADERS_CLIENTES, "SELECT id, name, ruc, created_at FROM clients ORDER BY id"),
    (
        TAB_PRODUCTOS,
        "products",
        HEADERS_PRODUCTOS,
        """
        SELECT id, name, code, origin, um, active, lot, production_text, expiration_text,
               humidity, broken_grains, chalky_1, chalky_2, damaged_grains, whiteness, created_at
        FROM products ORDER BY id
        """,
    ),
    (TAB_TRANSPORTES, "transports", HEADERS_TRANSPORTES, "SELECT id, plate, created_at FROM transports ORDER BY id"),
    (
        TAB_CONSTANCIAS,
        "constancias",
        HEADERS_CONSTANCIAS,
        """
        SELECT id, number, issue_date, client_name, transport_plate, fumigacion, calidad, status, items_json, created_at
        FROM constancias ORDER BY id
        """,
    ),
    (
        TAB_TRASIEGOS,
        "trasiegos",
        HEADERS_TRASIEGOS,
        """
        SELECT id, fecha, mp, f_ingreso, estado, p_final, lote, f_p, f_v, cantidad, created_at, updated_at
        FROM trasiegos ORDER BY id
        """,
    ),
]


def _row_from_sql(headers: Sequence[str], row: tuple) -> list[Any]:
    return [_fmt_cell(v) for v in row]


def _export_missing_for_tab_batch(
    conn: sqlite3.Connection,
    tab: str,
    headers: Sequence[str],
    sql: str,
) -> int:
    state = get_tab_state(tab, headers)
    if state is None:
        return 0
    rows = conn.execute(sql).fetchall()
    sheet_rows = [_row_from_sql(headers, r) for r in rows]
    return _append_rows_batch(state, sheet_rows)


def _upsert_all_for_tab_batch(
    conn: sqlite3.Connection,
    tab: str,
    headers: Sequence[str],
    sql: str,
) -> int:
    """Actualiza filas existentes y agrega las faltantes (upsert por id)."""
    if get_tab_state(tab, headers) is None:
        return 0
    rows = conn.execute(sql).fetchall()
    count = 0
    for row in rows:
        values = _row_from_sql(headers, row)
        if upsert_row_by_id(tab, headers, values):
            count += 1
    return count


def export_all_missing_from_sqlite(
    db_path: Path,
    *,
    pause_between_tabs: bool = True,
    reset: bool = True,
) -> dict[str, Any]:
    if reset:
        reset_connection()
        reset_metrics()
    if get_spreadsheet() is None:
        return {
            "ok": False,
            "error": "No hay conexión a Google Sheets",
            "total": 0,
            "by_tab": {},
            "metrics": get_metrics().as_dict(),
        }

    by_tab: dict[str, int] = {}
    total = 0
    specs = list(ENTITY_SPECS)
    with sqlite3.connect(db_path) as conn:
        for idx, (tab, _table_key, headers, sql) in enumerate(specs):
            if pause_between_tabs and idx > 0:
                logger.info("[MIGRATE] Pausa %ss antes de %s", MIGRATE_TAB_PAUSE_SEC, tab)
                time.sleep(MIGRATE_TAB_PAUSE_SEC)
            n = _upsert_all_for_tab_batch(conn, tab, headers, sql)
            by_tab[tab] = n
            total += n
            print(f"{tab}: {n} exportados")

    m = get_metrics().as_dict()
    print(f"TOTAL EXPORTADOS: {total}")
    print(f"Lecturas API: {m['reads']} | Escrituras API: {m['writes']} | Filas: {m['rows_exported']}")
    return {"ok": True, "total": total, "by_tab": by_tab, "metrics": m, "synced": total}


def run_initial_migration(db_path: Path) -> dict[str, Any]:
    print("=== MIGRACIÓN SQLite → Google Sheets (por lotes) ===")
    print("Base de datos:", db_path)
    print(f"Lote: {BATCH_APPEND_SIZE} filas | Pausa entre pestañas: {MIGRATE_TAB_PAUSE_SEC}s")
    return export_all_missing_from_sqlite(db_path, pause_between_tabs=True)


def run_manual_resync(db_path: Path) -> dict[str, Any]:
    result = export_all_missing_from_sqlite(db_path, pause_between_tabs=True)
    result["message"] = "Sincronización completada"
    result["synced"] = result.get("total", 0)
    return result


def check_startup_sheets_access() -> bool:
    logger.warning(
        "GOOGLE_SERVICE_ACCOUNT_JSON presente=%s",
        bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")),
    )
    logger.warning(
        "GOOGLE_CREDENTIALS_PATH=%s",
        os.getenv("GOOGLE_CREDENTIALS_PATH"),
    )
    logger.warning("google_sheets version = ENV_SUPPORT_V1")
    reset_connection()
    if _load_credentials() is None:
        env_json = (os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or "").strip()
        if env_json:
            logger.error(
                "[STARTUP] Sheets ERROR | GOOGLE_SERVICE_ACCOUNT_JSON inválido o incompleto"
            )
        else:
            logger.error(
                "[STARTUP] Sheets ERROR | credenciales no encontradas: %s",
                CREDENTIALS_PATH,
            )
        return False
    if get_spreadsheet() is None:
        logger.error("[STARTUP] Sheets ERROR | no se pudo abrir spreadsheet")
        return False
    for tab in REQUIRED_TABS:
        if _get_worksheet_cached(tab) is None:
            logger.error("[STARTUP] Sheets ERROR | pestaña faltante: %s", tab)
            return False
    logger.info("[STARTUP] Sheets OK | spreadsheet=%s", SPREADSHEET_NAME)
    return True


def verify_sheets_sync(db_path: Path, *, auto_sync_missing: bool = False) -> dict[str, Any]:
    reset_metrics()
    report: dict[str, Any] = {"tabs": {}, "total_missing": 0, "synced": 0}
    if get_spreadsheet() is None:
        report["error"] = "Sin conexión a Sheets"
        return report

    with sqlite3.connect(db_path) as conn:
        for tab, _table_key, headers, sql in ENTITY_SPECS:
            sqlite_ids = {int(r[0]) for r in conn.execute(sql).fetchall()}
            state = get_tab_state(tab, headers)
            sheet_ids = set(state.existing_ids) if state else set()
            missing = len(sqlite_ids - sheet_ids)
            report["tabs"][tab] = {
                "sqlite": len(sqlite_ids),
                "sheets": len(sheet_ids),
                "missing": missing,
            }
            print(f"{tab}:")
            print(f"  SQLite: {len(sqlite_ids)}")
            print(f"  Sheets: {len(sheet_ids)}")
            if missing > 0:
                print(f"  Faltan: {missing}")
                report["total_missing"] += missing
            else:
                print("  OK")

    if auto_sync_missing and report["total_missing"] > 0:
        print("Sincronizando faltantes automáticamente (por lotes)...")
        sync_result = export_all_missing_from_sqlite(
            db_path, pause_between_tabs=True, reset=False
        )
        report["synced"] = sync_result.get("total", 0)
        report["by_tab"] = sync_result.get("by_tab", {})
        report["metrics"] = sync_result.get("metrics", {})

    report["metrics"] = report.get("metrics") or get_metrics().as_dict()
    return report


def run_startup_sheets_backup_check(db_path: Path) -> None:
    if check_startup_sheets_access():
        verify_sheets_sync(db_path, auto_sync_missing=True)
    else:
        logger.warning("[STARTUP] Respaldo Sheets no disponible; SQLite sigue activo")
