"""Stack 2D edge-assembled blocks into multi-floor level clusters.

Consumes:
  _render/blocks.json   - rigid horizontal floor pieces from assemble_regions.py
  _render/portals.js    - classified up/down/fall cells (extract_portals.py)
  coordinate SECs       - same-base a/b/c filenames pin exact layer stacks

Each 2D block is treated as a rigid slab. Local stair cells are projected into
block-global coordinates; UP cells in block A vote for offsets against DOWN
cells in block B. Multiple agreeing stairs lock a vertical join. Single-stair
matches are suggestions unless a filename/coord-layer clue resolves them.

Many stairs between the same floors are allowed (OMR-style); endpoints are
NOT forced into one-to-one pairs.

Outputs:
  _render/level_clusters.json
  _render/level_clusters.js  -> window.LEVEL_CLUSTERS

Usage: python assemble_levels.py
"""
import json
import os
import re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, "_render")
BLOCKS_JSON = os.path.join(RENDER, "blocks.json")
PORTALS_JS = os.path.join(RENDER, "portals.js")
OUT_JSON = os.path.join(RENDER, "level_clusters.json")
OUT_JS = os.path.join(RENDER, "level_clusters.js")

# match quality
ADJ_RADIUS = 1          # Manhattan distance for UP↔DOWN cell pairing (SCB overlap rule)
MULTI_MIN = 2           # >= this many agreeing stairs => auto join
SCORE_GAP = 0.25        # best offset must beat runner-up by this fraction of matches
SOLO_HINT_OK = True     # single-stair ok if filename/coord hint agrees


def load_js_object(path, prefix):
    s = open(path, encoding="utf-8").read()
    i = s.index(prefix) + len(prefix)
    j = s.rindex("}")
    return json.loads(s[i:j + 1].rstrip().rstrip(";").strip())


def coord_layer(fn):
    """Return (base, layer_letter) for coordinate SECs like EWGB322353b.SEC."""
    m = re.match(r"^([A-Z]{3,4}\d+)([abc])\.SEC$", fn, re.I)
    if not m:
        return None
    return m.group(1).upper(), m.group(2).lower()


def stair_points(exits, fn, kind):
    """kind: 'up' or 'down' (legacy 'dn' accepted)."""
    e = exits.get(fn) or {}
    key = kind if kind in e else ("dn" if kind == "down" and "dn" in e else kind)
    return [(c["r"], c["c"]) for c in e.get(key, [])]


def block_stairs(block, exits):
    """Project stair cells into block-global (gx, gy) using piece offsets.

    gx/gy use sector-cell units: each piece sits at (dx*32, dy*32) so adjacent
    pieces share no cell space (playable area is 32x32).
    """
    up, down = [], []
    for p in block["pieces"]:
        ox, oy = p["dx"] * 32, p["dy"] * 32
        for r, c in stair_points(exits, p["filename"], "up"):
            up.append({"gx": ox + c, "gy": oy + r, "r": r, "c": c,
                       "file": p["filename"]})
        for r, c in stair_points(exits, p["filename"], "down"):
            down.append({"gx": ox + c, "gy": oy + r, "r": r, "c": c,
                         "file": p["filename"]})
    return up, down


def match_count(ups, downs, ox, oy):
    """How many UP cells find a DOWN within ADJ_RADIUS after offset (ox,oy).

    Offset means: down.gx ~= up.gx + ox, down.gy ~= up.gy + oy
    (i.e. place the DOWN-bearing block relative to the UP-bearing block).
    Greedy unique pairing.
    """
    used = set()
    hits = []
    # sort by distance so closest pairs win
    cands = []
    for i, u in enumerate(ups):
        for j, d in enumerate(downs):
            dist = abs((u["gx"] + ox) - d["gx"]) + abs((u["gy"] + oy) - d["gy"])
            if dist <= ADJ_RADIUS:
                cands.append((dist, i, j))
    cands.sort()
    taken_u, taken_d = set(), set()
    for dist, i, j in cands:
        if i in taken_u or j in taken_d:
            continue
        taken_u.add(i)
        taken_d.add(j)
        hits.append({"up": ups[i], "down": downs[j], "dist": dist})
    return hits


