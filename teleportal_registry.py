"""Build the blue-teleportal tile registry for a compiled world map.

Blue/public teleportals are SEC object byte 0x01.  Their names are editor
metadata, not part of the SEC bytes, so this module keeps that metadata separate
from custom travelLinks and recomputes absolute world coordinates after every
map build.
"""
from __future__ import annotations

import copy
import json
import os
import re
from collections import defaultdict


SEC_GRID = 33
SEC_PLAY = 32
SEC_CELL = 6
SEC_SIZE = SEC_GRID * SEC_GRID * SEC_CELL
BLUE_TELEPORTAL = 0x01


def _load_json(path):
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _base(value):
    return os.path.splitext(os.path.basename(str(value or "")))[0]


def _cell_key(base, x, y):
    return f"{_base(base).lower()}:{int(x)}:{int(y)}"


def _find_sec(filename, roots):
    name = os.path.basename(str(filename or ""))
    if not name:
        return None
    candidates = [name]
    if not name.lower().endswith(".sec"):
        candidates.append(name + ".SEC")
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for candidate in candidates:
            path = os.path.join(root, candidate)
            if os.path.isfile(path):
                return path
        wanted = name.lower()
        if not wanted.endswith(".sec"):
            wanted += ".sec"
        try:
            for entry in os.scandir(root):
                if entry.is_file() and entry.name.lower() == wanted:
                    return entry.path
        except OSError:
            pass
    return None


def scan_blue_teleportals(world_map, sec_roots):
    """Return placed blue portal cells and missing/invalid SEC filenames."""
    found = []
    missing = []
    invalid = []
    sectors = world_map.get("sectors") or {}
    ordered = sorted(
        sectors.items(),
        key=lambda item: (
            int(item[1].get("y_block", 0)),
            int(item[1].get("x_block", 0)),
            str(item[1].get("layer", "b")),
            item[0].lower(),
        ),
    )
    for sector_base, sector in ordered:
        filename = sector.get("filename") or (sector_base + ".SEC")
        path = _find_sec(filename, sec_roots)
        if not path:
            missing.append(filename)
            continue
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            missing.append(filename)
            continue
        if len(data) != SEC_SIZE:
            invalid.append({"filename": filename, "size": len(data)})
            continue
        for y in range(SEC_PLAY):
            for x in range(SEC_PLAY):
                offset = (y * SEC_GRID + x) * SEC_CELL
                if data[offset + 1] != BLUE_TELEPORTAL:
                    continue
                found.append(
                    {
                        "sector_base": sector_base,
                        "filename": filename,
                        "x": x,
                        "y": y,
                        "world": {
                            "x": int(sector.get("x_block", 0)) * SEC_PLAY + x,
                            "y": int(sector.get("y_start", 0)) + y,
                            "layer": str(sector.get("layer", "b")),
                        },
                    }
                )
    return found, missing, invalid


def labels_from_raw(raw):
    """Normalize unified-export, portable-labeler, or registry labels by cell."""
    if not isinstance(raw, dict):
        return {}
    source = raw.get("teleportalLabels")
    if source is None:
        source = raw.get("teleportal_labels")
    if source is None and isinstance(raw.get("labels"), dict):
        source = raw["labels"]
    if source is None and isinstance(raw.get("teleportals"), dict):
        source = raw["teleportals"]
    if not isinstance(source, dict):
        return {}

    out = {}
    for raw_key, value in source.items():
        if isinstance(value, str):
            value = {"name": value}
        if not isinstance(value, dict):
            continue
        name = str(value.get("name") or raw_key or "").strip().upper()
        base = value.get("sector_base")
        x = value.get("x", value.get("col"))
        y = value.get("y", value.get("row"))
        if (base is None or x is None or y is None) and ":" in str(raw_key):
            parts = str(raw_key).rsplit(":", 2)
            if len(parts) == 3:
                base, x, y = parts
        try:
            key = _cell_key(base, x, y)
        except (TypeError, ValueError):
            continue
        if not name or not _base(base):
            continue
        out[key] = {
            "name": name,
            "sector_base": _base(base),
            "x": int(x),
            "y": int(y),
            "subtype": int(value.get("subtype", BLUE_TELEPORTAL)),
            "_grade": value.get("_grade") or value.get("grade") or "DERIVED",
            "_evidence": value.get("_evidence") or value.get("evidence") or "",
        }
    return out


