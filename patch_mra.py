"""Patch MRA.EXE to enable viewport rendering with emulated server.

Nine patches are applied (old patch 5 removed in v23; v24 patch 10 removed in v25):

Patch 1 - Bypass slot state check (VA 0x417FEE, file offset 0x17FEE):
  Safety net. The rendering code checks [0x4539F1] (slot 1 state byte).
  If 0, skips ALL rendering via JZ. NOP'd to ensure fall-through.
  
  Before: 0F 84 20 01 00 00  (JZ +0x120 -> skip rendering)
  After:  90 90 90 90 90 90  (6x NOP -> fall through to rendering)

Patch 2 - Bypass container check clear (VA 0x41809E, file offset 0x1809E):
  Safety net. NOP the flag-clearing instruction for container mismatch.
  
  Before: 80 25 73 C1 45 00 00  (AND BYTE [0x45C173], 0)
  After:  90 90 90 90 90 90 90  (7x NOP)

Patch 3 - Set in-room flag in cleanup (VA 0x41B05E, file offset 0x1B05E):
  The cleanup function at VA 0x41B042 is called after each 0x0D rendering
  cycle. At 0x41B05E it has AND BYTE [0x44ED01], 0 which is REDUNDANT
  (already cleared at VA 0x414808). Replace with MOV BYTE [0x45C173], 1
  to set the in-room flag that gates the viewport renderer. Without this,
  [0x45C173] is never SET (Patch 2 only prevents clearing).
  
  Before: 80 25 01 ED 44 00 00  (AND BYTE [0x44ED01], 0 - redundant clear)
  After:  C6 05 73 C1 45 00 01  (MOV BYTE [0x45C173], 1 - set in-room flag)

Patch 4 - Bypass level byte NULL dereference + init MAP types
           (VA 0x4180BA, file offset 0x180BA):
  The rendering gate at 0x4180BA loads pointer [0x457288], dereferences it
  to read a level byte, and checks if it's ASCII '1'-'9'. But [0x457288]
  is NULL (record parser never ran), so the dereference would crash.
  
  Replace the entire 22-byte sequence (MOV EAX,[ptr] / MOV [buf],EAX /
  MOV EAX,[buf] / MOV AL,[EAX] / MOV [level],AL) with direct writes:
    - [0x4538FC] = 0x31 ('1')  -- level byte (passes range check)
    - [0x45D8F5] = 0x0E        -- TType fallback (open ground)
  
  MRADUMP showed TType=0 as the root cause of the black viewport.
  Value 0x0E is Haven open ground. Do NOT use 0x02: in SARTA.256 that
  index selects the fire/lava tile row (0x29 fill at file offset 1024).
  
  Before: A1 88 72 45 00 A3 8C 32 45 00 A1 8C 32 45 00
          8A 00 A2 FC 38 45 00  (22 bytes: ptr deref chain)
  After:  C6 05 FC 38 45 00 31  (MOV BYTE [0x4538FC], 0x31)
          C6 05 F5 D8 45 00 0E  (MOV BYTE [0x45D8F5], 0x0E)
          90 90 90 90 90 90 90 90  (8x NOP)

  Patch 5 (removed in v23): Previously NOP'd the per-cell TType copy from
  [0x4571C0]. That forced global TType=0x02 (fire). With terrain injected
  before render, the original copy instruction must run.

Patch 6 - Force session state byte for viewport rendering
           (VA 0x418100, file offset 0x18100):
  After the level check passes (Patch 4), the rendering code loads
  [0x4539F3] (rendering array slot 3, never populated) into [0x461C2D]
  (session state byte). When [0x461C2D]=0, JZ at VA 0x41811D skips the
  entire viewport drawing block (0x418123-0x4181CF), only rendering
  UI panels (stats, messages). This is why the map viewport is black
  while stats bars and messages work fine.
  
  Replace MOV AL,[0x4539F3] with MOV AL,1 so [0x461C2D]=1 and the
  viewport drawing block executes.
  
  Before: A0 F3 39 45 00 A2 2D 1C 46 00
          (MOV AL,[0x4539F3] / MOV [0x461C2D],AL -- loads 0)
  After:  B0 01 A2 2D 1C 46 00 90 90 90
          (MOV AL,1 / MOV [0x461C2D],AL / 3x NOP -- forces 1)

Patch 7 - Enable terrain-only rendering (VA 0x418ED3, file offset 0x18ED3):
  The rendering loop has a terrain-only path for cells without objects.
  This path is gated by [0x4569F8] > 1. The TType check at VA 0x418EBC
  sets [0x4569F8] based on TType: if TType==0x8A -> 3, else -> 1.
  With TType=0x0E the value is 1, so the JLE check (value <= 1) would
  skip terrain-only rendering unless we raise the default to 2.
  
  Change the default detail level from 1 to 2 so the terrain-only
  path activates. This lets the renderer draw terrain tiles from the
  terrain type table [0x4571C0] even when the object array is empty.
  
  Before: C6 05 F8 69 45 00 01  (MOV BYTE [0x4569F8], 1 -- detail=1)
  After:  C6 05 F8 69 45 00 02  (MOV BYTE [0x4569F8], 2 -- detail=2)

Patch 8 - NOP in-room flag gate (VA 0x4180AE, file offset 0x180AE):
  At VA 0x4180A5, the code loads [0x45C173] (in-room flag) and at
  VA 0x4180AE, JZ +100 skips EVERYTHING past it: the level/TType
  setup (Patch 4), session state override (Patch 6), tileset pointer
  load, and the viewport block. Without this NOP, if [0x45C173] is
  ever 0 when checked, the entire viewport pipeline is bypassed.
  
  Before: 74 64  (JZ +100 -> skip viewport setup)
  After:  90 90  (NOP NOP -> always proceed)

Patch 9 - Fix movement crash on NULL [0x461714] (VA 0x40544B, file offset 0x0544B):
  Arrow key handler at VA 0x405447 loads [0x461714] into EAX then
  executes AND BYTE [EAX], 0. When [0x461714] is NULL (no server
  initialized the movement buffer), this causes ACCESS_VIOLATION
  (0xC0000005). MRADUMP confirmed crash at VA 0x40544B on keypress.
  
  NOP the 3-byte AND instruction so movement doesn't crash when the
  buffer pointer hasn't been set yet.
  
  Before: 80 20 00  (AND BYTE [EAX], 0)
  After:  90 90 90  (3x NOP)

(v24 patch 10 was removed in v25 - see note after the PATCHES list.)
"""
import os
import sys

