"""
MRA Launcher + Game Server Emulator v25
========================================
Launches MRA_PATCHED.EXE (bypassing OGN.EXE) with the correct command-line
arguments, and provides a local game server on port 1111.

Changes in v25 (point tileset cursor at real SARTA base):
  - Removed v24 patch 10. Diagnostics showed [0x45328C] pointed at the
    network packet buffer (0x458506), so the blit drew packet bytes as fire.
  - inject_tileset_cursor() now reads the loaded SARTA base from [0x45312C]
    and writes it to [0x45728C] (+[0x45328C]); the game's per-frame copy at
    VA 0x41810A then keeps [0x45328C] pointed at valid tile graphics.

Changes in v24 (fix fire tileset cursor NULL wipe - superseded by v25):
  - patch 10 NOP at VA 0x41810A (removed in v25)
  - Re-inject terrain/layers/cursor on movement (cmd 0x32) and all cmds

Changes in v23 (fix fire/lava tile flood):
  - patch_mra.py: TType fallback 0x02 -> 0x0E (0x02 = fire row in SARTA.256)
  - Removed patch 5 so TType follows injected terrain table per cell
  - Enter-game subcmd 0x30/0x31 use 0x0E (layer index 0, not 1)
  - v22: uniform 0x0E terrain, player placement, elevation error hint

MRA.EXE command line format:
  <5-digit-account><server-char><account-name>
  Server char 'L' = localhost 127.0.0.1:1111
"""

import socket
import subprocess
import threading
import time
import sys
import os
import struct
import ctypes
from ctypes import wintypes
from datetime import datetime

from map256_decoder import MAP256, load_haven_terrain

# ============================================================
#  Config
# ============================================================
MRA_EXE      = "MRA_PATCHED.EXE"
SERVER_HOST  = "0.0.0.0"
SERVER_PORT  = 1111
ACCOUNT_NUM  = "10481"          # 5-digit OGN account number
SERVER_CHAR  = "L"              # 'L' = localhost 127.0.0.1:1111
ACCOUNT_NAME = "Player1"        # account name (arbitrary)

# Direction markers
DIR_CLIENT = 0xAE   # client -> server
DIR_SERVER = 0xAF   # server -> client

def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def hexdump(data, prefix="  "):
    """Pretty hex dump of bytes."""
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hexpart = ' '.join(f'{b:02X}' for b in chunk)
        ascpart = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f'{prefix}{i:04X}: {hexpart:<48}  {ascpart}')
    return '\n'.join(lines)

# ============================================================
#  Process Memory Writer (for terrain table injection)
# ============================================================

# Windows API constants
PROCESS_VM_WRITE     = 0x0020
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ      = 0x0010
PROCESS_ALL_ACCESS   = 0x1F0FFF
MEM_COMMIT           = 0x1000
MEM_RESERVE          = 0x2000
PAGE_READWRITE       = 0x04

# Terrain type table: 13x13 grid at VA 0x4571C0 (BSS, 169 bytes)
TERRAIN_TABLE_VA = 0x4571C0
TERRAIN_TABLE_SIZE = 169  # 13 * 13

# Room data pointer: VA 0x457288 (BSS, 4 bytes - pointer to room record)
ROOM_DATA_PTR_VA = 0x457288
# Movement buffer pointer: VA 0x461714 (crashes on arrow key if NULL)
MOVEMENT_BUF_PTR_VA = 0x461714
# Room index byte: VA 0x4531B0
ROOM_INDEX_VA = 0x4531B0
# Terrain data buffer: VA 0x458420 (169 bytes, mirror of terrain table)
TERRAIN_BUFFER_VA = 0x458420

# Object array: 13x13 cells, stride row*52 + col*4 at VA 0x456D20
OBJECT_ARRAY_VA = 0x456D20
OBJECT_ROW_STRIDE = 52
OBJECT_COL_STRIDE = 4

# Terrain layer indices written by subcmd 0x30
TERRAIN_LAYER_IDX_VA = 0x45D909
OVERLAY_LAYER_IDX_VA = 0x456FD6
HAVEN_START_COL = 12
HAVEN_START_ROW = 10
# Player position from MRADUMP Haven session (MAP: x=12, y=10)
PLAYER_POS_X_VA = 0x453370
PLAYER_POS_Y_VA = 0x4538B5
# Tileset pointers. The viewport blit reads terrain graphics from
# [0x45328C]. Render setup at VA 0x41810A copies [0x45728C] -> [0x45328C]
# every frame, but [0x45728C] (per-room tileset base) is only set by the
# real room loader, which we bypass. SARTA's loaded base lives in [0x45312C].
SARTA_BASE_VA = 0x45312C   # set once by SARTA loader at VA 0x407072
TILESET_SRC_VA = 0x45728C  # per-room tileset base (renderer copies this)
TILESET_PTR_VA = 0x45328C  # live tileset cursor the blit reads from

_map_decoder = None

def get_map_decoder():
    global _map_decoder
    if _map_decoder is None:
        map_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'MAP.256')
        _map_decoder = MAP256(map_path)
    return _map_decoder

