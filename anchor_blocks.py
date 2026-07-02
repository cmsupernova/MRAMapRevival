"""Compute world-position anchors for assembled region blocks (flat canvas).

Where should each assembled 2011 block sit on the flat surface canvas?
Evidence, in priority order:

  1. block-level 2006 content matching: every piece of every block is compared
     (terrain bytes, small offset search) against positioned 2006 coordinate
     SECs OF THE SAME REGION (place-name scoped - repetitive farm/grass tiles
     match across regions otherwise). Each good match votes for the block
     anchor implied by that piece's offset inside the block; agreeing votes
     from multiple pieces lock the block to the 2006 world layout. era_map.js
     confident matches (match_eras.py, region-scoped + offset search) are
     folded in as extra high-weight votes.
  2. guide names: the community layout names each world cell ("W Haven",
     "Castle Krell", "Guildhalls"...). A block whose region matches named
     cells is centered on their centroid. Region tokens follow MAPS.TXT /
     the Tekken map (unvil = Undead Village, greenwood = Guildhalls...).

Flat canvas mapping: world cell (mp_x, mp_y) -> col=(mp_x-10)/5*2+WORLD_OFF,
row=(mp_y-15)/5*2+WORLD_OFF. Each world cell gets a 2x2 canvas area because
the 2011 regions are physically larger than their 2006 footprint (Haven alone
is 4x3 sectors); at 1:1 everything around Haven collides. The margin keeps
blocks off the canvas edge so everything stays draggable in every direction.

Output: _render/block_anchors.js  ->  window.BLOCK_ANCHORS = {
    "Towns/Haven#1": {"col":16,"row":11,"method":"era","votes":4}, ... }

Usage: python anchor_blocks.py
"""
import json
import os
from collections import Counter, defaultdict

import numpy as np

import build_world_coords as B

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, "_render")
OUT = os.path.join(RENDER, "block_anchors.js")

# must match FLAT_W/FLAT_H, FLAT_WORLD_OFF, FLAT_WORLD_SCALE in sec_map.html
CANVAS_W = CANVAS_H = 56
WORLD_OFF = 6
WORLD_SCALE = 2       # canvas cells per world cell (19x16 world -> 38x32)
VOTE_TOL = 2          # anchor votes within this Chebyshev distance agree

GRID, CELL = 33, 6
FEAT_MIN_CELLS = 60   # coord tile needs this many non-background cells
PRE_S = 0.45          # prefilter: direct overall similarity
PRE_F = 0.35          # prefilter: direct feature similarity
CAND_S = 0.55         # candidate thresholds after offset refinement
CAND_F = 0.50
SOLO_S = 0.75         # a single-piece anchor needs this strong a match

# region folder -> lowercase tokens matched against layout guide names.
# Derived from MAPS.TXT / Tekken map naming: unvil=Undead Village,
# greenwood=Guildhalls, val=Valadia, DTN/DTS=Dunsmore town.
NAME_TOKENS = {
    "Towns/Haven": ["haven"],
    "Towns/Clysmort": ["clysmort"],
    "Towns/Salazad": ["salazad"],
    "Towns/Uswick": ["uswick"],
    "Towns/Verbonic": ["verbonic"],
    "Towns/Sanctuary": ["sanctuary"],
    "Towns/Baralza": ["baralza"],
    "Krell": ["krell"],
    "greenwood": ["greenwood", "guildhalls"],
    "gom": ["gom"],
    "jal": ["jal"],
    "maranda": ["maranda", "mar "],
    "per": ["per ", "prg"],
    "orcs": ["orc"],
    "rem": ["rem"],
    "omr": ["omr"],
    "iun": ["iun"],
    "Kokas": ["kokas"],
    "unvil": ["undead village"],
    "GobCavE": ["goblin cave"],
    "GobTun": ["gob tunnel"],
    "swamp": ["swamp"],
    "val": ["valadia"],
    "DTN and DTS": ["dunsmore"],
}


def load_js_object(path, prefix):
    s = open(path, encoding="utf-8").read()
    i = s.index(prefix) + len(prefix)
    j = s.rindex("}")
    return json.loads(s[i:j + 1].rstrip().rstrip(";").strip())


