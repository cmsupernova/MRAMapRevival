"""Cross-verify every MRA map source against the others, so we trust nothing
on faith. Sources:
  A. _winmra_dump/world_map.json   (running server build, from CSV)
  B. world_map(new).json           (friend's newest build)
  C. world_layout_authoritative.json (extracted from MRA map.ods 'Layout')
  D. _maps_unzip/*.SEC             (coordinate-named files actually present)
  E. MAPS.TXT                      (original game adjacency)
Checks:
  1. A vs B   - is the "new" json actually different?
  2. C vs D   - does the .ods Layout agree with which coordinate SEC files
                actually exist (and do Void cells correctly have no file)?
  3. C self   - sanity of the central band adjacency the friend flagged.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def load(p):
    with open(os.path.join(HERE, p)) as fh:
        return json.load(fh)


EW_TO_FILE_PREFIX = {45: "BECJ", 50: "CKDP", 55: "DQEV", 60: "EWGB",
                     65: "GCHH", 70: "HIIN", 75: "IOX", 80: "YBD"}


def ns_to_ystart(ns):
    return 2 + ((ns - 15) // 5) * 32


def sectors_of(world):
    """Return {base: (mp_x, mp_y, layer, place)} from a world_map.json."""
    out = {}
    for base, v in world["sectors"].items():
        out[base] = (v.get("mp_x"), v.get("mp_y"), v.get("layer"),
                     v.get("place_name"))
    return out


def check_AB():
    a = sectors_of(load("_winmra_dump/world_map.json"))
    b = sectors_of(load("world_map(new).json"))
    print("=== CHECK 1: running server json  vs  world_map(new).json ===")
    if a == b:
        print("  IDENTICAL sector tables (the 'new' file is the same build).")
        return
    only_a = set(a) - set(b)
    only_b = set(b) - set(a)
    changed = [k for k in set(a) & set(b) if a[k] != b[k]]
    print(f"  only in server: {len(only_a)}  only in new: {len(only_b)}  "
          f"changed: {len(changed)}")
    for k in list(only_b)[:20]:
        print(f"    NEW adds {k}: {b[k]}")
    for k in changed[:20]:
        print(f"    CHANGED {k}: server={a[k]} new={b[k]}")


def collect_present_secs():
    have = set()
    for root, _d, files in os.walk(os.path.join(HERE, "_maps_unzip")):
        for f in files:
            if f.upper().endswith(".SEC"):
                have.add(f[:-4])
    return have


def check_CD():
    print("\n=== CHECK 2: .ods Layout  vs  coordinate SEC files present ===")
    layout = load("world_layout_authoritative.json")["cells"]
    have = collect_present_secs()
    # only test central band (where coord files can exist)
    void_with_file = []
    named_no_file = []
    named_with_file = 0
    for key, name in layout.items():
        ew, ns = (int(x) for x in key.split(","))
        if ew not in EW_TO_FILE_PREFIX:
            continue
        ys = ns_to_ystart(ns)
        p = EW_TO_FILE_PREFIX[ew]
        cands = [f"{p}{ys}{ys+31}{lyr}" for lyr in ("a", "b", "c")]
        has = any(c in have for c in cands)
        is_void = name in ("Void", "Empty") or name.startswith("River")
        if is_void and has:
            void_with_file.append((ew, ns, name))
        elif not is_void and has:
            named_with_file += 1
        elif not is_void and not has:
            named_no_file.append((ew, ns, name))
    print(f"  named cells WITH a coord file (consistent): {named_with_file}")
    print(f"  VOID/empty cells that unexpectedly HAVE a file: {len(void_with_file)}")
    for ew, ns, n in void_with_file:
        print(f"    EW{ew} NS{ns} {n}")
    print(f"  named cells with NO coord file (real holes): {len(named_no_file)}")
    for ew, ns, n in named_no_file:
        print(f"    EW{ew} NS{ns} {n!r}")


def check_C_core():
    print("\n=== CHECK 3: .ods Layout core adjacency vs MAPS.TXT expectation ===")
    layout = load("world_layout_authoritative.json")["cells"]
    # MAPS.TXT 'areas around haven' expected neighbors (coarse):
    # GOBS west of UNDV; KOBS south of UNDV; Haven south of the Sanctuary col;
    # Verbonic south-west; Uswick NE.
    def at(ew, ns):
        return layout.get(f"{ew},{ns}", "(empty)")
    checks = [
        ("Undead Village @ EW55/NS40", at(55, 40), "Undead Village"),
        ("west of UNDV (EW50/NS40)", at(50, 40), "Goblin Cave 1S"),
        ("south of UNDV (EW55/NS45)", at(55, 45), "KOKAS + KOFOR"),
        ("Sanctuary @ EW65/NS40", at(65, 40), "Sanctuary"),
        ("Haven core @ EW60/NS45", at(60, 45), "W Haven"),
        ("Verbonic @ EW50/NS50", at(50, 50), "Verbonic"),
        ("Uswick @ EW70/NS30", at(70, 30), "Uswick"),
    ]
    for label, got, expect in checks:
        ok = "OK " if got == expect else "?? "
        print(f"  {ok}{label}: ods={got!r} (MAPS.TXT-consistent={expect!r})")


if __name__ == "__main__":
    check_AB()
    check_CD()
    check_C_core()
