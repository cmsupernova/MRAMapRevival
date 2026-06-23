"""Decode the game's real tile art (SCBART.256 + PAL256) into _render/tileset.js.

Port of the reference Mapmaker's art.py to PIL (no pygame), so our browser tools
render true game art instead of mined approximations. Emits, as base64 PNG data
URLs in _render/tileset.js:
  window.TILESET      = {terrain_id: url}            12x12 RGB terrain tiles
  window.TILESET_OBJ  = {object_id:  url}            RGBA object sprites
  window.TILESET_WALL = {"type|EDGE": url}           RGBA wall sprites (N/E/S/W)
  window.TILESET_DOOR = {"type|EDGE": url}           RGBA door sprites (N/E/S/W)

SCBART.256 layout (from art.py): 256-byte u16 header, then 12x12 terrain tiles at
0x100 + block*0x94 (terrain art slots 96..119 are skipped), then an RLE object
region, then RLE walls (0xe4 stride) and doors (0x80 stride) addressed by edge.
"""
import base64
import io
import os
import struct

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_render", "tileset.js")

TILE = 12
TERRAIN_BASE = 0x100
TERRAIN_STRIDE = 0x94
OBJ_BASE = 0x100 + 120 * TERRAIN_STRIDE          # 18016
WALL_STRIDE = 0xE4
DOOR_STRIDE = 0x80
WALL_EDGE = {"N": 0, "E": 0x1F, "W": 0x5C, "S": 0x7B}
DOOR_EDGE = {"N": 0, "E": 0x17, "W": 0x40, "S": 0x57}


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


def to_url(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


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
    img = [[-1] * TILE for _ in range(TILE)]
    i, guard = start, 0
    while i + 2 < end and i + 2 < len(ART) and ART[i] < 0x0C and guard < 64:
        x, y, n = ART[i], ART[i + 1], ART[i + 2]
        i += 3
        for k in range(n):
            if 0 <= x + k < TILE and 0 <= y < TILE and i + k < len(ART):
                img[y][x + k] = ART[i + k]
        i += n
        guard += 1
    return img


def rle_to_img(img):
    if not any(v >= 0 for row in img for v in row):
        return None
    out = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    px = out.load()
    for y in range(TILE):
        for x in range(TILE):
            v = img[y][x]
            if v >= 0:
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


def main():
    terrain, obj, wall, door = {}, {}, {}, {}
    for tid in list(range(0, 96)) + list(range(120, 141)):
        im = terrain_tile(tid)
        if im:
            terrain[tid] = to_url(im)
    for oid in range(1, 128):
        im = object_tile(oid)
        if im:
            obj[oid] = to_url(im)
    for t in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 0x1D, 0x1F]:
        for e in ("N", "E", "S", "W"):
            im = wall_tile(t, e)
            if im:
                wall[f"{t}|{e}"] = to_url(im)
    for d in range(1, 6):
        for e in ("N", "E", "S", "W"):
            im = door_tile(d, e)
            if im:
                door[f"{d}|{e}"] = to_url(im)

    def dump(name, d):
        items = ",\n".join(f'  {k!r}:{v!r}' if isinstance(k, str) else f'  "{k}":{v!r}'
                           for k, v in d.items())
        return f"window.{name} = {{\n{items}\n}};\n"

    with open(OUT, "w") as fh:
        fh.write("// Real game tile art decoded from SCBART.256 / PAL256 by "
                 "extract_scbart.py. Do not edit by hand.\n")
        fh.write(dump("TILESET", terrain))
        fh.write(dump("TILESET_OBJ", obj))
        fh.write(dump("TILESET_WALL", wall))
        fh.write(dump("TILESET_DOOR", door))

    print(f"wrote {os.path.basename(OUT)}")
    print(f"  terrain tiles: {len(terrain)}")
    print(f"  object tiles:  {len(obj)}")
    print(f"  wall tiles:    {len(wall)} (edge variants)")
    print(f"  door tiles:    {len(door)} (edge variants)")
    print(f"  size: {os.path.getsize(OUT)//1024} KB")


if __name__ == "__main__":
    main()
