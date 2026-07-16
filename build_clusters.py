"""Compile community interior layouts -> a server-ready cluster index.

Companion to build_world_map.py, but for interiors. The interior/cluster editor
(sec_cluster.html) lets the community arrange a region's non-coordinate SECs
on a local lx,ly grid per floor and syncs them to the `cluster_cells` Supabase
table. Those SECs are NOT on the world coordinate grid, so stitching is purely
local adjacency.

This folds the cells into:
  - per-cluster placements + derived walkable edge links, and
  - a flat `sector_links` index keyed by SEC filename: for each interior sector,
    which sector lies n / s / e / w, plus up / down from verified stair
    constraints (preferred) or same-cell floor stacking (legacy fallback).

Level model:
  - Preferred: integer `level` (0 = lowest / bottom, higher = above).
  - Legacy: letters a/b/c map to 0/1/2 (under / ground / upper).
  - `surface_level` marks which floor belongs on the Flat world canvas;
    every other floor is an interior.

Sources (first that yields rows wins):
  1. JSON file/dir argument(s): cluster_*.json exports from the editor, OR a raw
     Supabase row dump, OR level_clusters.json from assemble_levels.py.
  2. live Supabase REST (the baked community project), if reachable.
  3. `_render/level_clusters.json` auto multi-floor stacks (seed).

Run:
  python build_clusters.py                       # pull from Supabase / levels
  python build_clusters.py cluster_orc.json ...  # use exported file(s)
  python build_clusters.py _render/clusters/     # a folder of exports
Output: clusters_built.json
"""
import glob
import json
import os
import sys
import urllib.request

import build_world_coords as B

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "clusters_built.json")
LEVEL_CLUSTERS = os.path.join(HERE, "_render", "level_clusters.json")
UNIFIED_MAP = os.path.join(HERE, "_render", "unified_map.json")

SUPABASE_URL = "https://msnxqnqqpdwamzfbwskm.supabase.co"
SUPABASE_KEY = "sb_publishable_MjRmbztlv0wlOQXpTvoBlQ__BJobsxC"

# edge direction -> (dlx, dly).  down(south) increases ly.
DIRS = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}
# legacy letter -> integer level (higher = above)
FLOOR_ORDER = {"a": 0, "b": 1, "c": 2}
FLOOR_LETTER = {0: "a", 1: "b", 2: "c"}


def fetch_supabase():
    url = f"{SUPABASE_URL}/rest/v1/cluster_cells?select=*"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def normalize_level(raw, default=1):
    """Accept int level or legacy a/b/c. Higher int = higher floor."""
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return default
    if isinstance(raw, int):
        return raw
    s = str(raw).strip().lower()
    if s in FLOOR_ORDER:
        return FLOOR_ORDER[s]
    try:
        return int(s)
    except ValueError:
        return default


def level_letter(level):
    """Legacy a/b/c when level is 0/1/2; otherwise the decimal string."""
    return FLOOR_LETTER.get(level, str(level))


def cells_from_unified(path):
    """Non-surface floors from the authoritative unified map become interiors.

    Surface (Floor 0) pieces that belong to a multi-floor cluster are also
    included and flagged surface=True so stair up/down links can resolve.
    Lone Floor 0 world pieces stay in build_world_map.py only.
    """
    if not os.path.isfile(path):
        return [], []
    data = json.load(open(path, encoding="utf-8"))
    surf = int(data.get("surface_level", 0))
    # regions that have any non-surface placement
    multi_regions = set()
    for p in data.get("placements") or []:
        if int(p.get("level", 0)) != surf:
            multi_regions.add(p.get("region") or p.get("cluster_id") or "world")
    cells = []
    for p in data.get("placements") or []:
        lv = int(p.get("level", 0))
        region = p.get("region") or "world"
        if lv == surf:
            # only keep surface tiles that belong to a multi-floor region/stack
            if not p.get("cluster_id") and region not in multi_regions:
                continue
            if region == "world" and not p.get("cluster_id"):
                continue
        cells.append({
            "cluster": region if region != "world" or not p.get("cluster_id")
                       else (p.get("cluster_id") or region).split("#")[0],
            "lx": int(p["col"]), "ly": int(p["row"]),
            "level": lv,
            "layer": level_letter(lv),
            "filename": p["filename"],
            "surface_level": surf,
        })
    # Prefer region name from cluster_id when region missing
    fixed = []
    for c in cells:
        if c["cluster"] == "world":
            # try filename stem region
            pass
        fixed.append(c)
    stair_edges = []
    if os.path.isfile(LEVEL_CLUSTERS):
        _, edges = cells_from_level_clusters(LEVEL_CLUSTERS, include_suggest=False)
        stair_edges = [e for e in edges if e.get("confidence") == "auto"]
    return fixed, stair_edges


