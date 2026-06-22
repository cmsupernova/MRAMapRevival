"""Build a coordinate-driven world_map.json straight from the SEC filenames.

NO CSV. Every placement comes from the filename, which is binary-grounded:
  - prefix    -> East-West block + MP-X   (BECJ=0/45 .. YBD=7/80)
  - Y-range   -> North-South block + MP-Y (y_block=(Ystart-2)//32, MP-Y=15+y_block*5? see below)
  - layer a/b/c -> altitude

Place names are attached from the VERIFIED .ods 'Layout' sheet
(world_layout_authoritative.json), which independently agrees with MAPS.TXT
(7/7 core adjacencies) and with the on-disk SEC files (69/69 named cells).

Output: world_map_coords.json  (drop-in replacement for review; same schema the
server's mra_stub.py WorldMap consumes: sectors / block_to_base / y_axis_ranges).
Also prints a holes report: Layout-named cells with no SEC file + MAPSALL
candidates that could fill them.
"""
import json
import os
import re
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
MAPS_DIR = os.path.join(HERE, "_maps_unzip")
MAPSALL_DIR = os.path.join(HERE, "_mapsall_unzip")
LAYOUT = os.path.join(HERE, "world_layout_authoritative.json")
TEMPLATE = os.path.join(HERE, "_winmra_dump", "world_map.json")
OUT = os.path.join(HERE, "world_map_coords.json")

PREFIX_TO_XBLOCK = {"BECJ": 0, "CKDP": 1, "DQEV": 2, "EWGB": 3,
                    "GCHH": 4, "HIIN": 5, "IOX": 6, "YBD": 7}
PREFIX_TO_MPX = {"BECJ": 45, "CKDP": 50, "DQEV": 55, "EWGB": 60,
                 "GCHH": 65, "HIIN": 70, "IOX": 75, "YBD": 80}
LAYER_TO_MPZ = {"a": 45, "b": 50, "c": 55}
# Layer is optional in some filenames (ground sector stored without a/b/c).
FNAME_RE = re.compile(r"^([A-Z]{2,5})(\d+)([abc])?\.SEC$", re.I)
# Known Y-range typos (from friend's verified sec_list cross-check): the digit
# run violates Yend=Ystart+31; map to the corrected digit run.
YRANGE_TYPOS = {"257289": "258289", "354389": "354385"}
DEFAULT_LAYER = "c"  # unlayered files are the ground sector; slot them at 'c'


def split_yrange(digits):
    for s in range(1, len(digits)):
        a, b = digits[:s], digits[s:]
        if len(a) > 1 and a[0] == "0":
            continue
        if len(b) > 1 and b[0] == "0":
            continue
        if int(b) == int(a) + 31:
            return int(a), int(b)
    return None


def y_block_of(ystart):
    return (ystart - 2) // 32


