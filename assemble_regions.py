"""Assemble MAPSALL region folders into positioned multi-sector blocks.

The 2011 name-based SECs were cut from continuous region paintings, so adjacent
pieces share identical terrain along their common edge (verified: Haven pieces
chain at exactly 1.0 similarity). This solver reconstructs each folder's layout
from those edge matches, conservatively:

  - a placement must agree with EVERY already-placed neighbor it touches
    (terrain edge similarity >= TOUCH_MIN), and
  - at least one touched edge must be STRONG evidence: a near-exact match on an
    informative (non-uniform) edge. Uniform edges (all void / water / grass)
    match each other trivially, so they count as compatible but never as
    evidence.

Pieces that never earn a strong link stay unplaced (reported as singletons)
rather than being guessed. A folder can yield several disconnected blocks -
many legitimately contain multiple areas (e.g. krell town + graveyard + guilds).

A merge pass then joins blocks (and singletons) within a region when they
INTERLOCK: if a sub-block slots against another satisfying several borders at
once, that combinatorial fit is accepted as evidence even when each individual
border is uniform (plain grass/water). This is what reunites e.g. greenwood's
lake pieces with the town block despite their all-grass junctions.

Filename direction hints (breedery2east, iun1south, dz1nw...) participate in
the solve: a candidate position that agrees with a hint gets a score bonus and
one that contradicts it gets a penalty, and a cardinal hint whose edges are
compatible can seed or justify a placement on its own (rem2north sits north of
rem2 even though that junction is nearly uniform). Remaining disagreements are
reported as warnings.

Outputs:
  _render/blocks.json           block layouts, junction scores, ambiguities
  _render/blocks.js             same data as window.BLOCKS for the browser tools
  _render/_blocks/<block>.png   montage per multi-piece block (from _render/tiles)

Usage: python assemble_regions.py
"""
import json
import os
from collections import Counter

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
MAPSALL = os.path.join(HERE, "_mapsall_unzip", "MAPSALL")
TILES = os.path.join(HERE, "_render", "tiles")
OUT_JSON = os.path.join(HERE, "_render", "blocks.json")
OUT_JS = os.path.join(HERE, "_render", "blocks.js")
OUT_IMG = os.path.join(HERE, "_render", "_blocks")

GRID, CELL, PLAY = 33, 6, 32
STRONG_SIM = 0.97    # near-exact terrain match required for evidence
STRONG_INFO = 0.12   # ...on an edge that is not (nearly) uniform
TOUCH_MIN = 0.85     # every touched neighbor edge must at least be compatible
AMBIG_EPS = 0.02     # alternate positions scoring within this of the winner
HINT_WEIGHT = 0.15   # score bonus/penalty when a name hint agrees/contradicts
TOUCH_BONUS = 0.03   # merge-pass score per satisfied junction (interlock)
MERGE_MARGIN = 0.03  # best merge offset must beat runner-up by this much
MERGE_TOUCHES = 3    # junction count that counts as interlock evidence
MERGE_FLOOR = 0.60   # merge junctions may dip to here (redrawn borders)...
MERGE_MEAN = 0.90    # ...as long as the average junction similarity stays high
MERGE_STRONG = 0.95  # slightly softer "strong" in the merge pass

# filename suffix -> expected (dx, dy) sign relative to the base piece
DIR_HINTS = {
    "northeast": (1, -1), "northwest": (-1, -1),
    "southeast": (1, 1), "southwest": (-1, 1),
    "north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0),
    "ne": (1, -1), "nw": (-1, -1), "se": (1, 1), "sw": (-1, 1),
}


def read_sec(path):
    d = open(path, "rb").read()
    return d if len(d) == GRID * GRID * CELL else None


def edges_of(d):
    return {
        "T": bytes(d[(0 * GRID + c) * CELL] for c in range(PLAY)),
        "B": bytes(d[(31 * GRID + c) * CELL] for c in range(PLAY)),
        "L": bytes(d[(r * GRID + 0) * CELL] for r in range(PLAY)),
        "R": bytes(d[(r * GRID + 31) * CELL] for r in range(PLAY)),
    }


