"""Generates the Pallet Depot textures procedurally (our own work, no third-party art).

Writes PNG sources to src/textures/ and converts them to .dds in textures/ with GIANTS' textureTool.
Gloss maps follow the FS25 PBR layout: R = smoothness, G = ambient occlusion, B = metalness.
The mask map is read by buildingShader through the second UV set: R = moss, B = dirt.

    python tools/make_textures.py [--no-dds]
"""
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import layout as L  # noqa: E402

ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src", "textures")
OUT = os.path.join(ROOT, "textures")
TEXTURE_TOOL = r"C:\Program Files\GIANTS Software\GIANTS_Editor_10.0.14\tools\textureTool.exe"
FONT = r"C:\Program Files\Blender Foundation\Blender 5.2\5.2\datafiles\fonts\Inter.woff2"   # SIL OFL

RNG = np.random.default_rng(2510)


# --- helpers ----------------------------------------------------------------------------------------
def noise(h, w, sx, sy=None):
    """Tileable smooth noise in 0..1, feature size sx/sy in pixels (Gaussian-filtered white noise)."""
    sy = sx if sy is None else sy
    f = np.fft.fft2(RNG.standard_normal((h, w)))
    ky = np.fft.fftfreq(h)[:, None]
    kx = np.fft.fftfreq(w)[None, :]
    r = np.real(np.fft.ifft2(f * np.exp(-2 * math.pi ** 2 * ((kx * sx) ** 2 + (ky * sy) ** 2))))
    return (r - r.min()) / (r.max() - r.min() + 1e-9)


def fbm(h, w, scales, weights=None):
    weights = weights or [1.0 / (i + 1) for i in range(len(scales))]
    acc = sum(wt * noise(h, w, s) for s, wt in zip(scales, weights))
    return (acc - acc.min()) / (acc.max() - acc.min() + 1e-9)