def vote_offsets(ups, downs):
    """Enumerate plausible offsets from every UP↔DOWN pair within radius."""
    votes = Counter()
    for u in ups:
        for d in downs:
            for dx in range(-ADJ_RADIUS, ADJ_RADIUS + 1):
                for dy in range(-ADJ_RADIUS, ADJ_RADIUS + 1):
                    if abs(dx) + abs(dy) > ADJ_RADIUS:
                        continue
                    # offset that places down-block so d aligns near u
                    ox = d["gx"] - u["gx"] - dx
                    oy = d["gy"] - u["gy"] - dy
                    votes[(ox, oy)] += 1
    return votes


def best_offset(ups, downs):
    """Return (ox, oy, hits, runner_hits) or None.

    Rank by unique match count, then tighter cell distances, then smaller
    translation. Nearby offset variants of the same pairing (within
    ADJ_RADIUS) are not treated as competing runners.
    """
    if not ups or not downs:
        return None
    votes = vote_offsets(ups, downs)
    if not votes:
        return None
    ranked = []
    for off, _ in votes.most_common(80):
        hits = match_count(ups, downs, *off)
        if not hits:
            continue
        total_dist = sum(h["dist"] for h in hits)
        manh = abs(off[0]) + abs(off[1])
        ranked.append((len(hits), -total_dist, -manh, off, hits))
    ranked.sort(reverse=True)
    if not ranked:
        return None
    best_n, _td, _mh, best_off, best_hits = ranked[0]
    runner = 0
    for n, _td, _mh, off, _hits in ranked[1:]:
        if abs(off[0] - best_off[0]) + abs(off[1] - best_off[1]) <= ADJ_RADIUS:
            continue
        runner = n
        break
    return best_off[0], best_off[1], best_hits, runner


def _name_has_token(text, tokens):
    """True if any token appears as its own path segment / suffix."""
    t = text.lower().replace("\\", "/").replace(".sec", "")
    parts = re.split(r"[^a-z0-9]+", t)
    joined = " ".join(parts)
    for tok in tokens:
        if tok in parts or joined.endswith(" " + tok) or joined.startswith(tok + " "):
            return True
        # allow glued suffixes like kokastop / northfloor
        if any(p.endswith(tok) and len(p) >= len(tok) for p in parts):
            # avoid tiny false hits like 'up' inside arbitrary words unless exact
            if len(tok) >= 3 or tok in parts:
                return True
    return False


def filename_hint(a_files, b_files):
    """Soft clue that B sits above A from naming (top/northfloor/etc.)."""
    al = " ".join(f.lower() for f in a_files)
    bl = " ".join(f.lower() for f in b_files)
    above_words = ("top", "upper", "northfloor", "attic", "roof", "upstairs")
    below_words = ("under", "basement", "cave", "lower", "cellar", "downstairs")
    score = 0
    if _name_has_token(bl, above_words):
        score += 1
    if _name_has_token(al, below_words):
        score += 1
    if _name_has_token(al, above_words):
        score -= 1
    if _name_has_token(bl, below_words):
        score -= 1
    # numeric floor: foo1 below foo2 when both share a stem
    nums = []
    for label, files in (("a", a_files), ("b", b_files)):
        for f in files:
            m = re.search(r"(\d+)(?:[a-z]*)\.sec$", f, re.I)
            if m:
                nums.append((label, int(m.group(1)), f.lower()))
    if len(nums) >= 2:
        a_nums = [n for lab, n, _ in nums if lab == "a"]
        b_nums = [n for lab, n, _ in nums if lab == "b"]
        if a_nums and b_nums and min(b_nums) == max(a_nums) + 1:
            score += 1
    return score


