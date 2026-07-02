"""Compute world-position anchors for assembled region blocks (flat canvas).

Where should each assembled 2011 block sit on the flat surface canvas? Two
evidence sources, in priority order:

  1. era matches (match_eras.py): a block piece that is a confident content
     match of a 2006 coordinate SEC inherits that SEC's world cell. Each
     matched piece votes for the block anchor; majority wins.
  2. guide names: the community layout (world_layout_authoritative.json via
     build_world_coords.load_layout) names each world cell ("W Haven",
     "Castle Krell", "Guildhalls"...). A block whose region matches some
     named cells is centered on their centroid. Cross-checked against the
     Tekken-map adjacency chart (MAPS.TXT) - region tokens below follow it
     (e.g. unvil = Undead Village, val = Valadia, greenwood = Guildhalls).

Flat canvas mapping: world cell (mp_x, mp_y) -> col=(mp_x-10)/5+1,
row=(mp_y-15)/5+1 (one-cell border). The world grid spans cols 1..19,
rows 1..16 of the 40x40 canvas; the rest is free space.

Output: _render/block_anchors.js  ->  window.BLOCK_ANCHORS = {
    "Towns/Haven#1": {"col":10, "row":8, "method":"era", "votes":3}, ... }

Usage: python anchor_blocks.py
"""
import json
import os
from collections import Counter

import build_world_coords as B

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, "_render")
OUT = os.path.join(RENDER, "block_anchors.js")

CANVAS_W = CANVAS_H = 40
BORDER = 1  # world cell (0,0) lands at canvas (1,1)

# region folder -> lowercase tokens matched against layout guide names.
# Derived from MAPS.TXT / Tekken map naming: unvil=Undead Village,
# greenwood=Guildhalls, val=Valadia, DTN/DTS=Dunsmore town.
NAME_TOKENS = {
    "Towns/Haven": ["haven"],
    "Towns/Clysmort": ["clysmort"],
    "Towns/Salazad": ["salazad"],
    "Towns/Uswick": ["uswick"],
    "Towns/Verbonic": ["verbonic"],
    "Towns/Sanctuary": ["sanctuary"],
    "Towns/Baralza": ["baralza"],
    "Krell": ["krell"],
    "greenwood": ["greenwood", "guildhalls"],
    "gom": ["gom"],
    "jal": ["jal"],
    "maranda": ["maranda", "mar "],
    "per": ["per ", "prg"],
    "orcs": ["orc"],
    "rem": ["rem"],
    "omr": ["omr"],
    "iun": ["iun"],
    "Kokas": ["kokas"],
    "unvil": ["undead village"],
    "GobCavE": ["goblin cave"],
    "GobTun": ["gob tunnel"],
    "swamp": ["swamp"],
    "val": ["valadia"],
    "DTN and DTS": ["dunsmore"],
}


def load_js_object(path, prefix):
    s = open(path, encoding="utf-8").read()
    i = s.index(prefix) + len(prefix)
    j = s.rindex("}")
    return json.loads(s[i:j + 1].rstrip().rstrip(";").strip())


def world_to_canvas(mp_x, mp_y):
    return (mp_x - 10) // 5 + BORDER, (mp_y - 15) // 5 + BORDER


def main():
    blocks = json.load(open(os.path.join(RENDER, "blocks.json")))["blocks"]
    manifest = json.load(open(os.path.join(RENDER, "manifest.json")))
    era = load_js_object(os.path.join(RENDER, "era_map.js"), "window.ERA_MAP =")

    coord_cell = {t["filename"]: (t["mp_x"], t["mp_y"])
                  for t in manifest.get("coordinate", [])
                  if t.get("mp_x") is not None}
    # invert era map: 2011 area file -> world cell of its 2006 counterpart
    area_cell = {}
    for cf, v in era.items():
        if v.get("ok") and cf in coord_cell:
            area_cell[v["area"]] = coord_cell[cf]

    # guide-name cells per region
    layout = B.load_layout()  # (mp_x, mp_y) -> name
    region_cells = {}
    for (mx, my), name in layout.items():
        n = name.lower()
        if " of " in n:            # "N of Salazad" = neighbor, not the place
            continue
        for region, tokens in NAME_TOKENS.items():
            if any(t in n for t in tokens):
                region_cells.setdefault(region, []).append((mx, my))

    anchors = {}
    for b in blocks:
        if len(b["pieces"]) < 2:
            continue
        votes = Counter()
        for p in b["pieces"]:
            cell = area_cell.get(p["filename"])
            if cell:
                cx, cy = world_to_canvas(*cell)
                votes[(cx - p["dx"], cy - p["dy"])] += 1
        method = None
        if votes:
            (col, row), n = votes.most_common(1)[0]
            method, conf = "era", n
        else:
            cells = region_cells.get(b["region"])
            if not cells:
                continue
            cx = sum(world_to_canvas(mx, my)[0] for mx, my in cells) / len(cells)
            cy = sum(world_to_canvas(mx, my)[1] for mx, my in cells) / len(cells)
            col = round(cx - (b["w"] - 1) / 2)
            row = round(cy - (b["h"] - 1) / 2)
            method, conf = "name", len(cells)
        col = max(0, min(CANVAS_W - b["w"], col))
        row = max(0, min(CANVAS_H - b["h"], row))
        anchors[b["id"]] = {"col": col, "row": row,
                            "method": method, "votes": conf}

    with open(OUT, "w") as fh:
        fh.write("// Block anchors (world positions on the flat canvas) by "
                 "anchor_blocks.py. Do not edit by hand.\n")
        fh.write("window.BLOCK_ANCHORS = " + json.dumps(anchors) + ";\n")

    n_era = sum(1 for a in anchors.values() if a["method"] == "era")
    n_name = sum(1 for a in anchors.values() if a["method"] == "name")
    total = sum(1 for b in blocks if len(b["pieces"]) > 1)
    print(f"anchored {len(anchors)}/{total} blocks "
          f"({n_era} via era matches, {n_name} via guide names)")
    for bid, a in sorted(anchors.items()):
        print(f"  {bid:28s} -> ({a['col']:2d},{a['row']:2d})  "
              f"{a['method']}({a['votes']})")
    missing = [b["id"] for b in blocks
               if len(b["pieces"]) > 1 and b["id"] not in anchors]
    if missing:
        print("unanchored (parked when laying out):", ", ".join(missing))


if __name__ == "__main__":
    main()