def cells_from_export(obj):
    """Normalize an editor export ({cluster, placements:[...]}) to flat cells."""
    # Unified map export: dataset=unified with col/row/level
    if obj.get("dataset") == "unified" or (
            "placements" in obj and obj.get("grid") and "cluster" not in obj):
        surf = int(obj.get("surface_level", 0))
        out = []
        for p in obj.get("placements") or []:
            lv = int(p.get("level", 0))
            if lv == surf:
                continue
            region = p.get("region") or "world"
            out.append({
                "cluster": region,
                "lx": int(p.get("col", p.get("lx", 0))),
                "ly": int(p.get("row", p.get("ly", 0))),
                "level": lv,
                "layer": level_letter(lv),
                "filename": p["filename"],
                "surface_level": surf,
            })
        return out
    out = []
    clu = obj.get("cluster")
    surface = obj.get("surface_level")
    if surface is None and obj.get("surface_layer") is not None:
        surface = normalize_level(obj.get("surface_layer"), 1)
    for p in obj.get("placements", []):
        if "level" in p and p["level"] is not None:
            lv = normalize_level(p["level"], 1)
        else:
            lv = normalize_level(p.get("layer") or "b", 1)
        # prefer col/row from unified-style rows
        lx = p.get("lx", p.get("col"))
        ly = p.get("ly", p.get("row"))
        out.append({
            "cluster": clu,
            "lx": int(lx), "ly": int(ly),
            "level": lv,
            "layer": level_letter(lv),
            "filename": p["filename"],
            "surface_level": surface,
        })
    return out


def cells_from_level_clusters(path, include_suggest=False):
    """Seed placements from assemble_levels.py auto (and optional suggest) stacks."""
    if not os.path.isfile(path):
        return [], []
    data = json.load(open(path, encoding="utf-8"))
    cells = []
    stair_edges = []  # (up_file, down_file, confidence)
    stacks = list(data.get("clusters") or [])
    if include_suggest:
        stacks += list(data.get("proposed_stacks") or [])
    for cl in stacks:
        if cl.get("confidence") not in ("auto", "suggest"):
            continue
        if len(cl.get("floors") or []) < 2:
            continue
        if cl.get("confidence") == "suggest" and not include_suggest:
            continue
        name = cl.get("region") or cl.get("id") or "level"
        surf = int(cl.get("surface_level", 0))
        for fl in cl["floors"]:
            lv = int(fl["level"])
            for p in fl.get("pieces") or []:
                cells.append({
                    "cluster": name,
                    "lx": int(p["dx"]), "ly": int(p["dy"]),
                    "level": lv,
                    "layer": level_letter(lv),
                    "filename": p["filename"],
                    "surface_level": surf,
                })
        for j in cl.get("joins") or []:
            for e in j.get("evidence") or []:
                stair_edges.append({
                    "up_file": e["up_file"], "down_file": e["down_file"],
                    "confidence": j.get("confidence", cl.get("confidence")),
                    "cluster": name,
                })
    # also harvest standalone suggested/review joins as stair evidence only
    for key in ("suggested_joins", "review_joins"):
        for j in data.get(key) or []:
            for e in j.get("evidence") or []:
                stair_edges.append({
                    "up_file": e["up_file"], "down_file": e["down_file"],
                    "confidence": j.get("confidence", key),
                    "cluster": None,
                })
    return cells, stair_edges