def sim(a, b):
    return sum(x == y for x, y in zip(a, b)) / PLAY


def info(e):
    # 0 for a uniform edge, ->1 as the edge gets more varied
    return 1 - Counter(e).most_common(1)[0][1] / PLAY


def load_regions():
    regions = {}
    for r, _d, fs in os.walk(MAPSALL):
        if "__MACOSX" in r:
            continue
        rel = os.path.relpath(r, MAPSALL).replace(os.sep, "/")
        region = "misc" if rel == "." else rel
        for f in sorted(fs):
            if not f.upper().endswith(".SEC"):
                continue
            d = read_sec(os.path.join(r, f))
            if d:
                regions.setdefault(region, {})[f] = edges_of(d)
    return regions


# junction between piece at pos and candidate/neighbor: which edges meet
def junction(E, a, b, dx, dy):
    """Edge pair when b sits at a's offset (dx,dy). Returns (sim, info)."""
    if dx == 1:
        ea, eb = E[a]["R"], E[b]["L"]
    elif dx == -1:
        ea, eb = E[a]["L"], E[b]["R"]
    elif dy == 1:
        ea, eb = E[a]["B"], E[b]["T"]
    else:
        ea, eb = E[a]["T"], E[b]["B"]
    return sim(ea, eb), min(info(ea), info(eb))


def parse_hints(names):
    """piece -> (base piece, ex, ey, cardinal). breedery2east -> breedery2,+1,0."""
    lower = {n.lower(): n for n in names}
    hints = {}
    for n in names:
        stem = os.path.splitext(n)[0].lower()
        for suf, (ex, ey) in sorted(DIR_HINTS.items(), key=lambda kv: -len(kv[0])):
            if stem.endswith(suf) and len(stem) > len(suf):
                base = lower.get(stem[: -len(suf)] + ".sec")
                if base:
                    hints[n] = (base, ex, ey, (ex == 0) != (ey == 0))
                break
    return hints


def rel_ok(ex, ey, dx, dy):
    """Does relative position (dx,dy) agree with hint direction (ex,ey)?"""
    if ex and (dx == 0 or (dx > 0) != (ex > 0)):
        return False
    if ey and (dy == 0 or (dy > 0) != (ey > 0)):
        return False
    return True


def hint_adjust(hints, pos, p, x, y):
    """Score bonus/penalty from name hints involving p at (x,y)."""
    adj = 0.0
    h = hints.get(p)
    if h and h[0] in pos:
        bx, by = pos[h[0]]
        adj += HINT_WEIGHT if rel_ok(h[1], h[2], x - bx, y - by) else -HINT_WEIGHT
    for q, (base, ex, ey, _c) in hints.items():
        if base == p and q in pos:
            qx, qy = pos[q]
            adj += HINT_WEIGHT if rel_ok(ex, ey, qx - x, qy - y) else -HINT_WEIGHT
    return adj


def evaluate(E, byPos, pos, hints, p, x, y):
    """Can piece p sit at (x,y)? Must satisfy every touched neighbor."""
    touches, strong, score = 0, False, 0.0
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        n = byPos.get((x + dx, y + dy))
        if not n:
            continue
        # p is at (x,y); neighbor n at offset (dx,dy) from p
        s, w = junction(E, p, n, dx, dy)
        if s < TOUCH_MIN:
            return None
        touches += 1
        score += s * w
        if s >= STRONG_SIM and w >= STRONG_INFO:
            strong = True
    if not touches:
        return None
    # a cardinal name hint at its exact offset justifies an otherwise
    # uniform-edge placement (edges were already checked compatible above)
    h = hints.get(p)
    if not strong and h and h[3] and h[0] in pos:
        bx, by = pos[h[0]]
        if (x - bx, y - by) == (h[1], h[2]):
            strong = True
    if not strong:
        return None
    return score + touches * 0.001 + hint_adjust(hints, pos, p, x, y)


DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def best_merge_offset(E, hints, A, B):
    """Best non-overlapping placement of block B against block A.

    Every A-B junction must be edge-compatible; the fit is accepted only with
    real evidence (a strong informative junction, an interlock of several
    junctions, or a hint-backed pair) and only if the best offset clearly
    beats the runner-up. Returns (score, (ox, oy)) or None.
    """
    apos = {v: k for k, v in A.items()}
    offs = set()
    for ax, ay in A.values():
        for bx, by in B.values():
            for dx, dy in DIRS:
                offs.add((ax + dx - bx, ay + dy - by))
    results = []
    for off in offs:
        newcells = {(x + off[0], y + off[1]) for x, y in B.values()}
        if newcells & set(apos):
            continue
        touches, score, strong, ok, sims = 0, 0.0, False, True, []
        for p, (x, y) in B.items():
            px, py = x + off[0], y + off[1]
            for dx, dy in DIRS:
                n = apos.get((px + dx, py + dy))
                if not n:
                    continue
                s, w = junction(E, p, n, dx, dy)
                if s < MERGE_FLOOR:
                    ok = False
                    break
                touches += 1
                sims.append(s)
                score += s * w
                if s >= MERGE_STRONG and w >= STRONG_INFO:
                    strong = True
            if not ok:
                break
        if not ok or not touches:
            continue
        if sum(sims) / len(sims) < MERGE_MEAN:
            continue
        hadj = 0.0
        for p, (x, y) in B.items():
            h = hints.get(p)
            if h and h[0] in A:
                bx, by = A[h[0]]
                hadj += HINT_WEIGHT if rel_ok(h[1], h[2], x + off[0] - bx,
                                             y + off[1] - by) else -HINT_WEIGHT
        for p, (x, y) in A.items():
            h = hints.get(p)
            if h and h[0] in B:
                bx, by = B[h[0]]
                hadj += HINT_WEIGHT if rel_ok(h[1], h[2], x - bx - off[0],
                                             y - by - off[1]) else -HINT_WEIGHT
        total = score + touches * TOUCH_BONUS + hadj
        evidence = strong or touches >= MERGE_TOUCHES or (touches >= 2 and hadj > 0)
        results.append((total, off, evidence))
    if not results:
        return None
    results.sort(key=lambda r: (-r[0], r[1]))
    top = results[0]
    if not top[2]:
        return None
    if len(results) > 1 and top[0] - results[1][0] < MERGE_MARGIN:
        return None
    return top[0], top[1]


def merge_blocks(E, hints, units):
    """Repeatedly merge (pos, amb) units that interlock. Modifies list order."""
    merged = True
    while merged:
        merged = False
        best = None
        for i in range(len(units)):
            for j in range(len(units)):
                if i == j or len(units[i][0]) < len(units[j][0]):
                    continue
                if len(units[i][0]) == len(units[j][0]) and i > j:
                    continue
                r = best_merge_offset(E, hints, units[i][0], units[j][0])
                if r and (not best or r[0] > best[0]):
                    best = (r[0], i, j, r[1])
        if best:
            _sc, i, j, (ox, oy) = best
            posA, ambA = units[i]
            posB, ambB = units[j]
            for p, (x, y) in posB.items():
                posA[p] = (x + ox, y + oy)
            for a in ambB:
                a["chosen"] = [a["chosen"][0] + ox, a["chosen"][1] + oy]
                a["alts"] = [[x + ox, y + oy] for x, y in a["alts"]]
            ambA.extend(ambB)
            del units[j]
            merged = True
    return units


