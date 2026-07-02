"""Render .SEC sectors using the REAL game tile art from SCBART.256 + PAL256.

Unlike sec_render.py (flat palette-color schematic) this composites each cell
from the actual 12x12 terrain tiles and overlays the real object / wall / door
sprites, so a sector looks like the game instead of colored blocks. It reuses
the proven SCBART decode from extract_scbart.py (the same art that powers the
SEC paint editor's tileset.js).

Note: MAP.256 is a separate art bank with a different internal layout (its
0x100 region is not the 12x12 terrain table), so it is NOT the per-cell sector
tileset; SCBART.256 is.

Usage:
  python render_sec_art.py sample     -> _render/_sec_art_sample.png (side-by-side)
  python render_sec_art.py one NAME   -> _render/_sec_art_<NAME>.png (real art only)
"""
import os
import struct
import sys

from PIL import Image

import sec_render as S  # reuse schematic render + SEC reader

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_render")

TILE = 12
GRID, CELL, PLAY = 33, 6, 32
TERRAIN_BASE = 0x100
TERRAIN_STRIDE = 0x94
OBJ_BASE = 0x100 + 120 * TERRAIN_STRIDE
WALL_STRIDE = 0xE4
DOOR_STRIDE = 0x80
WALL_EDGE = {"N": 0, "E": 0x1F, "W": 0x5C, "S": 0x7B}
DOOR_EDGE = {"N": 0, "E": 0x17, "W": 0x40, "S": 0x57}
# magenta transparency key + out-of-palette indices are "no pixel" in sprites
TRANSPARENT = {164, 165, 254, 255}


def find(*names):
    cands = []
    for n in names:
        cands += [os.path.join(HERE, n), os.path.join(HERE, "scb", n),
                  os.path.join(HERE, "Reference", "MRA-Mapmaker-1.0.0", "assets", n)]
    for p in cands:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(names)