def load_stair_edges(path):
    """Load UP->DOWN filename pairs from level_clusters (auto joins only for links)."""
    cells, edges = cells_from_level_clusters(path, include_suggest=False)
    # Prefer auto-cluster join evidence; also keep suggest as soft (tagged)
    auto = [e for e in edges if e.get("confidence") == "auto"]
    return auto, edges


def load_cells(args):
    paths = []
    for a in args:
        if os.path.isdir(a):
            paths += sorted(glob.glob(os.path.join(a, "*.json")))
        elif a:
            paths.append(a)
    stair_edges = []
    if paths:
        cells = []
        for path in paths:
            raw = json.load(open(path, encoding="utf-8"))
            if isinstance(raw, dict) and "placements" in raw:
                # Prefer dedicated unified loader when this is the generated map
                if (path.endswith("unified_map.json")
                        or raw.get("dataset") == "unified"
                        or (raw.get("review") is not None and raw.get("grid"))):
                    c2, e2 = cells_from_unified(path if path.endswith("unified_map.json")
                                                else UNIFIED_MAP)
                    if path.endswith("unified_map.json") or raw.get("review") is not None:
                        # If export file (not generated), rebuild cells from export body
                        if raw.get("dataset") == "unified" and not path.endswith("unified_map.json"):
                            cells += cells_from_export(raw)
                        else:
                            cells += c2
                        for e in e2:
                            if (e["up_file"], e["down_file"]) not in {
                                    (x["up_file"], x["down_file"]) for x in stair_edges}:
                                stair_edges.append(e)
                    else:
                        cells += cells_from_export(raw)
                else:
                    cells += cells_from_export(raw)
                if os.path.isfile(LEVEL_CLUSTERS):
                    auto, _all = load_stair_edges(LEVEL_CLUSTERS)
                    for e in auto:
                        if (e["up_file"], e["down_file"]) not in {
                                (x["up_file"], x["down_file"]) for x in stair_edges}:
                            stair_edges.append(e)
            elif isinstance(raw, dict) and "clusters" in raw and (
                    "proposed_stacks" in raw or "suggested_joins" in raw
                    or any(isinstance(c, dict) and "floors" in c
                           for c in (raw.get("clusters") or []))):
                c2, e2 = cells_from_level_clusters(path, include_suggest=False)
                cells += c2
                stair_edges += e2
                print(f"loaded level clusters {path}")
            elif isinstance(raw, list):
                cells += raw
            elif isinstance(raw, dict) and "cluster_cells" in raw:
                cells += raw["cluster_cells"]
            print(f"loaded {path}")
        print(f"loaded {len(cells)} cells from {len(paths)} file(s)")
        return cells, stair_edges
    try:
        cells = fetch_supabase()
        print(f"fetched {len(cells)} cells from Supabase")
        auto, all_e = load_stair_edges(LEVEL_CLUSTERS)
        return cells, auto
    except Exception as e:
        print(f"Supabase fetch failed ({e}); trying unified / level seeds")
        c3, e3 = cells_from_unified(UNIFIED_MAP)
        if c3:
            print(f"seeded {len(c3)} interior cells from unified_map.json")
            return c3, e3
        c2, e2 = cells_from_level_clusters(LEVEL_CLUSTERS, include_suggest=False)
        if c2:
            print(f"seeded {len(c2)} cells from {os.path.basename(LEVEL_CLUSTERS)}")
        return c2, [x for x in e2 if x.get("confidence") == "auto"]


