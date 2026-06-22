"""Suggest MAPSALL area files for each empty named cell in the .ods Layout.

Strategy (no guessing of exact coords - we only NARROW the choice):
  - A cell's .ods name -> a region core + direction tokens
    ("W Salazad" -> core 'salazad', dir {w}; "Mar MAA" -> core 'marmaa').
  - Each MAPSALL file -> region core (digits/direction stripped) + dir tokens.
  - Candidate if the cores match (containment or >=4-char shared prefix);
    rank by direction-token overlap, then closeness of core length.
This turns "hunt through 367 files" into "confirm 1-of-a-few" in the tool.

Output: _render/suggestions.js  (window.SUGGESTIONS = {"ew,ns":[cands...]})
Console: coverage report (cells with/without candidates).
"""
import json, os, re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT = os.path.join(HERE, "world_layout_authoritative.json")
COORDS = os.path.join(HERE, "world_map_coords.json")
MAPSALL_DIR = os.path.join(HERE, "_mapsall_unzip")
OUT = os.path.join(HERE, "_render", "suggestions.js")

DIRS = ["northeast", "northwest", "southeast", "southwest",
        "north", "south", "east", "west",
        "ne", "nw", "se", "sw", "n", "s", "e", "w",
        "middle", "mid", "far", "center", "central", "top"]
DIRSET = set(DIRS)
FILLER = {"of", "the", "mtn", "village", "caves", "cave", "fortress",
          "tower", "pub", "arena", "training", "guild", "guildhalls",
          "castle", "college"}
# region-word aliases: .ods word -> MAPSALL base keyword
ALIAS = {"goblin": "gob", "castle": "krell", "perdition": "per",
         "maranda": "mar", "salazad": "sal", "green": "greenwood",
         "greenwood": "greenwood", "dunsmore": "dunsmor"}


def collapse(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse_name(name):
    """-> (region_core, dir_tokens, raw_extra_tokens)."""
    toks = [t for t in re.split(r"[\s/+]+", name.lower()) if t]
    region, dirs = [], set()
    for t in toks:
        tc = re.sub(r"[^a-z0-9]", "", t)
        # split a token like '1n' into number + dir
        m = re.match(r"^(\d+)?([a-z]*)$", tc)
        num, word = (m.group(1), m.group(2)) if m else (None, tc)
        if word in DIRSET:
            dirs.add(word)
            continue
        if word in FILLER or word == "":
            continue
        region.append(ALIAS.get(word, word))
    return collapse("".join(region)), dirs


def parse_file(fn):
    base = fn[:-4].lower()
    c = collapse(base)
    dirs = set()
    # peel trailing direction words
    changed = True
    core = c
    while changed:
        changed = False
        for d in DIRS:
            if core.endswith(d) and len(core) - len(d) >= 3:
                dirs.add(d)
                core = core[:-len(d)]
                changed = True
                break
    core = re.sub(r"\d+$", "", core)  # strip trailing number
    return core, dirs


def region_match(ods_core, fcore):
    if not ods_core or not fcore:
        return 0
    if ods_core == fcore:
        return 100
    if ods_core in fcore or fcore in ods_core:
        return 60 + min(len(ods_core), len(fcore))
    # shared prefix
    n = 0
    for a, b in zip(ods_core, fcore):
        if a != b:
            break
        n += 1
    return n if n >= 4 else 0


def main():
    layout = {tuple(int(x) for x in k.split(",")): v
              for k, v in json.load(open(LAYOUT))["cells"].items()}
    placed = {(s["mp_x"], s["mp_y"]) for s in
              json.load(open(COORDS))["sectors"].values()}

    files = []
    for r, _d, fs in os.walk(MAPSALL_DIR):
        for f in sorted(fs):
            if f.upper().endswith(".SEC") and not f.startswith("._"):
                core, dirs = parse_file(f)
                files.append((f, core, dirs))

    suggestions = {}
    matched = unmatched = 0
    report = []
    for (ew, ns), name in sorted(layout.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if name in ("Void", "Empty") or name.startswith("River"):
            continue
        if (ew, ns) in placed:
            continue
        ods_core, ods_dirs = parse_name(name)
        scored = []
        for fn, fcore, fdirs in files:
            rm = region_match(ods_core, fcore)
            if rm <= 0:
                continue
            dscore = len(ods_dirs & fdirs) * 10
            if ods_dirs and ods_dirs == fdirs:
                dscore += 15
            scored.append((rm + dscore, fn))
        scored.sort(key=lambda x: (-x[0], x[1]))
        cands = [{"filename": fn, "png": f"tiles/{fn}.png", "score": sc}
                 for sc, fn in scored[:10]]
        key = f"{ew},{ns}"
        suggestions[key] = {"place_name": name, "candidates": cands}
        if cands:
            matched += 1
        else:
            unmatched += 1
        report.append((ew, ns, name, [c["filename"] for c in cands[:5]]))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        fh.write("window.SUGGESTIONS = " + json.dumps(suggestions) + ";\n")

    print(f"empty named cells: {matched + unmatched}")
    print(f"  with candidates:  {matched}")
    print(f"  no match (manual):{unmatched}")
    print(f"-> {os.path.relpath(OUT, HERE)}\n")
    print("=== per-cell suggestions ===")
    for ew, ns, name, cands in report:
        c = ", ".join(cands) if cands else "(NO MATCH - manual)"
        print(f"  EW{ew:>3} NS{ns:>3}  {name:22} -> {c}")


if __name__ == "__main__":
    main()
