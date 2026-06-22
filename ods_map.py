"""Parse the cartographer's MRA map.ods (tab "50" = complete ground-level world).

The .ods is an OpenDocument spreadsheet (zip of XML); it is already unpacked at
'SEC mapping/SEC mapping/MRA map copy/content.xml'. Each sheet is a
<table:table>; cells repeat via table:number-columns-repeated /
number-rows-repeated. Tab "50" is the authoritative (row=N->S, col=W->E) layout
where each non-empty cell names the area/sector occupying that MP grid position.

Per map_readme.txt: Verbonic = MP505050 (dead center), coords step +5 per sector.
So a cell's (col,row) maps linearly to (MP-X, MP-Y) once we anchor on Verbonic.
"""

import json
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "SEC mapping", "SEC mapping",
                       "MRA map copy", "content.xml")

NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
}
T = f"{{{NS['table']}}}"
TX = f"{{{NS['text']}}}"


def cell_text(cell):
    """Concatenate all text:p content in a table cell."""
    parts = []
    for p in cell.iter(f"{TX}p"):
        parts.append("".join(p.itertext()))
    return " ".join(s for s in parts if s).strip()


def parse_tables():
    """Return OrderedDict {sheet_name: grid} where grid is list of row lists."""
    tree = ET.parse(CONTENT)
    root = tree.getroot()
    tables = {}
    for table in root.iter(f"{T}table"):
        name = table.get(f"{T}name")
        grid = []
        for row in table.findall(f"{T}table-row"):
            rrep = int(row.get(f"{T}number-rows-repeated", "1"))
            cells = []
            for cell in row.findall(f"{T}table-cell") + \
                    row.findall(f"{T}covered-table-cell"):
                crep = int(cell.get(f"{T}number-columns-repeated", "1"))
                txt = cell_text(cell)
                # cap absurd repeats (trailing empty padding)
                crep = min(crep, 4000)
                cells.extend([txt] * crep)
            # trim trailing empties
            while cells and cells[-1] == "":
                cells.pop()
            rrep = min(rrep, 4000)
            for _ in range(rrep):
                grid.append(list(cells))
            # trim trailing empty rows lazily later
        # trim trailing fully-empty rows
        while grid and not any(c for c in grid[-1]):
            grid.pop()
        tables[name] = grid
    return tables


def grid_bounds(grid):
    """Return (n_rows, max_cols, n_nonempty)."""
    nonempty = sum(1 for r in grid for c in r if c)
    maxc = max((len(r) for r in grid), default=0)
    return len(grid), maxc, nonempty


def layout_authoritative():
    """Parse 'Layout' into {(ew, ns): place_name}.

    Column axis = East-West (yy) coord: header row has 10..100 at cols 4..22,
    so ew = 10 + (col-4)*5.  Row axis = North-South (xx) coord: rows 11..25
    label 15..90 in col 25, so ns = 15 + (row-11)*5 (matches the y-code col).
    Data cells live at cols 4..22, rows 11..25.
    """
    grid = parse_tables()["Layout"]
    placed = {}
    for r in range(11, 26):
        if r >= len(grid):
            break
        ns = 15 + (r - 11) * 5
        row = grid[r]
        for c in range(4, 23):
            if c >= len(row):
                continue
            val = row[c].strip()
            if not val:
                continue
            ew = 10 + (c - 4) * 5
            placed[(ew, ns)] = val
    return placed


def current_json_map():
    """Return {(mp_x, mp_y): set(place_names)} from world_map.json."""
    d = json.load(open(WORLD_JSON))
    out = {}
    for v in d["sectors"].values():
        x, y = v.get("mp_x"), v.get("mp_y")
        pn = v.get("place_name") or "-"
        if x is None or y is None:
            continue
        out.setdefault((x, y), set()).add(pn)
    return out


def diff_layout_vs_current():
    auth = layout_authoritative()
    cur = current_json_map()
    cur_keys = set(cur)
    auth_keys = set(auth)
    overlap = sorted(auth_keys & cur_keys, key=lambda k: (k[1], k[0]))
    print("=== MISMATCHES in overlapping EW/NS band (authoritative vs server) ===")
    n = 0
    for k in overlap:
        a = auth[k]
        c = cur[k]
        if a not in c:
            print(f"  EW{k[0]} NS{k[1]}: ods={a!r:30} server={sorted(c)}")
            n += 1
    print(f"  {n} mismatched cells of {len(overlap)} overlapping")
    miss = sorted(auth_keys - cur_keys, key=lambda k: (k[1], k[0]))
    print(f"\n=== in ods Layout but MISSING from server ({len(miss)}) ===")
    for k in miss:
        print(f"  EW{k[0]} NS{k[1]}: {auth[k]}")


