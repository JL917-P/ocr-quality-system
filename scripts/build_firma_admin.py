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

y0, y1 = 114, h
draw.rectangle((0, y0, w, y1), fill=(255, 255, 255, 255))

# Centro visual del logo (no del canvas: la imagen tiene margen derecho vacío)
logo_xs = []
for y in range(0, y0):
    for x in range(w):
        r, g, b, a = img.getpixel((x, y))
        if not (r > 240 and g > 240 and b > 240):
            logo_xs.append(x)
center_x = (min(logo_xs) + max(logo_xs)) // 2 if logo_xs else w // 2

text = "Área de Control de Calidad"
color = (75, 136, 192, 255)
font_size = 12

font = None
for fp in (
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
):
    try:
        font = ImageFont.truetype(fp, font_size)
        break
    except OSError:
        pass
if font is None:
    font = ImageFont.load_default()

center_y = y0 + (y1 - y0) // 2
draw.text((center_x, center_y), text, fill=color, font=font, anchor="mm")

img.save(out, format="PNG")
print(f"saved {out} ({w}x{h}) center_x={center_x}")
