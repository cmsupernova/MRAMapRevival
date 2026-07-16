"""Compile one authoritative multi-floor world map.

Consumes:
  world_map_coords.json     - 2006 coordinate placements + place names
  _render/era_map.js        - confident 2006 -> 2011 substitutions
  _render/equiv.js          - strict 2011 <-> 2006 content duplicates
  _render/blocks.json       - assembled 2011 region blocks
  _render/block_anchors.js  - flat-canvas anchors for blocks
  _render/level_clusters.json - vertical stacks / stair joins
  _render/manifest.json     - tile catalog (png paths)
  world_layout_authoritative.json - guide names

Rules:
  - Prefer one 2011 SEC when it owns the strongest accepted era/equiv match.
  - Otherwise keep the 2006 SEC (including landmarks like Last Chance Pub).
  - Place complete 2011 blocks at anchors with spacing; never duplicate a SEC.
  - Floors are integers relative to Floor 0 (surface). Below = negative.
  - Auto stair stacks are placed; suggest/review stay in review queues.

Outputs:
  _render/unified_map.json
  _render/unified_map.js  -> window.UNIFIED_MAP

Usage: python build_unified_map.py
"""
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, "_render")
COORDS = os.path.join(HERE, "world_map_coords.json")
LAYOUT = os.path.join(HERE, "world_layout_authoritative.json")
BLOCKS = os.path.join(RENDER, "blocks.json")
LEVELS = os.path.join(RENDER, "level_clusters.json")
MANIFEST = os.path.join(RENDER, "manifest.json")
ERA_JS = os.path.join(RENDER, "era_map.js")
EQUIV_JS = os.path.join(RENDER, "equiv.js")
ANCHORS_JS = os.path.join(RENDER, "block_anchors.js")
OUT_JSON = os.path.join(RENDER, "unified_map.json")
OUT_JS = os.path.join(RENDER, "unified_map.js")

# Must match sec_map.html canvas geometry
CANVAS_W = CANVAS_H = 56
WORLD_OFF = 6
WORLD_SCALE = 2
GAP = 1  # empty cells between adjacent non-overlapping assemblies

# 2006 layer letter -> floor relative to ground (b)
LAYER_FLOOR = {"a": -1, "b": 0, "c": 1}


def load_js_object(path, prefix):
    s = open(path, encoding="utf-8").read()
    i = s.index(prefix) + len(prefix)
    j = s.rindex("}")
    return json.loads(s[i:j + 1].rstrip().rstrip(";").strip())


