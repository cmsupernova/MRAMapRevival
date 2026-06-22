"""Compile community interior layouts -> a server-ready cluster index.

Companion to build_world_map.py, but for interiors. The interior/cluster editor
(sec_cluster.html) lets the community arrange a region's non-coordinate SECs
(e.g. the 13 ORC sectors) on a local lx,ly grid per floor and syncs them to the
`cluster_cells` Supabase table. Those SECs are NOT on the world coordinate grid,
so stitching is purely local adjacency.

This folds the cells into:
  - per-cluster placements + derived walkable edge links, and
  - a flat `sector_links` index keyed by SEC filename: for each interior sector,
    which sector lies n / s / e / w, plus inferred up / down (a cell directly
    above/below on an adjacent floor at the same lx,ly).

Sources (first that yields rows wins):
  1. JSON file/dir argument(s): cluster_*.json exports from the editor, OR a raw
     Supabase row dump.
  2. live Supabase REST (the baked community project), if reachable.

Run:
  python build_clusters.py                       # pull from Supabase
  python build_clusters.py cluster_orc.json ...  # use exported file(s)
  python build_clusters.py _render/clusters/     # a folder of exports
Output: clusters_built.json
"""
import glob
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "clusters_built.json")

SUPABASE_URL = "https://msnxqnqqpdwamzfbwskm.supabase.co"
SUPABASE_KEY = "sb_publishable_MjRmbztlv0wlOQXpTvoBlQ__BJobsxC"

# edge direction -> (dlx, dly).  down(south) increases ly.
DIRS = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}
FLOOR_ORDER = {"a": 0, "b": 1, "c": 2}   # under < ground < upper


def fetch_supabase():
    url = f"{SUPABASE_URL}/rest/v1/cluster_cells?select=*"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def cells_from_export(obj):
    """Normalize an editor export ({cluster, placements:[...]}) to flat cells."""
    out = []
    clu = obj.get("cluster")
    for p in obj.get("placements", []):
        out.append({
            "cluster": clu,
            "lx": int(p["lx"]), "ly": int(p["ly"]),
            "layer": (p.get("layer") or "b").lower(),
            "filename": p["filename"],
        })
    return out


def load_cells(args):
    paths = []
    for a in args:
        if os.path.isdir(a):
            paths += sorted(glob.glob(os.path.join(a, "*.json")))
        elif a:
            paths.append(a)
    if paths:
        cells = []
        for path in paths:
            raw = json.load(open(path))
            if isinstance(raw, dict) and "placements" in raw:
                cells += cells_from_export(raw)
            elif isinstance(raw, list):                  # raw supabase dump
                cells += raw
            elif isinstance(raw, dict) and "cluster_cells" in raw:
                cells += raw["cluster_cells"]
            print(f"loaded {path}")
        print(f"loaded {len(cells)} cells from {len(paths)} file(s)")
        return cells
    try:
        cells = fetch_supabase()
        print(f"fetched {len(cells)} cells from Supabase")
        return cells
    except Exception as e:
        print(f"Supabase fetch failed ({e}); nothing to compile")
        return []


def base(fn):
    return fn[:-4] if fn.upper().endswith(".SEC") else fn


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    cells = load_cells(args)

    # index: clusters[name][(lx,ly,layer)] = filename
    clusters = {}
    for c in cells:
        try:
            clu = c["cluster"]
            k = (int(c["lx"]), int(c["ly"]), (c.get("layer") or "b").lower())
            clusters.setdefault(clu, {})[k] = c["filename"]
        except (KeyError, TypeError, ValueError):
            continue

    out = {"clusters": {}, "sector_links": {}, "_meta": {
        "title": "MRA interior cluster stitching (community-defined)",
        "note": "Interiors are not on the world grid; links are local adjacency. "
                "dir is the edge of `from` that leads into `to`. up/down are "
                "inferred from a sector directly above/below at the same lx,ly.",
    }}

    dup_filenames = []
    for clu, grid in sorted(clusters.items()):
        placements, links = [], []
        for (lx, ly, lay), fn in sorted(grid.items()):
            placements.append({"filename": fn, "lx": lx, "ly": ly, "layer": lay})
            nb = {}
            for d, (dx, dy) in DIRS.items():
                t = grid.get((lx + dx, ly + dy, lay))
                if t:
                    links.append({"from": fn, "to": t, "dir": d, "layer": lay})
                    nb[d] = base(t)
            # inferred vertical links: same lx,ly on adjacent floor
            up = grid.get((lx, ly, {"a": "b", "b": "c"}.get(lay)))
            dn = grid.get((lx, ly, {"c": "b", "b": "a"}.get(lay)))
            if up:
                nb["up"] = base(up)
                links.append({"from": fn, "to": up, "dir": "up", "layer": lay})
            if dn:
                nb["down"] = base(dn)
                links.append({"from": fn, "to": dn, "dir": "down", "layer": lay})

            bkey = base(fn)
            if bkey in out["sector_links"]:
                dup_filenames.append(bkey)
            out["sector_links"][bkey] = {"cluster": clu, "layer": lay,
                                         "lx": lx, "ly": ly, **nb}

        out["clusters"][clu] = {
            "placements": placements,
            "links": links,
            "floors": sorted({p["layer"] for p in placements},
                             key=lambda l: FLOOR_ORDER.get(l, 1)),
            "sector_count": len(placements),
        }

    out["_meta"]["stats"] = {
        "clusters": len(out["clusters"]),
        "sectors": sum(c["sector_count"] for c in out["clusters"].values()),
        "links": sum(len(c["links"]) for c in out["clusters"].values()),
        "duplicate_filenames": sorted(set(dup_filenames)),
    }

    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1)

    print(f"\nWrote {os.path.basename(OUT)}")
    for clu, c in sorted(out["clusters"].items()):
        print(f"  {clu:<14} {c['sector_count']:>3} sectors  "
              f"{len(c['links']):>3} links  floors={','.join(c['floors'])}")
    if dup_filenames:
        print(f"  NOTE: {len(set(dup_filenames))} filename(s) appear in >1 cell; "
              "last wins in sector_links:", sorted(set(dup_filenames))[:8])


if __name__ == "__main__":
    main()
