"""Render MRA .SEC sectors to images for visual inspection / puzzle placement.

Each SEC is 33x33 cells x 6 bytes; byte 0 of each cell is the terrain tile
index, byte 1 is a wall/overlay marker. We map terrain index -> color (a tuned
palette for the common indices, HSV-hash for the rest) and darken cells that
carry a wall overlay, so room/area shapes and walls are visible.

Modes:
  python sec_render.py composite      -> _render/world_composite.png
       (all coordinate-named sectors stitched at their EW/NS positions; this is
        the visual sanity check vs the .ods painted map)
  python sec_render.py tiles          -> _render/tiles/<name>.png + manifest.json
       (one PNG per sector + placement metadata, for the interactive tool)
"""
import base64
import colorsys
import json
import os
import sys

from PIL import Image

import build_world_coords as B

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_render")
GRID, CELL = 33, 6
PLAY = 32  # playable area (drop padding row/col 32)

# Tuned palette for the common terrain indices (refined by eye vs .ods).
PALETTE = {
    0x00: (8, 8, 12),       # void / black
    0x14: (54, 122, 50),    # grass (most common)
    0x15: (74, 150, 64),    # grass light
    0x12: (120, 96, 60),    # dirt / path
    0x10: (96, 140, 66),    # scrub
    0x18: (58, 104, 176),   # water
    0x1C: (170, 156, 104),  # sand / road
    0x2C: (28, 78, 30),     # trees / bush
    0x13: (88, 132, 58),    # grass var
    0x27: (66, 116, 196),   # water var
    0x25: (74, 124, 200),   # water var
    0x23: (132, 132, 138),  # stone / wall floor
    0x0F: (140, 120, 84),   # dirt var
    0x1B: (150, 150, 110),  # path var
    0x17: (80, 140, 70),    # grass var
    0x03: (60, 60, 70),     # cave floor
    0x1A: (160, 150, 100),  # path
    0x05: (40, 40, 52),     # cave
}


def color_for(idx):
    if idx in PALETTE:
        return PALETTE[idx]
    # stable HSV hash for unmapped indices
    h = (idx * 0.137) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.5, 0.7)
    return (int(r * 255), int(g * 255), int(b * 255))


def render_sector(data, scale=4, drop_pad=True):
    n = PLAY if drop_pad else GRID
    img = Image.new("RGB", (n * scale, n * scale))
    px = img.load()
    for r in range(n):
        for c in range(n):
            off = (r * GRID + c) * CELL
            terr = data[off]
            wall = data[off + 1]
            col = color_for(terr)
            if wall:  # darken cells with a wall/overlay marker
                col = tuple(int(v * 0.45) for v in col)
            for yy in range(scale):
                for xx in range(scale):
                    px[c * scale + xx, r * scale + yy] = col
    return img


def read_sec(path):
    d = open(path, "rb").read()
    return d if len(d) == GRID * GRID * CELL else None


def composite():
    os.makedirs(OUT, exist_ok=True)
    world = B.build()
    sectors = world["sectors"]
    ews = sorted(B.PREFIX_TO_MPX.values())          # 45..80
    nss = sorted({s["mp_y"] for s in sectors.values()})
    ew_idx = {e: i for i, e in enumerate(ews)}
    ns_idx = {n: i for i, n in enumerate(nss)}
    scale = 3
    tile = PLAY * scale
    W, H = len(ews) * tile, len(nss) * tile
    canvas = Image.new("RGB", (W, H), (20, 20, 24))
    maps_dir = B.MAPS_DIR
    # index files by basename
    paths = {}
    for r, _d, fs in os.walk(maps_dir):
        for f in fs:
            if f.upper().endswith(".SEC"):
                paths[f] = os.path.join(r, f)
    placed = 0
    for base, s in sectors.items():
        if s["layer"] != "c" and f"{base[:-1]}c" in sectors:
            continue  # prefer ground layer c for the view
        p = paths.get(s["filename"])
        if not p:
            continue
        d = read_sec(p)
        if not d:
            continue
        img = render_sector(d, scale=scale)
        x = ew_idx[s["mp_x"]] * tile
        y = ns_idx[s["mp_y"]] * tile
        canvas.paste(img, (x, y))
        placed += 1
    out = os.path.join(OUT, "world_composite.png")
    canvas.save(out)
    print(f"composite: placed {placed} sectors -> {out} ({W}x{H})")


def tiles():
    os.makedirs(os.path.join(OUT, "tiles"), exist_ok=True)
    world = B.build()
    coord = {}
    for base, s in world["sectors"].items():
        coord[s["filename"]] = {
            "mp_x": s["mp_x"], "mp_y": s["mp_y"], "mp_z": s["mp_z"],
            "place_name": s["place_name"], "layer": s["layer"],
        }
    manifest = {"coordinate": [], "area": []}
    for label, root in (("coordinate", B.MAPS_DIR), ("area", B.MAPSALL_DIR)):
        for r, _d, fs in os.walk(root):
            for f in sorted(fs):
                if not f.upper().endswith(".SEC") or f.startswith("._"):
                    continue
                p = os.path.join(r, f)
                d = read_sec(p)
                if not d:
                    continue
                img = render_sector(d, scale=4)
                safe = f.replace("/", "_")
                img.save(os.path.join(OUT, "tiles", safe + ".png"))
                rec = {"filename": f, "png": f"tiles/{safe}.png"}
                if label == "coordinate" and f in coord:
                    rec.update(coord[f])
                else:
                    region = os.path.basename(r)
                    rec["region"] = region
                manifest[label].append(rec)
    with open(os.path.join(OUT, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    # also emit JS (so the HTML tool works from file:// with no fetch/CORS)
    layout = B.load_layout()
    layout_js = {f"{k[0]},{k[1]}": v for k, v in layout.items()}
    with open(os.path.join(OUT, "data.js"), "w") as fh:
        fh.write("window.MANIFEST = " + json.dumps(manifest) + ";\n")
        fh.write("window.LAYOUT = " + json.dumps(layout_js) + ";\n")
    print(f"tiles: {len(manifest['coordinate'])} coordinate + "
          f"{len(manifest['area'])} area -> {OUT}/tiles, manifest.json, data.js")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "composite"
    if mode == "composite":
        composite()
    elif mode == "tiles":
        tiles()
    else:
        print(__doc__)
