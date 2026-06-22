"""World map reconciliation tools for MRA.

Ground-truth sources:
  - Tekken/index.html : clickable image-map of the master world map
    (Mystic Realms Of Alhanzar.gif, 1776x1520). Each region is a polygon
    with pixel coords -> authoritative on-map position.
  - MAPS.TXT          : the game's own regional adjacency text.
  - _winmra_dump/world_map.json : the server's CURRENT (community-derived,
    unverified) (x_block, y_block, layer) -> sector mapping.

This module extracts canonical region centroids from the image map and
compares them against the server's current sector placement so we can build
a corrected world_map.json (a drop-in override beside MRA_Server.exe).
"""

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML = os.path.join(HERE, "Tekken", "index.html")
WORLD_JSON = os.path.join(HERE, "_winmra_dump", "world_map.json")

MAP_W, MAP_H = 1776, 1520

# Tekken region slug -> canonical place name (matches world_map.json place_name)
SLUG_TO_PLACE = {
    "krellx": "Krell X",
    "krell": "Krell",
    "krelle": "Krell Elite",
    "krellk": "Krell Castle",
    "krellg": "Krell Graveyard",
    "bke": "Bastion of Krell Elite",
    "gobcave": "Goblins",
    "uswick": "Uswick",
    "unvil": "Undead Village",
    "kokas": "Kobold Castle",
    "haven": "Haven",
    "breedery": "Breedery",
    "salazad": "Salazad",
    "omr": "Old Minton Ruins",
    "rem": "East Minton Ruins",
    "clysmort": "Clysmort",
    "greenwd": "Greenwood",
    "verbonic": "Verbonic",
    "dunsmore": "Dunsmore",
    "college": "Newbie College",
}


def parse_image_map(path=INDEX_HTML):
    """Return list of (slug, centroid_x, centroid_y, bbox) from the image map."""
    html = open(path, encoding="latin1").read()
    out = []
    pat = re.compile(r'coords="([0-9,]+)"\s+href="([a-z0-9]+)\.html"', re.I)
    for m in pat.finditer(html):
        nums = [int(n) for n in m.group(1).split(",")]
        xs, ys = nums[0::2], nums[1::2]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        out.append((m.group(2), cx, cy, (min(xs), min(ys), max(xs), max(ys))))
    return out


def canonical_layout():
    """Return regions sorted with normalized compass position.

    north_south: 0.0 = far north (top), 1.0 = far south (bottom)
    west_east:   0.0 = far west (left), 1.0 = far east (right)
    """
    regs = parse_image_map()
    rows = []
    for slug, cx, cy, _bbox in regs:
        rows.append({
            "slug": slug,
            "place": SLUG_TO_PLACE.get(slug, slug),
            "cx": cx, "cy": cy,
            "ns": round(cy / MAP_H, 3),
            "we": round(cx / MAP_W, 3),
        })
    rows.sort(key=lambda r: (r["ns"], r["we"]))
    return rows


def current_layout():
    """Return {place_name: [(x_block, y_block, layer, mp_x, mp_y), ...]}."""
    d = json.load(open(WORLD_JSON))
    out = {}
    for key, v in d["sectors"].items():
        pn = v.get("place_name")
        if not pn:
            continue
        out.setdefault(pn, []).append(
            (v.get("x_block"), v.get("y_block"), v.get("layer"),
             v.get("mp_x"), v.get("mp_y"))
        )
    return out


def coverage_report():
    """Classify each server region by whether Tekken / MAPS.TXT documents it."""
    tekken_places = {v.lower() for v in SLUG_TO_PLACE.values()}
    # keyword tokens present in the Tekken master map (regions + sub-areas)
    tekken_tokens = {
        "krell", "goblin", "gob", "haven", "sanctuary", "breedery",
        "verbonic", "uswick", "undead", "kobold", "kobs", "minton", "omr",
        "clysmort", "greenwood", "dunsmore", "college", "salazad", "bke",
        "bastion",
    }
    # tokens named in MAPS.TXT regional overview
    maps_txt_tokens = {
        "krell", "uswick", "happy valley", "orc", "undv", "undead",
        "sanctuary", "anthill", "gob", "kobs", "kobold", "haven", "have",
        "misty", "omruins", "omr", "minton", "verbonic", "styx", "swamp",
        "clysmort", "greenwood", "salazad",
    }

    cur = current_layout()
    rows = []
    for place in sorted(cur):
        pl = place.lower()
        in_tek = any(t in pl for t in tekken_tokens)
        in_maps = any(t in pl for t in maps_txt_tokens)
        rows.append((place, in_tek, in_maps))
    return rows


def server_grid():
    """Return {(x_block, y_block): [(place, layer, mp_x, mp_y), ...]}."""
    d = json.load(open(WORLD_JSON))
    grid = {}
    for key, v in d["sectors"].items():
        xb, yb = v.get("x_block"), v.get("y_block")
        if xb is None or yb is None:
            continue
        grid.setdefault((xb, yb), []).append(
            (v.get("place_name") or "-", v.get("layer"),
             v.get("mp_x"), v.get("mp_y"))
        )
    return grid


def print_grid():
    """Print the server grid as x_block (cols) x y_block (rows)."""
    grid = server_grid()
    xs = sorted({k[0] for k in grid})
    ys = sorted({k[1] for k in grid})
    print("Grid: x_block (W->E) across, y_block (N->S?) down")
    print("cols x_block:", xs)
    for yb in ys:
        print(f"\ny_block {yb}:")
        for xb in xs:
            cell = grid.get((xb, yb))
            if not cell:
                continue
            names = ", ".join(sorted({c[0] for c in cell if c[0] != '-'}))
            if names:
                mpx = sorted({c[2] for c in cell if c[2] is not None})
                mpy = sorted({c[3] for c in cell if c[3] is not None})
                print(f"  x{xb}: {names:<28} mp_x={mpx} mp_y={mpy}")


if __name__ == "__main__":
    import sys
    if "--grid" in sys.argv:
        print_grid()
        sys.exit(0)
    if "--coverage" in sys.argv:
        print(f"{'server region':<24}{'Tekken':>8}{'MAPS.TXT':>10}")
        only_server = []
        for place, in_tek, in_maps in coverage_report():
            t = "yes" if in_tek else "-"
            m = "yes" if in_maps else "-"
            print(f"{place:<24}{t:>8}{m:>10}")
            if not in_tek and not in_maps:
                only_server.append(place)
        print(f"\nUNDOCUMENTED (server-only, need friends/screenshots): {len(only_server)}")
        print("  " + ", ".join(only_server))
        sys.exit(0)

    print("=== CANONICAL region layout (from Tekken master map) ===")
    print(f"{'region':<22}{'N->S':>6}{'W->E':>6}")
    for r in canonical_layout():
        print(f"{r['place']:<22}{r['ns']:>6}{r['we']:>6}")

    print("\n=== CURRENT server placement (world_map.json place_names) ===")
    cur = current_layout()
    for place in sorted(cur):
        cells = cur[place]
        mpx = sorted({c[3] for c in cells if c[3] is not None})
        mpy = sorted({c[4] for c in cells if c[4] is not None})
        print(f"{place:<24} mp_x={mpx}  mp_y={mpy}  ({len(cells)} sectors)")