def solve_region(region, E):
    """Greedy constraint growth. Returns (blocks, singletons)."""
    remaining = set(E)
    hints = parse_hints(set(E))
    blocks = []
    while True:
        # seed: best pair among remaining. Strong edges qualify; a cardinal
        # name hint at its exact offset with edge-compatible junction also
        # qualifies (uniform borders happen). Hints adjust seed scores so an
        # exact-but-coincidental edge cannot beat the named orientation.
        best = None
        for a in sorted(remaining):
            for b in sorted(remaining):
                if a == b:
                    continue
                for dx, dy in ((1, 0), (0, 1)):
                    s, w = junction(E, a, b, dx, dy)
                    h, ha = hints.get(b), hints.get(a)
                    hinted = (h and h[3] and h[0] == a and (h[1], h[2]) == (dx, dy)) or \
                             (ha and ha[3] and ha[0] == b and (ha[1], ha[2]) == (-dx, -dy))
                    if not ((s >= STRONG_SIM and w >= STRONG_INFO) or
                            (hinted and s >= TOUCH_MIN)):
                        continue
                    sc = s * w
                    if h and h[0] == a:
                        sc += HINT_WEIGHT if rel_ok(h[1], h[2], dx, dy) else -HINT_WEIGHT
                    if ha and ha[0] == b:
                        sc += HINT_WEIGHT if rel_ok(ha[1], ha[2], -dx, -dy) else -HINT_WEIGHT
                    if not best or sc > best[0]:
                        best = (sc, a, b, dx, dy)
        if not best:
            break
        _sc, a, b, dx, dy = best
        pos = {a: (0, 0), b: (dx, dy)}
        byPos = {(0, 0): a, (dx, dy): b}
        remaining -= {a, b}
        ambiguous = []
        while True:
            cands = []
            for p in sorted(remaining):
                tried = set()
                for (px, py) in byPos:
                    for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        t = (px + ddx, py + ddy)
                        if t in byPos or t in tried:
                            continue
                        tried.add(t)
                        sc = evaluate(E, byPos, pos, hints, p, t[0], t[1])
                        if sc is not None:
                            cands.append((sc, p, t))
            if not cands:
                break
            cands.sort(key=lambda c: (-c[0], c[1], c[2]))
            sc, p, t = cands[0]
            alts = [c[2] for c in cands if c[1] == p and c[2] != t
                    and c[0] >= sc - AMBIG_EPS]
            if alts:
                ambiguous.append({"piece": p, "chosen": list(t),
                                  "alts": [list(x) for x in alts]})
            pos[p] = t
            byPos[t] = p
            remaining.discard(p)
        blocks.append((pos, ambiguous))
    # merge pass: interlocking sub-blocks and singletons rejoin their block
    units = blocks + [({p: (0, 0)}, []) for p in sorted(remaining)]
    units = merge_blocks(E, hints, units)
    blocks = [u for u in units if len(u[0]) > 1]
    singles = sorted(p for u in units if len(u[0]) == 1 for p in u[0])
    return blocks, singles


def hint_warnings(pos):
    """Check filename direction suffixes against the solved layout."""
    lower = {p.lower(): p for p in pos}
    warns = []
    for p in pos:
        stem = os.path.splitext(p)[0].lower()
        for suf, (ex, ey) in sorted(DIR_HINTS.items(), key=lambda kv: -len(kv[0])):
            if not stem.endswith(suf) or len(stem) == len(suf):
                continue
            base = lower.get(stem[: -len(suf)] + ".sec")
            if not base:
                break
            bx, by = pos[base]
            px, py = pos[p]
            dx, dy = px - bx, py - by
            bad = (ex and (dx == 0 or (dx > 0) != (ex > 0))) or \
                  (ey and (dy == 0 or (dy > 0) != (ey > 0)))
            if bad:
                warns.append(f"{p} is {suf} of {base} by name but placed at "
                             f"({dx:+d},{dy:+d})")
            break
    return warns


