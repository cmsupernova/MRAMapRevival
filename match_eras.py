"""Match each 2006 coordinate SEC to its closest 2011 name-based SEC.

The 2006 set is incomplete; the 2011 set is larger and newer. Each coordinate
SEC carries a place_name (e.g. EWGB194225b = "W Haven"), so instead of comparing
every tile to every tile (noisy), we scope the comparison to the region implied
by that place_name (the haven* files) and pick the closest.

Cross-era tiles are redrawn, not byte-copied, so an exact cell compare fails. We
score with a small offset search (+/-3 cells) on (terrain, wall) per cell, which
tolerates the shift while still ranking the true counterpart far above the rest
(e.g. W Haven -> haven1 at 0.85 vs 0.17 for the next best).

Run:  python match_eras.py
Output: _render/era_map.js  (window.ERA_MAP = {coordFile: {area, score, next, ok}})
"""
import json
import os

import build_equiv as E

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "_render", "manifest.json")
OUT = os.path.join(HERE, "_render", "era_map.js")

GRID, CELL, PLAY = E.GRID, E.CELL, E.PLAY
OFFSET = 3            # search +/- this many cells in x and y
SCORE_MIN = 0.40     # below this, no confident counterpart
SEP_GAP = 0.12       # best must beat runner-up by this absolute gap to be "ok".
# An absolute gap (not a ratio) is used so near-uniform tiles - which match many
# same-region tiles at ~1.0 - are rejected for being ambiguous, while genuinely
# distinctive tiles (a town with buildings) clear it easily.

# place_name tokens that carry no region meaning
STOP = {"of", "the", "n", "s", "e", "w", "ne", "nw", "se", "sw", "north",
        "south", "east", "west", "upper", "lower", "training", "arena",
        "village", "tower", "castle", "pub", "cave", "caves", "tunnel",
        "mtn", "guild", "guildhalls", "docks", "hall", "halls"}


def grid_of(data):
    g = [[None] * PLAY for _ in range(PLAY)]
    for r in range(PLAY):
        for c in range(PLAY):
            o = (r * GRID + c) * CELL
            g[r][c] = (data[o], data[o + 2] | (data[o + 3] << 8))
    return g


def best_overlap(ga, gb):
    best = 0.0
    for dy in range(-OFFSET, OFFSET + 1):
        for dx in range(-OFFSET, OFFSET + 1):
            match = total = 0
            for r in range(PLAY):
                rr = r + dy
                if rr < 0 or rr >= PLAY:
                    continue
                row_a, row_b = ga[r], gb[rr]
                for c in range(PLAY):
                    cc = c + dx
                    if 0 <= cc < PLAY:
                        total += 1
                        if row_a[c] == row_b[cc]:
                            match += 1
            if total:
                best = max(best, match / total)
    return best


def tokens(place_name):
    out = []
    cur = ""
    for ch in place_name.lower():
        if ch.isalpha():
            cur += ch
        else:
            if cur:
                out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return [t for t in out if len(t) >= 3 and t not in STOP]


def region_match(tok, regionkey):
    """True if a place_name token and an area region share a 3+ char prefix."""
    if not regionkey:
        return False
    return tok.startswith(regionkey[:3]) or regionkey.startswith(tok[:3])


def main():
    man = json.load(open(MANIFEST))
    # locate every SEC file on disk
    paths = {}
    for root in (E.MAPS_DIR, E.MAPSALL_DIR):
        for r, _d, fs in os.walk(root):
            for f in fs:
                if f.upper().endswith(".SEC") and not f.startswith("._"):
                    paths.setdefault(f, os.path.join(r, f))

    # area files grouped by region key (folder name lowercased)
    area = []
    for t in man["area"]:
        reg = (t.get("region") or "").lower()
        key = reg if reg not in ("mapsall", "?", "") else \
            "".join(ch for ch in t["filename"].lower() if ch.isalpha())[:6]
        area.append((t["filename"], key, t["png"]))

    grids = {}

    def get_grid(fn):
        if fn not in grids:
            d = E.read_sec(paths[fn]) if fn in paths else None
            grids[fn] = grid_of(d) if d else None
        return grids[fn]

    era = {}
    for t in man["coordinate"]:
        cf, pn = t["filename"], t.get("place_name")
        if not pn or cf not in paths:
            continue
        toks = tokens(pn)
        if not toks:
            continue
        cands = [(af, png) for (af, key, png) in area
                 if any(region_match(tok, key) for tok in toks)]
        if not cands:
            continue
        cg = get_grid(cf)
        if cg is None:
            continue
        scored = []
        for af, png in cands:
            ag = get_grid(af)
            if ag is not None:
                scored.append((best_overlap(cg, ag), af, png))
        if not scored:
            continue
        scored.sort(reverse=True)
        best_s, best_f, best_png = scored[0]
        nxt = scored[1][0] if len(scored) > 1 else 0.0
        ok = best_s >= SCORE_MIN and (best_s - nxt) >= SEP_GAP
        era[cf] = {"area": best_f, "png": best_png, "place": pn,
                   "score": round(best_s, 3), "next": round(nxt, 3), "ok": ok}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        fh.write("window.ERA_MAP = " + json.dumps(era, sort_keys=True) + ";\n")

    okc = sum(1 for v in era.values() if v["ok"])
    print(f"coordinate tiles matched: {len(era)} ({okc} confident) -> {OUT}")
    for cf in sorted(era, key=lambda k: (not era[k]["ok"], -era[k]["score"])):
        v = era[cf]
        flag = "OK " if v["ok"] else "  ?"
        print(f"  {flag} {cf:16s} {v['place']:18s} -> {v['area']:22s} {v['score']:.2f} (next {v['next']:.2f})")


if __name__ == "__main__":
    main()
