"""Transparent logo v2: flood-fill the outside, then morphological closing so
every white region enclosed by the logo's silhouette stays OPAQUE white —
the mark looks complete on any background, light or dark."""

from collections import deque

from PIL import Image, ImageFilter

SRC = r"C:\Users\jamie\src\familyroots\docs\brand\iconHD.png"
OUT_LOGO = r"C:\Users\jamie\src\familyroots\apps\web\public\logo-mark.png"
OUT_ICON = r"C:\Users\jamie\src\familyroots\apps\web\src\app\icon.png"

img = Image.open(SRC).convert("RGBA")
w, h = img.size
px = img.load()


def near_white(p, tol=38):
    return (255 - p[0]) + (255 - p[1]) + (255 - p[2]) < tol * 3


# 1. Flood fill from the borders: contiguous near-white = candidate background
outside = [[False] * w for _ in range(h)]
queue = deque()
for x in range(w):
    for y in (0, h - 1):
        if near_white(px[x, y]) and not outside[y][x]:
            outside[y][x] = True
            queue.append((x, y))
for y in range(h):
    for x in (0, w - 1):
        if near_white(px[x, y]) and not outside[y][x]:
            outside[y][x] = True
            queue.append((x, y))
while queue:
    x, y = queue.popleft()
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < w and 0 <= ny < h and not outside[ny][nx] and near_white(px[nx, ny]):
            outside[ny][nx] = True
            queue.append((nx, ny))

# 2. Content mask -> morphological closing (dilate then erode, r=10) to get
#    the logo silhouette including enclosed gaps (pixel notch, square gaps)
mask = Image.new("L", (w, h), 0)
mpx = mask.load()
for y in range(h):
    for x in range(w):
        if not outside[y][x]:
            mpx[x, y] = 255
closed = mask.filter(ImageFilter.MaxFilter(21)).filter(ImageFilter.MinFilter(21))
cpx = closed.load()

# 3. Apply: outside-and-not-enclosed -> transparent. Enclosed whites become
#    opaque ONLY in the pixel-corner region (top-right), where the squares'
#    surrounding white is part of the mark's design; elsewhere the closing
#    would bleed white past the silhouette (e.g. under the swoosh tip).
for y in range(h):
    for x in range(w):
        if outside[y][x]:
            in_pixel_corner = x > w * 0.55 and y < h * 0.45
            if cpx[x, y] > 0 and in_pixel_corner:
                px[x, y] = (255, 255, 255, 255)
            else:
                r, g, b, _ = px[x, y]
                px[x, y] = (r, g, b, 0)

# 4. Feather the true outer edge (anti-halo), never touching enclosed whites
for y in range(h):
    for x in range(w):
        r, g, b, a = px[x, y]
        if a == 0:
            continue
        touches_bg = any(
            0 <= x + dx < w and 0 <= y + dy < h and px[x + dx, y + dy][3] == 0
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
        )
        if touches_bg:
            brightness = min(r, g, b)
            if brightness > 180:
                alpha = max(0, min(255, int(255 * (255 - brightness) / 75)))
                px[x, y] = (r, g, b, alpha)

bbox = img.getbbox()
left, top, right, bottom = bbox
cropped = img.crop(
    (max(0, left - 2), max(0, top - 2), min(w, right + 2), min(h, bottom + 2))
)
cropped.save(OUT_LOGO)
print(f"logo: {cropped.size} -> {OUT_LOGO}")

side = max(cropped.size)
icon = Image.new("RGBA", (side, side), (0, 0, 0, 0))
icon.paste(cropped, ((side - cropped.size[0]) // 2, (side - cropped.size[1]) // 2))
icon.resize((128, 128), Image.LANCZOS).save(OUT_ICON)
print(f"icon: 128x128 -> {OUT_ICON}")