def mp_y_of(ystart):
    # .ods: ycode = Ystart + 513; MP-Y = 15 + (ycode-515)/32*5 = 15 + (Ystart-2)/32*5
    return 15 + ((ystart - 2) // 32) * 5


def load_layout():
    cells = json.load(open(LAYOUT))["cells"]
    return {tuple(int(x) for x in k.split(",")): v for k, v in cells.items()}


def list_sec(dirpath):
    out = []
    for r, _d, fs in os.walk(dirpath):
        for f in fs:
            if f.upper().endswith(".SEC"):
                out.append(f)
    return out


def build():
    layout = load_layout()
    template = json.load(open(TEMPLATE))

    sectors = OrderedDict()
    block_to_base = OrderedDict()
    unmapped = []
    max_yblock = 0

    all_files = [f for f in sorted(list_sec(MAPS_DIR)) if not f.startswith("._")]
    # Pre-pass: which (prefix, ystart) already have an explicit-layer file?
    explicit_layered = set()
    for fname in all_files:
        m = FNAME_RE.match(fname)
        if not m or not m.group(3):
            continue
        digits = YRANGE_TYPOS.get(m.group(2), m.group(2))
        yr = split_yrange(digits)
        if yr:
            explicit_layered.add((m.group(1).upper(), yr[0]))

    for fname in all_files:
        m = FNAME_RE.match(fname)
        if not m:
            unmapped.append({"filename": fname,
                             "reason": "non-standard filename (area-named, not coordinate)"})
            continue
        prefix, digits, layer = m.group(1).upper(), m.group(2), \
            (m.group(3) or "").lower()
        if prefix not in PREFIX_TO_XBLOCK:
            unmapped.append({"filename": fname,
                             "reason": f"unknown prefix {prefix} (not in EW cipher; "
                                       "likely typo, NOT auto-placed)"})
            continue
        digits = YRANGE_TYPOS.get(digits, digits)
        yr = split_yrange(digits)
        if yr is None:
            unmapped.append({"filename": fname,
                             "reason": f"Y-range not splittable: {digits}"})
            continue
        ystart, yend = yr
        base = fname[:-4]
        if not layer:
            if (prefix, ystart) in explicit_layered:
                unmapped.append({"filename": fname,
                                 "reason": "unlayered duplicate of an explicit-layer "
                                           "sector at the same cell"})
                continue
            layer = DEFAULT_LAYER
        x_block = PREFIX_TO_XBLOCK[prefix]
        y_block = y_block_of(ystart)
        max_yblock = max(max_yblock, y_block)
        mp_x = PREFIX_TO_MPX[prefix]
        mp_y = mp_y_of(ystart)
        name = layout.get((mp_x, mp_y))
        is_real = bool(name) and name not in ("Void", "Empty") \
            and not name.startswith("River")
        sectors[base] = OrderedDict([
            ("filename", fname),
            ("prefix", prefix),
            ("y_start", ystart),
            ("y_end", yend),
            ("layer", layer),
            ("x_block", x_block),
            ("y_block", y_block),
            ("mp_x", mp_x),
            ("mp_y", mp_y),
            ("mp_z", LAYER_TO_MPZ.get(layer)),
            ("place_name", name),
            ("status", "mapped" if is_real else None),
            ("provenance", "coordinate-driven: position from filename "
                           "(binary-grounded); name from .ods Layout"),
        ])
        block_to_base[f"{x_block},{y_block},{layer}"] = base

    y_axis_ranges = [[2 + 32 * i, 33 + 32 * i] for i in range(max_yblock + 1)]

    out = OrderedDict()
    out["_meta"] = OrderedDict([
        ("title", "MRA world map (coordinate-driven, CSV-free)"),
        ("provenance",
         "Placement derived ENTIRELY from SEC filenames (binary-grounded: "
         "prefix->EW, Y-range->NS, Yend=Ystart+31, 32x32 playable). The "
         "community CSV is NOT used. place_name/status carried from the .ods "
         "'Layout' sheet, which cross-checks 7/7 vs MAPS.TXT and 69/69 vs the "
         "on-disk SEC files."),
        ("binary_grounded_facts", template["_meta"].get("binary_grounded_facts")),
        ("stats", OrderedDict([
            ("sectors_placed", len(sectors)),
            ("block_to_base_entries", len(block_to_base)),
            ("y_axis_ranges", len(y_axis_ranges)),
            ("unmapped", len(unmapped)),
        ])),
    ])
    out["coordinate_system"] = template["coordinate_system"]
    out["status_legend"] = template["status_legend"]
    out["y_axis_ranges"] = y_axis_ranges
    out["sectors"] = sectors
    out["block_to_base"] = block_to_base
    out["unmapped"] = unmapped

    # ---- holes report ----
    mapsall = [f for f in list_sec(MAPSALL_DIR) if not f.startswith("._")]
    holes = []
    coord_ew = set(PREFIX_TO_MPX.values())
    placed_cells = {(s["mp_x"], s["mp_y"]) for s in sectors.values()}
    for (ew, ns), name in sorted(layout.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if ew not in coord_ew:
            continue  # outside coordinate band; needs MAPSALL anyway
        if name in ("Void", "Empty") or name.startswith("River"):
            continue
        if (ew, ns) in placed_cells:
            continue
        # candidate MAPSALL files by keyword
        kw = re.sub(r"[^a-z0-9]", "", name.lower())[:5]
        cands = [f for f in mapsall
                 if kw and kw[:4] in f.lower().replace("_", "")]
        holes.append(OrderedDict([
            ("mp_x", ew), ("mp_y", ns), ("place_name", name),
            ("expected_coord_file",
             f"{[p for p,x in PREFIX_TO_MPX.items() if x==ew][0]}"
             f"{2+((ns-15)//5)*32}{2+((ns-15)//5)*32+31}c.SEC"),
            ("mapsall_candidates", cands[:6]),
        ]))
    out["holes"] = holes

    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1)
    return out


def verify(out):
    """Engine-consistency + .ods agreement checks."""
    layout = load_layout()
    sectors = out["sectors"]
    b2b = out["block_to_base"]
    yr = out["y_axis_ranges"]
    errs = []
    # 1. block_to_base <-> sectors consistency
    for key, base in b2b.items():
        if base not in sectors:
            errs.append(f"block_to_base {key} -> missing sector {base}")
    for base, s in sectors.items():
        k = f"{s['x_block']},{s['y_block']},{s['layer']}"
        if k not in b2b:
            errs.append(f"sector {base} has no block_to_base entry {k}")
        if not (0 <= s["y_block"] < len(yr)):
            errs.append(f"sector {base} y_block {s['y_block']} out of y_axis_ranges")
    # 2. placement matches .ods Layout (name at mp_x,mp_y)
    mism = 0
    for base, s in sectors.items():
        exp = layout.get((s["mp_x"], s["mp_y"]))
        if exp is not None and s["place_name"] != exp:
            mism += 1
            errs.append(f"{base}: name {s['place_name']!r} != ods {exp!r}")
    print("\n=== VERIFY ===")
    print(f"  engine-consistency errors: "
          f"{sum(1 for e in errs if 'block_to_base' in e or 'y_block' in e)}")
    print(f"  .ods placement mismatches: {mism}")
    if errs:
        for e in errs[:20]:
            print("   ", e)
    else:
        print("  ALL CHECKS PASS")
    # 3. confirm the recovered cells
    for name in ("Last Chance Pub",):
        hit = [b for b, s in sectors.items() if s["place_name"] == name]
        print(f"  '{name}' placed as: {hit}")


if __name__ == "__main__":
    out = build()
    s = out["_meta"]["stats"]
    print(f"Wrote {os.path.basename(OUT)}")
    print(f"  sectors placed:  {s['sectors_placed']}")
    print(f"  y_axis_ranges:   {s['y_axis_ranges']}")
    print(f"  unmapped files:  {s['unmapped']}")
    for u in out["unmapped"]:
        print(f"    - {u['filename']}: {u['reason']}")
    print(f"\n  holes (named central cell, no SEC file): {len(out['holes'])}")
    for h in out["holes"]:
        c = ", ".join(h["mapsall_candidates"]) or "(no obvious MAPSALL match)"
        print(f"    EW{h['mp_x']} NS{h['mp_y']} {h['place_name']!r}: candidates -> {c}")
    verify(out)
