"""Build WINMRA/MRA_Server_Travel.exe: stock frozen server + travel-link entry.

Replaces the embedded mra_stub script with mra_stub_travel_boot.py and adds the
original stub bytecode as mra_stub_orig.pyc.bin. Copies mra_travel_runtime.py
next to the exe for import.

Requires Python 3.14 to compile the boot script (matches embedded pyvers).
"""
from __future__ import annotations

import os
import shutil
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
WINMRA = os.path.join(HERE, "WINMRA")
SRC_EXE = os.path.join(WINMRA, "MRA_Server.exe")
OUT_EXE = os.path.join(WINMRA, "MRA_Server_Travel.exe")
STUB_ORIG = os.path.join(HERE, "_winmra_dump", "mra_stub.pyc.bin")
BOOT_SRC = os.path.join(HERE, "mra_stub_travel_boot.py")
RUNTIME_SRC = os.path.join(HERE, "mra_travel_runtime.py")
MAGIC = b"MEI\014\013\012\013\016"
COOKIE_LEN = 88


def _require_314():
    if sys.version_info[:2] != (3, 14):
        print(f"Need Python 3.14 to compile boot (got {sys.version})")
        sys.exit(1)


def _align16(n):
    return (n + 15) // 16 * 16


def _toc_entry(name, typecd, dpos, clen, ulen, cflag):
    name_b = name.encode("latin1") + b"\x00"
    elen = _align16(18 + len(name_b))
    pad = elen - 18 - len(name_b)
    return (
        struct.pack(">IIIIB", elen, dpos, clen, ulen, cflag)
        + typecd.encode("latin1")
        + name_b
        + (b"\x00" * pad)
    )


def _parse_exe(data):
    cpos = data.rfind(MAGIC)
    if cpos < 0:
        raise SystemExit("PyInstaller cookie not found")
    (_, pkg_len, toc_pos, toc_len, pyvers) = struct.unpack(">8sIIII", data[cpos : cpos + 24])
    libname = data[cpos + 24 : cpos + 88]
    arch_start = len(data) - pkg_len
    toc = data[arch_start + toc_pos : arch_start + toc_pos + toc_len]
    entries = []
    p = 0
    while p < len(toc):
        (elen,) = struct.unpack(">I", toc[p : p + 4])
        if elen == 0:
            break
        dpos, clen, ulen, cflag = struct.unpack(">IIIB", toc[p + 4 : p + 17])
        typecd = toc[p + 17 : p + 18].decode("latin1")
        name = toc[p + 18 : p + elen].rstrip(b"\x00").decode("latin1")
        blob = data[arch_start + dpos : arch_start + dpos + clen]
        entries.append(
            {
                "name": name,
                "typecd": typecd,
                "cflag": cflag,
                "ulen": ulen,
                "blob": blob,
            }
        )
        p += elen
    bootloader = data[:arch_start]
    return bootloader, entries, pyvers, libname


def _compile_boot():
    src = open(BOOT_SRC, encoding="utf-8").read()
    code = compile(src, "mra_stub.py", "exec", optimize=2)
    return marshal_dumps(code)


def marshal_dumps(code):
    import marshal

    return marshal.dumps(code)


def _pack_blob(raw, compress=True):
    if compress:
        return zlib.compress(raw, 9), 1, len(raw)
    return raw, 0, len(raw)


def build():
    _require_314()
    if not os.path.isfile(SRC_EXE):
        raise SystemExit(f"Missing {SRC_EXE}")
    if not os.path.isfile(STUB_ORIG):
        raise SystemExit(f"Missing {STUB_ORIG} — run python _winmra_extract.py")
    if not os.path.isfile(BOOT_SRC):
        raise SystemExit(f"Missing {BOOT_SRC}")
    if not os.path.isfile(RUNTIME_SRC):
        raise SystemExit(f"Missing {RUNTIME_SRC}")

    data = open(SRC_EXE, "rb").read()
    bootloader, entries, pyvers, libname = _parse_exe(data)
    if pyvers != 314:
        print(f"WARNING: exe pyvers={pyvers}, boot compiled with 3.14")

    boot_raw = _compile_boot()
    boot_blob, boot_cflag, boot_ulen = _pack_blob(boot_raw)
    orig_raw = open(STUB_ORIG, "rb").read()
    orig_blob, orig_cflag, orig_ulen = _pack_blob(orig_raw)

    new_entries = []
    replaced = False
    for e in entries:
        if e["name"] == "mra_stub" and e["typecd"] == "s":
            new_entries.append(
                {
                    "name": "mra_stub",
                    "typecd": "s",
                    "cflag": boot_cflag,
                    "ulen": boot_ulen,
                    "blob": boot_blob,
                }
            )
            replaced = True
        else:
            new_entries.append(e)

    if not replaced:
        raise SystemExit("mra_stub script entry not found in exe")

    # Drop any previous inject, then append original stub blob for the boot to load.
    new_entries = [e for e in new_entries if e["name"] != "mra_stub_orig.pyc.bin"]
    new_entries.append(
        {
            "name": "mra_stub_orig.pyc.bin",
            "typecd": "b",
            "cflag": orig_cflag,
            "ulen": orig_ulen,
            "blob": orig_blob,
        }
    )

    # Rebuild PKG: data blobs then TOC then cookie.
    blobs = b""
    toc = b""
    for e in new_entries:
        dpos = len(blobs)
        blobs += e["blob"]
        toc += _toc_entry(
            e["name"], e["typecd"], dpos, len(e["blob"]), e["ulen"], e["cflag"]
        )

    toc_pos = len(blobs)
    toc_len = len(toc)
    pkg = blobs + toc
    pkg_len = len(pkg) + COOKIE_LEN
    cookie = struct.pack(">8sIIII", MAGIC, pkg_len, toc_pos, toc_len, pyvers) + libname
    if len(cookie) != COOKIE_LEN:
        # libname field must pad to 64 bytes inside cookie
        cookie = cookie[:24] + (libname + b"\x00" * 64)[:64]
        assert len(cookie) == COOKIE_LEN

    out = bootloader + pkg + cookie
    open(OUT_EXE, "wb").write(out)

    # Sidecar import for travel runtime (and keep a copy of orig blob beside exe as fallback).
    shutil.copy2(RUNTIME_SRC, os.path.join(WINMRA, "mra_travel_runtime.py"))
    shutil.copy2(STUB_ORIG, os.path.join(WINMRA, "mra_stub_orig.pyc.bin"))

    print(f"Wrote {OUT_EXE} ({len(out)} bytes)")
    print(f"  boot script compressed {len(boot_blob)} (raw {boot_ulen})")
    print(f"  stub orig embedded {len(orig_blob)} (raw {orig_ulen})")
    print(f"  copied mra_travel_runtime.py + mra_stub_orig.pyc.bin next to exe")


if __name__ == "__main__":
    build()
