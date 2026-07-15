"""Mine and classify transition cells from every .SEC.

Object / terrain bytes (SCB palette):
  object 1 = Teleportal         -> waypoint (blue pad; memorized travel, not a fixed link)
  object 2 = Room Teleportal    -> room_waypoint
  object 3 = Instant Teleportal -> fixed_warp (step-on destination)
  object 4 = Invisible Teleportal -> fixed_warp (hidden step-on)
  terrain 5 = Go to sector above -> up
  terrain 4 = Go to sector below -> down
  terrain 6/7 or object 7        -> fall

Destinations for fixed warps lived in lost .CRT/.MSG companions, so this only
classifies and locates them. Stairs/falls drive the multi-floor assembler.

Emits _render/portals.js -> window.SEC_EXITS = {
  "haven1.SEC": {
    "waypoint":[{"r":12,"c":5,"k":1,"e":0,"pad":0}, ...],
    "room_waypoint":[...],
    "fixed_warp":[{"r":3,"c":8,"k":3,"e":0,"pad":0}, ...],
    "up":[{"r":4,"c":8,"pad":0}, ...],
    "down":[{"r":5,"c":8,"pad":0}, ...],
    "fall":[{"r":10,"c":2,"k":"air7","pad":0}, ...],
    "pads":[{"id":0,"kind":"waypoint","cells":[[12,5]],"r":12,"c":5}, ...]
  },
  ...
}

Also keeps a legacy "tp"/"dn" alias for older UI code during migration.
"""
import glob
import json
import os
from collections import Counter, deque

import build_world_coords as B

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_render", "portals.js")
GRID, CELL, PLAY = 33, 6, 32

TP_KIND = {1: "waypoint", 2: "room_waypoint", 3: "fixed_warp", 4: "fixed_warp"}
TP_LABEL = {1: "teleportal", 2: "room", 3: "instant", 4: "invisible"}


def group_pads(cells, kind):
    """4-way connected components of same-kind cells -> pad records."""
    remaining = {(c["r"], c["c"]): c for c in cells}
    pads, assigned = [], {}
    while remaining:
        start = next(iter(remaining))
        q = deque([start])
        members = []
        while q:
            rc = q.popleft()
            if rc not in remaining:
                continue
            cell = remaining.pop(rc)
            members.append(cell)
            r, c = rc
            for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if (nr, nc) in remaining:
                    q.append((nr, nc))
        members.sort(key=lambda x: (x["r"], x["c"]))
        pad_id = len(pads)
        pads.append({
            "id": pad_id,
            "kind": kind,
            "cells": [[m["r"], m["c"]] for m in members],
            "r": members[0]["r"],
            "c": members[0]["c"],
            "n": len(members),
        })
        for m in members:
            assigned[(m["r"], m["c"])] = pad_id
            m["pad"] = pad_id
    return pads


def scan(path):
    d = open(path, "rb").read()
    if len(d) != GRID * GRID * CELL:
        return None
    waypoint, room_wp, fixed, up, down, fall = [], [], [], [], [], []
    for r in range(PLAY):
        for c in range(PLAY):
            o = (r * GRID + c) * CELL
            terr, obj, ent = d[o], d[o + 1], d[o + 5]
            if obj == 1:
                waypoint.append({"r": r, "c": c, "k": 1, "e": int(ent)})
            elif obj == 2:
                room_wp.append({"r": r, "c": c, "k": 2, "e": int(ent)})
            elif obj in (3, 4):
                fixed.append({"r": r, "c": c, "k": obj, "e": int(ent)})
            if terr == 5:
                up.append({"r": r, "c": c})
            elif terr == 4:
                down.append({"r": r, "c": c})
            if terr in (6, 7):
                fall.append({"r": r, "c": c, "k": f"air{terr}"})
            elif obj == 7:
                fall.append({"r": r, "c": c, "k": "hole"})
    if not (waypoint or room_wp or fixed or up or down or fall):
        return None

    pads = []
    out = {}

    def add_group(key, cells, kind):
        nonlocal pads
        if not cells:
            return
        g = group_pads(cells, kind)
        # renumber pad ids into the sector-global pad list
        for p in g:
            pid = len(pads)
            for cell in cells:
                if cell.get("pad") == p["id"]:
                    cell["pad"] = pid
            p["id"] = pid
            pads.append(p)
        out[key] = cells

    add_group("waypoint", waypoint, "waypoint")
    add_group("room_waypoint", room_wp, "room_waypoint")
    add_group("fixed_warp", fixed, "fixed_warp")
    add_group("up", up, "up")
    add_group("down", down, "down")
    add_group("fall", fall, "fall")
    if pads:
        out["pads"] = pads
    # legacy aliases used by older UI during migration
    legacy_tp = waypoint + room_wp + fixed
    if legacy_tp:
        out["tp"] = legacy_tp
    if down:
        out["dn"] = down
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
        fh.write("// Sector transitions (extract_portals.py). "
                 "waypoint/room_waypoint = blue TP pads (no fixed dest). "
                 "fixed_warp = instant/invisible step-on. "
                 "up/down/fall = floor transitions. "
                 "pads = connected components.\n")
        fh.write("window.SEC_EXITS = " + json.dumps(exits, separators=(",", ":"))
                 + ";\n")

    n_wp = sum(len(v.get("waypoint", [])) for v in exits.values())
    n_rw = sum(len(v.get("room_waypoint", [])) for v in exits.values())
    n_fw = sum(len(v.get("fixed_warp", [])) for v in exits.values())
    n_up = sum(len(v.get("up", [])) for v in exits.values())
    n_dn = sum(len(v.get("down", [])) for v in exits.values())
    n_fall = sum(len(v.get("fall", [])) for v in exits.values())
    n_pads = sum(len(v.get("pads", [])) for v in exits.values())
    fw_kinds = Counter(x["k"] for v in exits.values() for x in v.get("fixed_warp", []))
    print(f"wrote {os.path.basename(OUT)}: {len(exits)} sectors with exits")
    print(f"  waypoint={n_wp}  room_waypoint={n_rw}  "
          f"fixed_warp={n_fw} (kinds {dict(fw_kinds)})")
    print(f"  stairs up={n_up} down={n_dn}  fall={n_fall}  pads={n_pads}")
    print(f"  {os.path.getsize(OUT) // 1024} KB")


if __name__ == "__main__":
    main()
