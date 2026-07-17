"""Compile community / unified placements -> a server-ready world_map.json.

Closes the loop: the unified map (sec_map.html) preloads generated Floor 0
placements and lets the community override them. This folds Floor 0 placements
onto the binary-grounded core (build_world_coords) and emits the engine schema
mra_stub.py consumes (sectors / block_to_base / y_axis_ranges).

Non-zero floors are interiors and are ignored here (see build_clusters.py).

Placement sources (first that yields rows wins):
  1. a JSON file argument - unified_map_export.json OR legacy area_placements
  2. live Supabase REST (unified: rows only; legacy four-tab rows ignored)
  3. --from-generated uses _render/unified_map.json Floor 0

A placement whose filename is the blank sentinel "__cleared__" REMOVES the core
tile at that cell.

Run:
  python build_world_map.py                         # pull unified from Supabase
  python build_world_map.py unified_map_export.json # use an exported file
  python build_world_map.py --from-generated         # use unified_map.json Floor 0
  python build_world_map.py export.json --allow-expand  # allow MP outside 45-80/15-80
Output: world_map_built.json

By default, editor cells that map outside the engine band (MP 45-80 x 15-80)
are skipped so parked far-canvas assemblies do not become real geography.
haven1.SEC is pinned as the spawn *content* under base name EWGB194225b
(the server hardcodes that name in Player.set_initial; without it, spawn
picks a random high-breathing-room sector).
"""
import json
import os
import sys
import urllib.request

import build_world_coords as B

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "world_map_built.json")
UNIFIED = os.path.join(HERE, "_render", "unified_map.json")
CLEARED = "__cleared__"

SUPABASE_URL = "https://msnxqnqqpdwamzfbwskm.supabase.co"
SUPABASE_KEY = "sb_publishable_MjRmbztlv0wlOQXpTvoBlQ__BJobsxC"

WORLD_OFF = 6
WORLD_SCALE = 2

# Engine-safe outdoor band (original WINMRA / 2006 prefix grid).
# Editor canvas is larger and parks interiors/far assemblies outside this;
# those must NOT become real MP coordinates or spawn/position math breaks.
MP_X_MIN, MP_X_MAX = 45, 80
MP_Y_MIN, MP_Y_MAX = 15, 80
XB_MIN, XB_MAX = 0, 7
YB_MIN, YB_MAX = 0, 13

MPX_TO_XBLOCK = {v: k for k, v in
                 zip(B.PREFIX_TO_XBLOCK.values(), B.PREFIX_TO_MPX.values())}
MPX_TO_PREFIX = {v: k for k, v in B.PREFIX_TO_MPX.items()}
LAYER_FROM_LEVEL = {0: "b", -1: "a", 1: "c"}

# When several editor cells crush onto one MP cell, prefer these bases.
CELL_PRIORITY = {
    "haven1": 100, "haven2": 90, "haven3": 90, "haven5": 90, "haven9": 90,
    "sanctuary1": 80, "sanctuary2": 80, "sanctuary3": 80, "sanctuary4": 80,
}


def xblock_of_mpx(mp_x):
    if mp_x in MPX_TO_XBLOCK:
        return MPX_TO_XBLOCK[mp_x]
    return (mp_x - 45) // 5


def yblock_of_mpy(mp_y):
    return (mp_y - 15) // 5


