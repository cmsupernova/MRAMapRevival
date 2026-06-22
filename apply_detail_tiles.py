"""Swap the schematic SEC tiles for the detailed BYOND/chef PNG renders.

The `contents/` folder holds 256x256 tileset-accurate renders named by SEC
basename (e.g. aph1.png, BECJ226257b.png). Our interactive tool already keys
every tile by SEC filename via `_render/manifest.json` / `data.js`, so we can
drop these in for display without touching any coordinate / placement logic.

This copies the best-matching detailed PNG over each `_render/tiles/<name>.png`.
Tiles with no detailed render keep their schematic image (from sec_render.py).

Run:  python apply_detail_tiles.py            # apply
      python apply_detail_tiles.py --audit    # report only, no changes
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENTS = os.path.join(HERE, "contents")
TILES = os.path.join(HERE, "_render", "tiles")
MANIFEST = os.path.join(HERE, "_render", "manifest.json")

# folder priority when the same basename appears in multiple places
PRIORITY = ["coordinate", "chef", "chef-by-area", "chef-copies"]


def index_detailed():
    """basename(lower, no ext) -> absolute png path, honoring PRIORITY."""
    found = {}
    rank = {}
    for root, _dirs, files in os.walk(CONTENTS):
        top = os.path.relpath(root, CONTENTS).split(os.sep)[0]
        pr = PRIORITY.index(top) if top in PRIORITY else len(PRIORITY)
        for f in files:
            if not f.lower().endswith(".png"):
                continue
            key = os.path.splitext(f)[0].lower()
            if key not in found or pr < rank[key]:
                found[key] = os.path.join(root, f)
                rank[key] = pr
    return found


def main(audit=False):
    manifest = json.load(open(MANIFEST))
    detailed = index_detailed()
    tiles = manifest.get("coordinate", []) + manifest.get("area", [])
    matched, missing, applied = [], [], 0
    for t in tiles:
        base = os.path.splitext(t["filename"])[0].lower()  # "aph1.SEC" -> "aph1"
        src = detailed.get(base)
        if src:
            matched.append(t["filename"])
            if not audit:
                dst = os.path.join(HERE, "_render", t["png"].replace("/", os.sep))
                shutil.copyfile(src, dst)
                applied += 1
        else:
            missing.append(t["filename"])
    print(f"detailed PNGs indexed : {len(detailed)}")
    print(f"tiles in manifest     : {len(tiles)}")
    print(f"matched (detailed)    : {len(matched)}")
    print(f"no detailed render    : {len(missing)}")
    if missing:
        print("  missing -> keeping schematic:")
        for m in sorted(missing):
            print("   ", m)
    if not audit:
        print(f"copied {applied} detailed tiles into _render/tiles/")
    else:
        print("(audit only, nothing written)")


if __name__ == "__main__":
    main(audit="--audit" in sys.argv)
