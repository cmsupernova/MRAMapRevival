"""Run the extracted MRA stub with custom travel-link support.

Prefer WINMRA\\MRA_Server_Travel.exe when available (frozen, stock-speed).
This script is the fallback / dev path: loads stub bytecode under Python 3.14.

Usage:
  py -3.14 run_mra_server.py
  Or: Run MRA Travel Server.bat
"""
from __future__ import annotations

import marshal
import os
import sys

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
        print("Or use:  WINMRA\\MRA_Server_Travel.exe")
        sys.exit(1)


def load_stub():
    if not os.path.isfile(STUB_BIN):
        print(f"Missing stub bytecode: {STUB_BIN}")
        print("Re-run: python _winmra_extract.py")
        sys.exit(1)
    with open(STUB_BIN, "rb") as fh:
        code = marshal.loads(fh.read())
    stub_file = os.path.join(WINMRA, "mra_stub.py")
    ns = {
        "__name__": "mra_stub",
        "__file__": stub_file,
        "__builtins__": __builtins__,
    }
    exec(code, ns, ns)
    return ns


def main():
    # Per-step probe dumps hammer the Windows console; stock feel needs this off.
    os.environ.setdefault("MRA_TILE_PROBE", "0")

    _require_python314()
    if not os.path.isdir(WINMRA):
        print(f"Missing WINMRA folder: {WINMRA}")
        sys.exit(1)

    if WINMRA not in sys.path:
        sys.path.insert(0, WINMRA)
    if HERE not in sys.path:
        sys.path.insert(0, HERE)

    from mra_travel_runtime import install_hooks, run_stub_main

    ns = load_stub()
    install_hooks(ns, os.path.join(WINMRA, "world_map.json"))
    run_stub_main(ns)


if __name__ == "__main__":
    main()
