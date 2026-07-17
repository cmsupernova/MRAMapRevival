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
  python build_world_map.py unified_map_export.json
      # DEFAULT: 1 editor cell = 1 game cell (your export layout is authority;
      # 2006 filename coords are ignored; mixed haven1/sal*/IOX* OK)
  python build_world_map.py export.json --classic-grid
      # old 2006 MP band + 2 editor cells per game cell
  python build_world_map.py --from-generated
Output: world_map_built.json

Spawn: server set_initial requires base name EWGB194225b. We place that key
at wherever haven1 sits in the export, loading haven1_spawn.SEC (south-biased
intra cell).
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
# Default matches the SEC editor: one canvas cell per engine sector.
# --classic-grid switches back to WORLD_SCALE=2 (2006-dense crush).
WORLD_SCALE = 1

# Only used with --classic-grid (original WINMRA / 2006 prefix band).
MP_X_MIN, MP_X_MAX = 45, 80
MP_Y_MIN, MP_Y_MAX = 15, 80
XB_MIN, XB_MAX = 0, 7
YB_MIN, YB_MAX = 0, 13

MPX_TO_XBLOCK = {v: k for k, v in
                 zip(B.PREFIX_TO_XBLOCK.values(), B.PREFIX_TO_MPX.values())}
MPX_TO_PREFIX = {v: k for k, v in B.PREFIX_TO_MPX.items()}
LAYER_FROM_LEVEL = {0: "b", -1: "a", 1: "c"}

CELL_PRIORITY = {
    "haven1": 100, "haven2": 90, "haven3": 90, "haven5": 90, "haven9": 90,
    "sanctuary1": 80, "sanctuary2": 80, "sanctuary3": 80, "sanctuary4": 80,
}

SPAWN_SEC_NAME = "haven1_spawn.SEC"
SPAWN_TARGET_ROW = 27
SPAWN_TARGET_COL = 16
SEC_GRID, SEC_PLAY, SEC_CELL = 33, 32, 6
SEC_SIZE = SEC_GRID * SEC_GRID * SEC_CELL
SEC_IMPASS = {0x00, 0x02, 0x03, 0x06, 0x07}



def _sec_walkable(data, r, c):
    if not (0 <= r < SEC_PLAY and 0 <= c < SEC_PLAY):
        return False
    return data[(r * SEC_GRID + c) * SEC_CELL] not in SEC_IMPASS


def _sec_breathing(data, r, c):
    mins = []
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        n = 0
        rr, cc = r + dr, c + dc
        while _sec_walkable(data, rr, cc):
            n += 1
            rr += dr
            cc += dc
        mins.append(n)
    return min(mins) if mins else 0


def _sec_best_spawn(data):
    best_sc = -1
    best = []
    for r in range(SEC_PLAY):
        for c in range(SEC_PLAY):
            if not _sec_walkable(data, r, c):
                continue
            sc = _sec_breathing(data, r, c)
            if sc > best_sc:
                best_sc = sc
                best = [(r, c)]
            elif sc == best_sc:
                best.append((r, c))
    return best_sc, best


def find_haven1_bytes():
    for root in (
        os.path.join(HERE, "WINMRA", "MAPS"),
        os.path.join(HERE, "_render", "secs"),
        B.MAPSALL_DIR,
        B.MAPS_DIR,
    ):
        if not root or not os.path.isdir(root):
            continue
        path = os.path.join(root, "haven1.SEC")
        if os.path.isfile(path):
            raw = open(path, "rb").read()
            if len(raw) == SEC_SIZE:
                return raw, path
    return None, None


def write_haven_spawn_sec():
    """Write haven1_spawn.SEC biased so set_initial picks ~ (27,16)."""
    raw, src_path = find_haven1_bytes()
    if not raw:
        return None
    data = bytearray(raw)
    # Iteratively mark current winners impassable until spawn is far enough south.
    for _ in range(600):
        _sc, cells = _sec_best_spawn(data)
        if not cells:
            break
        r, c = cells[0]
        if r >= SPAWN_TARGET_ROW and abs(c - SPAWN_TARGET_COL) <= 2:
            break
        if r < SPAWN_TARGET_ROW or abs(c - SPAWN_TARGET_COL) > 2:
            data[(r * SEC_GRID + c) * SEC_CELL] = 0x02
        else:
            break
    out_dir = os.path.join(HERE, "WINMRA", "MAPS")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, SPAWN_SEC_NAME)
    open(out_path, "wb").write(data)
    sc, cells = _sec_best_spawn(data)
    print(f"wrote {SPAWN_SEC_NAME} from {os.path.basename(src_path)} "
          f"-> spawn intra {cells[0] if cells else '?'} (score {sc})")
    return out_path



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


