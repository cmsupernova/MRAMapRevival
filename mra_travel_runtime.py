"""In-game travel / teleport links for the MRA stub server.

Editor links live in unified export `travelLinks` (and localStorage).
`build_world_map.py` copies them into world_map.json. This module indexes
those ends and teleports the player when they step onto a linked cell.

Hook point: wrap stub `maybe_layer_transition` (called after each committed step).
"""
from __future__ import annotations

import json
import os
import threading

LAYER_FROM_LEVEL = {0: "b", -1: "a", 1: "c"}


def travel_debug():
    return os.environ.get("MRA_TRAVEL_DEBUG", "0").strip() not in ("", "0", "false", "False")


def _base_name(filename):
    if not filename:
        return None
    name = os.path.basename(str(filename)).strip()
    if name.lower().endswith(".sec"):
        name = name[:-4]
    return name or None


def _end_cell(end):
    if not end or not isinstance(end, dict):
        return None
    base = _base_name(end.get("filename"))
    r, c = end.get("r"), end.get("c")
    if base is None or r is None or c is None:
        return None
    try:
        return base, int(r), int(c)
    except (TypeError, ValueError):
        return None


def load_travel_links(world_map_path, extra_paths=None):
    """Load link list from world_map.json and optional sidecar files."""
    links = []
    paths = []
    if world_map_path:
        paths.append(world_map_path)
        side = os.path.join(os.path.dirname(os.path.abspath(world_map_path)), "travel_links.json")
        paths.append(side)
    if extra_paths:
        paths.extend(extra_paths)

    seen = set()
    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        raw = []
        if isinstance(data, list):
            raw = data
        elif isinstance(data, dict):
            raw = data.get("travelLinks") or data.get("travel_links") or []
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            lid = item.get("id") or json.dumps(item, sort_keys=True)
            if lid in seen:
                continue
            seen.add(lid)
            links.append(item)
    return links


def build_index(links):
    """Map (base_lower, r, c) -> dest end dict. Bidirectional links register both ways."""
    index = {}
    for link in links:
        if not isinstance(link, dict):
            continue
        fr = _end_cell(link.get("from"))
        to = _end_cell(link.get("to"))
        if not fr or not to:
            continue
        fb, fr_, fc = fr
        tb, tr, tc = to
        index[(fb.lower(), fr_, fc)] = link.get("to")
        if link.get("bidirectional"):
            index[(tb.lower(), tr, tc)] = link.get("from")
    return index


def attach_to_world(world, world_map_path, log=None):
    """Index links onto a WorldMap instance. Safe to call more than once."""
    links = load_travel_links(world_map_path)
    index = build_index(links)
    world.travel_links = links
    world.travel_link_index = index
    if log:
        log("[travel]", f"Loaded {len(links)} travel link(s), {len(index)} trigger cell(s)")
    return index


def _intra_y(world, world_y, sec_play_dim):
    for i, pair in enumerate(world.y_axis_ranges):
        y_start, y_end = pair[0], pair[1]
        if y_start <= world_y <= y_end:
            return i, world_y - y_start
    for i, pair in enumerate(world.y_axis_ranges):
        y_start = pair[0]
        if y_start <= world_y < y_start + sec_play_dim:
            return i, world_y - y_start
    return None, None


def player_trigger_key(world, player, sec_play_dim):
    x_block = player.x // sec_play_dim
    intra_x = player.x % sec_play_dim
    y_block, intra_y = _intra_y(world, player.y, sec_play_dim)
    if y_block is None or intra_y is None:
        return None
    base = world.lookup_base(x_block, y_block, player.layer)
    if not base:
        return None
    return base, int(intra_y), int(intra_x)


def resolve_dest_world(world, end, sec_play_dim, log=None):
    """Convert a link end {filename,r,c,level?} to (world_x, world_y, layer)."""
    cell = _end_cell(end)
    if not cell:
        return None
    base, r, c = cell
    if not (0 <= r < sec_play_dim and 0 <= c < sec_play_dim):
        if log and travel_debug():
            log("[travel]", f"Dest cell out of range {base} r{r}c{c}")
        return None

    sec = None
    if getattr(world, "sectors", None):
        sec = world.sectors.get(base) or world.sectors.get(base.lower())
        if sec is None:
            for k, v in world.sectors.items():
                if k.lower() == base.lower():
                    sec = v
                    base = k
                    break
    if not sec:
        if log and travel_debug():
            log("[travel]", f"Dest sector not on world map: {base}")
        return None

    try:
        x_block = int(sec["x_block"])
        y_block = int(sec["y_block"])
    except (KeyError, TypeError, ValueError):
        return None

    layer = (sec.get("layer") or "b").lower()
    if end.get("level") is not None:
        try:
            layer = LAYER_FROM_LEVEL.get(int(end["level"]), layer)
        except (TypeError, ValueError):
            pass
    if layer not in ("a", "b", "c"):
        layer = "b"

    if y_block < 0 or y_block >= len(world.y_axis_ranges):
        if log and travel_debug():
            log("[travel]", f"Dest y_block {y_block} out of y_axis_ranges for {base}")
        return None

    y_start = world.y_axis_ranges[y_block][0]
    world_x = x_block * sec_play_dim + c
    world_y = y_start + r

    if not world.lookup_base(x_block, y_block, layer):
        layer = (sec.get("layer") or layer).lower()
        if not world.lookup_base(x_block, y_block, layer):
            if log and travel_debug():
                log("[travel]", f"No block entry for {base} at {x_block},{y_block},{layer}")
            return None

    if not world.load_sec(base):
        if log and travel_debug():
            log("[travel]", f"Could not load SEC for {base}")
        return None

    return world_x, world_y, layer, base


