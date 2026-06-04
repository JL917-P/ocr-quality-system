# Control de Calidad · OCR Logística

Panel administrativo y API OCR (constancias, productos, trasiegos, trazabilidad).

## URL de producción (panel principal)

**https://ocr-quality-system.onrender.com/admin**

- Usuario por defecto: `admin` / `123456` (cambiar en `frontend/auth-gate.js` antes de uso público)
- Raíz del sitio `/` redirige a `/admin`
- Health: https://ocr-quality-system.onrender.com/health

La ruta `/capture` existe solo como **OCR móvil opcional**; no es la entrada principal.

## Estructura

```
├── backend/
│   ├── app.py              # FastAPI
│   ├── app_config.py       # PUBLIC_APP_URL, ADMIN_URL
│   ├── google_sheets.py    # Sync creaciones → Sheets
│   └── requirements.txt
├── frontend/
│   ├── admin.html          # Panel (ruta /admin)
│   └── capture.html        # OCR móvil opcional (/capture)
├── secrets/                # Credenciales Google (no subir a GitHub)
├── Dockerfile
└── render.yaml
```

## Rutas FastAPI (resumen)

| Método | Ruta | Uso |
|--------|------|-----|
| GET | `/` | Redirección → `/admin` |
| GET | `/admin` | Panel administrativo |
| GET | `/capture` | Captura móvil (opcional) |
| GET | `/health` | Estado del servicio |
| GET | `/api/app-config` | URL base y panel |
| GET/POST/PUT/DELETE | `/api/*` | API REST (SQLite) |

No hay `APIRouter` ni `include_router`; todo está en `app.py`.

## Desarrollo local (opcional)

Solo para pruebas en tu PC. **No es la URL de producción.**

```powershell
cd backend
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

- Panel local: http://127.0.0.1:8000/admin (misma app, otro host)
- Las peticiones `fetch("/api/...")` usan rutas relativas y funcionan en local y en Render

Variable opcional en local:

```powershell
$env:PUBLIC_APP_URL = "http://127.0.0.1:8000"
```

Si no la defines, `app_config.py` sigue apuntando por defecto a la URL de Render.

## Google Sheets (pruebas)

La sincronización corre en el **mismo backend** (local o Render):

1. Coloca `secrets/chatbot-registros-1bef43c0e1a6.json`
2. Comparte el spreadsheet `ocr_control_calidad` con la cuenta de servicio
3. Crea un registro (cliente, producto, etc.) vía panel o API
4. Revisa logs: `Sheets sync OK` o `Sheets sync FALLIDA`

| Entorno | Dónde probar | Base de datos | Sheets |
|---------|----------------|---------------|--------|
| **Producción** | https://ocr-quality-system.onrender.com/admin | SQLite en disco Render | Credenciales en Render (secret file / env) |
| **Local** | http://127.0.0.1:8000/admin | `backend/results.db` | Mismo JSON en `secrets/` |

Recomendación: probar Sheets en **local** primero; en **Render** sube el JSON como variable/secreto (no está en GitHub).

## Desplegar en Render

1. Conecta el repo en [render.com](https://render.com)
2. Usa `render.yaml` (servicio `ocr-quality-system`)
3. Variables: `PUBLIC_APP_URL`, `DATA_DIR`, `DATABASE_PATH` (ya en blueprint)

## Subir a GitHub

```powershell
git add .
git commit -m "Configuración panel producción Render"
git push
```

No subir: `.env`, `secrets/`, `backend/results.db`

## Seguridad

- Cambiar contraseña en `auth-gate.js`
- No commitear credenciales Google ni `.db` con datos reales