def coord_stack_hint(a_files, b_files):
    """If both sides are coordinate SECs of same base with adjacent letters."""
    def layers(files):
        out = {}
        for f in files:
            cl = coord_layer(f)
            if cl:
                out[cl[0]] = cl[1]
        return out
    la, lb = layers(a_files), layers(b_files)
    for base in set(la) & set(lb):
        order = "abc"
        ia, ib = order.find(la[base]), order.find(lb[base])
        if ia >= 0 and ib >= 0 and ib == ia + 1:
            return True
    return False


def evaluate_pair(A, B, exits):
    """Can B sit one floor above A? Returns candidate dict or None."""
    upA, _dnA = block_stairs(A, exits)
    _upB, dnB = block_stairs(B, exits)
    if not upA or not dnB:
        return None
    res = best_offset(upA, dnB)
    if not res:
        return None
    ox, oy, hits, runner = res
    n = len(hits)
    a_files = [p["filename"] for p in A["pieces"]]
    b_files = [p["filename"] for p in B["pieces"]]
    hinted = filename_hint(a_files, b_files) > 0
    coord = coord_stack_hint(a_files, b_files)
    exact = sum(1 for h in hits if h["dist"] == 0)
    near = sum(1 for h in hits if h["dist"] <= ADJ_RADIUS)
    strong_gap = (n - runner) >= max(2, int(n * SCORE_GAP))
    weak_gap = (n - runner) >= 1 or runner == 0
    # Auto only for clear multi-stair agreement. SCB stairs often sit on
    # adjacent cells (dist=1), so "near" counts as valid evidence.
    # Name/coord clues promote weaker matches to suggest for UI accept.
    if n >= 3 and strong_gap and near >= 3:
        conf = "auto"
    elif n >= MULTI_MIN and runner == 0 and near >= MULTI_MIN:
        conf = "auto"
    elif n >= 1 and (coord or (SOLO_HINT_OK and hinted and weak_gap)):
        conf = "suggest"
    elif n >= 1 and weak_gap:
        conf = "review"
    else:
        return None
    return {
        "below": A["id"], "above": B["id"],
        "ox": ox, "oy": oy,
        "matches": n, "runner": runner, "exact": exact,
        "confidence": conf,
        "coord_hint": coord, "name_hint": hinted,
        "evidence": [{"up_file": h["up"]["file"], "up_r": h["up"]["r"],
                      "up_c": h["up"]["c"],
                      "down_file": h["down"]["file"], "down_r": h["down"]["r"],
                      "down_c": h["down"]["c"], "dist": h["dist"]}
                     for h in hits],
    }


def build_region_graph(blocks, exits):
    """Find vertical join candidates between blocks of the same region."""
    by_region = defaultdict(list)
    for b in blocks:
        by_region[b["region"]].append(b)
    joins = []
    for region, blist in by_region.items():
        for A in blist:
            for B in blist:
                if A["id"] == B["id"]:
                    continue
                cand = evaluate_pair(A, B, exits)
                if cand:
                    joins.append(cand)
    return joins