WORLD_JSON = os.path.join(HERE, "_winmra_dump", "world_map.json")

# File-prefix cipher (the actual coordinate-named SEC files), EW coord -> prefix.
EW_TO_FILE_PREFIX = {
    45: "BECJ", 50: "CKDP", 55: "DQEV", 60: "EWGB",
    65: "GCHH", 70: "HIIN", 75: "IOX", 80: "YBD",
}
def ns_to_ystart(ns):
    """SEC filename Y-start for a north-south coord. Derived from the .ods
    y-code (515 + ((ns-15)/5)*32) minus the verified 513 file offset."""
    return 2 + ((ns - 15) // 5) * 32


def coordinate_filename(ew, ns, layer="c"):
    """Return the coordinate-named SEC base for a central-band cell, or None."""
    p = EW_TO_FILE_PREFIX.get(ew)
    if p is None:
        return None
    ys = ns_to_ystart(ns)
    return f"{p}{ys}{ys + 31}{layer}"


def export_and_check():
    """Export authoritative layout; check coordinate-file availability for the
    central band against MAPS.zip filenames."""
    auth = layout_authoritative()
    # save full authoritative layout
    out = {f"{ew},{ns}": name for (ew, ns), name in sorted(auth.items())}
    with open(os.path.join(HERE, "world_layout_authoritative.json"), "w") as fh:
        json.dump({
            "_meta": {
                "source": "MRA map.ods 'Layout' sheet (cartographer, ground level)",
                "axes": "key 'EW,NS'; EW=east-west(yy) 10..100, NS=north-south(xx) 15..90, +5/cell",
                "cells": len(out),
            },
            "cells": out,
        }, fh, indent=1)
    print(f"Wrote world_layout_authoritative.json ({len(out)} cells)")

    # central band coordinate-file availability
    maps_dir = os.path.join(HERE, "_maps_unzip")
    have = set()
    for root, _d, files in os.walk(maps_dir):
        for f in files:
            if f.upper().endswith(".SEC"):
                have.add(f[:-4].rstrip("abc") if f[-5] in "abc" else f[:-4])
    # collect real base names (with layer) too
    have_full = set()
    for root, _d, files in os.walk(maps_dir):
        for f in files:
            if f.upper().endswith(".SEC"):
                have_full.add(f[:-4])

    print("\n=== Central band (EW45-80) Layout cells: file availability ===")
    missing_file = []
    placeable = []
    for (ew, ns), name in sorted(auth.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if ew not in EW_TO_FILE_PREFIX:
            continue
        if name in ("Void", "Empty", "River") or name.startswith("River"):
            continue
        base_any = coordinate_filename(ew, ns, "c")
        base_b = coordinate_filename(ew, ns, "b")
        exists = base_any in have_full or base_b in have_full
        if exists:
            placeable.append((ew, ns, name))
        else:
            missing_file.append((ew, ns, name, base_any))
    print(f"placeable (coord file exists): {len(placeable)}")
    print(f"NOT present as coord file: {len(missing_file)}")
    for ew, ns, name, base in missing_file:
        print(f"  EW{ew} NS{ns} {name!r:24} expected {base}.SEC")


if __name__ == "__main__":
    if "--diff" in sys.argv:
        diff_layout_vs_current()
        sys.exit(0)
    if "--check" in sys.argv:
        export_and_check()
        sys.exit(0)
    tables = parse_tables()
    print("Sheets in MRA map.ods:")
    for name, grid in tables.items():
        r, c, ne = grid_bounds(grid)
        print(f"  {name!r}: {r} rows x {c} cols, {ne} non-empty cells")

    if len(sys.argv) > 1:
        target = sys.argv[1]
        grid = tables.get(target)
        if grid is None:
            print(f"\nNo sheet named {target!r}")
            sys.exit(1)
        print(f"\n=== sheet {target!r} non-empty cells (row,col,value) ===")
        for ri, row in enumerate(grid):
            for ci, val in enumerate(row):
                if val:
                    print(f"  r{ri:>3} c{ci:>3}: {val}")
