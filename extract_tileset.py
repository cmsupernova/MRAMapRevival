"""Mine real 8x8 terrain sprites from the detailed PNG renders.

The detailed renders in contents/ are 256x256 = 8px per SEC cell, aligned to
the 32x32 playable grid. Because we ALSO have the source SEC bytes, we can read
terrain byte 0 for each cell and copy the matching 8x8 pixel block out of the
PNG. Sampling many "clean" cells (no object, no wall) per terrain value and
taking the most common block yields a representative sprite per terrain index -
the real game art, without decoding the .256 binaries.

Output:
  _render/terrain_atlas.png   visual sheet of value -> sprite (for inspection)
  _render/tileset.js          window.TILESET = {value: dataURL(8x8 png)}
  _render/_verify_<name>.png  one re-rendered sector vs its original, for a look
"""
import base64
import io
import json
import os
from collections import Counter

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENTS = os.path.join(HERE, "contents")
MAPS = [os.path.join(HERE, "_maps_unzip"), os.path.join(HERE, "_mapsall_unzip")]
OUT = os.path.join(HERE, "_render")
GRID, CELL, PLAY, PX = 33, 6, 32, 8


def index_pngs():
    d = {}
    for r, _x, fs in os.walk(CONTENTS):
        for f in fs:
            if f.lower().endswith(".png"):
                d.setdefault(os.path.splitext(f)[0].lower(), os.path.join(r, f))
    return d


def index_secs():
    d = {}
    for base in MAPS:
        for r, _x, fs in os.walk(base):
            for f in fs:
                if f.lower().endswith(".sec") and not f.startswith("._"):
                    d.setdefault(os.path.splitext(f)[0].lower(), os.path.join(r, f))
    return d


def main():
    pngs, secs = index_pngs(), index_secs()
    pairs = sorted(set(pngs) & set(secs))
    print(f"SEC+PNG pairs: {len(pairs)}")

    samples = {}      # terrain value -> Counter of 8x8 RGB block bytes
    objsamp = {}      # object value -> Counter of (block, terrain_under)
    for base in pairs:
        d = open(secs[base], "rb").read()
        if len(d) != GRID * GRID * CELL:
            continue
        im = Image.open(pngs[base]).convert("RGB")
        if im.size != (PLAY * PX, PLAY * PX):
            im = im.resize((PLAY * PX, PLAY * PX), Image.NEAREST)
        px = im.load()
        for r in range(PLAY):
            for c in range(PLAY):
                o = (r * GRID + c) * CELL
                terr, obj = d[o], d[o + 1]
                walls = d[o + 2] | (d[o + 3] << 8)
                if walls:                  # walls overlay the block; skip
                    continue
                block = bytes(
                    v for yy in range(PX) for xx in range(PX)
                    for v in px[c * PX + xx, r * PX + yy]
                )
                if obj:
                    objsamp.setdefault(obj, Counter())[(block, terr)] += 1
                else:
                    samples.setdefault(terr, Counter())[block] += 1

    tileset, atlas_items, terr_block = {}, [], {}
    for terr in sorted(samples):
        block, count = samples[terr].most_common(1)[0]
        terr_block[terr] = block
        spr = Image.frombytes("RGB", (PX, PX), block)
        buf = io.BytesIO(); spr.save(buf, "PNG")
        tileset[terr] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        atlas_items.append((terr, spr, count, sum(samples[terr].values())))

    # object sprites: isolate the overlay by diffing the composited block
    # against the terrain sprite that sits under it (RGBA, transparent where
    # the pixels match the bare terrain).
    objsprites, obj_items = {}, []
    THRESH = 40
    for obj in sorted(objsamp):
        (block, terr), count = objsamp[obj].most_common(1)[0]
        base_block = terr_block.get(terr)
        rgba = bytearray(PX * PX * 4)
        for i in range(PX * PX):
            r, g, b = block[i * 3], block[i * 3 + 1], block[i * 3 + 2]
            if base_block is not None:
                br, bg, bb = base_block[i * 3], base_block[i * 3 + 1], base_block[i * 3 + 2]
                diff = abs(r - br) + abs(g - bg) + abs(b - bb)
            else:
                diff = 999
            rgba[i * 4:i * 4 + 4] = bytes((r, g, b, 255 if diff > THRESH else 0))
        spr = Image.frombytes("RGBA", (PX, PX), bytes(rgba))
        buf = io.BytesIO(); spr.save(buf, "PNG")
        objsprites[obj] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        opaque = sum(1 for i in range(PX * PX) if rgba[i * 4 + 3])
        obj_items.append((obj, spr, count, sum(objsamp[obj].values()), opaque))

    # atlas sheet: 16 per row, each sprite scaled x4 with a label gap
    cols, sz = 16, PX * 4
    rows = (len(atlas_items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * sz, rows * sz), (24, 24, 28))
    for i, (terr, spr, _c, _t) in enumerate(atlas_items):
        big = spr.resize((sz, sz), Image.NEAREST)
        sheet.paste(big, ((i % cols) * sz, (i // cols) * sz))
    sheet.save(os.path.join(OUT, "terrain_atlas.png"))

    # object atlas over a checkerboard so transparency is visible
    if obj_items:
        orows = (len(obj_items) + cols - 1) // cols
        osheet = Image.new("RGB", (cols * sz, orows * sz), (24, 24, 28))
        for i, (obj, spr, *_r) in enumerate(obj_items):
            x0, y0 = (i % cols) * sz, (i // cols) * sz
            for yy in range(sz):           # checker bg
                for xx in range(sz):
                    if ((xx // 8) + (yy // 8)) % 2:
                        osheet.putpixel((x0 + xx, y0 + yy), (44, 44, 50))
            osheet.paste(spr.resize((sz, sz), Image.NEAREST), (x0, y0), spr.resize((sz, sz), Image.NEAREST))
        osheet.save(os.path.join(OUT, "object_atlas.png"))

    # NOTE: objsprites are intentionally NOT written. The detailed renders draw
    # objects only as a generic ~4px marker (no real art), so mining them yields
    # dots, not sprites. Real object art needs OBJ.256 decoding. We keep the
    # object pass only as a diagnostic (object_atlas.png + the report below).
    with open(os.path.join(OUT, "tileset.js"), "w") as fh:
        fh.write("window.TILESET = " + json.dumps(tileset) + ";\n")

    print(f"terrain values with a sprite: {len(tileset)}")
    for terr, _s, count, total in sorted(atlas_items):
        print(f"  0x{terr:02x}: {count}/{total} clean cells agree")
    print(f"object values with a sprite: {len(objsprites)}")
    for obj, _s, count, total, opaque in sorted(obj_items):
        print(f"  0x{obj:02x}: {count}/{total} samples, {opaque}/64 px opaque")

    # verification: re-render the first pair from the atlas only
    base = pairs[0]
    d = open(secs[base], "rb").read()
    canvas = Image.new("RGB", (PLAY * PX, PLAY * PX), (0, 0, 0))
    for r in range(PLAY):
        for c in range(PLAY):
            terr = d[(r * GRID + c) * CELL]
            if terr in tileset:
                raw = base64.b64decode(tileset[terr].split(",", 1)[1])
                canvas.paste(Image.open(io.BytesIO(raw)), (c * PX, r * PX))
    canvas.save(os.path.join(OUT, f"_verify_{base}.png"))
    print(f"wrote terrain_atlas.png, tileset.js, _verify_{base}.png")


if __name__ == "__main__":
    main()