def _build_cluster_from_edges(by_id, members, edge_joins, contradictions, conf_label):
    """Assign levels/offsets for blocks linked by directed below->above joins."""
    above_of = defaultdict(list)
    for j in edge_joins:
        if j["below"] in members and j["above"] in members:
            above_of[j["below"]].append((j["above"], j))

    has_below = {j["above"] for j in edge_joins
                 if j["below"] in members and j["above"] in members}
    starts = [m for m in members if m not in has_below]
    if not starts:
        starts = [members[0]]
        contradictions.append({"a": members[0], "b": None,
                               "reason": "cycle; forced start"})
    level = {s: 0 for s in starts}
    q = list(starts)
    offsets = {s: (0, 0) for s in starts}
    used_joins = []
    while q:
        cur = q.pop(0)
        for nxt, j in above_of.get(cur, []):
            nl = level[cur] + 1
            bx, by = offsets[cur]
            nx, ny = bx + j["ox"], by + j["oy"]
            if nxt in level:
                if level[nxt] != nl or offsets[nxt] != (nx, ny):
                    contradictions.append({
                        "a": cur, "b": nxt,
                        "reason": f"conflict level/offset "
                                  f"have={level[nxt]},{offsets[nxt]} "
                                  f"want={nl},{(nx, ny)}",
                    })
                continue
            level[nxt] = nl
            offsets[nxt] = (nx, ny)
            used_joins.append(j)
            q.append(nxt)
    for m in members:
        level.setdefault(m, 0)
        offsets.setdefault(m, (0, 0))

    # Relative levels start at 0 = lowest. Designate the lowest floor as the
    # default surface (Floor 0 in the unified map). Upper floors become +1,+2...
    # Callers may later re-mark surface; then lower floors become negative.
    min_lv = min(level.values())
    for m in level:
        level[m] -= min_lv
    surface_level = 0
    for m in level:
        level[m] = level[m] - surface_level  # identity for default surface=lowest
    surf = [m for m, lv in level.items() if lv == surface_level]
    if surf:
        minx = min(offsets[m][0] for m in surf)
        miny = min(offsets[m][1] for m in surf)
        for m in offsets:
            ox, oy = offsets[m]
            offsets[m] = (ox - minx, oy - miny)

    floors = []
    region = by_id[members[0]]["region"]
    for m in sorted(members, key=lambda x: (level[x], x)):
        b = by_id[m]
        dx, dy = offsets[m]
        fdx, fdy = dx // 32, dy // 32
        floors.append({
            "level": level[m],
            "block_id": m,
            "dx": fdx, "dy": fdy,
            "cell_ox": dx, "cell_oy": dy,
            "pieces": [{"filename": p["filename"],
                        "dx": fdx + p["dx"], "dy": fdy + p["dy"],
                        "dz": level[m]}
                       for p in b["pieces"]],
        })
    ones = []
    for m in members:
        ones.extend(one_sided_for(by_id[m]))
    return {
        "id": f"{region}#{members[0].split('#')[-1]}@{conf_label}",
        "region": region,
        "surface_level": surface_level,
        "confidence": conf_label,
        "floors": floors,
        "joins": used_joins,
        "one_sided": ones,
    }