def block_record(region, idx, E, pos, ambiguous):
    xs = [x for x, _ in pos.values()]
    ys = [y for _, y in pos.values()]
    mx, my = min(xs), min(ys)
    pieces = [{"filename": p, "dx": x - mx, "dy": y - my}
              for p, (x, y) in sorted(pos.items())]
    norm = {p["filename"]: (p["dx"], p["dy"]) for p in pieces}
    byPos = {v: k for k, v in norm.items()}
    juncs = []
    for p, (x, y) in norm.items():
        for dx, dy, d in ((1, 0, "E"), (0, 1, "S")):
            n = byPos.get((x + dx, y + dy))
            if n:
                s, w = junction(E, p, n, dx, dy)
                juncs.append({"a": p, "b": n, "dir": d,
                              "sim": round(s, 3), "info": round(w, 3)})
    for a in ambiguous:
        a["chosen"] = [a["chosen"][0] - mx, a["chosen"][1] - my]
        a["alts"] = [[x - mx, y - my] for x, y in a["alts"]]
    return {
        "id": f"{region}#{idx}", "region": region,
        "w": max(xs) - mx + 1, "h": max(ys) - my + 1,
        "pieces": pieces, "junctions": juncs,
        "ambiguous": ambiguous, "warnings": hint_warnings(norm),
    }


def montage(block, size=128):
    img = Image.new("RGB", (block["w"] * size, block["h"] * size), (16, 17, 22))
    draw = ImageDraw.Draw(img)
    for p in block["pieces"]:
        x0, y0 = p["dx"] * size, p["dy"] * size
        src = os.path.join(TILES, p["filename"] + ".png")
        if os.path.exists(src):
            img.paste(Image.open(src).convert("RGB").resize((size, size)), (x0, y0))
        else:
            draw.rectangle([x0, y0, x0 + size, y0 + size], fill=(40, 40, 48))
        draw.rectangle([x0, y0, x0 + size, y0 + 12], fill=(10, 10, 14))
        draw.text((x0 + 3, y0 + 1), p["filename"].replace(".SEC", ""),
                  fill=(230, 230, 240))
    return img


def main():
    os.makedirs(OUT_IMG, exist_ok=True)
    for f in os.listdir(OUT_IMG):          # stale montages from previous runs
        if f.endswith(".png"):
            os.remove(os.path.join(OUT_IMG, f))
    regions = load_regions()
    all_blocks, singles = [], {}
    placed = warn_total = 0
    for region in sorted(regions):
        E = regions[region]
        blocks, lone = solve_region(region, E)
        recs = []
        for i, (pos, amb) in enumerate(blocks, 1):
            rec = block_record(region, i, E, pos, amb)
            recs.append(rec)
            placed += len(rec["pieces"])
            warn_total += len(rec["warnings"])
        if lone:
            singles[region] = lone
        all_blocks += recs
        multi = [r for r in recs if len(r["pieces"]) > 1]
        print(f"{region:28s} pieces={len(E):3d} blocks={len(multi)} "
              f"placed={sum(len(r['pieces']) for r in recs):3d} "
              f"singletons={len(lone):3d} "
              f"warnings={sum(len(r['warnings']) for r in recs)}")
        for r in recs:
            for wmsg in r["warnings"]:
                print(f"    WARN {wmsg}")
    out = {"blocks": all_blocks, "singletons": singles}
    with open(OUT_JSON, "w") as fh:
        json.dump(out, fh, indent=1)
    with open(OUT_JS, "w") as fh:
        fh.write("// Region blocks assembled from edge matches by "
                 "assemble_regions.py. Do not edit by hand.\n")
        fh.write("window.BLOCKS = " + json.dumps(out) + ";\n")
    n_img = 0
    for b in all_blocks:
        if len(b["pieces"]) < 2:
            continue
        safe = b["id"].replace("/", "_").replace("#", "_").replace(" ", "_")
        montage(b).save(os.path.join(OUT_IMG, safe + ".png"))
        n_img += 1
    total = sum(len(e) for e in regions.values())
    lonely = sum(len(v) for v in singles.values())
    print(f"\ntotal pieces {total}: {placed} placed into "
          f"{len([b for b in all_blocks if len(b['pieces'])>1])} multi-piece blocks, "
          f"{lonely} singletons, {warn_total} name-hint warnings")
    print(f"wrote blocks.json, blocks.js, {n_img} montages -> _render/_blocks/")


if __name__ == "__main__":
    main()