def try_travel_link(world, player, stub_ns):
    """If the player just stepped onto a trigger cell, teleport. Return True if teleported."""
    index = getattr(world, "travel_link_index", None)
    if not index:
        return False

    sec_play_dim = stub_ns["SEC_PLAY_DIM"]
    log = stub_ns.get("log")
    key = player_trigger_key(world, player, sec_play_dim)
    if not key:
        return False

    base, r, c = key
    dest = index.get((base.lower(), r, c))
    if not dest:
        return False

    resolved = resolve_dest_world(world, dest, sec_play_dim, log=log)
    if not resolved:
        return False

    world_x, world_y, layer, dest_base = resolved
    if player.x == world_x and player.y == world_y and player.layer == layer:
        return False

    if log and travel_debug():
        log(
            "[travel]",
            f"Teleport {base} r{r}c{c} -> {dest_base} ({world_x},{world_y},{layer})",
        )
    elif log:
        # Always one short line so console shows links firing without probe spam.
        log("[travel]", f"{base} r{r}c{c} -> {dest_base}")
    player.x = world_x
    player.y = world_y
    player.layer = layer
    return True


def install_hooks(stub_ns, world_map_path):
    """Wrap maybe_layer_transition and attach links after WorldMap construction."""
    orig_layer = stub_ns["maybe_layer_transition"]
    OrigWorldMap = stub_ns["WorldMap"]

    class WorldMap(OrigWorldMap):
        def __init__(self, world_map_path, maps_dir):
            super().__init__(world_map_path, maps_dir)
            attach_to_world(self, world_map_path, log=stub_ns.get("log"))

    def maybe_layer_transition(world, player):
        if try_travel_link(world, player, stub_ns):
            return None
        return orig_layer(world, player)

    stub_ns["WorldMap"] = WorldMap
    stub_ns["maybe_layer_transition"] = maybe_layer_transition
    stub_ns["_travel_world_map_path"] = world_map_path
    return stub_ns


def run_stub_main(ns):
    """Start MRA/OGN listen loops using an already-loaded+patched stub namespace."""
    os_mod = ns["os"]
    log = ns["log"]
    WorldMap = ns["WorldMap"]
    _MRA_RESOLVE = ns["_MRA_RESOLVE"]
    _MRA_BASE_DIR = ns["_MRA_BASE_DIR"]
    server_thread = ns["server_thread"]
    handle_mra = ns["handle_mra"]
    _ogn_thread = ns["_ogn_thread"]

    print("============================================================")
    print("MRA Stub Server  + travel links")
    print("Close any OTHER MRA_Server*.exe first (old instances keep the")
    print("port and ignore new world_map.json / travelLinks).")
    print("============================================================")

    _exe_dir, _meipass = _MRA_BASE_DIR()
    maps_dir = None
    for base in (_exe_dir, _meipass):
        if not base:
            continue
        for cand in ("MAPS", "maps", "."):
            full = os_mod.path.join(base, cand)
            if not os_mod.path.isdir(full):
                continue
            secs = [
                f for f in os_mod.listdir(full)
                if f.upper().endswith(".SEC")
            ]
            if secs:
                maps_dir = full
                break
        if maps_dir:
            break
    if maps_dir is None:
        maps_dir = _exe_dir

    log("[world]", f"Maps dir: {maps_dir}")
    world_map_path = _MRA_RESOLVE("world_map.json")
    world = WorldMap(world_map_path, maps_dir)

    ports_raw = os_mod.environ.get("MRA_PORTS", "1109,1111").replace(" ", "")
    ports = [int(x) for x in ports_raw.split(",") if x]
    for port in ports:
        threading.Thread(
            target=server_thread,
            args=(world, port, "MRA", handle_mra),
            daemon=True,
        ).start()

    threading.Thread(target=_ogn_thread, args=(22276,), daemon=True).start()

    n = len(getattr(world, "travel_link_index", {}) or {})
    print(f"Travel triggers armed: {n}")
    print("Leave this window open. Client: MRA.EXE \"put >L>\"")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nShutting down.")
