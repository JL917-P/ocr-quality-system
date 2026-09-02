from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = Path(
    r"C:\Users\JL\.cursor\projects\c-Users-JL-OneDrive-Escritorio-ocr-copia-en-cursor\assets"
    r"\c__Users_JL_AppData_Roaming_Cursor_User_workspaceStorage_8fc9f459154b51561595c26aad098c98"
    r"_images_image-936be7ed-e13b-43d9-912b-e824df753d0e.png"
)
out = ROOT / "frontend" / "firma.png"

img = Image.open(src).convert("RGBA")
w, h = img.size
draw = ImageDraw.Draw(img)

# Solo la línea inferior (INDUAMERICA INTERNACIONAL S.A.C.)
y0, y1 = 114, h
draw.rectangle((0, y0, w, y1), fill=(255, 255, 255, 255))

text = "Área de Control de Calidad"
color = (75, 136, 192, 255)

font = None
for fp in (
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
):
    try:
        font = ImageFont.truetype(fp, 10)
        break
    except OSError:
        pass
if font is None:
    font = ImageFont.load_default()

center_x = w // 2
center_y = y0 + (y1 - y0) // 2
draw.text((center_x, center_y), text, fill=color, font=font, anchor="mm")

img.save(out, format="PNG")
print(f"saved {out} ({w}x{h})")