def open_process_all(pid):
    """Open process with full access for VirtualAllocEx."""
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not handle:
        err = ctypes.get_last_error()
        print(f"[{ts()}]   OpenProcess failed (error {err})")
    return kernel32, handle

def write_process_memory_ex(handle, address, data):
    """Write data using an existing process handle."""
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    buf = ctypes.create_string_buffer(data)
    written = ctypes.c_size_t(0)
    result = kernel32.WriteProcessMemory(
        handle, ctypes.c_void_p(address), buf, len(data), ctypes.byref(written)
    )
    if not result:
        err = ctypes.get_last_error()
        print(f"[{ts()}]   WriteProcessMemory failed at 0x{address:08X} (error {err})")
        return False
    return True

def write_process_memory(pid, address, data):
    """Write data to a running process's memory via Windows API.
    
    Returns True on success, False on failure.
    """
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    
    handle = kernel32.OpenProcess(
        PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
        False,
        pid
    )
    if not handle:
        err = ctypes.get_last_error()
        print(f"[{ts()}]   OpenProcess failed (error {err})")
        return False
    
    try:
        buf = ctypes.create_string_buffer(data)
        written = ctypes.c_size_t(0)
        result = kernel32.WriteProcessMemory(
            handle,
            ctypes.c_void_p(address),
            buf,
            len(data),
            ctypes.byref(written)
        )
        if not result:
            err = ctypes.get_last_error()
            print(f"[{ts()}]   WriteProcessMemory failed (error {err})")
            return False
        print(f"[{ts()}]   Wrote {written.value} bytes to VA 0x{address:08X}")
        return True
    finally:
        kernel32.CloseHandle(handle)

def inject_render_layers(pid):
    """Set terrain/overlay layer indices to 0 (subcmd 0x30 defaults were 1)."""
    write_process_memory(pid, TERRAIN_LAYER_IDX_VA, bytes([0]))
    write_process_memory(pid, OVERLAY_LAYER_IDX_VA, bytes([0]))

def inject_tileset_cursor(pid):
    """Point the room tileset cursor at the loaded SARTA tileset base.

    The viewport blit reads terrain graphics from [0x45328C]. Render setup at
    VA 0x41810A copies [0x45728C] -> [0x45328C] each frame, but [0x45728C]
    (per-room tileset base) is only set by the real room loader, which we
    bypass. We read the loaded SARTA base from [0x45312C] and write it to
    [0x45728C] (so the frame copy fills [0x45328C]) and to [0x45328C] directly
    for the current frame. Without this the cursor pointed at the network
    buffer (0x458506), rendering packet bytes as fire/garbage.
    """
    base = read_process_memory(pid, SARTA_BASE_VA, 4)
    if not base:
        print(f"[{ts()}]   Tileset cursor: could not read SARTA base [0x45312C]")
        return
    addr = int.from_bytes(base, 'little')
    if addr == 0:
        print(f"[{ts()}]   Tileset cursor: SARTA base NULL (tilesets not loaded)")
        return
    val = struct.pack('<I', addr)
    write_process_memory(pid, TILESET_SRC_VA, val)
    write_process_memory(pid, TILESET_PTR_VA, val)
    print(f"[{ts()}]   Tileset cursor -> SARTA base 0x{addr:08X}")

def inject_render_state(pid, room_id=0):
    """Refresh terrain table, layer indices, and tileset cursor."""
    inject_terrain_data(pid, room_id)
    inject_render_layers(pid)
    inject_tileset_cursor(pid)

def inject_player_object(pid, row=HAVEN_START_ROW, col=HAVEN_START_COL):
    """Place a minimal player object on the room grid.

    Disabled for now: byte at [obj+0x0B]=0xA1 was rendering as a lone fire
    tile in the viewport center. Re-enable once CRT/OBJ sprite ids are known.
    """
    print(f"[{ts()}] === Skipping player object inject (sprite id unknown) ===")
    write_process_memory(pid, PLAYER_POS_X_VA, bytes([col]))
    write_process_memory(pid, PLAYER_POS_Y_VA, bytes([row]))
    return True

def inject_terrain_data(pid, room_id=0):
    """Fill terrain tables from MAP.256 decoded room data."""
    print(f"[{ts()}] === Injecting MAP.256 terrain for room {room_id} (PID {pid}) ===")
    
    try:
        decoder = get_map_decoder()
        terrain = decoder.terrain_grid_flat(room_id)
        info = decoder.decode_room_info(room_id)
        print(f"[{ts()}]   Decoded: {info['row_templates']} row templates, "
              f"{info['non_default_cells']} non-default cells")
    except Exception as e:
        print(f"[{ts()}]   MAP.256 decode failed: {e}, using 0x0E fill")
        terrain = bytes([0x0E] * TERRAIN_TABLE_SIZE)
    
    success = write_process_memory(pid, TERRAIN_TABLE_VA, terrain)
    if success:
        # Also mirror into terrain buffer used by renderer
        write_process_memory(pid, TERRAIN_BUFFER_VA, terrain)
        # Show first row for verification
        row0 = ' '.join(f'{b:02X}' for b in terrain[:13])
        print(f"[{ts()}]   Terrain row 0: {row0}")
    else:
        print(f"[{ts()}]   WARNING: Failed to inject terrain data!")
    
    return success

