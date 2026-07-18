"""Run the extracted MRA stub with custom travel-link support.

The stock MRA_Server.exe has no travelLinks handling. This launcher loads the
same stub bytecode (Python 3.14), wraps post-step movement with teleports from
world_map.json / travel_links.json, then listens on the usual ports.

Usage (from repo root, Python 3.14 required):
  py -3.14 run_mra_server.py

Or double-click WINMRA\\Run MRA Travel Server.bat

Data files are resolved next to WINMRA\\ (world_map.json, MAPS\\, travel_links.json)
exactly like the frozen exe.
"""
from __future__ import annotations

import marshal
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
WINMRA = os.path.join(HERE, "WINMRA")
STUB_BIN = os.path.join(HERE, "_winmra_dump", "mra_stub.pyc.bin")


def _require_python314():
    if sys.version_info[:2] != (3, 14):
        print(
            f"This launcher needs Python 3.14 (stub bytecode is 3.14); got {sys.version}"
        )
        print("Install: winget install Python.Python.3.14")
        print("Then:    py -3.14 run_mra_server.py")
        sys.exit(1)


def load_stub():
    if not os.path.isfile(STUB_BIN):
        print(f"Missing stub bytecode: {STUB_BIN}")
        print("Re-run: python _winmra_extract.py")
        sys.exit(1)
    with open(STUB_BIN, "rb") as fh:
        code = marshal.loads(fh.read())
    # Point __file__ at WINMRA so _MRA_BASE_DIR / _MRA_RESOLVE find sidecars.
    stub_file = os.path.join(WINMRA, "mra_stub.py")
    ns = {
        "__name__": "mra_stub",
        "__file__": stub_file,
        "__builtins__": __builtins__,
    }
    exec(code, ns, ns)
    return ns


def start_servers(ns):
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
    print("IMPORTANT: close WINMRA\\MRA_Server.exe first (stock exe")
    print("has no travelLinks). This process must own ports 1109/1111.")
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


def main():
    _require_python314()
    if not os.path.isdir(WINMRA):
        print(f"Missing WINMRA folder: {WINMRA}")
        sys.exit(1)

    # Ensure WINMRA is first on path for optional catalog/critter sidecars.
    if WINMRA not in sys.path:
        sys.path.insert(0, WINMRA)
    if HERE not in sys.path:
        sys.path.insert(0, HERE)

    from mra_travel_runtime import install_hooks

    ns = load_stub()
    install_hooks(ns, os.path.join(WINMRA, "world_map.json"))
    start_servers(ns)


if __name__ == "__main__":
    main()