def _registry_by_cell(registry):
    out = {}
    for name, row in (registry.get("teleportals") or {}).items():
        if not isinstance(row, dict):
            continue
        base = row.get("sector_base")
        x, y = row.get("x"), row.get("y")
        if base is None or x is None or y is None:
            continue
        try:
            out[_cell_key(base, x, y)] = (str(name).upper(), row)
        except (TypeError, ValueError):
            continue
    return out


def _default_prefix(base):
    cleaned = re.sub(r"[^A-Z0-9]", "", _base(base).upper())
    alpha = "".join(ch for ch in cleaned if ch.isalpha())
    return (alpha or cleaned or "TP")[:3].ljust(3, "X")


def build_registry(world_map, raw_export, seed_paths, sec_roots):
    """Merge labels and scan all placed SECs into a server-ready registry."""
    seed = {}
    for path in seed_paths:
        candidate = _load_json(path)
        if not candidate:
            continue
        if not seed:
            seed = copy.deepcopy(candidate)
            continue
        seed.setdefault("teleportals", {}).update(
            copy.deepcopy(candidate.get("teleportals") or {})
        )
        for key, value in candidate.items():
            if key != "teleportals":
                seed[key] = copy.deepcopy(value)

    existing_by_cell = _registry_by_cell(seed)
    explicit_by_cell = labels_from_raw(raw_export)
    cells, missing, invalid = scan_blue_teleportals(world_map, sec_roots)

    result = copy.deepcopy(seed) if seed else {}
    result["_provenance"] = (
        "[GENERATED] Blue/public teleportal registry rebuilt from placed SEC object "
        "byte 0x01 cells. Existing and editor labels are preserved by "
        "(sector_base,x,y); absolute world coordinates are recomputed from the "
        "current world map. AUTO names are editable defaults."
    )
    result["_schema"] = {
        "sector_base": "str  SEC base name (key into world_map.json sectors)",
        "x": "int  intra-sector col 0..31",
        "y": "int  intra-sector row 0..31",
        "world": "{x,y,layer}  current derived server world coordinates",
        "color": "'blue'",
        "subtype": "1  SEC object byte 0x01",
        "level_req": "int|null",
        "dest": "null  TP <name> targets this row's world tile",
        "_grade": "'VERIFIED'|'DERIVED'|'AUTO'",
    }
    result["_auto_name_policy"] = (
        "Unlabeled cells use the first three alphanumeric letters of the SEC "
        "base plus a stable numeric suffix, for example HAV_1. A prior generated "
        "registry or editor teleportalLabels keeps names stable across rebuilds."
    )

    used_names = {
        str(name).upper() for name in (seed.get("teleportals") or {}).keys()
    }
    used_names.update(
        label["name"].upper() for label in explicit_by_cell.values()
    )
    next_suffix = defaultdict(lambda: 1)
    generated = {}
    counts = defaultdict(int)
    name_conflicts = []

    for cell in cells:
        key = _cell_key(cell["sector_base"], cell["x"], cell["y"])
        explicit = explicit_by_cell.get(key)
        existing = existing_by_cell.get(key)
        if explicit:
            name = explicit["name"]
            old_row = existing[1] if existing and existing[0] == name else {}
            row = copy.deepcopy(old_row)
            row["_grade"] = explicit.get("_grade") or "DERIVED"
            if explicit.get("_evidence"):
                row["_evidence"] = explicit["_evidence"]
            elif not row.get("_evidence"):
                row["_evidence"] = (
                    "[DERIVED] Named in the SEC/world-map editor; tile byte "
                    "verified as object 0x01 during this build."
                )
        elif existing:
            name, old_row = existing
            row = copy.deepcopy(old_row)
        else:
            prefix = _default_prefix(cell["sector_base"])
            suffix = next_suffix[prefix]
            name = f"{prefix}_{suffix}"
            while name in used_names:
                suffix += 1
                name = f"{prefix}_{suffix}"
            next_suffix[prefix] = suffix + 1
            row = {
                "_grade": "AUTO",
                "_evidence": (
                    "[AUTO] Default editable name assigned from the SEC filename; "
                    "tile byte verified as blue/public object 0x01."
                ),
            }
        used_names.add(name)
        if name in generated:
            original = name
            prefix = _default_prefix(cell["sector_base"])
            suffix = next_suffix[prefix]
            name = f"{prefix}_{suffix}"
            while name in used_names or name in generated:
                suffix += 1
                name = f"{prefix}_{suffix}"
            next_suffix[prefix] = suffix + 1
            used_names.add(name)
            name_conflicts.append(
                {
                    "name": original,
                    "cell": key,
                    "resolution": name,
                }
            )
            row["_grade"] = "AUTO"
            row["_evidence"] = (
                f"[AUTO] Duplicate requested name {original} was already bound; "
                f"assigned unique editable default {name}."
            )
        row.update(
            {
                "sector_base": cell["sector_base"],
                "x": cell["x"],
                "y": cell["y"],
                "world": cell["world"],
                "color": "blue",
                "subtype": BLUE_TELEPORTAL,
                "level_req": row.get("level_req"),
                "dest": None,
            }
        )
        generated[name] = row
        counts[row.get("_grade") or "DERIVED"] += 1

    active_cell_keys = {
        _cell_key(cell["sector_base"], cell["x"], cell["y"]) for cell in cells
    }
    # Preserve intentional named pins whose cell is outside this assembled
    # world. Do not retain replaced names for an active cell or disposable AUTO
    # defaults, since those become misleading aliases after an editor rename.
    for name, row in (seed.get("teleportals") or {}).items():
        upper = str(name).upper()
        if upper in generated or not isinstance(row, dict):
            continue
        base, x, y = row.get("sector_base"), row.get("x"), row.get("y")
        try:
            old_cell_key = _cell_key(base, x, y)
        except (TypeError, ValueError):
            old_cell_key = None
        if old_cell_key in active_cell_keys or row.get("_grade") == "AUTO":
            continue
        saved = copy.deepcopy(row)
        saved["world"] = None
        saved["_inactive"] = "sector/cell is not present in the current assembled world"
        generated[upper] = saved
        counts["INACTIVE"] += 1

    result["teleportals"] = generated
    result["_build"] = {
        "placed_blue_cells": len(cells),
        "registry_rows": len(generated),
        "labels_from_export": len(explicit_by_cell),
        "grades": dict(sorted(counts.items())),
        "missing_sec_files": sorted(set(missing), key=str.lower),
        "invalid_sec_files": invalid,
        "name_conflicts": name_conflicts,
    }
    return result


def editor_labels(registry):
    """Return the compact cell-keyed form used by the browser editors."""
    out = {}
    for name, row in (registry.get("teleportals") or {}).items():
        if not isinstance(row, dict):
            continue
        base, x, y = row.get("sector_base"), row.get("x"), row.get("y")
        if base is None or x is None or y is None:
            continue
        key = f"{_base(base)}:{int(x)}:{int(y)}"
        out[key] = {
            "name": str(name).upper(),
            "subtype": int(row.get("subtype", BLUE_TELEPORTAL)),
            "grade": row.get("_grade") or "DERIVED",
        }
    return out


def write_registry_js(path, registry):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = json.dumps(registry, separators=(",", ":"), ensure_ascii=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("// Auto-generated by build_world_map.py.\n")
        fh.write("window.TELEPORTAL_REGISTRY=")
        fh.write(payload)
        fh.write(";\n")
