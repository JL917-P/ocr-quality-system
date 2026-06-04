"""URLs públicas de la aplicación (panel admin en producción)."""
from __future__ import annotations

import os

# Producción Render (panel principal)
DEFAULT_PUBLIC_APP_URL = "https://ocr-quality-system.onrender.com"

PUBLIC_APP_URL = os.getenv("PUBLIC_APP_URL", DEFAULT_PUBLIC_APP_URL).rstrip("/")
ADMIN_PATH = "/admin"
ADMIN_URL = f"{PUBLIC_APP_URL}{ADMIN_PATH}"
PANEL_PATH = ADMIN_PATH


def app_config_payload() -> dict[str, str]:
    return {
        "base_url": PUBLIC_APP_URL,
        "admin_url": ADMIN_URL,
        "admin_path": ADMIN_PATH,
        "panel_path": PANEL_PATH,
    }