def world_to_canvas(mp_x, mp_y):
    return ((mp_x - 10) // 5 * WORLD_SCALE + WORLD_OFF,
            (mp_y - 15) // 5 * WORLD_SCALE + WORLD_OFF)


def floor_label(lv):
    if lv == 0:
        return "Floor 0"
    return f"Floor {'+' if lv > 0 else ''}{lv}"


def tile_png(fn, by_name):
    t = by_name.get(fn)
    if t and t.get("png"):
        return t["png"]
    return f"tiles/{fn}.png"


def build_area_owner(era, equiv):
    """Map each 2011 area SEC to the single best owning coordinate SEC."""
    # area -> list of (score, ok, coord, place)
    cands = defaultdict(list)
    for coord, v in era.items():
        area = v.get("area")
        if not area:
            continue
        cands[area].append((
            1 if v.get("ok") else 0,
            float(v.get("score") or 0),
            -float(v.get("next") or 0),
            coord,
            v.get("place"),
            bool(v.get("ok")),
        ))
    owner = {}
    for area, lst in cands.items():
        lst.sort(reverse=True)
        best = lst[0]
        owner[area] = {
            "coord": best[3],
            "score": best[1],
            "ok": best[5],
            "place": best[4],
            "runners": len(lst) - 1,
        }
    # EQUIV: area already knows its coord; reinforce ownership if missing
    for area, v in equiv.items():
        if area not in owner and v.get("coord"):
            owner[area] = {
                "coord": v["coord"],
                "score": float(v.get("sim") or 0),
                "ok": True,
                "place": None,
                "runners": 0,
                "via": "equiv",
            }
    return owner


def coord_to_preferred(era, equiv, owner):
    """coord SEC -> preferred display filename (2011 if confident owner)."""
    prefer = {}
    # reverse: only if this coord owns the area
    for area, info in owner.items():
        if not info.get("ok"):
            continue
        prefer[info["coord"]] = {
            "filename": area,
            "source": "2011",
            "confidence": "confirmed",
            "score": info["score"],
            "via": info.get("via", "era"),
        }
    # EQUIV also maps area->coord; if coord not yet preferred, use it
    for area, v in equiv.items():
        coord = v.get("coord")
        if coord and coord not in prefer:
            prefer[coord] = {
                "filename": area,
                "source": "2011",
                "confidence": "confirmed",
                "score": float(v.get("sim") or 0),
                "via": "equiv",
            }
    return prefer


def block_of_file(blocks):
    """filename -> block id (multi-piece preferred over solo)."""
    out = {}
    for b in blocks:
        for p in b["pieces"]:
            # multi-piece blocks win over solos if both claim
            cur = out.get(p["filename"])
            if cur is None or (len(b["pieces"]) > 1 and "#" in cur and "/solo#" in cur):
                out[p["filename"]] = b["id"]
            elif cur is None:
                out[p["filename"]] = b["id"]
            elif "/solo#" in (cur or "") and "/solo#" not in b["id"]:
                out[p["filename"]] = b["id"]
            elif cur is None or (len(b["pieces"]) >= 1 and out.get(p["filename"]) is None):
                out[p["filename"]] = b["id"]
    # simpler pass
    out = {}
    for b in sorted(blocks, key=lambda x: (-len(x["pieces"]), x["id"])):
        for p in b["pieces"]:
            if p["filename"] not in out:
                out[p["filename"]] = b["id"]
    return out


def occupied_set(placements):
    return {(p["col"], p["row"]) for p in placements if p.get("level", 0) == 0}


def fits(col, row, pieces, occ, gap=GAP):
    """pieces are {dx,dy} relative; check canvas bounds + gap around occupied."""
    cells = [(col + p["dx"], row + p["dy"]) for p in pieces]
    for x, y in cells:
        if x < 0 or y < 0 or x >= CANVAS_W or y >= CANVAS_H:
            return False
        for dy in range(-gap, gap + 1):
            for dx in range(-gap, gap + 1):
                if (x + dx, y + dy) in occ and (x + dx, y + dy) not in cells:
                    # allow gap=0 exact self; for gap>0 reject neighbors
                    if gap == 0:
                        if (x, y) in occ:
                            return False
                    else:
                        return False
        if gap == 0 and (x, y) in occ:
            return False
    return True


def find_near(tx, ty, pieces, occ, gap=GAP):
    for r in range(0, CANVAS_W):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                if fits(tx + dx, ty + dy, pieces, occ, gap):
                    return tx + dx, ty + dy
    return None


def stack_for_block(levels, block_id):
    """Return (cluster, floor) covering block_id from auto clusters, else None."""
    for cl in levels.get("clusters") or []:
        if cl.get("confidence") != "auto":
            continue
        for fl in cl.get("floors") or []:
            if fl.get("block_id") == block_id:
                return cl, fl
    return None


def relative_floors(cl):
    """Convert cluster floors so surface_level becomes Floor 0."""
    surf = int(cl.get("surface_level", 0))
    out = []
    for fl in cl.get("floors") or []:
        f = dict(fl)
        f["level"] = int(fl["level"]) - surf
        f["pieces"] = [
            {**p, "dz": int(p.get("dz", fl["level"])) - surf}
            for p in (fl.get("pieces") or [])
        ]
        out.append(f)
    return out, 0


def main():
    coords = json.load(open(COORDS, encoding="utf-8"))
    layout = json.load(open(LAYOUT, encoding="utf-8")) if os.path.isfile(LAYOUT) else {}
    blocks_data = json.load(open(BLOCKS, encoding="utf-8"))
    levels = json.load(open(LEVELS, encoding="utf-8")) if os.path.isfile(LEVELS) else {}
    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    era = load_js_object(ERA_JS, "window.ERA_MAP =") if os.path.isfile(ERA_JS) else {}
    equiv = load_js_object(EQUIV_JS, "window.EQUIV =") if os.path.isfile(EQUIV_JS) else {}
    anchors = load_js_object(ANCHORS_JS, "window.BLOCK_ANCHORS =") if os.path.isfile(ANCHORS_JS) else {}

    by_name = {}
    for t in (manifest.get("coordinate") or []) + (manifest.get("area") or []):
        by_name[t["filename"]] = t

    blocks = list(blocks_data.get("blocks") or [])
    for region, files in (blocks_data.get("singletons") or {}).items():
        for i, fn in enumerate(files, 1):
            blocks.append({
                "id": f"{region}/solo#{i}", "region": region,
                "w": 1, "h": 1,
                "pieces": [{"filename": fn, "dx": 0, "dy": 0}],
            })
    by_block = {b["id"]: b for b in blocks}
    file_block = block_of_file(blocks)

    owner = build_area_owner(era, equiv)
    prefer = coord_to_preferred(era, equiv, owner)

    # area files that are confirmed substitutes - their owning coord is covered
    substituted_coords = set(prefer.keys())
    used_files = set()
    placements = []
    review = {
        "probable_era": [],
        "unmatched_coords": [],
        "stair_suggest": list(levels.get("proposed_stacks") or []),
        "stair_review": list(levels.get("review_joins") or []),
        "one_sided": [],
        "duplicates_skipped": [],
        "unanchored_blocks": [],
    }

    # Collect one_sided from auto clusters
    for cl in levels.get("clusters") or []:
        for side in cl.get("one_sided") or []:
            review["one_sided"].append(side)

    # Probable (not auto) era matches
    for coord, v in era.items():
        if v.get("ok"):
            continue
        score = float(v.get("score") or 0)
        nxt = float(v.get("next") or 0)
        if score >= 0.55 and (score - nxt) >= 0.08:
            review["probable_era"].append({
                "coord": coord, "area": v.get("area"),
                "place": v.get("place"), "score": score, "next": nxt,
            })

    # --- Place auto multi-floor stacks first (complete regional frames) ---
    placed_block_ids = set()
    for cl in levels.get("clusters") or []:
        if cl.get("confidence") != "auto" or len(cl.get("floors") or []) < 2:
            continue
        floors, surf = relative_floors(cl)
        # Anchor from any floor block that has an anchor; prefer surface
        surf_floor = next((f for f in floors if f["level"] == surf), floors[0])
        anchor_id = surf_floor["block_id"]
        anch = anchors.get(anchor_id)
        # Prefer era-anchored sibling in the stack
        for f in floors:
            a = anchors.get(f["block_id"])
            if a and a.get("method") == "era":
                anch = a
                anchor_id = f["block_id"]
                break
        if not anch:
            # try any piece's owning block anchor
            for f in floors:
                if f["block_id"] in anchors:
                    anch = anchors[f["block_id"]]
                    break
        pieces0 = [{"dx": p["dx"], "dy": p["dy"]} for p in surf_floor["pieces"]]
        if not pieces0:
            continue
        occ = occupied_set(placements)
        if anch:
            spot = (anch["col"], anch["row"])
            if not fits(spot[0], spot[1], pieces0, occ, GAP):
                spot = find_near(anch["col"], anch["row"], pieces0, occ, GAP)
        else:
            spot = find_near(2, CANVAS_H - 8, pieces0, occ, GAP)
            review["unanchored_blocks"].append({
                "cluster": cl["id"], "region": cl["region"],
            })
        if not spot:
            review["unanchored_blocks"].append({
                "cluster": cl["id"], "region": cl["region"],
                "reason": "no room",
            })
            continue
        ax, ay = spot
        # Align: surf_floor pieces are already in cluster-local coords;
        # place so min piece sits at ax,ay relative to surf origin.
        # pieces already include absolute dx/dy within cluster; treat
        # surf_floor.dx/dy as origin offset of that floor's block.
        # Simpler: stamp each piece at ax+p.dx, ay+p.dy using piece coords
        # as stored (they're cluster-absolute). Shift so min surface cell
        # lands on ax,ay.
        surf_cells = [(p["dx"], p["dy"]) for p in surf_floor["pieces"]]
        minx = min(c[0] for c in surf_cells)
        miny = min(c[1] for c in surf_cells)
        ox, oy = ax - minx, ay - miny
        for fl in floors:
            for p in fl["pieces"]:
                fn = p["filename"]
                if fn in used_files:
                    review["duplicates_skipped"].append({
                        "filename": fn, "reason": "already placed",
                        "cluster": cl["id"],
                    })
                    continue
                # Prefer 2011 as-is (blocks are already 2011). Mark source.
                used_files.add(fn)
                placements.append({
                    "filename": fn,
                    "col": ox + p["dx"],
                    "row": oy + p["dy"],
                    "level": fl["level"],
                    "source": "2011",
                    "confidence": "auto_stack",
                    "block_id": fl["block_id"],
                    "cluster_id": cl["id"],
                    "region": cl["region"],
                    "place_name": None,
                    "png": tile_png(fn, by_name),
                    "generated": True,
                })
            placed_block_ids.add(fl["block_id"])

    # --- Place remaining 2011 blocks at anchors ---
    # Sort: era-anchored first, then name, big before small
    def block_sort_key(b):
        a = anchors.get(b["id"]) or {}
        method = 0 if a.get("method") == "era" else (1 if a else 2)
        return (method, b["region"], -(b.get("w", 1) * b.get("h", 1)), b["id"])

    park_x, park_y = 2, WORLD_OFF + 16 * WORLD_SCALE + 2
    for b in sorted(blocks, key=block_sort_key):
        if b["id"] in placed_block_ids:
            continue
        if len(b["pieces"]) < 1:
            continue
        # Skip if every piece already used
        if all(p["filename"] in used_files for p in b["pieces"]):
            continue
        pieces = [p for p in b["pieces"] if p["filename"] not in used_files]
        if not pieces:
            continue
        # Normalize piece offsets to 0-based for fit check
        minx = min(p["dx"] for p in pieces)
        miny = min(p["dy"] for p in pieces)
        rel = [{"dx": p["dx"] - minx, "dy": p["dy"] - miny, "filename": p["filename"]}
               for p in pieces]
        occ = occupied_set(placements)
        anch = anchors.get(b["id"])
        gap = 0 if (anch and anch.get("method") == "era") else GAP
        if anch:
            spot = (anch["col"], anch["row"])
            if not fits(spot[0], spot[1], rel, occ, gap):
                spot = find_near(anch["col"], anch["row"], rel, occ, gap)
        else:
            spot = find_near(park_x, park_y, rel, occ, GAP)
            if not spot:
                review["unanchored_blocks"].append({"block": b["id"], "reason": "no room"})
                continue
            park_x = min(CANVAS_W - 1, (spot[0] if spot else park_x) + b.get("w", 1) + 2)
            review["unanchored_blocks"].append({"block": b["id"], "reason": "parked"})
        if not spot:
            review["unanchored_blocks"].append({"block": b["id"], "reason": "no room"})
            continue
        ax, ay = spot
        conf = "confirmed" if (anch and anch.get("method") == "era") else (
            "name_anchor" if anch else "parked")
        for p in rel:
            fn = p["filename"]
            if fn in used_files:
                review["duplicates_skipped"].append({
                    "filename": fn, "reason": "already placed", "block": b["id"],
                })
                continue
            used_files.add(fn)
            placements.append({
                "filename": fn,
                "col": ax + p["dx"],
                "row": ay + p["dy"],
                "level": 0,
                "source": "2011",
                "confidence": conf,
                "block_id": b["id"],
                "cluster_id": None,
                "region": b["region"],
                "place_name": None,
                "png": tile_png(fn, by_name),
                "generated": True,
            })
        placed_block_ids.add(b["id"])

    # --- Place remaining 2006-only coordinate SECs (no 2011 substitute used) ---
    # If a coord was substituted via era, skip it (2011 already placed via block).
    # If substitute area wasn't placed (not in a block / singleton miss), place
    # the 2011 file at the coord canvas cell instead of the 2006 file.
    for base, sec in sorted((coords.get("sectors") or {}).items()):
        fn = sec["filename"]
        layer = (sec.get("layer") or "b").lower()
        level = LAYER_FLOOR.get(layer, 0)
        col, row = world_to_canvas(sec["mp_x"], sec["mp_y"])
        place = sec.get("place_name")
        pref = prefer.get(fn)

        if pref and pref["filename"] in used_files:
            # 2011 already on the map from a block stamp
            continue
        if pref and pref["filename"] not in used_files:
            # Confident 2011 match not covered by a block - place the 2011 tile
            out_fn = pref["filename"]
            source = "2011"
            confidence = "confirmed"
            via = pref.get("via", "era")
        else:
            out_fn = fn
            source = "2006"
            confidence = "2006_only"
            via = "coord"
            if fn not in substituted_coords:
                review["unmatched_coords"].append({
                    "filename": fn, "place": place,
                    "mp_x": sec["mp_x"], "mp_y": sec["mp_y"], "layer": layer,
                })

        if out_fn in used_files:
            review["duplicates_skipped"].append({
                "filename": out_fn, "reason": "coord conflict", "coord": fn,
            })
            continue

        # Collision: if Floor 0 cell taken, only place non-zero floors, or shift
        occ = occupied_set(placements)
        place_col, place_row = col, row
        if level == 0 and (col, row) in occ:
            # surface already filled by a 2011 block - keep 2006-only as review
            if source == "2006":
                continue
            # 2011 singleton wanting this cell - skip if occupied
            continue
        if level != 0:
            # allow stacking on same col,row different level
            pass

        used_files.add(out_fn)
        placements.append({
            "filename": out_fn,
            "col": place_col,
            "row": place_row,
            "level": level,
            "source": source,
            "confidence": confidence,
            "block_id": file_block.get(out_fn),
            "cluster_id": None,
            "region": None,
            "place_name": place,
            "png": tile_png(out_fn, by_name),
            "generated": True,
            "from_coord": fn if source == "2011" else None,
            "via": via,
            "mp_x": sec["mp_x"],
            "mp_y": sec["mp_y"],
            "layer": layer,
        })

    # Guide names projected onto canvas (same mapping as anchors)
    guides = {}
    guide_labels = {}
    for k, name in (layout.items() if isinstance(layout, dict) else []):
        if not isinstance(k, str) or "," not in k:
            continue
        try:
            ew, ns = map(int, k.split(","))
        except ValueError:
            continue
        c, r = world_to_canvas(ew, ns)
        guide_labels[f"{c},{r}"] = name
        for dy in range(WORLD_SCALE):
            for dx in range(WORLD_SCALE):
                guides[f"{c+dx},{r+dy}"] = name

    levels_present = sorted({p["level"] for p in placements})
    by_level = defaultdict(int)
    for p in placements:
        by_level[p["level"]] += 1

    stats = {
        "placements": len(placements),
        "by_source": {
            "2011": sum(1 for p in placements if p["source"] == "2011"),
            "2006": sum(1 for p in placements if p["source"] == "2006"),
        },
        "by_confidence": {},
        "by_level": {str(k): by_level[k] for k in sorted(by_level)},
        "levels": levels_present,
        "era_confirmed": sum(1 for v in prefer.values()),
        "probable_era": len(review["probable_era"]),
        "unmatched_coords": len(review["unmatched_coords"]),
        "duplicates_skipped": len(review["duplicates_skipped"]),
        "stair_suggest_stacks": len(review["stair_suggest"]),
        "stair_review_joins": len(review["stair_review"]),
        "one_sided": len(review["one_sided"]),
        "auto_stacks_placed": sum(
            1 for cl in (levels.get("clusters") or [])
            if cl.get("confidence") == "auto" and len(cl.get("floors") or []) > 1
        ),
    }
    for p in placements:
        stats["by_confidence"][p["confidence"]] = (
            stats["by_confidence"].get(p["confidence"], 0) + 1)

    out = {
        "grid": {"w": CANVAS_W, "h": CANVAS_H,
                 "world_off": WORLD_OFF, "world_scale": WORLD_SCALE},
        "surface_level": 0,
        "levels": levels_present,
        "floor_labels": {str(lv): floor_label(lv) for lv in levels_present},
        "placements": placements,
        "guides": guides,
        "guide_labels": guide_labels,
        "review": review,
        "prefer": {k: v for k, v in prefer.items()},
        "_meta": {
            "title": "Authoritative unified multi-floor SEC map",
            "note": "Floor 0 is the surface. Prefer 2011 when era/equiv confirms; "
                    "otherwise keep 2006. Old four-tab placements are ignored.",
            "stats": stats,
        },
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    with open(OUT_JS, "w", encoding="utf-8") as fh:
        fh.write("// Authoritative unified map (build_unified_map.py). "
                 "Do not edit by hand.\n")
        fh.write("window.UNIFIED_MAP = " + json.dumps(out) + ";\n")

    print("wrote unified_map.json/.js")
    print(f"  placements={stats['placements']} "
          f"2011={stats['by_source']['2011']} 2006={stats['by_source']['2006']}")
    print(f"  levels={stats['levels']} by_level={stats['by_level']}")
    print(f"  confidence={stats['by_confidence']}")
    print(f"  era_confirmed={stats['era_confirmed']} "
          f"probable={stats['probable_era']} "
          f"unmatched_coords={stats['unmatched_coords']}")
    print(f"  auto_stacks={stats['auto_stacks_placed']} "
          f"suggest_stacks={stats['stair_suggest_stacks']} "
          f"review_joins={stats['stair_review_joins']}")
    # spot-check Last Chance Pub
    lcp = [p for p in placements if "Last Chance" in (p.get("place_name") or "")
           or p["filename"] == "HIIN162193.SEC"]
    print(f"  Last Chance Pub placements: {lcp}")


if __name__ == "__main__":
    main()
