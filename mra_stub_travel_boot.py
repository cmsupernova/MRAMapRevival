"""PyInstaller entry replacement for mra_stub: original stub + travel hooks.

Compiled and injected into MRA_Server_Travel.exe by patch_mra_server_travel.py.
Also runnable under plain Python 3.14 for debugging.
"""
from __future__ import annotations

import marshal
import os
import sys


def _exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _mei():
    return getattr(sys, "_MEIPASS", None)


def _find_stub_blob():
    here = _exe_dir()
    mei = _mei()
    candidates = []
    if mei:
        candidates.append(os.path.join(mei, "mra_stub_orig.pyc.bin"))
    candidates.append(os.path.join(here, "mra_stub_orig.pyc.bin"))
    # Dev fallback: repo dump next to WINMRA
    candidates.append(
        os.path.normpath(os.path.join(here, "..", "_winmra_dump", "mra_stub.pyc.bin"))
    )
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def main():
    # Stock stub defaults TILE_PROBE ON and logs a full cell dump every step —
    # that alone makes Windows consoles feel laggy. Opt back in with MRA_TILE_PROBE=1.
    os.environ.setdefault("MRA_TILE_PROBE", "0")

    exe_dir = _exe_dir()
    mei = _mei()
    for path in (exe_dir, mei):
        if path and path not in sys.path:
            sys.path.insert(0, path)

    stub_bin = _find_stub_blob()
    if not stub_bin:
        print("Missing mra_stub_orig.pyc.bin (original stub bytecode)")
        sys.exit(1)

    with open(stub_bin, "rb") as fh:
        code = marshal.loads(fh.read())

    ns = {
        "__name__": "mra_stub",
        "__file__": os.path.join(exe_dir, "mra_stub.py"),
        "__builtins__": __builtins__,
    }
    exec(code, ns, ns)

    from mra_travel_runtime import install_hooks, run_stub_main

    install_hooks(ns, os.path.join(exe_dir, "world_map.json"))
    run_stub_main(ns)


if __name__ == "__main__":
    main()
