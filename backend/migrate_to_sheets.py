"""
Migración inicial: exporta todo el histórico de SQLite a Google Sheets.

Uso:
  cd backend
  python migrate_to_sheets.py

Variables opcionales: DATABASE_PATH, GOOGLE_CREDENTIALS_PATH
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
DEFAULT_DB = BACKEND_ROOT / "results.db"
DB_PATH = Path(os.getenv("DATABASE_PATH", str(DEFAULT_DB)))


def main() -> int:
    if not DB_PATH.is_file():
        print(f"ERROR: No existe la base de datos: {DB_PATH}")
        return 1

    from google_sheets import run_initial_migration

    result = run_initial_migration(DB_PATH)
    if not result.get("ok"):
        print("ERROR:", result.get("error", "desconocido"))
        return 1

    print("\n--- RESUMEN ---")
    for tab, count in result.get("by_tab", {}).items():
        print(f"{tab}: {count} exportados")
    print(f"TOTAL EXPORTADOS: {result.get('total', 0)}")
    metrics = result.get("metrics") or {}
    print(f"Lecturas API: {metrics.get('reads', 0)}")
    print(f"Escrituras API: {metrics.get('writes', 0)}")
    print(f"Filas exportadas (métrica): {metrics.get('rows_exported', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