SRC = "MRA.EXE"
DST = "MRA_PATCHED.EXE"

PATCHES = [
    {
        'name': 'Bypass slot state check (safety net)',
        'offset': 0x17FEE,
        'expected': bytes([0x0F, 0x84, 0x20, 0x01, 0x00, 0x00]),
        'patched':  bytes([0x90, 0x90, 0x90, 0x90, 0x90, 0x90]),
        'desc_before': 'JZ +0x120 (skip all rendering)',
        'desc_after':  '6x NOP (fall through to rendering)',
    },
    {
        'name': 'Bypass container check clear (safety net)',
        'offset': 0x1809E,
        'expected': bytes([0x80, 0x25, 0x73, 0xC1, 0x45, 0x00, 0x00]),
        'patched':  bytes([0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90]),
        'desc_before': 'AND BYTE [0x45C173], 0',
        'desc_after':  '7x NOP',
    },
    {
        'name': 'Set in-room flag in cleanup function',
        'offset': 0x1B05E,
        'expected': bytes([0x80, 0x25, 0x01, 0xED, 0x44, 0x00, 0x00]),
        'patched':  bytes([0xC6, 0x05, 0x73, 0xC1, 0x45, 0x00, 0x01]),
        'desc_before': 'AND BYTE [0x44ED01], 0 (redundant clear)',
        'desc_after':  'MOV BYTE [0x45C173], 1 (set in-room flag)',
    },
    {
        'name': 'Bypass level NULL deref + set level/TType',
        'offset': 0x180BA,
        'expected': bytes([
            0xA1, 0x88, 0x72, 0x45, 0x00,   # MOV EAX, [0x457288]
            0xA3, 0x8C, 0x32, 0x45, 0x00,   # MOV [0x45328C], EAX
            0xA1, 0x8C, 0x32, 0x45, 0x00,   # MOV EAX, [0x45328C]
            0x8A, 0x00,                       # MOV AL, [EAX]
            0xA2, 0xFC, 0x38, 0x45, 0x00,   # MOV [0x4538FC], AL
        ]),
        'patched': bytes([
            0xC6, 0x05, 0xFC, 0x38, 0x45, 0x00, 0x31,  # MOV BYTE [0x4538FC], '1'
            0xC6, 0x05, 0xF5, 0xD8, 0x45, 0x00, 0x0E,  # MOV BYTE [0x45D8F5], 0x0E
            0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90,  # 8x NOP
        ]),
        'desc_before': 'Ptr deref [0x457288] -> level byte (crashes on NULL)',
        'desc_after':  'Set level=0x31, TType=0x0E, 8x NOP',
    },
    {
        'name': 'Force session state byte for viewport drawing',
        'offset': 0x18100,
        'expected': bytes([
            0xA0, 0xF3, 0x39, 0x45, 0x00,  # MOV AL, [0x4539F3]
            0xA2, 0x2D, 0x1C, 0x46, 0x00,  # MOV [0x461C2D], AL
        ]),
        'patched': bytes([
            0xB0, 0x01,                      # MOV AL, 1
            0xA2, 0x2D, 0x1C, 0x46, 0x00,  # MOV [0x461C2D], AL
            0x90, 0x90, 0x90,               # 3x NOP
        ]),
        'desc_before': 'MOV AL,[0x4539F3] / MOV [0x461C2D],AL (loads 0 from empty array)',
        'desc_after':  'MOV AL,1 / MOV [0x461C2D],AL / 3x NOP (force viewport drawing)',
    },
    {
        'name': 'Enable terrain-only rendering (detail level 1->2)',
        'offset': 0x18ED3,
        'expected': bytes([
            0xC6, 0x05, 0xF8, 0x69, 0x45, 0x00, 0x01,  # MOV BYTE [0x4569F8], 1
        ]),
        'patched': bytes([
            0xC6, 0x05, 0xF8, 0x69, 0x45, 0x00, 0x02,  # MOV BYTE [0x4569F8], 2
        ]),
        'desc_before': 'MOV BYTE [0x4569F8], 1 (terrain-only skipped: 1 <= 1)',
        'desc_after':  'MOV BYTE [0x4569F8], 2 (terrain-only enabled: 2 > 1)',
    },
    {
        'name': 'NOP in-room flag gate (belt-and-suspenders)',
        'offset': 0x180AE,
        'expected': bytes([
            0x74, 0x64,  # JZ +100 (skip to 0x418114 if [0x45C173]==0)
        ]),
        'patched': bytes([
            0x90, 0x90,  # 2x NOP (always fall through to viewport setup)
        ]),
        'desc_before': 'JZ +100 (skip viewport if in-room flag is 0)',
        'desc_after':  '2x NOP (always proceed to viewport setup)',
    },
    {
        'name': 'Fix movement crash on NULL [0x461714]',
        'offset': 0x0544B,
        'expected': bytes([
            0x80, 0x20, 0x00,  # AND BYTE [EAX], 0
        ]),
        'patched': bytes([
            0x90, 0x90, 0x90,  # 3x NOP
        ]),
        'desc_before': 'AND BYTE [EAX], 0 (crashes when [0x461714] is NULL)',
        'desc_after':  '3x NOP (skip NULL dereference on arrow key)',
    },
]
# v24 patch 10 (NOP [0x45328C]=[0x45728C] at 0x1810A) was REMOVED in v25.
# That copy is the room-tileset load the renderer needs every frame; the
# real fix is to set [0x45728C] to the loaded SARTA base (see launcher
# inject_tileset_cursor), letting this copy fill [0x45328C] with valid
# tile graphics. NOPing it left [0x45328C] pointing at the network buffer
# (0x458506), which rendered packet bytes as fire/garbage.