def resolve_stacks(blocks, joins):
    """Union-find stacking: auto joins form clusters; suggest/review listed.

    Detects contradictory cycles (A above B and B above A via auto edges).
    Also emits proposed multi-floor clusters from suggest joins for UI review.
    """
    by_id = {b["id"]: b for b in blocks}
    auto = [j for j in joins if j["confidence"] == "auto"]
    suggest = [j for j in joins if j["confidence"] == "suggest"]
    review = [j for j in joins if j["confidence"] == "review"]

    parent = {b["id"]: b["id"] for b in blocks}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    contradictions = []
    accepted_auto = []
    for j in auto:
        if any(x["below"] == j["above"] and x["above"] == j["below"] for x in auto):
            contradictions.append({"a": j["below"], "b": j["above"],
                                   "reason": "mutual auto above"})
            continue
        accepted_auto.append(j)
        union(j["below"], j["above"])

    components = defaultdict(list)
    for b in blocks:
        components[find(b["id"])].append(b["id"])

    clusters = []
    for _root, members in sorted(components.items()):
        member_joins = [j for j in accepted_auto
                        if j["below"] in members and j["above"] in members]
        if not member_joins:
            bid = members[0]
            b = by_id[bid]
            clusters.append({
                "id": bid + "@0",
                "region": b["region"],
                "surface_level": 0,
                "confidence": "flat",
                "floors": [{
                    "level": 0, "block_id": bid,
                    "dx": 0, "dy": 0,
                    "pieces": [{"filename": p["filename"],
                                "dx": p["dx"], "dy": p["dy"], "dz": 0}
                               for p in b["pieces"]],
                }],
                "joins": [],
                "one_sided": one_sided_for(b),
            })
            continue
        clusters.append(_build_cluster_from_edges(
            by_id, members, member_joins, contradictions, "auto"))

    # Proposed stacks:
    # 1) Prefer complete regional suggest DAGs when they form a clean chain
    #    (no contradictions) covering 2+ blocks.
    # 2) Fall back to pairwise propose when a region graph has conflicts.
    proposed = []
    prop_parent = {b["id"]: b["id"] for b in blocks}

    def pfind(x):
        while prop_parent[x] != x:
            prop_parent[x] = prop_parent[prop_parent[x]]
            x = prop_parent[x]
        return x

    def punion(a, b):
        ra, rb = pfind(a), pfind(b)
        if ra != rb:
            prop_parent[rb] = ra

    # Exclude blocks already in an auto multi-floor cluster
    auto_ids = {f["block_id"] for c in clusters if len(c["floors"]) > 1
                for f in c["floors"]}
    usable_suggest = []
    for j in suggest:
        if j["below"] in auto_ids or j["above"] in auto_ids:
            continue
        if any(x["below"] == j["above"] and x["above"] == j["below"] for x in suggest):
            contradictions.append({"a": j["below"], "b": j["above"],
                                   "reason": "mutual suggest above"})
            continue
        usable_suggest.append(j)
        punion(j["below"], j["above"])

    prop_comp = defaultdict(list)
    for b in blocks:
        if b["id"] in auto_ids:
            continue
        prop_comp[pfind(b["id"])].append(b["id"])

    used_in_chain = set()
    for _root, members in sorted(prop_comp.items()):
        member_joins = [j for j in usable_suggest
                        if j["below"] in members and j["above"] in members]
        if len(members) < 2 or not member_joins:
            continue
        # Try full regional chain; if it creates conflicts, fall back to pairs
        before = len(contradictions)
        trial = _build_cluster_from_edges(
            by_id, members, member_joins, contradictions, "suggest")
        new_conflicts = contradictions[before:]
        # Keep only conflicts that touch these members
        bad = [c for c in new_conflicts
               if (c.get("a") in members) or (c.get("b") in members)]
        if not bad and len(trial["floors"]) > 1:
            # Drop the trial conflicts we just added (none were bad)
            proposed.append(trial)
            used_in_chain.update(members)
        else:
            # Roll back those conflict notes and emit pairs instead
            del contradictions[before:]

    for j in usable_suggest:
        if j["below"] in used_in_chain and j["above"] in used_in_chain:
            continue
        if j["below"] in used_in_chain or j["above"] in used_in_chain:
            # one side already chained; skip dangling edge to avoid double-use
            continue
        members = [j["below"], j["above"]]
        if any(m not in by_id for m in members):
            continue
        proposed.append(_build_cluster_from_edges(
            by_id, members, [j], contradictions, "suggest"))
        used_in_chain.update(members)

    return clusters, proposed, suggest, review, contradictions


# need exits in one_sided_for - pass via closure after load
_EXITS = {}


def one_sided_for(block):
    """Stairs that have no partner on any other block in the same region."""
    up, dn = block_stairs(block, _EXITS)
    out = []
    if up and not any(True for _ in []):  # filled below in main with partner check
        pass
    # simple: report counts; partner resolution happens in report phase
    if up:
        out.append({"block": block["id"], "kind": "up", "n": len(up),
                    "files": sorted({u["file"] for u in up})})
    if dn:
        out.append({"block": block["id"], "kind": "down", "n": len(dn),
                    "files": sorted({d["file"] for d in dn})})
    return out