def valid_filenames():
    out = set()
    for root in (B.MAPS_DIR, B.MAPSALL_DIR):
        for p in glob.glob(os.path.join(root, "**", "*.SEC"), recursive=True):
            f = os.path.basename(p)
            if not f.startswith("._"):
                out.add(f)
    return out


def base(fn):
    return fn[:-4] if fn.upper().endswith(".SEC") else fn


def normalize_cell_row(c):
    """Return (cluster, lx, ly, level, filename, surface_level|None) or None."""
    try:
        clu = c["cluster"]
        fn = c["filename"]
        lx, ly = int(c["lx"]), int(c["ly"])
    except (KeyError, TypeError, ValueError):
        return None
    if "level" in c and c["level"] is not None:
        lv = normalize_level(c["level"], 1)
    else:
        lv = normalize_level(c.get("layer") or "b", 1)
    surf = c.get("surface_level")
    if surf is not None:
        surf = normalize_level(surf, lv)
    return clu, lx, ly, lv, fn, surf


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    include_suggest = "--suggest" in sys.argv
    cells, stair_edges = load_cells(args)
    if include_suggest and not args:
        # re-seed with suggest stacks when explicitly requested
        c2, e2 = cells_from_level_clusters(LEVEL_CLUSTERS, include_suggest=True)
        if not cells:
            cells = c2
        stair_edges = e2

    # If editor cells exist but no stair edges yet, still load auto evidence
    if os.path.isfile(LEVEL_CLUSTERS):
        auto, all_e = load_stair_edges(LEVEL_CLUSTERS)
        have = {(e["up_file"], e["down_file"]) for e in stair_edges}
        for e in auto:
            if (e["up_file"], e["down_file"]) not in have:
                stair_edges.append(e)

    valid = valid_filenames()

    # index: clusters[name][(lx,ly,level)] = filename
    clusters = {}
    surface_of = {}  # cluster -> surface_level
    invalid = duplicate = skipped = 0
    seen_files = {}
    for c in cells:
        row = normalize_cell_row(c)
        if not row:
            skipped += 1
            continue
        clu, lx, ly, lv, fn, surf = row
        k = (lx, ly, lv)
        if fn not in valid:
            invalid += 1
            continue
        if fn in seen_files:
            duplicate += 1
            continue
        seen_files[fn] = (clu, k)
        clusters.setdefault(clu, {})[k] = fn
        if surf is not None:
            surface_of[clu] = surf

    # default surface = minimum level present in each cluster
    for clu, grid in clusters.items():
        if clu not in surface_of and grid:
            surface_of[clu] = min(lv for (_x, _y, lv) in grid)

    # stair map: up_file -> [down_file,...] and reverse (verified only: auto)
    up_to_down = {}
    down_to_up = {}
    for e in stair_edges:
        # only auto evidence becomes hard links; suggest/review stay out of compile
        if e.get("confidence") != "auto":
            continue
        u, d = e["up_file"], e["down_file"]
        up_to_down.setdefault(u, [])
        if d not in up_to_down[u]:
            up_to_down[u].append(d)
        down_to_up.setdefault(d, [])
        if u not in down_to_up[d]:
            down_to_up[d].append(u)

    out = {"clusters": {}, "sector_links": {}, "_meta": {
        "title": "MRA interior cluster stitching (community-defined)",
        "note": "Interiors are not on the world grid; links are local adjacency. "
                "dir is the edge of `from` that leads into `to`. up/down prefer "
                "verified stair constraints from level_clusters.json; same "
                "lx,ly on adjacent integer levels is the legacy fallback. "
                "Only surface_level belongs on the Flat canvas; other floors "
                "are interiors.",
    }}

    dup_filenames = []
    stair_link_count = 0
    legacy_vert_count = 0

    for clu, grid in sorted(clusters.items()):
        placements, links = [], []
        files_in = set(grid.values())
        surf_lv = surface_of.get(clu, 0)
        for (lx, ly, lv), fn in sorted(grid.items()):
            placements.append({
                "filename": fn, "lx": lx, "ly": ly,
                "level": lv, "layer": level_letter(lv),
                "surface": lv == surf_lv,
            })
            nb = {}
            for d, (dx, dy) in DIRS.items():
                t = grid.get((lx + dx, ly + dy, lv))
                if t:
                    links.append({"from": fn, "to": t, "dir": d, "level": lv})
                    nb[d] = base(t)

            # Prefer stair-evidence vertical links (may connect different lx,ly)
            stair_up = [t for t in up_to_down.get(fn, []) if t in files_in]
            stair_dn = [t for t in down_to_up.get(fn, []) if t in files_in]
            if stair_up:
                # UP terrain on fn leads to the DOWN-bearing destination
                dest = stair_up[0]
                nb["up"] = base(dest)
                links.append({"from": fn, "to": dest, "dir": "up",
                              "level": lv, "via": "stair"})
                stair_link_count += 1
            if stair_dn:
                dest = stair_dn[0]
                nb["down"] = base(dest)
                links.append({"from": fn, "to": dest, "dir": "down",
                              "level": lv, "via": "stair"})
                stair_link_count += 1

            # Legacy fallback: same lx,ly on adjacent integer level
            if "up" not in nb:
                up = grid.get((lx, ly, lv + 1))
                if up:
                    nb["up"] = base(up)
                    links.append({"from": fn, "to": up, "dir": "up",
                                  "level": lv, "via": "colocate"})
                    legacy_vert_count += 1
            if "down" not in nb:
                dn = grid.get((lx, ly, lv - 1))
                if dn:
                    nb["down"] = base(dn)
                    links.append({"from": fn, "to": dn, "dir": "down",
                                  "level": lv, "via": "colocate"})
                    legacy_vert_count += 1

            bkey = base(fn)
            if bkey in out["sector_links"]:
                dup_filenames.append(bkey)
            out["sector_links"][bkey] = {
                "cluster": clu, "level": lv, "layer": level_letter(lv),
                "lx": lx, "ly": ly, "surface": lv == surf_lv, **nb,
            }

        interiors = [p["filename"] for p in placements if not p["surface"]]
        levels = sorted({p["level"] for p in placements})
        out["clusters"][clu] = {
            "placements": placements,
            "links": links,
            "levels": levels,
            "floors": [level_letter(lv) for lv in levels],  # legacy alias
            "surface_level": surf_lv,
            "interiors": interiors,
            "sector_count": len(placements),
        }

    out["_meta"]["stats"] = {
        "clusters": len(out["clusters"]),
        "sectors": sum(c["sector_count"] for c in out["clusters"].values()),
        "links": sum(len(c["links"]) for c in out["clusters"].values()),
        "stair_vertical_links": stair_link_count,
        "legacy_vertical_links": legacy_vert_count,
        "duplicate_filenames": sorted(set(dup_filenames)),
        "cells_skipped": skipped,
        "invalid_filenames": invalid,
        "duplicate_cells_by_filename": duplicate,
    }

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)

    print(f"\nWrote {os.path.basename(OUT)}")
    for clu, c in sorted(out["clusters"].items()):
        print(f"  {clu:<14} {c['sector_count']:>3} sectors  "
              f"{len(c['links']):>3} links  levels={c['levels']}  "
              f"surface={c['surface_level']} interiors={len(c['interiors'])}")
    if dup_filenames:
        print(f"  NOTE: {len(set(dup_filenames))} filename(s) appear in >1 cell; "
              "last wins in sector_links:", sorted(set(dup_filenames))[:8])
    print(f"  stair vertical links: {stair_link_count}")
    print(f"  legacy vertical links:{legacy_vert_count}")
    print(f"  skipped rows:       {skipped}")
    print(f"  invalid filenames:  {invalid}")
    print(f"  duplicate filenames:{duplicate}")


if __name__ == "__main__":
    main()
