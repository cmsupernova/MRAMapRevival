"""Render MRA .SEC sectors to images for visual inspection / puzzle placement.

Per the verified SEC format (SEC FILE FORMAT.md, from SCB.exe): each SEC is
33x33 cells x 6 bytes:
  byte 0   terrain index   (named palette, see PALETTE below)
  byte 1   object index    (decorations: trees, furniture; 0 = none)
  byte 2-3 wall + door bits (u16 LE: bits0-4 north wall, bits5-9 west wall)
  byte 4   west-edge door bits
  byte 5   entity index into .MSG/.CRT

We map terrain -> color, draw walls as dark edges, and dot object cells, so
room/building shapes read. NOTE: for display the tool now prefers the detailed
256px renders in contents/ (see apply_detail_tiles.py); this schematic is the
fallback for any sector lacking a detailed render.

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

# Palette keyed to the VERIFIED terrain byte reference (SEC FILE FORMAT.md 13a).
PALETTE = {
    0x00: (8, 8, 12),       # void / black, impassable
    0x02: (40, 40, 48),     # no see through
    0x03: (30, 28, 40),     # veil of darkness (boundary)
    0x04: (90, 80, 140),    # go to sector below (transition)
    0x05: (140, 120, 90),   # go to sector above (transition)
    0x06: (60, 64, 78),     # indoor air
    0x07: (70, 90, 110),    # outdoor air
    0x0F: (90, 150, 200),   # shallow water
    0x10: (150, 110, 66),   # wood panel floor
    0x11: (178, 140, 92),   # light wood panel floor
    0x12: (132, 132, 138),  # stone floor
    0x13: (198, 198, 204),  # marble floor
    0x14: (54, 122, 50),    # grass (most common)
    0x15: (40, 78, 170),    # deep water (not walkable)
    0x16: (140, 100, 58),   # solid wood floor
    0x17: (90, 90, 98),     # darkened stone floor
    0x18: (96, 70, 44),     # dark wood panel floor
    0x19: (224, 224, 228),  # styled white floor
    0x1A: (170, 150, 100),  # styled pub floor
    0x1B: (110, 108, 116),  # cave stone floor
    0x1C: (150, 118, 78),   # dirt
    0x1D: (60, 48, 40),     # refuse hole
    0x1E: (128, 96, 60),    # plowed ground
    0x1F: (138, 104, 66),   # plowed ground var
    0x21: (44, 44, 52),     # blackened marble
    0x22: (52, 42, 34),     # blackened wood
    0x23: (70, 96, 70),     # marsh
    0x24: (70, 120, 120),   # shallow swamp water
    0x25: (44, 86, 90),     # deep swamp water
    0x26: (96, 168, 96),    # blue sky grass
    0x3C: (150, 70, 56),    # brick floor
    0x3D: (80, 120, 180),   # standing water
    0x3E: (70, 110, 60),    # moss
}
WALL_EDGE = (18, 16, 22)    # near-black wall edges
OBJECT_DOT = (230, 210, 120)  # small marker for object cells


def color_for(idx):
    if idx in PALETTE:
        return PALETTE[idx]
    # stairs / landing band
    if 0x30 <= idx <= 0x34:
        return (120, 120, 128)
    # stable HSV hash for unmapped indices
    h = (idx * 0.137) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.5, 0.7)
    return (int(r * 255), int(g * 255), int(b * 255))


def render_sector(data, scale=6, drop_pad=True):
    n = PLAY if drop_pad else GRID
    img = Image.new("RGB", (n * scale, n * scale))
    px = img.load()
    for r in range(n):
        for c in range(n):
            off = (r * GRID + c) * CELL
            terr = data[off]
            obj = data[off + 1]
            walls = data[off + 2] | (data[off + 3] << 8)
            north_wall = walls & 0x1F          # bits 0-4
            west_wall = (walls >> 5) & 0x1F     # bits 5-9
            col = color_for(terr)
            x0, y0 = c * scale, r * scale
            for yy in range(scale):
                for xx in range(scale):
                    px[x0 + xx, y0 + yy] = col
            # object decoration: a small center dot
            if obj:
                cx, cy = x0 + scale // 2, y0 + scale // 2
                px[cx, cy] = OBJECT_DOT
                if scale >= 6:
                    px[cx - 1, cy] = OBJECT_DOT
            # walls live on the owning cell's north / west edge
            if north_wall:
                for xx in range(scale):
                    px[x0 + xx, y0] = WALL_EDGE
            if west_wall:
                for yy in range(scale):
                    px[x0, y0 + yy] = WALL_EDGE
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
                img = render_sector(d, scale=6)  # 32*6=192px -> crisp hover preview
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
