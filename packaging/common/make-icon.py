"""Generate a 256x256 PNG icon for the application.

Draws the same animated "V" used by the in-app VLoader spinner: a purple
rounded square with a white V stroke (polyline 20,25 → 50,75 → 80,25).

Run inside the build Docker (Pillow is available via requirements.txt).
"""
from PIL import Image, ImageDraw

SIZE = 256
BG = (124, 58, 237, 255)        # violet-600 (matches Tailwind / CSS var --primary)
STROKE = (255, 255, 255, 255)
SCALE = SIZE / 100              # VLoader uses viewBox 0 0 100 100

# V shape points (same as VLoader.tsx polyline)
V_POINTS = [(20, 25), (50, 75), (80, 25)]
STROKE_WIDTH = 6 * SCALE

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Rounded rectangle background.
RADIUS = int(48 * SCALE)
draw.rounded_rectangle([(0, 0), (SIZE - 1, SIZE - 1)], radius=RADIUS, fill=BG)

# Draw the V as a thick white polyline.
scaled = [tuple(c * SCALE for c in p) for p in V_POINTS]
draw.line(scaled, fill=STROKE, width=int(STROKE_WIDTH), joint="curve")

# Round the endpoints with circles for stroke-linecap: round effect.
cap_r = int(STROKE_WIDTH / 2)
for p in scaled:
    draw.ellipse([p[0] - cap_r, p[1] - cap_r, p[0] + cap_r, p[1] + cap_r], fill=STROKE)

img.save("/tmp/vipergirls-viewer.png", "PNG")
print("Icon written to /tmp/vipergirls-viewer.png")
