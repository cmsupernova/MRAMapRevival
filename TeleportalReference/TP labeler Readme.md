# Teleportal Labeler

A tool to match every **blue teleportal** tile in the `MAPS/*.SEC` corpus to its
teleportal **name**, writing bindings into `mra_teleportal_registry.json`.

Two front-ends, same data + rendering:

1. **Local (server)** — for your own labeling, saves straight to the registry:
   ```
   python3 "teleportal labeler/teleportal_labeler_server.py"   # → http://localhost:8793
   ```
   (or `preview_start` the `teleportal-labeler` config in `.claude/launch.json`.)

2. **Portable (one file, offline)** — to hand out to players. No server, no Python.
   Build it, then send `teleportal_labeler_portable.html` (~4.4 MB) to anyone:
   ```
   python3 "teleportal labeler/build_portable.py"
   ```
   Players open it (double-click), label teleportals, click **Export labels** to
   download a small JSON, and send it back. Fold their work in with:
   ```
   python3 "teleportal labeler/merge_exports.py" their_export.json [more…] [--dry-run]
   ```
   Add `--no-seeds` to `build_portable.py` for a **blank** portable (no pre-loaded pins —
   players label from scratch; the registry's verified pins stay untouched on disk).
   Add `--with-worldmap` for a **trusted-audience** build that embeds the clickable
   world-map overview (the `🗺 world map` button — same block-position browser as the local
   editor). This embeds the `world_map.json` block layout, so use it ONLY for trusted
   recipients (LORs); the default build omits it and stays layout-free. Even the
   `--with-worldmap` build still strips absolute world coords and travelLinks.

   Re-using a name that's already on another tile does **not** block — the corpus has
   redundant map copies where the same teleportal recurs, so the tool assigns it and just
   warns (`… also on X — only one survives merge`); `merge_exports` reconciles at merge.
   `merge_exports` preserves existing pins verbatim, recomputes world coords, stamps
   each binding `DERIVED` with the labeler's handle, and **refuses to overwrite** a
   name/cell already bound (reports it as a conflict instead). Re-run
   `build_portable.py` after a merge to refresh the seeded pins players see.

   **Privacy — the portable leaks NO world layout.** `build_portable.py` strips every
   `world_map.json`-derived field (absolute world coords, `x_block`/`y_block`, sector
   `origin`, `placed`/`layer`, travelLinks), the seed entries' `_evidence` prose (which
   cites `world(…)` coords), and all mined-guide source citations (`reference/…` paths,
   wiki URLs). Sectors embed only `base` + `nblue`/`n` + filename `suggest` + `tps`
   `{x,y,subtype}` + the isolated sector art. Player exports carry only
   `name/subtype/sector_base/col,row` — no coordinates. World coords exist ONLY
   project-side, recomputed by `merge_exports.py` from the local `world_map.json`.
   The generator self-audits; verify anytime with a token scan of the output HTML.

   **Only the SECs used in `world_map.json` are detected** (directed 2026-07-20, on the new
   world_map + MAPS). That's **181 teleportal-bearing sectors (301 blue)** — the redundant
   archive/spawn/walk copies in `MAPS/` simply aren't referenced by the assembled world, so
   the duplication is gone at the source. Registry pins on an out-of-world sector (e.g. the
   old `HAV_BANK`→`haven1_spawn`) are **never dropped** — `registry_labels()` loads the whole
   registry so a hidden pin survives every save; it just isn't shown until re-pinned in-world.
   Any duplicates that remain *within* the world (`orclord`/`orclordwalk`) are still surfaced
   with the per-sector `siblings` map: **variant** (name-prefix + cells differ ≤50/1024 → same
   place → a label is inherited as `≈NAME via <twin>`) and **identical** (byte-identical md5 →
   info note only, never inherited, since `persw`=PER_SW vs `prg1b`=PRG_1B reuse one template).

   **World-map overview (local editor only).** The interactive tool has a **🗺 world map**
   button that opens a clickable grid of every sector positioned by its `world_map.json`
   block coords (layer a/b/c toggle; blue = has teleportals to label, green = all named, gray
   = none, white = current) — so you browse by spatial layout / adjacency instead of guessing
   the next area in the dropdown. Served from a **local-only** `/api/worldmap` endpoint and
   **never embedded in the portable** — the distributable stays layout-free per the privacy
   rule (a positional map *is* the world layout).

   **Location guidance.** Each teleportal shows mined **location evidence** (📍) for its
   candidate names — `USWICK → Town of Uswick [VERIFIED·area]`, `DZ1_C → Dhaza 1 [VERIFIED]` —
   from `reference/dumps/teleportal_location_evidence.json` (an 8-agent corpus sweep of
   `rqn.txt`, fan-site maps, wiki travel/place pages, and docs; 210 of 353 names have
   evidence). It is **area-level, not a tile binding** — no surviving source gives `(x,y)`; see
   that file's `derivability` verdict. In the portable the evidence `source` paths are stripped.