def normal_from_height(hgt, strength):
    """Tangent-space normal map from a height field (rows top to bottom, +v up)."""
    dx = (np.roll(hgt, -1, axis=1) - np.roll(hgt, 1, axis=1)) * 0.5 * strength
    dy = (np.roll(hgt, 1, axis=0) - np.roll(hgt, -1, axis=0)) * 0.5 * strength
    n = np.dstack([-dx, -dy, np.ones_like(hgt)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return to_img((n * 0.5 + 0.5) * 255)


def to_img(a):
    a = np.clip(a, 0, 255).astype(np.uint8)
    return Image.fromarray(a, "RGB" if a.ndim == 3 and a.shape[2] == 3 else "RGBA" if a.ndim == 3 else "L")


def rgb(color, shade):
    """Colour (r, g, b) scaled per pixel by shade (h x w array)."""
    return np.dstack([shade * c for c in color])


def gloss(smooth, ao=None, metal=0.0):
    """Gloss map: smooth/metal are scalars or arrays in 0..1."""
    shape = next((np.shape(x) for x in (smooth, ao, metal) if np.ndim(x) == 2), None)
    s = np.broadcast_to(smooth, shape) * 255
    a = np.broadcast_to(1.0 if ao is None else ao, shape) * 255
    m = np.broadcast_to(metal, shape) * 255
    return to_img(np.dstack([s, a, m]))


def flat_normal(h, w):
    return to_img(np.dstack([np.full((h, w), 127.0), np.full((h, w), 127.0), np.full((h, w), 255.0)]))


def region_px(region, w, h):
    """(u0, v0, u1, v1) with v from the bottom -> pixel box (x0, y0, x1, y1)."""
    u0, v0, u1, v1 = region
    return int(round(u0 * w)), int(round((1 - v1) * h)), int(round(u1 * w)), int(round((1 - v0) * h))


def font(px):
    f = ImageFont.truetype(FONT, px)
    f.set_variation_by_name("Black")
    return f


def draw_text_fit(img, box, text, color, squeeze=1.0, fill=0.62):
    """Centre text in box; squeeze < 1 narrows the glyphs (pre-distortion for stretched UVs)."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    size = int(bh * fill / 0.73)
    f = font(size)
    l, t, r, b = f.getbbox(text)
    while (r - l) * squeeze > bw * 0.88:
        size = int(size * 0.95)
        f = font(size)
        l, t, r, b = f.getbbox(text)
    layer = Image.new("RGBA", (r - l + 8, b - t + 8), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((4 - l, 4 - t), text, font=f, fill=color)
    layer = layer.resize((max(1, int(layer.width * squeeze)), layer.height), Image.LANCZOS)
    img.alpha_composite(layer, (x0 + (bw - layer.width) // 2, y0 + (bh - layer.height) // 2)) if img.mode == "RGBA" \
        else img.paste(layer, (x0 + (bw - layer.width) // 2, y0 + (bh - layer.height) // 2), layer)


def ribs(n, count, profile):
    """Height (0..1) of a repeating profile across n pixels; profile(t) with t in 0..1."""
    t = (np.arange(n) / n * count) % 1.0
    return np.vectorize(profile)(t)


def trapezoid(valley, rise, crest):
    def p(t):
        a, b, c = valley, valley + rise, valley + rise + crest
        if t < a:
            return 0.0
        if t < b:
            return (t - a) / rise
        if t < c:
            return 1.0
        if t < c + rise:
            return 1.0 - (t - c) / rise
        return 0.0
    return p


# --- materials --------------------------------------------------------------------------------------
def tex_wall():
    n = 1024                                    # 2 m, 8 ribs of 250 mm
    prof = ribs(n, 8, trapezoid(0.28, 0.1, 0.24))
    small = ribs(n, 8, lambda t: 0.12 if 0.06 < t < 0.1 or 0.82 < t < 0.86 else 0.0)
    hgt = np.tile(prof + small, (n, 1))
    streak = noise(n, n, 3, 90)
    grain = fbm(n, n, [40, 8, 2])
    shade = 0.93 + 0.05 * grain - 0.05 * streak - 0.06 * (1 - hgt)
    diffuse = rgb((205, 208, 204), shade)
    ao = 0.82 + 0.18 * hgt
    return to_img(diffuse), normal_from_height(hgt, 9), gloss(0.38 + 0.08 * grain, ao, 0.0)


def tex_roof():
    n = 1024                                    # 2 m, 8 ribs, taller narrow crests
    prof = ribs(n, 8, trapezoid(0.34, 0.08, 0.16))
    hgt = np.tile(prof, (n, 1))
    streak = noise(n, n, 2, 140)
    grain = fbm(n, n, [50, 10, 2])
    shade = 0.9 + 0.08 * grain - 0.08 * streak - 0.07 * (1 - hgt)
    return to_img(rgb((74, 78, 82), shade)), normal_from_height(hgt, 12), \
        gloss(0.3 + 0.08 * grain, 0.8 + 0.2 * hgt, 0.15)


def tex_door():
    n = 512                                     # 1 m, 8 slats of 125 mm
    t = (np.arange(n) / n * 8) % 1.0
    slat = np.where(t < 0.06, 0.0, np.sin(np.clip((t - 0.06) / 0.94, 0, 1) * math.pi) ** 0.5)
    hgt = np.tile(slat[:, None], (1, n))
    grain = fbm(n, n, [30, 6])
    shade = 0.9 + 0.08 * grain - 0.18 * (hgt < 0.05)
    return to_img(rgb((132, 140, 146), shade)), normal_from_height(hgt, 7), gloss(0.42, 0.75 + 0.25 * hgt, 0.35)


def tex_concrete():
    n = 1024                                    # 4 m, saw-cut joint on the tile edge
    base = fbm(n, n, [120, 30, 6, 1.5], [1.0, 0.6, 0.35, 0.25])
    stains = noise(n, n, 60)
    shade = 0.86 + 0.16 * base - 0.12 * np.clip(stains - 0.65, 0, 1) * 3
    joint = np.zeros((n, n), bool)
    joint[:, :3] = joint[:3, :] = True
    shade = np.where(joint, 0.55, shade)
    hgt = base * 0.6 - joint * 1.0
    return to_img(rgb((150, 149, 144), shade)), normal_from_height(hgt, 2.5), gloss(0.1 + 0.1 * base, 1 - 0.4 * joint, 0.0)


def tex_window():
    n = 512                                     # 1 m pane with a 6 cm frame on the tile edge
    yy, xx = np.mgrid[0:n, 0:n] / n
    edge = np.minimum(np.minimum(xx, 1 - xx), np.minimum(yy, 1 - yy))
    frame = edge < 0.03
    refl = 0.75 + 0.25 * yy + 0.35 * np.exp(-((xx - yy * 0.6 - 0.25) ** 2) / 0.004)
    glass = rgb((42, 54, 64), refl)
    alu = rgb((158, 163, 166), np.full((n, n), 1.0))
    diffuse = np.where(frame[..., None], alu, glass)
    hgt = np.clip(0.03 - edge, 0, 0.03) / 0.03
    return to_img(diffuse), normal_from_height(hgt, 6), gloss(np.where(frame, 0.5, 0.92), None, np.where(frame, 0.6, 0.0))


PAINT = {   # colour, smoothness, metalness
    "frame": ((60, 64, 68), 0.35, 0.0),
    "galv": ((168, 172, 174), 0.5, 0.8),
    "rackPost": ((28, 78, 158), 0.45, 0.0),
    "rackBeam": ((228, 108, 22), 0.45, 0.0),
    "trim": ((192, 195, 195), 0.4, 0.0),
    "doorFrame": ((112, 117, 120), 0.4, 0.2),
    "rubber": ((26, 26, 26), 0.2, 0.0),
    "yellow": ((236, 190, 24), 0.45, 0.0),
    "red": ((190, 32, 28), 0.55, 0.0),
    "white": ((232, 232, 226), 0.4, 0.0),
}


def tex_paint():
    n = 512
    diffuse = np.full((n, n, 3), 128.0)
    smooth = np.full((n, n), 0.3)
    metal = np.zeros((n, n))
    grain = fbm(n, n, [20, 4])
    for name, region in L.PAINT_SWATCHES.items():
        color, s, m = PAINT[name]
        x0, y0, x1, y1 = region_px(region, n, n)
        g = grain[y0:y1, x0:x1]
        diffuse[y0:y1, x0:x1] = rgb(color, 0.94 + 0.08 * g)
        smooth[y0:y1, x0:x1] = s + 0.06 * (g - 0.5)
        metal[y0:y1, x0:x1] = m
    return to_img(diffuse), None, gloss(smooth, None, metal)


def tex_brand(brand):
    w, h = 2048, 512
    accent = L.BRANDS[brand]["accent"]
    img = Image.new("RGB", (w, h), accent)
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = region_px(L.BRAND_SIGN, w, h)
    d.rectangle((x0 + 18, y0 + 18, x1 - 19, y1 - 19), outline=(250, 250, 250), width=12)
    # the 8 x 1.2 m board is wider than this 2048 x 384 region, so pre-squeeze the lettering
    squeeze = ((y1 - y0) / (x1 - x0)) * ((L.SIGN_X[1] - L.SIGN_X[0]) / (L.SIGN_Y[1] - L.SIGN_Y[0]))
    squeeze = 1.0 / squeeze
    draw_text_fit(img, (x0, y0 + 30, x1, y1 - 100), L.BRANDS[brand]["word"], (250, 250, 250), squeeze, 0.8)
    draw_text_fit(img, (x0, y1 - 118, x1, y1 - 40), "PALLET DEPOT", (235, 240, 235), squeeze, 0.62)
    grain = fbm(h, w, [30, 5])
    arr = np.asarray(img, float) * (0.95 + 0.07 * grain)[..., None]
    return to_img(arr)


def tex_brand_gloss():
    return gloss(np.full((128, 512), 0.5), None, 0.0)


def tex_stock():
    n = 1024
    img = Image.new("RGB", (n, n), (120, 100, 80))
    smooth = np.full((n, n), 0.12)

    def box(name):
        return region_px(L.STOCK_REGIONS[name], n, n)

    # pallet: pine boards with grain and seams
    x0, y0, x1, y1 = box("pallet")
    grain = noise(y1 - y0, x1 - x0, 60, 1.5)
    wood = rgb((200, 162, 112), 0.85 + 0.2 * grain)
    for k in range(1, 8):
        wood[:, k * (x1 - x0) // 8 - 2: k * (x1 - x0) // 8 + 2] *= 0.55
    img.paste(to_img(wood), (x0, y0))

    # cardboard boxes with tape and labels
    x0, y0, x1, y1 = box("boxes")
    bw, bh = x1 - x0, y1 - y0
    card = to_img(rgb((178, 136, 92), 0.9 + 0.12 * fbm(bh, bw, [25, 4])))
    d = ImageDraw.Draw(card)
    for i in range(3):
        for j in range(3):
            cx0, cy0 = i * bw // 3, j * bh // 3
            d.rectangle((cx0, cy0, cx0 + bw // 3 - 1, cy0 + bh // 3 - 1), outline=(120, 88, 56), width=4)
            ty = cy0 + bh // 6
            d.rectangle((cx0 + 4, ty - 10, cx0 + bw // 3 - 5, ty + 10), fill=(206, 182, 140))
            d.rectangle((cx0 + 22, cy0 + 22, cx0 + 70, cy0 + 52), fill=(236, 234, 226))
            for k in range(3):
                d.line((cx0 + 28, cy0 + 30 + k * 8, cx0 + 62, cy0 + 30 + k * 8), fill=(70, 70, 70), width=2)
    img.paste(card, (x0, y0))

    # sacks: rows of filled bags
    x0, y0, x1, y1 = box("sacks")
    bw, bh = x1 - x0, y1 - y0
    yy, xx = np.mgrid[0:bh, 0:bw]
    rows, cols = 5, 2
    fy = (yy / bh * rows) % 1.0
    fx = (xx / bw * cols + (np.floor(yy / bh * rows) % 2) * 0.5) % 1.0
    bulge = np.clip(1 - ((fx - 0.5) / 0.52) ** 2, 0, 1) * np.clip(1 - ((fy - 0.5) / 0.55) ** 2, 0, 1)
    shade = 0.62 + 0.38 * bulge ** 0.4 + 0.05 * fbm(bh, bw, [6, 2])
    img.paste(to_img(rgb((218, 210, 190), shade)), (x0, y0))

    # wooden crates: slats with dark gaps
    x0, y0, x1, y1 = box("crates")
    bw, bh = x1 - x0, y1 - y0
    grain = noise(bh, bw, 50, 1.5)
    crate = rgb((170, 124, 78), 0.85 + 0.2 * grain)
    for k in range(10):
        gy = k * bh // 10
        crate[gy: gy + 7, :] *= 0.25
    for k in range(4):
        a, b = max(0, k * bw // 3 - 14), min(bw, k * bw // 3 + 14)
        crate[:, a:b] = rgb((150, 106, 64), 0.9 + 0.15 * grain[:, a:b])
    img.paste(to_img(crate), (x0, y0))

    # stretch-wrapped stack: cardboard under a glossy film
    x0, y0, x1, y1 = box("wrapped")
    bw, bh = x1 - x0, y1 - y0
    yy, xx = np.mgrid[0:bh, 0:bw]
    seams = ((xx % (bw // 3)) < 4) | ((yy % (bh // 4)) < 4)
    under = rgb((176, 140, 98), (0.9 + 0.1 * fbm(bh, bw, [30, 5])) * np.where(seams, 0.6, 1.0))
    film = 0.5 + 0.5 * np.sin((xx * 0.6 + yy) / bh * math.pi * 9) * noise(bh, bw, 40)
    wrapped = under * 0.72 + rgb((175, 192, 206), 0.7 + 0.4 * film) * 0.28
    img.paste(to_img(wrapped), (x0, y0))
    smooth[y0:y1, x0:x1] = 0.55 + 0.25 * film

    return img, None, gloss(smooth, None, 0.0)


def tex_decals():
    n = 1024
    img = Image.new("RGB", (n, n), (52, 54, 55))
    wear = fbm(n, n, [30, 6, 2])
    # warning stripes, 45 degrees, tile along u
    yy, xx = np.mgrid[0:256, 0:n]
    stripe = ((xx + yy) // 64) % 2 == 0
    col = np.where(stripe[..., None], np.array([232, 186, 26.0]), np.array([28, 28, 28.0]))
    img.paste(to_img(col * (0.88 + 0.12 * wear[:256, :, None])), (0, 0))
    d = ImageDraw.Draw(img)
    for i, word in enumerate(("UNLOAD", "LOAD")):
        y0 = 256 + i * 256
        d.rectangle((6, y0 + 6, n - 7, y0 + 249), outline=(232, 186, 26), width=10)
        draw_text_fit(img, (0, y0 + 20, n, y0 + 236), word, (232, 186, 26), 1.0, 0.7)
    # chevron arrow pointing +u
    d.polygon([(40, 808), (150, 896), (40, 984), (96, 984), (206, 896), (96, 808)], fill=(232, 186, 26))
    arr = np.asarray(img, float)
    arr[256:] *= (0.9 + 0.1 * wear[256:, :, None])
    return to_img(arr), None, gloss(0.2 + 0.1 * wear, None, 0.0)


def tex_mask():
    """Second-UV mask: u < 0.02 is the clean indoor column, outdoors dirt rises towards the ground (v = 0)."""
    n = 512
    yy, xx = np.mgrid[0:n, 0:n] / n
    v = 1 - yy
    var = fbm(n, n, [40, 10, 3])
    dirt = np.clip(0.75 * np.exp(-v / 0.12) + 0.2 + 0.35 * (var - 0.5), 0, 1)
    moss = np.clip(0.5 * np.exp(-v / 0.06) * var + 0.08 * (var > 0.7), 0, 1)
    indoor = xx < 0.02
    dirt = np.where(indoor, 0.15, dirt)
    moss = np.where(indoor, 0.0, moss)
    return to_img(np.dstack([moss * 255, np.full((n, n), 255.0), dirt * 255]))


# --- output -----------------------------------------------------------------------------------------
def save(img, name):
    os.makedirs(SRC, exist_ok=True)
    path = os.path.join(SRC, name + ".png")
    img.convert("RGB").save(path)
    return path


def convert(paths):
    os.makedirs(OUT, exist_ok=True)
    for p in paths:
        target = os.path.join(OUT, os.path.splitext(os.path.basename(p))[0] + ".dds")
        r = subprocess.run([TEXTURE_TOOL, "-inputs", p, "-targetFile", target, "-ignoreTimestamp", "-silent"],
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(target):
            sys.exit("textureTool failed for %s:\n%s%s" % (p, r.stdout, r.stderr))


def main():
    paths = []
    for name, fn in (("wall", tex_wall), ("roof", tex_roof), ("door", tex_door), ("concrete", tex_concrete),
                     ("window", tex_window), ("paint", tex_paint), ("stock", tex_stock), ("decals", tex_decals)):
        d, nm, gl = fn()                        # flat parts have no normal map
        paths += [save(d, "depot_%s_diffuse" % name), save(gl, "depot_%s_specular" % name)]
        if nm is not None:
            paths.append(save(nm, "depot_%s_normal" % name))
    for brand in L.BRANDS:
        paths.append(save(tex_brand(brand), "depot_brand_%s_diffuse" % brand))
    paths.append(save(tex_brand_gloss(), "depot_brand_specular"))
    paths.append(save(tex_mask(), "depot_mask"))
    if "--no-dds" not in sys.argv:
        convert(paths)
    print("textures:", len(paths))


if __name__ == "__main__":
    main()