def canvas_to_world(col, row):
    mp_x = ((col - WORLD_OFF) // WORLD_SCALE) * 5 + 10
    mp_y = ((row - WORLD_OFF) // WORLD_SCALE) * 5 + 15
    return mp_x, mp_y


def fetch_supabase():
    url = f"{SUPABASE_URL}/rest/v1/placements?select=*&cell=like.unified:*"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def normalize_rows(raw):
    if isinstance(raw, dict):
        if "placements" in raw:
            rows = []
            for p in raw["placements"]:
                lv = int(p.get("level", 0))
                if lv != 0:
                    continue
                fname = p.get("filename")
                if not fname or fname == CLEARED:
                    continue
                if "col" in p and "row" in p:
                    mp_x = p.get("mp_x")
                    mp_y = p.get("mp_y")
                    if mp_x is None or mp_y is None:
                        mp_x, mp_y = canvas_to_world(int(p["col"]), int(p["row"]))
                    rows.append({
                        "filename": fname,
                        "mp_x": int(mp_x), "mp_y": int(mp_y),
                        "layer": LAYER_FROM_LEVEL.get(lv, "b"),
                        "place_name": p.get("place_name"),
                        "updated_by": "unified-export",
                    })
                elif "mp_x" in p:
                    rows.append(p)
            return rows
        if "area_placements" in raw:
            return raw["area_placements"]
        return []
    if isinstance(raw, list):
        out = []
        for p in raw:
            cell = p.get("cell") or ""
            if cell.startswith("unified:"):
                parts = cell.split(":", 1)[1].split(",")
                if len(parts) != 3:
                    continue
                col, row, lv = map(int, parts)
                if lv != 0:
                    continue
                mp_x, mp_y = canvas_to_world(col, row)
                out.append({
                    "filename": p["filename"],
                    "mp_x": mp_x, "mp_y": mp_y, "layer": "b",
                    "place_name": p.get("place_name"),
                    "updated_by": p.get("updated_by"),
                })
                continue
            if ":" in cell:
                continue  # ignore legacy four-tab prefixed rows
            if "mp_x" in p and "filename" in p:
                out.append(p)
        return out
    return []


def load_placements(arg, from_generated=False):
    if from_generated and os.path.isfile(UNIFIED):
        raw = json.load(open(UNIFIED, encoding="utf-8"))
        rows = normalize_rows({"dataset": "unified",
                               "placements": raw.get("placements") or []})
        print(f"loaded {len(rows)} Floor 0 placements from unified_map.json")
        return rows
    if arg:
        raw = json.load(open(arg, encoding="utf-8"))
        rows = normalize_rows(raw)
        print(f"loaded {len(rows)} Floor 0 placements from {arg}")
        return rows
    try:
        rows = normalize_rows(fetch_supabase())
        print(f"fetched {len(rows)} unified Floor 0 placements from Supabase")
        return rows
    except Exception as e:
        print(f"Supabase fetch failed ({e}); trying generated Floor 0")
        if os.path.isfile(UNIFIED):
            return load_placements(None, from_generated=True)
        print("building core only")
        return []


def valid_filenames():
    out = set()
    for root in (B.MAPS_DIR, B.MAPSALL_DIR,
                 os.path.join(HERE, "_render", "secs"),
                 os.path.join(HERE, "WINMRA", "MAPS")):
        if not os.path.isdir(root):
            continue
        for r, _d, fs in os.walk(root):
            for f in fs:
                if f.upper().endswith(".SEC") and not f.startswith("._"):
                    out.add(f)
    return out


def base_of(fname):
    return fname[:-4] if fname.upper().endswith(".SEC") else fname


def placement_priority(fname):
    base = base_of(fname).lower()
    if base in CELL_PRIORITY:
        return CELL_PRIORITY[base]
    # Prefer 2011-style area names over coordinate SECs when both crush
    # onto the same MP cell.
    if not any(base.upper().startswith(p) for p in B.PREFIX_TO_MPX):
        return 20
    return 0


def in_engine_band(mp_x, mp_y, xb, yb):
    return (MP_X_MIN <= mp_x <= MP_X_MAX and MP_Y_MIN <= mp_y <= MP_Y_MAX
            and XB_MIN <= xb <= XB_MAX and YB_MIN <= yb <= YB_MAX)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    from_generated = "--from-generated" in sys.argv
    allow_expand = "--allow-expand" in sys.argv
    arg = args[0] if args else None
    core = B.build()
    sectors = core["sectors"]
    b2b = core["block_to_base"]
    placements = load_placements(arg, from_generated=from_generated)
    valid = valid_filenames()
    sector_key_by_base = {base: f"{s['x_block']},{s['y_block']},{s['layer']}"
                          for base, s in sectors.items()}
    seen_files = {}
    # key -> winning placement dict (resolved after priority)
    pending = {}

    added = overridden = cleared = skipped = invalid = duplicate = name_conflict = 0
    out_of_band = crushed = 0
    for p in placements:
        try:
            mp_x, mp_y = int(p["mp_x"]), int(p["mp_y"])
            layer = (p.get("layer") or "b").lower()
            fname = p["filename"]
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if layer not in ("a", "b", "c"):
            skipped += 1
            continue
        xb, yb = xblock_of_mpx(mp_x), yblock_of_mpy(mp_y)
        key = f"{xb},{yb},{layer}"
        if fname == CLEARED:
            if key in b2b:
                old = b2b.pop(key)
                sectors.pop(old, None)
                cleared += 1
            pending.pop(key, None)
            continue
        if fname not in valid:
            invalid += 1
            continue
        if not allow_expand and not in_engine_band(mp_x, mp_y, xb, yb):
            out_of_band += 1
            continue
        if fname in seen_files:
            duplicate += 1
            continue
        base = base_of(fname)
        owner = sector_key_by_base.get(base)
        # Coordinate SECs already owned by core at another cell cannot move.
        # Area SECs (haven1, etc.) may relocate.
        is_coord = any(base.upper().startswith(px) for px in B.PREFIX_TO_MPX)
        if owner is not None and owner != key and is_coord:
            name_conflict += 1
            continue
        seen_files[fname] = key
        cand = {
            "filename": fname, "base": base, "mp_x": mp_x, "mp_y": mp_y,
            "layer": layer, "xb": xb, "yb": yb, "key": key,
            "place_name": p.get("place_name"),
            "updated_by": p.get("updated_by"),
            "prio": placement_priority(fname),
        }
        prev = pending.get(key)
        if prev is not None:
            crushed += 1
            if cand["prio"] < prev["prio"]:
                continue
            if cand["prio"] == prev["prio"]:
                # Same priority: keep later export row (editor intent).
                pass
        pending[key] = cand

    for key, cand in pending.items():
        base = cand["base"]
        fname = cand["filename"]
        mp_x, mp_y = cand["mp_x"], cand["mp_y"]
        layer, xb, yb = cand["layer"], cand["xb"], cand["yb"]
        # If this area SEC was previously at another core key, free it.
        old_key = sector_key_by_base.get(base)
        if old_key is not None and old_key != key and old_key in b2b and b2b[old_key] == base:
            b2b.pop(old_key, None)
            # leave orphan cleanup to overwrite below
        existed = key in b2b
        if existed:
            old_base = b2b[key]
            sectors.pop(old_base, None)
            sector_key_by_base.pop(old_base, None)
        sector_key_by_base[base] = key
        prefix = MPX_TO_PREFIX.get(mp_x)
        sectors[base] = {
            "filename": base + ".SEC",
            "prefix": prefix,
            "y_start": 2 + 32 * yb,
            "y_end": 2 + 32 * yb + 31,
            "layer": layer,
            "x_block": xb,
            "y_block": yb,
            "mp_x": mp_x,
            "mp_y": mp_y,
            "mp_z": B.LAYER_TO_MPZ.get(layer),
            "place_name": cand.get("place_name"),
            "status": "community-placed",
            "provenance": "unified map Floor 0 (" + (cand.get("updated_by") or "?") +
                          ") compiled onto binary-grounded core",
        }
        b2b[key] = base
        overridden += 1 if existed else 0
        added += 0 if existed else 1

    # Server Player.set_initial prefers sector BASE NAME "EWGB194225b", then
    # EWGB290321b, EWGB322353b, then any b-layer by max breathing room.
    # If EWGB194225b is missing, spawn lands in a random huge sector (castle).
    # Keep that key for spawn discovery, but load 2011 haven1.SEC bytes.
    if "haven1.SEC" in valid:
        spawn_key = "3,6,b"
        if spawn_key in b2b and b2b[spawn_key] not in ("EWGB194225b", "haven1"):
            sectors.pop(b2b[spawn_key], None)
        # Drop a competing haven1 key at the same cell if present
        if "haven1" in sectors and b2b.get(spawn_key) == "haven1":
            sectors.pop("haven1", None)
        elif "haven1" in sectors:
            # haven1 may sit elsewhere; remove only if it claims spawn cell
            h = sectors.get("haven1")
            if h and h.get("x_block") == 3 and h.get("y_block") == 6 and h.get("layer") == "b":
                sectors.pop("haven1", None)
        sectors["EWGB194225b"] = {
            "filename": "haven1.SEC",
            "prefix": "EWGB",
            "y_start": 2 + 32 * 6,
            "y_end": 2 + 32 * 6 + 31,
            "layer": "b",
            "x_block": 3,
            "y_block": 6,
            "mp_x": 60,
            "mp_y": 45,
            "mp_z": B.LAYER_TO_MPZ["b"],
            "place_name": "W Haven",
            "status": "community-placed",
            "provenance": "spawn key EWGB194225b -> haven1.SEC (2011 Haven; server set_initial requires this base name)",
        }
        b2b[spawn_key] = "EWGB194225b"
        sector_key_by_base["EWGB194225b"] = spawn_key
        sector_key_by_base.pop("haven1", None)

    max_yb = max((s["y_block"] for s in sectors.values()), default=0)
    # Keep ranges covering all placed blocks but never shrink below core needs.
    core["y_axis_ranges"] = [[2 + 32 * i, 33 + 32 * i] for i in range(max_yb + 1)]
    core["_meta"]["title"] = "MRA world map (core + unified Floor 0, compiled)"
    core["_meta"]["stats"] = {
        "sectors_placed": len(sectors),
        "block_to_base_entries": len(b2b),
        "y_axis_ranges": len(core["y_axis_ranges"]),
        "community_added": added,
        "community_overrode_core": overridden,
        "community_cleared": cleared,
        "placements_skipped": skipped,
        "placements_invalid_filename": invalid,
        "placements_duplicate_filename": duplicate,
        "placements_name_conflict": name_conflict,
        "placements_out_of_band": out_of_band,
        "placements_crushed": crushed,
        "allow_expand": allow_expand,
    }
    core.pop("holes", None)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(core, fh, indent=1)

    print(f"\nWrote {os.path.basename(OUT)}")
    print(f"  sectors total:        {len(sectors)}")
    print(f"  community added:      {added}")
    print(f"  community overrode:   {overridden}")
    print(f"  core tiles cleared:   {cleared}")
    print(f"  placements skipped:   {skipped}")
    print(f"  invalid filenames:    {invalid}")
    print(f"  duplicate filenames:  {duplicate}")
    print(f"  name conflicts:       {name_conflict}")
    print(f"  out of engine band:   {out_of_band} (editor-only / parked)")
    print(f"  crushed same-MP:      {crushed}")
    if "EWGB194225b" in sectors:
        h = sectors["EWGB194225b"]
        print(f"  spawn EWGB194225b:    MP({h['mp_x']},{h['mp_y']}) file={h['filename']} "
              f"block {h['x_block']},{h['y_block']},{h['layer']}")


if __name__ == "__main__":
    main()