def world_to_canvas(mp_x, mp_y):
    return ((mp_x - 10) // 5 * WORLD_SCALE + WORLD_OFF,
            (mp_y - 15) // 5 * WORLD_SCALE + WORLD_OFF)


def terrain_of(path):
    d = open(path, "rb").read()
    if len(d) != GRID * GRID * CELL:
        return None
    return np.frombuffer(d, dtype=np.uint8).reshape(GRID, GRID, CELL)[:32, :32, 0]


def index_secs(root):
    out = {}
    for r, _d, fs in os.walk(root):
        if "__MACOSX" in r:
            continue
        for f in fs:
            if f.upper().endswith(".SEC") and not f.startswith("._"):
                t = terrain_of(os.path.join(r, f))
                if t is not None:
                    out[f] = t
    return out


def refine(P, C, mask, featn):
    """Best (overall, feature) similarity over +/-1 cell offsets."""
    best_s = best_f = 0.0
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            x0, x1 = max(0, dx), min(32, 32 + dx)
            y0, y1 = max(0, dy), min(32, 32 + dy)
            eq = C[y0:y1, x0:x1] == P[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
            m = mask[y0:y1, x0:x1]
            s = eq.mean()
            fn = m.sum()
            f = (eq & m).sum() / fn if fn else 0.0
            if s + f > best_s + best_f:
                best_s, best_f = s, f
    return best_s, best_f


def main():
    blocks = json.load(open(os.path.join(RENDER, "blocks.json")))["blocks"]
    manifest = json.load(open(os.path.join(RENDER, "manifest.json")))
    era = load_js_object(os.path.join(RENDER, "era_map.js"), "window.ERA_MAP =")

    coord_cell = {t["filename"]: (t["mp_x"], t["mp_y"])
                  for t in manifest.get("coordinate", [])
                  if t.get("mp_x") is not None}
    coord_place = {t["filename"]: (t.get("place_name") or "").lower()
                   for t in manifest.get("coordinate", [])}
    era_vote = {}   # area file -> world cell (confident match_eras result)
    for cf, v in era.items():
        if v.get("ok") and cf in coord_cell:
            era_vote[v["area"]] = coord_cell[cf]

    # --- content matching: block pieces vs positioned 2006 tiles ------------
    coord_t = index_secs(B.MAPS_DIR)
    piece_t = index_secs(B.MAPSALL_DIR)
    coords = []           # (filename, cell, terrain, mask, featn)
    for f, t in coord_t.items():
        if f not in coord_cell:
            continue
        mode = Counter(t.flatten().tolist()).most_common(1)[0][0]
        mask = t != mode
        featn = int(mask.sum())
        if featn >= FEAT_MIN_CELLS:
            coords.append((f, coord_cell[f], t, mask, featn))

    piece_votes = defaultdict(list)   # piece filename -> [(w, s, cell, coordfile)]
    stack_names = [f for f in piece_t]
    stack = np.stack([piece_t[f] for f in stack_names]) if stack_names else None
    for cf, cell, C, mask, featn in coords:
        eq = stack == C                       # (N,32,32) direct compare
        s0 = eq.mean(axis=(1, 2))
        f0 = (eq & mask).sum(axis=(1, 2)) / featn
        for i in np.nonzero((s0 >= PRE_S) | (f0 >= PRE_F))[0]:
            s, f = refine(stack[i], C, mask, featn)
            if s >= CAND_S and f >= CAND_F:
                piece_votes[stack_names[i]].append((s * f, s, cell, cf))

    anchors = {}
    for b in blocks:
        if len(b["pieces"]) < 2:
            continue
        tokens = NAME_TOKENS.get(b["region"], [])
        # votes are clustered (Chebyshev <= VOTE_TOL): with WORLD_SCALE > 1,
        # adjacent world cells sit 2 canvas cells apart while block pieces sit
        # 1 apart, so agreeing evidence lands close together, not identical
        clusters = []   # [sx, sy, weight, pieces set, best_s, scoped, era_map]

        def add_vote(ax, ay, w, piece, s, scoped, from_era):
            for c in clusters:
                rx, ry = c[0] / c[2], c[1] / c[2]
                if abs(rx - ax) <= VOTE_TOL and abs(ry - ay) <= VOTE_TOL:
                    c[0] += ax * w; c[1] += ay * w; c[2] += w
                    c[3].add(piece)
                    c[4] = max(c[4], s)
                    c[5] |= scoped; c[6] |= from_era
                    return
            clusters.append([ax * w, ay * w, w, {piece}, s, scoped, from_era])

        for p in b["pieces"]:
            cands = sorted(piece_votes.get(p["filename"], []), reverse=True)[:3]
            for w, s, cell, cf in cands:
                cx, cy = world_to_canvas(*cell)
                scoped = any(t in coord_place.get(cf, "") for t in tokens)
                add_vote(cx - p["dx"], cy - p["dy"], w, p["filename"], s,
                         scoped, False)
            ev = era_vote.get(p["filename"])
            if ev:                             # match_eras confident: heavy vote
                cx, cy = world_to_canvas(*ev)
                add_vote(cx - p["dx"], cy - p["dy"], 2.0, p["filename"], 1.0,
                         False, True)
        method = None
        if clusters:
            # trusted anchors (era_map-backed or place-name aligned) outrank
            # raw content votes: reused art (guild/prison interiors) can make
            # several pieces agree on a wrong spot across regions
            ranked = sorted(clusters,
                            key=lambda c: (-(c[6] or c[5]), -len(c[3]), -c[2]))
            sx, sy, w, pieces, best_s, scoped, from_era = ranked[0]
            col, row = round(sx / w), round(sy / w)
            trusted = from_era or scoped
            # content votes alone aren't enough: repetitive art (grass, farm
            # grids) makes unrelated pieces agree. Require era_map backing or
            # place-name alignment.
            ok = from_era or (scoped and (len(pieces) >= 2
                                          or best_s >= SOLO_S))
            if ok and len(ranked) > 1:
                c2 = ranked[1]
                if ((c2[6] or c2[5]) == trusted
                        and len(c2[3]) == len(pieces) and w - c2[2] < 0.10):
                    ok = False                  # ambiguous, fall back to name
            if ok:
                method, conf = "era", len(pieces)
        if not method:
            cells = region_name_cells(b["region"])
            if not cells:
                continue
            cx = sum(world_to_canvas(*c)[0] for c in cells) / len(cells)
            cy = sum(world_to_canvas(*c)[1] for c in cells) / len(cells)
            col = round(cx - (b["w"] - 1) / 2)
            row = round(cy - (b["h"] - 1) / 2)
            method, conf = "name", len(cells)
        col = max(0, min(CANVAS_W - b["w"], col))
        row = max(0, min(CANVAS_H - b["h"], row))
        anchors[b["id"]] = {"col": col, "row": row,
                            "method": method, "votes": conf}

    with open(OUT, "w") as fh:
        fh.write("// Block anchors (world positions on the flat canvas) by "
                 "anchor_blocks.py. Do not edit by hand.\n")
        fh.write("window.BLOCK_ANCHORS = " + json.dumps(anchors) + ";\n")

    n_era = sum(1 for a in anchors.values() if a["method"] == "era")
    n_name = sum(1 for a in anchors.values() if a["method"] == "name")
    total = sum(1 for b in blocks if len(b["pieces"]) > 1)
    print(f"anchored {len(anchors)}/{total} blocks "
          f"({n_era} via 2006 content matches, {n_name} via guide names)")
    for bid, a in sorted(anchors.items()):
        print(f"  {bid:28s} -> ({a['col']:2d},{a['row']:2d})  "
              f"{a['method']}({a['votes']})")
    missing = [b["id"] for b in blocks
               if len(b["pieces"]) > 1 and b["id"] not in anchors]
    if missing:
        print("unanchored (parked when laying out):", ", ".join(missing))


_layout_cache = None


def region_name_cells(region):
    global _layout_cache
    if _layout_cache is None:
        _layout_cache = B.load_layout()
    tokens = NAME_TOKENS.get(region)
    if not tokens:
        return []
    cells = []
    for (mx, my), name in _layout_cache.items():
        n = name.lower()
        if " of " in n:            # "N of Salazad" = neighbor, not the place
            continue
        if any(t in n for t in tokens):
            cells.append((mx, my))
    return cells


if __name__ == "__main__":
    main()
