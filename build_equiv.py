"""Find 2011 name-based SECs that are content-equivalent to a 2006 coordinate SEC.

The coordinate SECs (_maps_unzip, ~2006) and the area/name SECs (_mapsall_unzip,
~2011) share no filename convention, so the only way to tell that a named tile is
"the same place" as an already-placed coordinate tile is to compare the actual
cell data. Each SEC is 33x33 cells x 6 bytes (see SEC FILE FORMAT.md):
  byte0 terrain | byte1 object | byte2-3 walls | byte4 west door | byte5 entity

We compare the playable 32x32 region on the layers that define the *shape* of a
sector (terrain + walls), since objects/entities drift between eras. For every
area SEC we keep its best coordinate match if the similarity clears a threshold,
and emit a lookup the world map tool uses to outline already-placed duplicates.

Run:  python build_equiv.py
Output: _render/equiv.js   (window.EQUIV = {areaFile: {coord, sim, terr}})
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MAPS_DIR = os.path.join(HERE, "_maps_unzip")        # 2006 coordinate SECs
MAPSALL_DIR = os.path.join(HERE, "_mapsall_unzip")  # 2011 name-based SECs
OUT = os.path.join(HERE, "_render", "equiv.js")

GRID, CELL, PLAY = 33, 6, 32
N = float(PLAY * PLAY)
# Thresholds. A confident "almost identical" pair must agree on BOTH:
#   - overall: most of the 1024 (terrain,wall) cells line up, and
#   - feat: most of the area tile's distinctive (non-background) cells line up.
# Requiring both rejects the common false positive where two mostly-uniform
# tiles match on background alone (high overall, feat ~ 0).
OVERALL_MIN = 0.70   # fraction of all 1024 (terrain,wall) cells that must match
FEAT_MIN = 0.80      # fraction of the area tile's feature cells that must match
MIN_FEATURES = 30    # ignore near-empty tiles: nothing distinctive to match on


def read_sec(path):
    d = open(path, "rb").read()
    return d if len(d) == GRID * GRID * CELL else None


def signature(data):
    """Returns (shape, feature_idx) for the playable 32x32 area.

    shape[i] = (terrain, walls) where walls = byte2 | byte3<<8.
    feature_idx = cells that carry information: terrain differs from the tile's
    most common terrain (its background), or a wall is present.
    """
    shape = []
    for r in range(PLAY):
        for c in range(PLAY):
            off = (r * GRID + c) * CELL
            t = data[off]
            w = data[off + 2] | (data[off + 3] << 8)
            shape.append((t, w))
    counts = {}
    for t, _w in shape:
        counts[t] = counts.get(t, 0) + 1
    bg = max(counts, key=counts.get)
    feature_idx = [i for i, (t, w) in enumerate(shape) if t != bg or w]
    return shape, feature_idx


def list_secs(root):
    out = {}
    for r, _d, fs in os.walk(root):
        for f in fs:
            if f.upper().endswith(".SEC") and not f.startswith("._"):
                out.setdefault(f, os.path.join(r, f))
    return out


def main():
    coord_sig, area_sig = {}, {}
    for f, p in list_secs(MAPS_DIR).items():
        d = read_sec(p)
        if d:
            coord_sig[f] = signature(d)
    for f, p in list_secs(MAPSALL_DIR).items():
        d = read_sec(p)
        if d:
            area_sig[f] = signature(d)

    equiv = {}
    for af, (ashape, afeat) in area_sig.items():
        if len(afeat) < MIN_FEATURES:
            continue
        nf = float(len(afeat))
        best = None  # (coord, overall, feat)
        for cf, (cshape, _cf) in coord_sig.items():
            feat_match = sum(1 for i in afeat if ashape[i] == cshape[i]) / nf
            if feat_match < FEAT_MIN:
                continue
            overall = sum(1 for a, b in zip(ashape, cshape) if a == b) / N
            if overall < OVERALL_MIN:
                continue
            score = overall + feat_match
            if best is None or score > best[3]:
                best = (cf, overall, feat_match, score)
        if best:
            equiv[af] = {"coord": best[0], "sim": round(best[1], 4), "feat": round(best[2], 4)}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        fh.write("window.EQUIV = " + json.dumps(equiv, sort_keys=True) + ";\n")

    print(f"coordinate SECs: {len(coord_sig)} | area SECs: {len(area_sig)}")
    print(f"equivalent pairs: {len(equiv)} -> {OUT}")
    for af in sorted(equiv):
        e = equiv[af]
        print(f"  {af:28s} ~ {e['coord']:16s} overall={e['sim']:.2f} feat={e['feat']:.2f}")


if __name__ == "__main__":
    main()
