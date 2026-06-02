# Control de Calidad · OCR Logística

Captura de etiquetas desde el celular, OCR con Tesseract, panel admin (constancias, productos, trasiegos, trazabilidad).

## Estructura

```
├── backend/          # API FastAPI + SQLite
│   ├── app.py
│   ├── data/         # Catálogo products.txt
│   └── requirements.txt
├── frontend/         # admin.html, capture.html, estilos
├── Dockerfile        # Despliegue web (Tesseract incluido)
└── render.yaml       # Blueprint Render.com
```

## Desarrollo local (Windows)

### Requisitos

- Python 3.10+
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) en el PATH

### Ejecutar

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

- Admin: http://127.0.0.1:8000/admin (`admin` / `123456`)
- Captura móvil: http://IP_DE_TU_PC:8000/capture

Si Tesseract no está en PATH:

```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

## Subir a GitHub

1. Crea un repositorio vacío en GitHub (sin README).
2. En esta carpeta:

```powershell
cd "ruta\ocr - copia en cursor"
git init
git add .
git commit -m "Initial commit: OCR Control de Calidad"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

**No se sube:** `.env`, `backend/results.db`, `.venv` (ya están en `.gitignore`).

## Desplegar en la web (Render.com)

Render ejecuta el `Dockerfile` (Python + Tesseract). El disco persistente guarda la base SQLite.

### Pasos

1. Cuenta en [render.com](https://render.com) y conecta tu cuenta de GitHub.
2. **New → Blueprint** y selecciona este repositorio (usa `render.yaml`),  
   **o** **New → Web Service** → Runtime **Docker** → mismo repo.
3. Espera el build (5–10 min la primera vez).
4. URL pública: `https://control-calidad-ocr.onrender.com` (según el nombre que elijas).

### Comprobar

- https://TU-APP.onrender.com/health → `{"ok":true,"tesseract":true}`
- https://TU-APP.onrender.com/admin

### Plan gratuito Render

- La app **se duerme** tras ~15 min sin visitas; el primer acceso puede tardar ~1 min.
- Disco de 1 GB en `/var/data` para SQLite (datos entre reinicios).
- Si necesitas siempre activo y más recursos, usa un plan de pago.

### Variables de entorno (producción)

| Variable | Valor típico |
|----------|----------------|
| `PORT` | `8000` |
| `DATA_DIR` | `/var/data` |
| `DATABASE_PATH` | `/var/data/results.db` |

## Catálogo de productos

Edita `backend/data/products.txt` (una línea por producto). En producción, tras el primer despliegue, los cambios en el repo no sobrescriben el disco; actualiza el archivo en el servidor o vuelve a desplegar según tu flujo.

## Seguridad (importante)

- Las credenciales del admin están en `frontend/auth-gate.js` (`admin` / `123456`). **Cámbialas antes de exponer la app en internet.**
- No subas `.env` ni bases de datos con datos reales a GitHub.
- Haz copias periódicas de `results.db` (descarga desde el servidor o backup del disco Render).

## Respaldo de datos

Descarga periódicamente la base desde el entorno de producción o automatiza backup del volumen `/var/data/results.db`.

## Licencia

Uso interno del proyecto.
