"""Flag which .SEC sectors carry a floor-transition tile, for the map tools.

Terrain id 5 = "Go to sector above" (UP), id 4 = "Go to sector below" (DOWN)
per the authoritative SCB table. A sector with either links to another floor at
the same world cell, so the world/interior tools can badge it. (Per SCB.TXT the
up/down tiles must overlap on adjacent, not identical, squares of the two
floors - so a cell with an UP tile expects a DOWN tile on the floor above.)

Emits _render/stairs.js:  window.STAIRS = {filename: {u:bool, d:bool}}  (only
sectors that have at least one transition tile are listed).
"""
import glob
import json
import os

import build_world_coords as B

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_render", "stairs.js")
GRID, CELL = 33, 6


def main():
    paths = {}
    for root in (B.MAPS_DIR, B.MAPSALL_DIR):
        for p in glob.glob(os.path.join(root, "**", "*.SEC"), recursive=True):
            f = os.path.basename(p)
            if not f.startswith("._"):
                paths.setdefault(f, p)

    stairs = {}
    for f, p in sorted(paths.items()):
        d = open(p, "rb").read()
        if len(d) != GRID * GRID * CELL:
            continue
        up = down = False
        for i in range(0, len(d), CELL):
            t = d[i]
            if t == 5:
                up = True
            elif t == 4:
                down = True
            if up and down:
                break
        if up or down:
            stairs[f] = {"u": up, "d": down}

    with open(OUT, "w") as fh:
        fh.write("// Floor-transition flags (extract_stairs.py). "
                 "u = has UP tile (terrain 5); d = has DOWN tile (terrain 4).\n")
        fh.write("window.STAIRS = " + json.dumps(stairs) + ";\n")

    u = sum(1 for v in stairs.values() if v["u"])
    dn = sum(1 for v in stairs.values() if v["d"])
    print(f"wrote {os.path.basename(OUT)}: {len(stairs)} sectors with stairs "
          f"({u} up, {dn} down), {os.path.getsize(OUT)//1024} KB")


if __name__ == "__main__":
    main()
