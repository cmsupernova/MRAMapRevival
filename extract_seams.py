"""Precompute .SEC edge seams for the interior/cluster editor's auto-stitch.

The reference SEC_FORMAT.md notes that for the area-named ("chef") interior set,
true neighbours share a content seam (verified on Chef's thfif 2x2):
    west.col[31] == east.col[0]      (right edge of left tile == left edge of right tile)
    north.row[31] == south.row[0]    (bottom edge of upper tile == top edge of lower tile)

So we hash each sector's four playable edges (full 6-byte cells) and emit
_render/seams.js. The cluster editor uses these to suggest which sectors fit
against the open edges of already-placed tiles. An edge is flagged "distinct"
(d=true) only if it carries more than one terrain value or any wall/object, so
all-grass / all-void edges don't produce noise matches.

Edges per file:  l = col 0 · r = col 31 · t = row 0 · b = row 31
Match rule:  X may sit EAST of P if P.r == X.l ; SOUTH of P if P.b == X.t.
"""
import glob
import hashlib
import json
import os

import build_world_coords as B

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_render", "seams.js")
GRID, CELL, PLAY = 33, 6, 32


def cell(d, r, c):
    o = (r * GRID + c) * CELL
    return d[o:o + CELL]


def edge_bytes(d, which):
    if which == "l":
        cells = [cell(d, r, 0) for r in range(PLAY)]
    elif which == "r":
        cells = [cell(d, r, 31) for r in range(PLAY)]
    elif which == "t":
        cells = [cell(d, 0, c) for c in range(PLAY)]
    else:
        cells = [cell(d, 31, c) for c in range(PLAY)]
    return cells


def edge_sig(cells):
    raw = b"".join(bytes(c) for c in cells)
    h = hashlib.md5(raw).hexdigest()[:12]
    terr = {c[0] for c in cells}
    distinct = len(terr) > 1 or any(c[1] or (c[2] | (c[3] << 8)) for c in cells)
    return h, distinct


def main():
    paths = {}
    for root in (B.MAPS_DIR, B.MAPSALL_DIR):
        for p in glob.glob(os.path.join(root, "**", "*.SEC"), recursive=True):
            f = os.path.basename(p)
            if f.startswith("._"):
                continue
            paths.setdefault(f, p)        # first occurrence wins

    seams = {}
    for f, p in sorted(paths.items()):
        d = open(p, "rb").read()
        if len(d) != GRID * GRID * CELL:
            continue
        rec = {}
        for w in ("l", "r", "t", "b"):
            h, dist = edge_sig(edge_bytes(d, w))
            rec[w] = h
            rec[w + "d"] = dist
        seams[f] = rec

    with open(OUT, "w") as fh:
        fh.write("// .SEC edge seam hashes for auto-stitch (extract_seams.py). "
                 "l/r/t/b = edge hash; *d = edge is distinct enough to match on.\n")
        fh.write("window.SEAMS = " + json.dumps(seams) + ";\n")

    dn = sum(1 for r in seams.values() if any(r[k + "d"] for k in "lrtb"))
    print(f"wrote {os.path.basename(OUT)}: {len(seams)} sectors "
          f"({dn} have at least one distinct edge), {os.path.getsize(OUT)//1024} KB")


if __name__ == "__main__":
    main()
