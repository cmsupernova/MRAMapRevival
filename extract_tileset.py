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
                if obj or walls:           # only clean terrain cells
                    continue
                block = bytes(
                    v for yy in range(PX) for xx in range(PX)
                    for v in px[c * PX + xx, r * PX + yy]
                )
                samples.setdefault(terr, Counter())[block] += 1

    tileset, atlas_items = {}, []
    for terr in sorted(samples):
        block, count = samples[terr].most_common(1)[0]
        spr = Image.frombytes("RGB", (PX, PX), block)
        buf = io.BytesIO(); spr.save(buf, "PNG")
        tileset[terr] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        atlas_items.append((terr, spr, count, sum(samples[terr].values())))

    # atlas sheet: 16 per row, each sprite scaled x4 with a label gap
    cols, sz = 16, PX * 4
    rows = (len(atlas_items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * sz, rows * sz), (24, 24, 28))
    for i, (terr, spr, _c, _t) in enumerate(atlas_items):
        big = spr.resize((sz, sz), Image.NEAREST)
        sheet.paste(big, ((i % cols) * sz, (i // cols) * sz))
    sheet.save(os.path.join(OUT, "terrain_atlas.png"))

    with open(os.path.join(OUT, "tileset.js"), "w") as fh:
        fh.write("window.TILESET = " + json.dumps(tileset) + ";\n")

    print(f"terrain values with a sprite: {len(tileset)}")
    for terr, _s, count, total in sorted(atlas_items):
        print(f"  0x{terr:02x}: {count}/{total} clean cells agree")

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