def mark_one_sided(clusters, joins):
    """Refine one_sided: drop stairs that participated in any accepted/suggested join."""
    covered = set()
    for j in joins:
        for e in j.get("evidence", []):
            covered.add((e["up_file"], "up", e["up_r"], e["up_c"]))
            covered.add((e["down_file"], "down", e["down_r"], e["down_c"]))
    for cl in clusters:
        refined = []
        for side in cl.get("one_sided", []):
            kind = side["kind"]
            pts = []
            for fn in side["files"]:
                for r, c in stair_points(_EXITS, fn, kind):
                    if (fn, kind, r, c) not in covered:
                        pts.append({"file": fn, "r": r, "c": c})
            if pts:
                refined.append({"block": side["block"], "kind": kind,
                                "n": len(pts), "cells": pts})
        cl["one_sided"] = refined


def main():
    global _EXITS
    blocks_data = json.load(open(BLOCKS_JSON, encoding="utf-8"))
    blocks = [b for b in blocks_data["blocks"] if len(b["pieces"]) >= 1]
    # include singletons as 1x1 blocks so stairs on them participate
    for region, files in (blocks_data.get("singletons") or {}).items():
        for i, fn in enumerate(files, 1):
            blocks.append({
                "id": f"{region}/solo#{i}", "region": region,
                "w": 1, "h": 1,
                "pieces": [{"filename": fn, "dx": 0, "dy": 0}],
                "junctions": [], "ambiguous": [], "warnings": [],
            })
    _EXITS = load_js_object(PORTALS_JS, "window.SEC_EXITS =")

    joins = build_region_graph(blocks, _EXITS)
    clusters, proposed, suggest, review, contradictions = resolve_stacks(blocks, joins)
    mark_one_sided(clusters, joins + suggest + review)
    mark_one_sided(proposed, joins + suggest + review)

    # drop pure-flat clusters that have no stairs at all (noise)
    kept = []
    for cl in clusters:
        has_multi = len(cl["floors"]) > 1
        if has_multi or cl["one_sided"] or cl["confidence"] != "flat":
            kept.append(cl)
        elif any(len(f["pieces"]) > 1 for f in cl["floors"]):
            kept.append(cl)
    clusters = kept

    out = {
        "clusters": clusters,
        "proposed_stacks": proposed,
        "suggested_joins": suggest,
        "review_joins": review,
        "contradictions": contradictions,
        "_meta": {
            "note": "Vertical stacks from UP/DOWN stair geometry on 2D blocks. "
                    "waypoint/fixed_warp portals are separate (see portals.js).",
            "stats": {
                "clusters": len(clusters),
                "multi_floor": sum(1 for c in clusters if len(c["floors"]) > 1),
                "proposed_stacks": len(proposed),
                "auto_joins": sum(len(c["joins"]) for c in clusters),
                "suggested": len(suggest),
                "review": len(review),
                "contradictions": len(contradictions),
                "one_sided": sum(len(c["one_sided"]) for c in clusters),
            },
        },
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    with open(OUT_JS, "w", encoding="utf-8") as fh:
        fh.write("// Multi-floor level clusters (assemble_levels.py). "
                 "Do not edit by hand.\n")
        fh.write("window.LEVEL_CLUSTERS = " + json.dumps(out) + ";\n")

    st = out["_meta"]["stats"]
    print(f"wrote level_clusters.json/.js")
    print(f"  clusters={st['clusters']} multi_floor={st['multi_floor']} "
          f"proposed={st['proposed_stacks']} auto_joins={st['auto_joins']} "
          f"suggested={st['suggested']} review={st['review']} "
          f"contradictions={st['contradictions']} one_sided={st['one_sided']}")
    for cl in clusters + proposed:
        if len(cl["floors"]) > 1:
            floors = ",".join(f"L{f['level']}:{f['block_id']}" for f in cl["floors"])
            print(f"  {cl['confidence'].upper():7s} {cl['region']:20s} {floors}  "
                  f"joins={len(cl['joins'])}")


if __name__ == "__main__":
    main()