def allocate_room_data(pid, room_id=0):
    """Allocate room record from MAP.256 in process memory."""
    print(f"[{ts()}] === Allocating room data for room {room_id} (PID {pid}) ===")
    
    kernel32, handle = open_process_all(pid)
    if not handle:
        return False
    
    try:
        decoder = get_map_decoder()
        room_bytes = bytearray(decoder.get_room_bytes(room_id))
        # Ensure level byte at offset 0 is ASCII '1'
        if len(room_bytes) > 0:
            room_bytes[0] = 0x31
        
        alloc_size = max(4096, len(room_bytes) + 256)
        alloc_addr = kernel32.VirtualAllocEx(
            handle, None, alloc_size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        if not alloc_addr:
            print(f"[{ts()}]   VirtualAllocEx failed (error {ctypes.get_last_error()})")
            return False
        
        print(f"[{ts()}]   Allocated {alloc_size} bytes at VA 0x{alloc_addr:08X}")
        
        # Zero-fill then write room record
        room_buf = bytes(room_bytes) + bytes(alloc_size - len(room_bytes))
        if not write_process_memory_ex(handle, alloc_addr, room_buf[:alloc_size]):
            return False
        
        print(f"[{ts()}]   Wrote {len(room_bytes)} bytes of MAP.256 room {room_id} data")
        
        # Set [0x457288] = allocated buffer
        if not write_process_memory_ex(handle, ROOM_DATA_PTR_VA, struct.pack('<I', alloc_addr)):
            return False
        print(f"[{ts()}]   Set [0x457288] = 0x{alloc_addr:08X}")
        
        # Set room index [0x4531B0] = room_id
        write_process_memory_ex(handle, ROOM_INDEX_VA, bytes([room_id]))
        print(f"[{ts()}]   Set [0x4531B0] = {room_id}")
        
        return True
    finally:
        kernel32.CloseHandle(handle)

def allocate_movement_buffer(pid):
    """Allocate movement command buffer at [0x461714]."""
    print(f"[{ts()}] === Allocating movement buffer (PID {pid}) ===")
    
    kernel32, handle = open_process_all(pid)
    if not handle:
        return False
    
    try:
        alloc_size = 4096
        alloc_addr = kernel32.VirtualAllocEx(
            handle, None, alloc_size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        if not alloc_addr:
            print(f"[{ts()}]   VirtualAllocEx failed (error {ctypes.get_last_error()})")
            return False
        
        # Zero-filled buffer (safe defaults)
        buf = bytes(alloc_size)
        if not write_process_memory_ex(handle, alloc_addr, buf):
            return False
        
        if not write_process_memory_ex(handle, MOVEMENT_BUF_PTR_VA, struct.pack('<I', alloc_addr)):
            return False
        
        print(f"[{ts()}]   Set [0x461714] = 0x{alloc_addr:08X} ({alloc_size} bytes)")
        return True
    finally:
        kernel32.CloseHandle(handle)

def read_process_memory(pid, address, size):
    """Read data from a running process's memory via Windows API.
    
    Returns bytes on success, None on failure.
    """
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    
    handle = kernel32.OpenProcess(
        PROCESS_VM_READ | PROCESS_VM_OPERATION,
        False,
        pid
    )
    if not handle:
        err = ctypes.get_last_error()
        print(f"[{ts()}]   ReadProcessMemory OpenProcess failed (error {err})")
        return None
    
    try:
        buf = ctypes.create_string_buffer(size)
        read_count = ctypes.c_size_t(0)
        result = kernel32.ReadProcessMemory(
            handle,
            ctypes.c_void_p(address),
            buf,
            size,
            ctypes.byref(read_count)
        )
        if not result:
            err = ctypes.get_last_error()
            print(f"[{ts()}]   ReadProcessMemory failed at 0x{address:08X} (error {err})")
            return None
        return buf.raw[:read_count.value]
    finally:
        kernel32.CloseHandle(handle)

def diagnose_rendering(pid):
    """Read key rendering variables from the running MRA process and log them."""
    print(f"[{ts()}] === Rendering diagnostics (PID {pid}) ===")
    
    checks = [
        # (name, VA, size, format)
        ("Terrain table [0x4571C0] row0", 0x4571C0, 13, "hex"),
        ("Object array [0x456D20] slot0", 0x456D20, 16, "hex"),
        ("Tileset ptr [0x45328C]",        0x45328C, 4,  "ptr"),
        ("SARTA base [0x45312C]",         0x45312C, 4,  "ptr"),
        ("Room data ptr [0x457288]",      0x457288, 4,  "ptr"),
        ("Tileset src [0x45728C]",        0x45728C, 4,  "ptr"),
        ("Detail flag [0x4569F8]",        0x4569F8, 1,  "byte"),
        ("TType [0x45D8F5]",             0x45D8F5, 1,  "byte"),
        ("Terrain layer [0x45D909]",     0x45D909, 1,  "byte"),
        ("Level byte [0x4538FC]",         0x4538FC, 1,  "byte"),
        ("Session state [0x461C2D]",      0x461C2D, 1,  "byte"),
        ("Terrain flags [0x4490D8]",      0x4490D8, 4,  "hex"),
        ("Slot1 state [0x4539F1]",        0x4539F1, 1,  "byte"),
        ("In-room flag [0x45C173]",       0x45C173, 1,  "byte"),
        ("Row counter [0x45EA34]",        0x45EA34, 2,  "hex"),
        ("Col counter [0x461C7C]",        0x461C7C, 2,  "hex"),
    ]
    
    for name, va, size, fmt in checks:
        data = read_process_memory(pid, va, size)
        if data is None:
            print(f"[{ts()}]   {name}: READ FAILED")
            continue
        
        if fmt == "ptr":
            val = int.from_bytes(data, 'little')
            print(f"[{ts()}]   {name}: 0x{val:08X}" + (" (NULL!)" if val == 0 else ""))
        elif fmt == "byte":
            print(f"[{ts()}]   {name}: 0x{data[0]:02X} ({data[0]})")
        else:
            hex_str = ' '.join(f'{b:02X}' for b in data)
            print(f"[{ts()}]   {name}: {hex_str}")
    
    terrain = read_process_memory(pid, TERRAIN_TABLE_VA, TERRAIN_TABLE_SIZE)
    if terrain:
        nonzero = sum(1 for b in terrain if b != 0)
        unique = sorted(set(terrain))
        print(f"[{ts()}]   Terrain table: {nonzero}/169 non-zero cells, "
              f"unique types: {' '.join(f'{b:02X}' for b in unique[:8])}")

    # Dereference tileset bases: confirm real .256 graphics are loaded there
    print(f"[{ts()}]   --- Tileset base dereferences ---")
    for name, ptr_va in [("SARTA [0x45312C]", 0x45312C),
                         ("Scratch [0x45328C]", 0x45328C),
                         ("Src [0x45728C]", 0x45728C)]:
        ptr = read_process_memory(pid, ptr_va, 4)
        if not ptr:
            print(f"[{ts()}]   {name}: ptr READ FAILED")
            continue
        addr = int.from_bytes(ptr, 'little')
        if addr == 0:
            print(f"[{ts()}]   {name} -> NULL")
            continue
        blob = read_process_memory(pid, addr, 24)
        if blob:
            print(f"[{ts()}]   {name} -> 0x{addr:08X}: "
                  f"{' '.join(f'{b:02X}' for b in blob)}")
        else:
            print(f"[{ts()}]   {name} -> 0x{addr:08X}: deref READ FAILED")

    # Terrain detail class selectors used by the per-cell draw dispatch
    for name, va, size in [("Terrain class [0x45EA94]", 0x45EA94, 1),
                          ("Detail flag [0x4569F8]", 0x4569F8, 1),
                          ("TType class [0x45EA52]", 0x45EA52, 1)]:
        b = read_process_memory(pid, va, size)
        if b:
            print(f"[{ts()}]   {name}: {' '.join(f'{x:02X}' for x in b)}")
    
    # Verify patch bytes in process memory (code section)
    print(f"[{ts()}]   --- Patch verification in process memory ---")
    patch_checks = [
        ("Patch 1 (NOP slot check)",   0x417FEE, bytes([0x90]*6)),
        ("Patch 4 (level+TType)",      0x4180BA, bytes([0xC6,0x05,0xFC,0x38,0x45,0x00,0x31,0xC6,0x05,0xF5,0xD8,0x45,0x00,0x0E])),
        ("Patch 6 (session=1)",        0x418100, bytes([0xB0,0x01,0xA2,0x2D])),
        ("Patch 7 (detail=2)",         0x418ED3, bytes([0xC6,0x05,0xF8,0x69,0x45,0x00,0x02])),
        ("Patch 8 (NOP in-room JZ)",   0x4180AE, bytes([0x90,0x90])),
        ("Patch 9 (movement crash)",   0x40544B, bytes([0x90,0x90,0x90])),
    ]
    for name, va, expected in patch_checks:
        data = read_process_memory(pid, va, len(expected))
        if data is None:
            print(f"[{ts()}]   {name}: READ FAILED")
            continue
        match = "OK" if data == expected else "MISMATCH!"
        hex_str = ' '.join(f'{b:02X}' for b in data)
        print(f"[{ts()}]   {name} @ 0x{va:08X}: {hex_str} [{match}]")
        if data != expected:
            exp_str = ' '.join(f'{b:02X}' for b in expected)
            print(f"[{ts()}]     Expected: {exp_str}")

# ============================================================
#  MRA SGN Protocol
# ============================================================

def compute_checksum(payload):
    """Compute MRA's 2-byte checksum over payload bytes.
    
    Sums only COMPLETE 2-byte little-endian words in payload.
    If payload has odd length, last byte is NOT included in sum.
    This matches MRA's code: half_count = (total_len - 8) / 2 (integer div).
    
    Then:
      check1 = (sum % 241) + 14
      check2 = ((sum // 241) % 241) + 14
    """
    word_sum = 0
    num_words = len(payload) // 2  # only complete words, ignore trailing byte
    for i in range(num_words):
        word = payload[i*2] | (payload[i*2+1] << 8)  # little-endian
        word_sum += word
    # Keep as 16-bit
    word_sum &= 0xFFFF
    
    check1 = (word_sum % 241) + 14
    check2 = ((word_sum // 241) % 241) + 14
    return check1, check2

def build_sgn_server(payload):
    """Build a server->client SGN message with proper header and checksum.
    
    payload = raw payload bytes (command byte + data), placed at byte 8+.
    Returns complete message bytes.
    """
    # Total message length = 8 (header) + payload
    total_length = 8 + len(payload)
    
    # Base-94 encode length (base 0x20)
    len_lo = (total_length % 94) + 0x20
    len_hi = (total_length // 94) + 0x20
    
    # Compute checksum over payload
    check1, check2 = compute_checksum(payload)
    
    # Build message
    msg = bytearray()
    msg += b'SGN'                          # bytes 0-2: magic
    msg.append(DIR_SERVER)                 # byte 3: direction
    msg.append(len_lo)                     # byte 4: length low
    msg.append(len_hi)                     # byte 5: length high
    msg.append(check1 & 0xFF)             # byte 6: checksum 1
    msg.append(check2 & 0xFF)             # byte 7: checksum 2
    msg += payload                         # bytes 8+: payload
    
    return bytes(msg)

def decode_sgn(data):
    """Decode an incoming SGN message from MRA."""
    if len(data) < 8 or data[0:3] != b'SGN':
        return None
    
    direction = data[3]
    len_lo = data[4] - 0x20
    len_hi = data[5] - 0x20
    total_length = len_hi * 94 + len_lo
    
    check1_recv = data[6]
    check2_recv = data[7]
    
    payload = data[8:] if len(data) > 8 else b''
    command = payload[0] if len(payload) > 0 else None
    
    # Verify checksum
    check1_calc, check2_calc = compute_checksum(payload)
    checksum_ok = (check1_recv == check1_calc and check2_recv == check2_calc)
    
    return {
        'direction': direction,
        'total_length': total_length,
        'actual_length': len(data),
        'checksum_recv': (check1_recv, check2_recv),
        'checksum_calc': (check1_calc, check2_calc),
        'checksum_ok': checksum_ok,
        'command': command,
        'payload': payload,
        'payload_data': payload[1:] if len(payload) > 1 else b''
    }

# ============================================================
#  Game Server
# ============================================================
class MRAServer:
    """Game server emulator for MRA.EXE.
    
    Protocol flow:
    1. MRA connects to server on port 1111
    2. Server sends raw byte 0x01 (session init signal)
    3. MRA sends SGN with cmd 0x26 (session request with account info)
    4. Server responds with SGN messages containing game state
    """
    
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self.running = False
        self.client = None
        self.mra_pid = None  # Set after launch for WriteProcessMemory
    
    def start(self):
        """Start listening for connections."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(1)
        self.sock.settimeout(1.0)
        self.running = True
        print(f"[{ts()}] Game server listening on {self.host}:{self.port}")
    
    def accept_client(self):
        """Wait for MRA to connect."""
        print(f"[{ts()}] Waiting for MRA.EXE to connect...")
        while self.running:
            try:
                conn, addr = self.sock.accept()
                print(f"[{ts()}] *** MRA.EXE connected from {addr[0]}:{addr[1]} ***")
                self.client = conn
                return conn
            except socket.timeout:
                continue
        return None
    
    def handle_client(self, conn):
        """Handle MRA.EXE's connection with proper SGN protocol.
        
        Uses buffer-based TCP stream reassembly to handle:
        - Multiple SGN messages in a single recv()
        - Partial messages split across recv() calls
        - Non-SGN data between messages
        """
        conn.settimeout(2.0)
        pkt_num = 0
        recv_buffer = bytearray()  # TCP stream reassembly buffer
        
        # --- Phase 1: Send session init handshake ---
        time.sleep(0.5)
        print(f"\n[{ts()}] === PHASE 1: Sending session init byte 0x01 ===")
        try:
            conn.send(b'\x01')
        except Exception as e:
            print(f"[{ts()}] Send failed: {e}")
            return
        
        # --- Phase 2: Wait for MRA's SGN session request ---
        print(f"[{ts()}] === PHASE 2: Waiting for SGN session request ===")
        
        while self.running:
            try:
                data = conn.recv(4096)
                if not data:
                    print(f"[{ts()}] MRA.EXE disconnected")
                    break
                
                recv_buffer += data
                
                # Process all complete SGN messages in the buffer
                while len(recv_buffer) >= 8:
                    # Look for SGN header
                    sgn_pos = recv_buffer.find(b'SGN')
                    if sgn_pos < 0:
                        # No SGN header found
                        if len(recv_buffer) > 0:
                            print(f"[{ts()}] Non-SGN data ({len(recv_buffer)}b): {bytes(recv_buffer[:20]).hex()}")
                        recv_buffer.clear()
                        break
                    
                    # Skip any non-SGN prefix bytes
                    if sgn_pos > 0:
                        prefix = recv_buffer[:sgn_pos]
                        print(f"[{ts()}] Non-SGN prefix ({len(prefix)}b): {bytes(prefix).hex()}")
                        recv_buffer = recv_buffer[sgn_pos:]
                    
                    # Need at least 6 bytes to read the length field
                    if len(recv_buffer) < 6:
                        break  # Wait for more data
                    
                    # Decode message length from header
                    len_lo = recv_buffer[4] - 0x20
                    len_hi = recv_buffer[5] - 0x20
                    total_length = len_hi * 94 + len_lo
                    
                    # Sanity check length
                    if total_length < 8 or total_length > 4096:
                        print(f"[{ts()}] Invalid SGN length {total_length}, skipping header")
                        recv_buffer = recv_buffer[3:]  # Skip past 'SGN'
                        continue
                    
                    # Wait for complete message
                    if len(recv_buffer) < total_length:
                        break  # Need more data
                    
                    # Extract the complete message
                    msg = bytes(recv_buffer[:total_length])
                    recv_buffer = recv_buffer[total_length:]
                    
                    # Process this single SGN message
                    pkt_num += 1
                    print(f"\n[{ts()}] === RECEIVED #{pkt_num} ({len(msg)} bytes) ===")
                    print(hexdump(msg))
                    
                    info = decode_sgn(msg)
                    if info:
                        dir_str = "C->S" if info['direction'] == DIR_CLIENT else "S->C"
                        cmd_str = f"0x{info['command']:02X}" if info['command'] is not None else "none"
                        print(f"[{ts()}] SGN [{dir_str}] cmd={cmd_str} "
                              f"len={info['total_length']} "
                              f"chk={info['checksum_ok']} "
                              f"payload={len(info['payload'])}b")
                        if not info['checksum_ok']:
                            print(f"[{ts()}]   checksum MISMATCH: "
                                  f"recv={info['checksum_recv']} "
                                  f"calc={info['checksum_calc']}")
                    
                    # Respond to SGN with proper format
                    responses = self.handle_sgn(msg, info, pkt_num)
                    for resp in responses:
                        print(f"\n[{ts()}] === SENDING response ({len(resp)} bytes) ===")
                        print(hexdump(resp))
                        verify = decode_sgn(resp)
                        if verify:
                            state = verify['command']
                            print(f"[{ts()}]   Self-check: "
                                  f"state=0x{state:02X} chk={verify['checksum_ok']}")
                        conn.send(resp)
                        time.sleep(0.05)  # small delay between messages
                    
            except socket.timeout:
                continue
            except ConnectionResetError:
                print(f"[{ts()}] MRA.EXE disconnected (reset)")
                break
            except Exception as e:
                print(f"[{ts()}] Error: {e}")
                import traceback
                traceback.print_exc()
                break
        
        conn.close()
        print(f"[{ts()}] Connection closed")
    
    def handle_sgn(self, raw_data, info, pkt_num):
        """Handle incoming SGN message, return list of SGN responses.
        
        TWO-PHASE PROTOCOL:
        
        A) CONTROL CODES (0x01-0x1F): Session state management.
           - 0x02 -> session setup acknowledgment
        
        B) GAME DATA (0x20-0x7E): Requires guard flag [0x4490C4]!=0.
           - 0x21: Enter game (room ID + sub-commands for terrain, level)
        
        Strategy:
          Phase 1: Control code 0x02 (session setup)
          Phase 2: Command 0x21 (enter game with sub-cmds 0x20/0x30/0x31/0x2F)
          Phase 3+: Sub-commands 0x30 + 0x0D (maintain terrain state)
        """
        if not info or info['command'] is None:
            return []
        
        cmd = info['command']
        responses = []
        
        if cmd == 0x26:
            # Session init request from MRA
            print(f"[{ts()}] >> Session init request (cmd 0x26)")
            print(f"[{ts()}]    Account data: {info['payload_data']}")
            
            # PHASE 1: Send control code to confirm session
            print(f"[{ts()}] >> Phase 1: Control code 0x02 (session setup)")
            payload1 = bytearray()
            payload1.append(0x02)        # Control code: session response
            payload1.append(0x00)        # Null terminator
            resp1 = build_sgn_server(payload1)
            responses.append(resp1)
            
            # PHASE 2: Send game data command 0x21 (enter game)
            room_id = 0  # Haven
            print(f"[{ts()}] >> Phase 2: Game data 0x21 (enter game, room={room_id})")
            payload2 = self.build_enter_game_payload(room_id)
            resp2 = build_sgn_server(payload2)
            responses.append(resp2)
            
            # PHASE 3: Inject MAP.256 room/terrain data into process memory
            if self.mra_pid:
                time.sleep(0.5)  # Let enter-game process and tilesets load
                
                room_id = 0  # Haven
                allocate_room_data(self.mra_pid, room_id)
                allocate_movement_buffer(self.mra_pid)
                inject_render_state(self.mra_pid, room_id)
                inject_player_object(self.mra_pid)
                time.sleep(0.2)
                inject_render_state(self.mra_pid, room_id)
                
                time.sleep(0.3)
                diagnose_rendering(self.mra_pid)
        
        elif cmd in (0x2E, 0x2F, 0x30):
            # In-game data requests
            cmd_names = {0x2E: 'refresh', 0x2F: 'command', 0x30: 'game data'}
            print(f"[{ts()}] >> {cmd_names.get(cmd, 'unknown')} request (cmd 0x{cmd:02X})")
            print(f"[{ts()}]    Payload: {info['payload_data'].hex() if info['payload_data'] else 'empty'}")
            
            if self.mra_pid:
                inject_render_state(self.mra_pid, 0)
            
            # Send bare 0x0D rendering trigger (no sub-cmds outside 0x21)
            print(f"[{ts()}] >> Responding with render trigger (0x0D)")
            payload = self.build_room_state_payload(room_id=0)
            resp = build_sgn_server(payload)
            responses.append(resp)
        
        elif cmd == 0x32:
            print(f"[{ts()}] >> Movement/update request (cmd 0x32)")
            print(f"[{ts()}]    Payload: {info['payload_data'].hex() if info['payload_data'] else 'empty'}")
            if self.mra_pid:
                inject_render_state(self.mra_pid, 0)
            payload = self.build_room_state_payload(room_id=0)
            resp = build_sgn_server(payload)
            responses.append(resp)
        
        else:
            print(f"[{ts()}] >> Other command 0x{cmd:02X}")
            print(f"[{ts()}]    Payload: {info['payload_data'].hex() if info['payload_data'] else 'empty'}")
            if self.mra_pid:
                inject_render_state(self.mra_pid, 0)
            # Respond with render trigger to keep game alive
            payload = self.build_room_state_payload(room_id=0)
            resp = build_sgn_server(payload)
            responses.append(resp)
        
        return responses
    
    def build_enter_game_payload(self, room_id):
        """Build a properly formatted 0x21 (enter game) payload.
        
        Format (from disassembly of MRA.EXE):
        
        Section 1 - Header (VA 0x408CC5):
          Byte 0:    0x21 (command byte - triggers enter-game handler)
          Bytes 1-4: Room ID encoded as 4 bytes base-241
          Bytes 5+:  Null-terminated text strings, ended by 0x00
        
        Section 2 - Game State Sub-commands (VA 0x412A2D dispatcher):
          Sub-command 0x20 (position, 9 data bytes)
          Sub-command 0x30 (terrain type + overlay, 2 bytes)
          Sub-command 0x31 (container/room layer types, 2 bytes)
          Sub-command 0x2F (file load + level setup, variable)
          Terminated by 0x00
        
        Section 3 - Buffer flush:
          Bare 0x0D flushes sub-command contamination and triggers
          cleanup which sets [0x45C173] = 1 (in-room flag, Patch 3).
        """
        payload = bytearray()
        
        # --- Section 1: Enter game header ---
        payload.append(0x21)                        # Command byte: enter game
        payload += self.encode_base241(room_id)     # Room ID (4 bytes)
        payload.append(0x00)                        # End of text section
        
        # --- Section 2: Game state sub-commands ---
        # Sub-command 0x20: Position and state data (9 bytes)
        # byte0 -> [0x45D900] raw; byte1 -> flag + [0x460B58]
        # byte3 -> [0x453370] (x/col); byte4 -> [0x4538B5] (y/row)
        payload.append(0x20)
        payload.append(0x0E)                                    # state byte
        payload.append(0x0E)                                    # flag=0, aux=0
        payload.append(0x0E)                                    # aux2=0
        payload.append(0x0E + HAVEN_START_COL)                  # x = 12
        payload.append(0x0E + HAVEN_START_ROW)                  # y = 10
        for _ in range(4):
            payload.append(0x0E)
        
        # Sub-command 0x30: Terrain type + overlay byte (2 bytes)
        # Handler at VA 0x412E9D:
        #   byte1 - 0x0E → [0x45D909] (terrain index, used by map renderer)
        #   byte2 - 0x0E → [0x456FD6] (overlay/obj index, used by renderer)
        # Also sets [0x453C06] = 1 (render-needed flag)
        payload.append(0x30)
        payload.append(0x0E)                        # [0x45D909] = 0
        payload.append(0x0E)                        # [0x456FD6] = 0
        
        # Sub-command 0x31: Room layer types (2 bytes)
        payload.append(0x31)
        payload.append(0x0E)                        # [0x461D16] = 0
        payload.append(0x0E)                        # [0x453A6F] = 0
        
        # Sub-command 0x2F: File load + level/state setup
        payload.append(0x2F)                        # Sub-cmd: tile/file ops
        payload.append(0x61)                        # State byte 'a'
        payload.append(0x31)                        # Level byte: ASCII '1'
        payload += bytearray([0x0E] * 16)           # Padding for inline reads
        payload.append(0x00)                        # End of sub-commands
        
        # --- Section 3: Flush buffer + set in-room flag ---
        payload.append(0x0D)                        # Flush + cleanup sets flag
        
        return payload
    
    def build_room_state_payload(self, room_id):
        """Build a minimal room state response.
        
        IMPORTANT: Sub-commands (0x20-0x33) only work inside the 0x21
        enter-game handler's dispatcher at VA 0x412A2D. Outside that
        context, the main loop processes each byte individually:
          - Bytes >= 0x20: game data text → written to display buffer
          - Bytes < 0x20: control codes → dispatched (0x0F = "You parry"!)
          - 0x0D: triggers rendering function
        
        So we just send a bare 0x0D to trigger a rendering cycle without
        injecting any garbage text or control codes.
        """
        payload = bytearray()
        payload.append(0x0D)                        # Trigger rendering cycle
        return payload
    
    def encode_base241(self, value):
        """Encode a value as 4 bytes using MRA's base-241 format.
        
        Each byte = digit + 14 (offset).
        value = (b[0]-14) + (b[1]-14)*241 + (b[2]-14)*241^2 + (b[3]-14)*241^3
        """
        result = bytearray(4)
        remaining = value
        for i in range(4):
            digit = remaining % 241
            result[i] = digit + 14
            remaining //= 241
        return result
    
    def stop(self):
        self.running = False
        if self.client:
            try:
                self.client.close()
            except:
                pass
        if self.sock:
            self.sock.close()

# ============================================================
#  MRA Launcher
# ============================================================
def launch_mra():
    """Launch MRA.EXE with correct command line arguments."""
    
    # Build args: <5-digit-account><server-char><account-name>
    args = ACCOUNT_NUM + SERVER_CHAR + ACCOUNT_NAME
    
    # Full command line
    cmdline = f"{MRA_EXE} {args}"
    
    print(f"[{ts()}] Launching: {cmdline}")
    print(f"[{ts()}]   Account: '{ACCOUNT_NUM}'")
    print(f"[{ts()}]   Server:  '{SERVER_CHAR}' (localhost:{SERVER_PORT})")
    print(f"[{ts()}]   Name:    '{ACCOUNT_NAME}'")
    print(f"[{ts()}]   Args length: {len(args)} (need >= 7)")
    
    # Get the directory containing MRA.EXE
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mra_path = os.path.join(script_dir, MRA_EXE)
    
    if not os.path.exists(mra_path):
        print(f"[{ts()}] ERROR: {mra_path} not found!")
        return None
    
    try:
        proc = subprocess.Popen(
            [mra_path, args],
            cwd=script_dir,
            creationflags=0
        )
        print(f"[{ts()}] MRA.EXE started (PID: {proc.pid})")
        return proc
    except OSError as e:
        print(f"[{ts()}] Failed to launch MRA.EXE: {e}")
        if getattr(e, 'winerror', None) == 740:
            print(f"[{ts()}]   Run your terminal as Administrator (WriteProcessMemory needs elevation).")
        return None
    except Exception as e:
        print(f"[{ts()}] Failed to launch MRA.EXE: {e}")
        return None

# ============================================================
#  Main
# ============================================================
def main():
    print("=" * 60)
    print("  MRA Launcher + Game Server v25 (tileset cursor -> SARTA base)")
    print(f"  Server: 127.0.0.1:{SERVER_PORT}")
    print(f"  Args:   {ACCOUNT_NUM}{SERVER_CHAR}{ACCOUNT_NAME}")
    print("=" * 60)
    print()
    
    # Start server first
    server = MRAServer(SERVER_HOST, SERVER_PORT)
    try:
        server.start()
    except OSError as e:
        print(f"[{ts()}] ERROR: Cannot bind port {SERVER_PORT}: {e}")
        print(f"[{ts()}] Make sure no other server is running on this port!")
        return
    
    # Small delay then launch MRA
    time.sleep(0.5)
    mra_proc = launch_mra()
    
    if not mra_proc:
        server.stop()
        return
    
    # Store PID for terrain injection via WriteProcessMemory
    server.mra_pid = mra_proc.pid
    
    # Wait for MRA to connect
    conn = server.accept_client()
    
    if conn:
        # Handle the connection
        try:
            server.handle_client(conn)
        except KeyboardInterrupt:
            print(f"\n[{ts()}] Interrupted by user")
    else:
        print(f"[{ts()}] MRA.EXE did not connect")
    
    # Check if MRA is still running
    poll = mra_proc.poll()
    if poll is not None:
        print(f"[{ts()}] MRA.EXE exited with code {poll}")
    else:
        print(f"[{ts()}] MRA.EXE is still running (PID: {mra_proc.pid})")
        print(f"[{ts()}] Press Ctrl+C to stop server")
        try:
            mra_proc.wait()
        except KeyboardInterrupt:
            pass
    
    server.stop()
    print(f"\n[{ts()}] Done.")

if __name__ == "__main__":
    main()