def coords_from_filename(fname):
    """Return (mp_x, mp_y, layer) from a 2006 coordinate SEC name, else None.

    Only used with --classic-grid. Default editor-layout mode ignores filename
    coordinates and trusts the export cell positions instead.
    """
    m = B.FNAME_RE.match(fname)
    if not m:
        return None
    prefix, digits, layer = m.group(1).upper(), m.group(2), m.group(3)
    if prefix not in B.PREFIX_TO_MPX:
        return None
    if digits in B.YRANGE_TYPOS:
        digits = B.YRANGE_TYPOS[digits]
    ypair = B.split_yrange(digits)
    if not ypair:
        return None
    ystart, _yend = ypair
    mp_x = B.PREFIX_TO_MPX[prefix]
    mp_y = B.mp_y_of(ystart)
    layer = (layer or "b").lower()
    if layer not in ("a", "b", "c"):
        layer = "b"
    return mp_x, mp_y, layer


def fetch_supabase():
    url = f"{SUPABASE_URL}/rest/v1/placements?select=*&cell=like.unified:*"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def normalize_rows(raw, classic_grid=False):
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
                    # Default: editor cell is authority (haven1 / sal3 / IOX mixed).
                    # --classic-grid: 2006 coordinate names snap to filename MP.
                    native = coords_from_filename(fname) if classic_grid else None
                    if native:
                        mp_x, mp_y, layer = native
                    else:
                        mp_x = p.get("mp_x")
                        mp_y = p.get("mp_y")
                        if mp_x is None or mp_y is None:
                            mp_x, mp_y = canvas_to_world(int(p["col"]), int(p["row"]))
                        layer = LAYER_FROM_LEVEL.get(lv, "b")
                    rows.append({
                        "filename": fname,
                        "mp_x": int(mp_x), "mp_y": int(mp_y),
                        "layer": layer,
                        "place_name": p.get("place_name"),
                        "updated_by": "unified-export",
                        "editor_col": int(p["col"]),
                        "editor_row": int(p["row"]),
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


def load_placements(arg, from_generated=False, classic_grid=False):
    if from_generated and os.path.isfile(UNIFIED):
        raw = json.load(open(UNIFIED, encoding="utf-8"))
        rows = normalize_rows({"dataset": "unified",
                               "placements": raw.get("placements") or []},
                              classic_grid=classic_grid)
        print(f"loaded {len(rows)} Floor 0 placements from unified_map.json")
        return rows
    if arg:
        raw = json.load(open(arg, encoding="utf-8"))
        rows = normalize_rows(raw, classic_grid=classic_grid)
        print(f"loaded {len(rows)} Floor 0 placements from {arg}")
        return rows
    try:
        rows = normalize_rows(fetch_supabase(), classic_grid=classic_grid)
        print(f"fetched {len(rows)} unified Floor 0 placements from Supabase")
        return rows
    except Exception as e:
        print(f"Supabase fetch failed ({e}); trying generated Floor 0")
        if os.path.isfile(UNIFIED):
            return load_placements(None, from_generated=True, classic_grid=classic_grid)
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
    return 10


def in_engine_band(mp_x, mp_y, xb, yb):
    return (MP_X_MIN <= mp_x <= MP_X_MAX and MP_Y_MIN <= mp_y <= MP_Y_MAX
            and XB_MIN <= xb <= XB_MAX and YB_MIN <= yb <= YB_MAX)


def main():
    global WORLD_SCALE
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    from_generated = "--from-generated" in sys.argv
    classic_grid = "--classic-grid" in sys.argv
    allow_expand = "--allow-expand" in sys.argv or not classic_grid
    if classic_grid:
        WORLD_SCALE = 2
        print("mode: classic-grid (WORLD_SCALE=2, 2006 MP band)")
    else:
        WORLD_SCALE = 1
        print("mode: editor-layout (WORLD_SCALE=1, export cells are authority)")
    arg = args[0] if args else None
    core = B.build()
    if classic_grid:
        sectors = core["sectors"]
        b2b = core["block_to_base"]
    else:
        # Export-only outdoor map: do not keep disconnected 2006 core tiles.
        sectors = {}
        b2b = {}
        core["block_to_base"] = b2b
        core["sectors"] = sectors
    placements = load_placements(arg, from_generated=from_generated,
                                 classic_grid=classic_grid)
    valid = valid_filenames()
    sector_key_by_base = {base: f"{s['x_block']},{s['y_block']},{s['layer']}"
                          for base, s in sectors.items()}
    seen_files = {}
    pending = {}
    haven1_place = None

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
        if classic_grid and (not allow_expand) and not in_engine_band(mp_x, mp_y, xb, yb):
            out_of_band += 1
            continue
        if fname in seen_files:
            duplicate += 1
            continue
        base = base_of(fname)
        owner = sector_key_by_base.get(base)
        # In classic mode, coordinate SECs cannot move off their core cell.
        if classic_grid and owner is not None and owner != key and coords_from_filename(fname):
            name_conflict += 1
            continue
        seen_files[fname] = key
        cand = {
            "filename": fname, "base": base, "mp_x": mp_x, "mp_y": mp_y,
            "layer": layer, "xb": xb, "yb": yb, "key": key,
            "place_name": p.get("place_name"),
            "updated_by": p.get("updated_by"),
            "prio": placement_priority(fname),
            "editor_col": p.get("editor_col"),
            "editor_row": p.get("editor_row"),
        }
        if base.lower() == "haven1":
            haven1_place = cand
        prev = pending.get(key)
        if prev is not None:
            crushed += 1
            if cand["prio"] < prev["prio"]:
                continue
        pending[key] = cand

    for key, cand in pending.items():
        base = cand["base"]
        fname = cand["filename"]
        mp_x, mp_y = cand["mp_x"], cand["mp_y"]
        layer, xb, yb = cand["layer"], cand["xb"], cand["yb"]
        old_key = sector_key_by_base.get(base)
        if old_key is not None and old_key != key and old_key in b2b and b2b[old_key] == base:
            b2b.pop(old_key, None)
        existed = key in b2b
        if existed:
            old_base = b2b[key]
            sectors.pop(old_base, None)
            sector_key_by_base.pop(old_base, None)
        sector_key_by_base[base] = key
        prefix = MPX_TO_PREFIX.get(mp_x)
        sectors[base] = {
            "filename": fname if fname.upper().endswith(".SEC") else base + ".SEC",
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

    # Spawn alias: EWGB194225b at haven1's export cell, content = haven1_spawn.
    if "haven1.SEC" in valid:
        spawn_path = write_haven_spawn_sec()
        spawn_file = SPAWN_SEC_NAME if spawn_path else "haven1.SEC"
        if haven1_place:
            sx, sy = haven1_place["mp_x"], haven1_place["mp_y"]
            sxb, syb = haven1_place["xb"], haven1_place["yb"]
            slayer = haven1_place["layer"]
        else:
            sx, sy, sxb, syb, slayer = 60, 45, 3, 6, "b"
        spawn_key = f"{sxb},{syb},{slayer}"
        if spawn_key in b2b and b2b[spawn_key] not in ("EWGB194225b", "haven1"):
            sectors.pop(b2b[spawn_key], None)
        if "haven1" in sectors:
            sectors.pop("haven1", None)
            for k, v in list(b2b.items()):
                if v == "haven1":
                    b2b.pop(k, None)
        sectors["EWGB194225b"] = {
            "filename": spawn_file,
            "prefix": MPX_TO_PREFIX.get(sx) or "EWGB",
            "y_start": 2 + 32 * syb,
            "y_end": 2 + 32 * syb + 31,
            "layer": slayer,
            "x_block": sxb,
            "y_block": syb,
            "mp_x": sx,
            "mp_y": sy,
            "mp_z": B.LAYER_TO_MPZ[slayer],
            "place_name": "W Haven",
            "status": "community-placed",
            "provenance": (
                "spawn key EWGB194225b -> " + spawn_file +
                " at export haven1 cell MP(%d,%d)" % (sx, sy)
            ),
        }
        b2b[spawn_key] = "EWGB194225b"
        sector_key_by_base["EWGB194225b"] = spawn_key
        sector_key_by_base.pop("haven1", None)

    ybs = [s["y_block"] for s in sectors.values()]
    max_yb = max(ybs) if ybs else 0
    min_yb = min(ybs) if ybs else 0
    # y_axis_ranges is indexed by y_block; pad from 0..max even if min>0.
    core["y_axis_ranges"] = [[2 + 32 * i, 33 + 32 * i] for i in range(max(max_yb, 0) + 1)]
    if min_yb < 0:
        print(f"WARNING: negative y_block={min_yb}; server may not index it")
    core["_meta"]["title"] = (
        "MRA world map (editor-layout 1:1)" if not classic_grid
        else "MRA world map (classic-grid + unified Floor 0)"
    )
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
        "world_scale": WORLD_SCALE,
        "classic_grid": classic_grid,
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
    print(f"  out of engine band:   {out_of_band}")
    print(f"  crushed same-MP:      {crushed}")
    if "EWGB194225b" in sectors:
        h = sectors["EWGB194225b"]
        print(f"  spawn EWGB194225b:    MP({h['mp_x']},{h['mp_y']}) file={h['filename']} "
              f"block {h['x_block']},{h['y_block']},{h['layer']}")


if __name__ == "__main__":
    main()