ART = open(find("SCBART.256"), "rb").read()
P = open(find("PAL256"), "rb").read()
PAL = [(P[i * 3], P[i * 3 + 1], P[i * 3 + 2]) for i in range(len(P) // 3)]
HDR = struct.unpack("<128H", ART[:256])
WALL_BASE = OBJ_BASE + HDR[127]
DOOR_BASE = WALL_BASE + 0xAB0


def col(v):
    return PAL[v] if v < len(PAL) else (255, 0, 255)


def terrain_block(tid):
    if tid < 96:
        return tid
    if tid >= 120:
        return tid - 24
    return None


def terrain_tile(tid):
    blk = terrain_block(tid)
    if blk is None:
        return None
    off = TERRAIN_BASE + blk * TERRAIN_STRIDE
    if off + 4 + TILE * TILE > len(ART):
        return None
    w = ART[off] | (ART[off + 1] << 8)
    h = ART[off + 2] | (ART[off + 3] << 8)
    if (w, h) != (TILE, TILE):
        return None
    px = ART[off + 4: off + 4 + TILE * TILE]
    if not any(px):
        return None
    img = Image.new("RGB", (TILE, TILE))
    img.putdata([col(v) for v in px])
    return img


def decode_rle(start, end):
    grid = [[-1] * TILE for _ in range(TILE)]
    i, guard = start, 0
    while i + 2 < end and i + 2 < len(ART) and ART[i] < 0x0C and guard < 64:
        x, y, n = ART[i], ART[i + 1], ART[i + 2]
        i += 3
        for k in range(n):
            if 0 <= x + k < TILE and 0 <= y < TILE and i + k < len(ART):
                grid[y][x + k] = ART[i + k]
        i += n
        guard += 1
    return grid


def rle_to_img(grid):
    if not any(v >= 0 for row in grid for v in row):
        return None
    out = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    px = out.load()
    for y in range(TILE):
        for x in range(TILE):
            v = grid[y][x]
            if v >= 0 and v not in TRANSPARENT:
                px[x, y] = (*col(v), 255)
    return out


def object_tile(oid):
    if 1 <= oid < 128 and HDR[oid] > HDR[oid - 1] and HDR[oid - 1] < 6900:
        return rle_to_img(decode_rle(OBJ_BASE + HDR[oid - 1], OBJ_BASE + HDR[oid]))
    return None


def wall_tile(t, edge):
    rt = 11 if t == 0x1D else (12 if t == 0x1F else t)
    if 1 <= rt <= 12:
        base = WALL_BASE + (rt - 1) * WALL_STRIDE + WALL_EDGE[edge]
        return rle_to_img(decode_rle(base, base + WALL_STRIDE))
    return None


def door_tile(d, edge):
    if 1 <= d <= 5:
        base = DOOR_BASE + (d - 1) * DOOR_STRIDE + DOOR_EDGE[edge]
        return rle_to_img(decode_rle(base, base + DOOR_STRIDE))
    return None


_TC, _OC = {}, {}


def get_terrain(tid):
    if tid not in _TC:
        _TC[tid] = terrain_tile(tid)
    return _TC[tid]


def get_object(oid):
    if oid not in _OC:
        _OC[oid] = object_tile(oid)
    return _OC[oid]


def render_sector_art(data, drop_pad=True):
    n = PLAY if drop_pad else GRID
    img = Image.new("RGBA", (n * TILE, n * TILE), (10, 10, 14, 255))
    for r in range(n):
        for c in range(n):
            off = (r * GRID + c) * CELL
            terr = data[off]
            obj = data[off + 1]
            walls = data[off + 2] | (data[off + 3] << 8)
            north = walls & 0x1F
            west = (walls >> 5) & 0x1F
            x0, y0 = c * TILE, r * TILE
            tt = get_terrain(terr)
            if tt is not None:
                img.paste(tt, (x0, y0))
            else:
                img.paste(Image.new("RGB", (TILE, TILE), S.color_for(terr)), (x0, y0))
            if obj:
                ot = get_object(obj)
                if ot is not None:
                    img.alpha_composite(ot, (x0, y0))
            if north:
                w = wall_tile(north, "N")
                if w is not None:
                    img.alpha_composite(w, (x0, y0))
            if west:
                w = wall_tile(west, "W")
                if w is not None:
                    img.alpha_composite(w, (x0, y0))
    return img.convert("RGB")


def find_sec(name):
    if not name.lower().endswith(".sec"):
        name += ".SEC"
    for root in (os.path.join(HERE, "scb", "MAPS"),
                 os.path.join(HERE, "WINMRA", "MAPS")):
        for r, _d, fs in os.walk(root):
            for f in fs:
                if f.lower() == name.lower():
                    return os.path.join(r, f)
    return None


def label(img, text):
    from PIL import ImageDraw
    bar = 18
    out = Image.new("RGB", (img.width, img.height + bar), (24, 24, 30))
    out.paste(img, (0, bar))
    ImageDraw.Draw(out).text((4, 4), text, fill=(235, 235, 240))
    return out


def render_one(name):
    p = find_sec(name)
    if not p:
        print("not found:", name)
        return None
    d = S.read_sec(p)
    if not d:
        print("bad SEC:", p)
        return None
    return render_sector_art(d)


def sample():
    os.makedirs(OUT, exist_ok=True)
    cols = []
    for name in ("haven1", "EWGB194225b"):
        p = find_sec(name)
        if not p:
            print("skip (not found):", name)
            continue
        d = S.read_sec(p)
        if not d:
            continue
        a = label(S.render_sector(d, scale=TILE), f"{name}  schematic (current)")
        b = label(render_sector_art(d), f"{name}  SCBART real art")
        stack = Image.new("RGB", (a.width, a.height + b.height + 6), (24, 24, 30))
        stack.paste(a, (0, 0))
        stack.paste(b, (0, a.height + 6))
        cols.append(stack)
    if not cols:
        print("no samples rendered")
        return
    gap = 10
    W = sum(c.width for c in cols) + gap * (len(cols) - 1)
    H = max(c.height for c in cols)
    canvas = Image.new("RGB", (W, H), (24, 24, 30))
    x = 0
    for c in cols:
        canvas.paste(c, (x, 0))
        x += c.width + gap
    out = os.path.join(OUT, "_sec_art_sample.png")
    canvas.save(out)
    print("wrote", out, canvas.size)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "sample"
    if mode == "sample":
        sample()
    elif mode == "one" and len(sys.argv) > 2:
        img = render_one(sys.argv[2])
        if img:
            out = os.path.join(OUT, f"_sec_art_{sys.argv[2]}.png")
            img.save(out)
            print("wrote", out, img.size)
    else:
        print(__doc__)