def main():
    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), SRC)
    dst_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), DST)
    
    if not os.path.exists(src_path):
        print(f"ERROR: {src_path} not found!")
        return False
    
    data = bytearray(open(src_path, 'rb').read())
    
    for i, patch in enumerate(PATCHES):
        off = patch['offset']
        expected = patch['expected']
        patched = patch['patched']
        
        actual = bytes(data[off:off+len(expected)])
        if actual != expected:
            print(f"ERROR: Patch {i+1} ({patch['name']}): unexpected bytes at 0x{off:X}")
            print(f"  Expected: {' '.join(f'{b:02X}' for b in expected)}")
            print(f"  Actual:   {' '.join(f'{b:02X}' for b in actual)}")
            return False
        
        data[off:off+len(patched)] = patched
        print(f"Patch {i+1}: {patch['name']}")
        print(f"  Offset 0x{off:X} (VA 0x{0x400000+off:X})")
        print(f"  Before: {' '.join(f'{b:02X}' for b in expected)}  ({patch['desc_before']})")
        print(f"  After:  {' '.join(f'{b:02X}' for b in patched)}  ({patch['desc_after']})")
    
    open(dst_path, 'wb').write(data)
    print(f"\nPatched binary written to: {dst_path}")
    print(f"Size: {len(data)} bytes ({len(PATCHES)} patches applied)")
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
