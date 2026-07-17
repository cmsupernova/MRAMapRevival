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

# Server set_initial picks the cell with max "breathing room" inside the
# preferred sector. Haven's natural winner is ~intra (14,16) (courtyard).
# Bias a game-only SEC copy so spawn lands ~13 tiles south of that.
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
    """Return (mp_x, mp_y, layer) from a coordinate SEC name, else None.

    Editor canvas is 2x denser than the engine grid, so canvas_to_world()
    often merges neighboring editor cells. Coordinate SECs must sit at their
    filename-derived MP or they vanish under area SECs (sal3 over IOX, etc.).
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
    # Unlayered coordinate files in Floor-0 exports play as outdoor 'b'.
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
                    native = coords_from_filename(fname)
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


def placement_priority(fname, mp_x=None, mp_y=None, layer=None):
    base = base_of(fname).lower()
    if base in CELL_PRIORITY:
        return CELL_PRIORITY[base]
    native = coords_from_filename(fname)
    if native:
        nmp_x, nmp_y, nlayer = native
        # Coordinate SECs at their true MP beat area SECs that crushed onto them.
        if (mp_x is None or int(mp_x) == nmp_x) and (mp_y is None or int(mp_y) == nmp_y):
            if layer is None or layer == nlayer:
                return 150
        return 5
    # Area / 2011 names
    return 20


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
        native = coords_from_filename(fname)
        is_coord = native is not None
        # Coordinate SECs already owned by core at another cell cannot move.
        # Area SECs (haven1, etc.) may relocate.
        if owner is not None and owner != key and is_coord:
            name_conflict += 1
            continue
        seen_files[fname] = key
        cand = {
            "filename": fname, "base": base, "mp_x": mp_x, "mp_y": mp_y,
            "layer": layer, "xb": xb, "yb": yb, "key": key,
            "place_name": p.get("place_name"),
            "updated_by": p.get("updated_by"),
            "prio": placement_priority(fname, mp_x, mp_y, layer),
        }
        prev = pending.get(key)
        if prev is not None:
            crushed += 1
            if cand["prio"] < prev["prio"]:
                continue
            if cand["prio"] == prev["prio"]:
                # Same priority: prefer coordinate SEC, else later export row.
                if prev.get("prio") == cand["prio"] and coords_from_filename(prev["filename"]):
                    continue
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
    # Keep that key for spawn discovery, but load a Haven SEC biased ~13 cells
    # south of the natural courtyard spawn (intra 14,16 -> ~27,16).
    spawn_file = None
    if "haven1.SEC" in valid:
        spawn_path = write_haven_spawn_sec()
        if spawn_path and os.path.isfile(spawn_path):
            spawn_file = SPAWN_SEC_NAME
            valid.add(SPAWN_SEC_NAME)
        else:
            spawn_file = "haven1.SEC"
        spawn_key = "3,6,b"
        if spawn_key in b2b and b2b[spawn_key] not in ("EWGB194225b", "haven1"):
            sectors.pop(b2b[spawn_key], None)
        if "haven1" in sectors and b2b.get(spawn_key) == "haven1":
            sectors.pop("haven1", None)
        elif "haven1" in sectors:
            h = sectors.get("haven1")
            if h and h.get("x_block") == 3 and h.get("y_block") == 6 and h.get("layer") == "b":
                sectors.pop("haven1", None)
        sectors["EWGB194225b"] = {
            "filename": spawn_file,
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
            "provenance": (
                "spawn key EWGB194225b -> " + spawn_file +
                " (2011 Haven; intra biased south for set_initial breathing-room)"
            ),
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