## What it does

The `.SEC` cell *object* byte (byte-1) encodes a teleportal family — VERIFIED
`FUN_00407a34`, GT §13b:

| byte | family | marker |
|------|--------|--------|
| 1 | Teleportal (**blue / public**) | blue ring |
| 2 | Room (green, owner-only) | green ring |
| 3 | Instant | purple ring |
| 4 | Invisible | dashed gray ring |

The tool scans all 498 `.SEC` files (→ **542** teleportal cells, **459** blue),
renders each sector with the **real client graphics** — terrain from
`ognall/TERRAIN.256` (`mra_atlas256`) plus the real object sprites from
`ognall/OBJ.256` (`mra_obj256`): the blue/green/red **teleportal portals**
themselves, furniture, trees, flowers, gravestones. Over that it draws a thin
locate-ring per teleportal, and lets you assign a name from the
**VERIFIED-OBSERVED vocabulary** (`reference/dumps/teleporter_names.json`, 353
live-server names) plus any mined extra candidates. Walls stay as clean lines
(the game draws them as pseudo-3D left/right-leaning parts that don't map to a
top-down grid). Both atlases fall back gracefully if `ognall/*.256` is absent.

- **?** = unlabeled · **◆** = labeled · **🔒** = a walk-recorded VERIFIED binding.
- Filename **suggestions** are shown per sector (e.g. `clysmort5` → CLYSMORT /
  CLYS_SOUTH / CLYS_WEST). Coordinate-named sectors (`EWGB…`, `DQEV…`) get no
  filename hint — use the full searchable list / the area guide.
- **Save** writes into `mra_teleportal_registry.json`.

## Grading & the cardinal rule (CLAUDE.md §0)

The tool **never invents a binding**. Suggestions are HINTS you confirm.
Every label you add is stamped grade **DERIVED** (human map/geography
judgement) — *not* VERIFIED. Only a live walk-record (MEMORIZE on the tile)
earns VERIFIED. The four walk-recorded seed entries (HAV_CHURCH, HAV_INN,
KOFOR, HAV_COM) keep their original VERIFIED `_evidence` **verbatim**: the save
path reuses the on-disk entry untouched whenever a name's `(sector,x,y)` is
unchanged, and preserves every top-level registry metadata key. A name binds to
**one** tile — assigning the same name twice is flagged as a conflict.

Jump **destinations** stay `null` (they lived in the LOST `.MSG` content layer).

## Files

- `teleportal_labeler_server.py` — stdlib HTTP server (scan + render + save).
- `teleportal_labeler.html` — self-contained front-end.
- `build_portable.py` — bakes the whole tool + all sector art into one offline HTML
  (`teleportal_labeler_portable.html`) with Export/Import for distribution.
- `merge_exports.py` — folds player export JSONs back into the registry (conflict-safe).
- `mra_obj256.py` (repo root) — OBJ.256 object-sprite decoder (Format 8, VERIFIED).
- `reference/dumps/teleportal_hints.json` — mined from the reference corpus (wiki +
  ognall-docs + fan sites) by a 25-agent pass: **24 area guides** (DOMAIN/DOC, cited),
  347 per-name location hints, and **27 extra candidate code-names** beyond the 353
  (e.g. `OMR_3B`, `DOC_1`, `ORCS_G1`, `KOKAS+1A`). Loaded automatically if present;
  the area-guide panel browses all 24 and auto-matches the current area.
