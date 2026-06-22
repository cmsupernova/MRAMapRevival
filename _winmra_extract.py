"""Extract embedded data files (world_map.json, ITEMS.TXT, MAPS list, .pyc)
from the PyInstaller-packed WINMRA/MRA_Server.exe for analysis.

PyInstaller CArchive layout (big-endian):
  Trailing cookie (88 bytes): magic[8], pkgLen, tocPos, tocLen, pyvers, pylib[64]
  TOC entries: entryLen, dataPos, cmprLen, uncmprLen, cflag, typecd, name...
"""
import struct
import zlib
import os

EXE = "WINMRA/MRA_Server.exe"
OUT = "_winmra_dump"

data = open(EXE, "rb").read()
magic = b"MEI\014\013\012\013\016"
cpos = data.rfind(magic)
print(f"cookie @ {cpos}, file size {len(data)}")

# cookie: 8s magic, then 4x uint32 BE, then 64s libname
(_, pkg_len, toc_pos, toc_len, pyvers) = struct.unpack(">8sIIII", data[cpos:cpos+24])
libname = data[cpos+24:cpos+88].rstrip(b"\x00").decode("latin1")
print(f"pkgLen={pkg_len} tocPos={toc_pos} tocLen={toc_len} pyvers={pyvers} lib={libname}")

# CArchive starts at end - pkg_len
arch_start = len(data) - pkg_len
toc_abs = arch_start + toc_pos
toc = data[toc_abs:toc_abs+toc_len]

os.makedirs(OUT, exist_ok=True)
entries = []
p = 0
while p < len(toc):
    (elen,) = struct.unpack(">I", toc[p:p+4])
    if elen == 0:
        break
    dpos, clen, ulen, cflag = struct.unpack(">IIIB", toc[p+4:p+17])
    typecd = toc[p+17:p+18].decode("latin1")
    name = toc[p+18:p+elen].rstrip(b"\x00").decode("latin1")
    entries.append((name, typecd, dpos, clen, ulen, cflag))
    p += elen

print(f"\n{len(entries)} TOC entries\n")
want = ("world_map", "ITEMS.TXT", "roster", ".json")
for name, typecd, dpos, clen, ulen, cflag in entries:
    interesting = any(w in name for w in want)
    if interesting:
        print(f"[{typecd}] {name}  (clen={clen} ulen={ulen} cflag={cflag})")
        raw = data[arch_start+dpos:arch_start+dpos+clen]
        if cflag:
            try:
                raw = zlib.decompress(raw)
            except Exception as e:
                print(f"   decompress failed: {e}")
                continue
        safe = name.replace("\\", "_").replace("/", "_")
        open(os.path.join(OUT, safe), "wb").write(raw)

# Also list all MAPS\*.SEC entries and any server .py modules
print("\n--- MAPS entries ---")
maps = [e for e in entries if "MAPS" in e[0] and e[0].lower().endswith(".sec")]
print(f"{len(maps)} .SEC files bundled")
for name, *_ in maps[:10]:
    print("  ", name)

print("\n--- python modules (mra_*) ---")
for name, typecd, *_ in entries:
    if name.startswith("mra") or typecd in ("s", "M", "m"):
        print(f"  [{typecd}] {name}")

# Dump script/source entries (s/M/m) decompressed for strings analysis
print("\n--- dumping script entries ---")
for name, typecd, dpos, clen, ulen, cflag in entries:
    if typecd in ("s", "M", "m") and ("mra" in name or "stub" in name):
        raw = data[arch_start+dpos:arch_start+dpos+clen]
        if cflag:
            try:
                raw = zlib.decompress(raw)
            except Exception as e:
                print(f"  {name}: decompress failed {e}")
                continue
        safe = name.replace("\\", "_").replace("/", "_").replace(".", "_") + ".pyc.bin"
        open(os.path.join(OUT, safe), "wb").write(raw)
        print(f"  wrote {safe} ({len(raw)} bytes)")
