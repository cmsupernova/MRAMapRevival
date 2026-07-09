"""Mine teleportal / stair / fall-through exit cells from every .SEC.

Destinations live in lost .CRT/.MSG companions (entity index is almost always
0), so this cannot auto-wire portals. It does give the Flat tab a concrete
checklist: every exit cell that still needs a human-authored link.

Emits _render/portals.js -> window.SEC_EXITS = {
  "haven1.SEC": {
    "tp":  [{"r":12,"c":5,"k":1,"e":0}, ...],   # teleportal objects 1..4
    "up":  [{"r":3,"c":8}, ...],                 # terrain 5 (go above)
    "dn":  [{"r":4,"c":8}, ...],                 # terrain 4 (go below)
    "fall":[{"r":10,"c":2,"k":"air7"}, ...]      # air 6/7 or hole object 7
  },
  ...
}

Kinds (tp.k): 1 Teleportal, 2 Room, 3 Instant, 4 Invisible.
"""
import glob
import json
import os
from collections import Counter

import build_world_coords as B

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_render", "portals.js")
GRID, CELL, PLAY = 33, 6, 32

TP_KINDS = {1: "teleportal", 2: "room", 3: "instant", 4: "invisible"}


def scan(path):
    d = open(path, "rb").read()
    if len(d) != GRID * GRID * CELL:
        return None
    tp, up, dn, fall = [], [], [], []
    for r in range(PLAY):
        for c in range(PLAY):
            o = (r * GRID + c) * CELL
            terr, obj, ent = d[o], d[o + 1], d[o + 5]
            if 1 <= obj <= 4:
                tp.append({"r": r, "c": c, "k": obj, "e": int(ent)})
            if terr == 5:
                up.append({"r": r, "c": c})
            elif terr == 4:
                dn.append({"r": r, "c": c})
            if terr in (6, 7):
                fall.append({"r": r, "c": c, "k": f"air{terr}"})
            elif obj == 7:
                fall.append({"r": r, "c": c, "k": "hole"})
    if not (tp or up or dn or fall):
        return None
    out = {}
    if tp:
        out["tp"] = tp
    if up:
        out["up"] = up
    if dn:
        out["dn"] = dn
    if fall:
        out["fall"] = fall
    return out


def main():
    # Prefer MAPSALL (2011 name-based) over MAPS (2006) when both exist.
    paths = {}
    for root in (B.MAPS_DIR, B.MAPSALL_DIR):
        for p in glob.glob(os.path.join(root, "**", "*.SEC"), recursive=True):
            f = os.path.basename(p)
            if not f.startswith("._"):
                paths[f] = p

    exits = {}
    for f, p in sorted(paths.items()):
        info = scan(p)
        if info:
            exits[f] = info

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("// Sector exit cells (extract_portals.py). "
                 "tp=teleportal, up/dn=stairs, fall=air/hole. "
                 "Destinations require manual portal links (.CRT/.MSG lost).\n")
        fh.write("window.SEC_EXITS = " + json.dumps(exits, separators=(",", ":"))
                 + ";\n")

    n_tp = sum(len(v.get("tp", [])) for v in exits.values())
    n_up = sum(len(v.get("up", [])) for v in exits.values())
    n_dn = sum(len(v.get("dn", [])) for v in exits.values())
    n_fall = sum(len(v.get("fall", [])) for v in exits.values())
    kinds = Counter(x["k"] for v in exits.values() for x in v.get("tp", []))
    print(f"wrote {os.path.basename(OUT)}: {len(exits)} sectors with exits")
    print(f"  teleports={n_tp} (kinds {dict(kinds)})  "
          f"stairs up={n_up} down={n_dn}  fall={n_fall}")
    print(f"  {os.path.getsize(OUT) // 1024} KB")


if __name__ == "__main__":
    main()
