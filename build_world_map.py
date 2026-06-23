"""Compile community placements -> a server-ready world_map.json.

Closes the loop: the world map builder (sec_map.html) lets the community place
MAPSALL sectors and blank wrong core tiles, syncing to Supabase. This folds
those placements onto the binary-grounded core (build_world_coords) and emits
the engine schema mra_stub.py consumes (sectors / block_to_base / y_axis_ranges).

Placement sources (first that yields rows wins):
  1. a JSON file argument - the tool's Export ("area_placements") OR a raw
     Supabase row dump.
  2. live Supabase REST (the baked community project), if reachable.

A placement whose filename is the blank sentinel "__cleared__" REMOVES the core
tile at that cell (so the community can delete wrong auto-placed sectors).

Run:
  python build_world_map.py                      # pull from Supabase
  python build_world_map.py area_placements.json # use an exported file
Output: world_map_built.json
"""
import json
import os
import sys
import urllib.request

import build_world_coords as B

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "world_map_built.json")
CLEARED = "__cleared__"

SUPABASE_URL = "https://msnxqnqqpdwamzfbwskm.supabase.co"
SUPABASE_KEY = "sb_publishable_MjRmbztlv0wlOQXpTvoBlQ__BJobsxC"

MPX_TO_XBLOCK = {v: k for k, v in
                 zip(B.PREFIX_TO_XBLOCK.values(), B.PREFIX_TO_MPX.values())}
# mp_x -> prefix, for labeling synthetic sector records
MPX_TO_PREFIX = {v: k for k, v in B.PREFIX_TO_MPX.items()}


def xblock_of_mpx(mp_x):
    # mp_x steps by 5 from 45 (BECJ=0). Falls back to direct arithmetic so
    # placements just outside the named band still resolve.
    if mp_x in MPX_TO_XBLOCK:
        return MPX_TO_XBLOCK[mp_x]
    return (mp_x - 45) // 5


def yblock_of_mpy(mp_y):
    return (mp_y - 15) // 5


def fetch_supabase():
    url = f"{SUPABASE_URL}/rest/v1/placements?select=*"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def load_placements(arg):
    if arg:
        raw = json.load(open(arg))
        rows = raw.get("area_placements", raw) if isinstance(raw, dict) else raw
        print(f"loaded {len(rows)} placements from {arg}")
        return rows
    try:
        rows = fetch_supabase()
        print(f"fetched {len(rows)} placements from Supabase")
        return rows
    except Exception as e:  # offline / no rows / RLS - keep going with core only
        print(f"Supabase fetch failed ({e}); building core only")
        return []


def valid_filenames():
    out = set()
    for root in (B.MAPS_DIR, B.MAPSALL_DIR):
        for r, _d, fs in os.walk(root):
            for f in fs:
                if f.upper().endswith(".SEC") and not f.startswith("._"):
                    out.add(f)
    return out


def main():
    arg = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
    core = B.build()                       # binary-grounded core (also writes coords json)
    sectors = core["sectors"]
    b2b = core["block_to_base"]
    placements = load_placements(arg)
    valid = valid_filenames()
    sector_key_by_base = {base: f"{s['x_block']},{s['y_block']},{s['layer']}"
                          for base, s in sectors.items()}
    seen_files = {}

    added = overridden = cleared = skipped = invalid = duplicate = name_conflict = 0
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
            continue
        if fname not in valid:
            invalid += 1
            continue
        if fname in seen_files:
            duplicate += 1
            continue
        seen_files[fname] = key
        base = fname[:-4] if fname.upper().endswith(".SEC") else fname
        owner = sector_key_by_base.get(base)
        if owner is not None and owner != key:
            # Same sector name at two addresses would overwrite sectors[base].
            name_conflict += 1
            continue
        existed = key in b2b
        # drop any prior occupant of this block so addressing stays 1:1
        if existed:
            sectors.pop(b2b[key], None)
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
            "place_name": p.get("place_name"),
            "status": "community-placed",
            "provenance": "community placement (" + (p.get("updated_by") or "?") +
                          ") compiled onto binary-grounded core",
        }
        b2b[key] = base
        overridden += existed and 1 or 0
        added += (not existed) and 1 or 0

    # widen y_axis_ranges if community placed further south than the core
    max_yb = max((s["y_block"] for s in sectors.values()), default=0)
    core["y_axis_ranges"] = [[2 + 32 * i, 33 + 32 * i] for i in range(max_yb + 1)]

    core["_meta"]["title"] = "MRA world map (core + community placements, compiled)"
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
    }
    core.pop("holes", None)                # holes report is core-only; drop here

    with open(OUT, "w") as fh:
        json.dump(core, fh, indent=1)

    # consistency check (block_to_base <-> sectors)
    errs = [f"{k}->{base} missing sector" for k, base in b2b.items() if base not in sectors]
    errs += [f"{base} has no block entry" for base, s in sectors.items()
             if f"{s['x_block']},{s['y_block']},{s['layer']}" not in b2b]

    print(f"\nWrote {os.path.basename(OUT)}")
    print(f"  sectors total:        {len(sectors)}")
    print(f"  community added:      {added}")
    print(f"  community overrode:   {overridden}")
    print(f"  core tiles cleared:   {cleared}")
    print(f"  placements skipped:   {skipped}")
    print(f"  invalid filenames:    {invalid}")
    print(f"  duplicate filenames:  {duplicate}")
    print(f"  name conflicts:       {name_conflict}")
    print(f"  consistency errors:   {len(errs)}")
    for e in errs[:10]:
        print("    ", e)


if __name__ == "__main__":
    main()
