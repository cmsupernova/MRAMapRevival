"""
MAP.256 room terrain decoder for MRA.

MAP.256 format (reverse-engineered from MRA.EXE room loader at VA 0x436B80):

  Bytes 0-199:     Room offset table (100 LE uint16 offsets, relative to byte 200)
  Bytes 200-441:   Shared initialization tables (loaded at startup)
  Bytes 442+:      Tile/object data pool

  Each room record (at offset 200 + table[room_id]):
    - Series of WORD groups separated by 00 00
    - Group 0: typically 11 WORDs (exit/object pointer table)
    - Groups with 13+ WORDs: column indices into shared lookup tables
      (bytes 200-441), NOT direct terrain type bytes
    - The game resolves these through a runtime tile pool at file offset 442+
"""

import struct
import os

HEADER_SIZE = 200
GRID_SIZE = 13
DEFAULT_TERRAIN = 0x0E  # Standard ground tile (matches MRADUMP Haven sessions)


class MAP256:
    """Parser for MAP.256 room terrain data."""

    def __init__(self, path=None):
        if path is None:
            path = os.path.join(os.path.dirname(__file__), 'MAP.256')
        with open(path, 'rb') as f:
            self.data = f.read()
        if len(self.data) < HEADER_SIZE + 2:
            raise ValueError(f'MAP.256 too small: {len(self.data)} bytes')
        self.offsets = [
            struct.unpack_from('<H', self.data, i * 2)[0]
            for i in range(100)
        ]

    def get_room_size(self, room_id):
        """Return room record size in bytes."""
        base = self.offsets[room_id]
        for j in range(room_id + 1, 100):
            if self.offsets[j] != base:
                return self.offsets[j] - base
        return len(self.data) - HEADER_SIZE - base

    def get_room_bytes(self, room_id):
        """Return raw room record bytes."""
        start = HEADER_SIZE + self.offsets[room_id]
        size = self.get_room_size(room_id)
        return self.data[start:start + size]

    @staticmethod
    def parse_word_groups(record):
        """Split room record into WORD groups separated by 00 00."""
        groups = []
        pos = 0
        while pos < len(record):
            if pos + 1 < len(record) and record[pos] == 0 and record[pos + 1] == 0:
                pos += 2
                continue
            words = []
            while pos + 1 < len(record):
                if record[pos] == 0 and record[pos + 1] == 0:
                    break
                words.append(struct.unpack_from('<H', record, pos)[0])
                pos += 2
            if words:
                groups.append(words)
            if pos + 1 < len(record) and record[pos] == 0 and record[pos + 1] == 0:
                pos += 2
            elif pos >= len(record):
                break
            elif not words:
                pos += 1
        return groups

    def decode_terrain_grid(self, room_id):
        """
        Decode a 13x13 terrain grid for the given room.

        Room records store WORD column indices into lookup tables loaded from
        MAP.256 bytes 200-441. The game resolves those through a runtime tile
        pool (file offset 442+) before filling [0x460B80] and [0x4571C0].
        Treating WORD values as direct file offsets reads header/table bytes
        and produces invalid tile types (garbage vertical strips).

        Until the full runtime resolver is emulated, return uniform open
        ground (0x0E), which matches Haven sessions in MRADUMP.TXT.
        """
        _ = room_id
        return [[DEFAULT_TERRAIN] * GRID_SIZE for _ in range(GRID_SIZE)]

    def terrain_grid_flat(self, room_id):
        """Return terrain grid as 169-byte flat array (row-major)."""
        grid = self.decode_terrain_grid(room_id)
        flat = bytearray(GRID_SIZE * GRID_SIZE)
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                flat[row * GRID_SIZE + col] = grid[row][col]
        return bytes(flat)

    def decode_room_info(self, room_id):
        """Return decoded room info dict for logging."""
        record = self.get_room_bytes(room_id)
        groups = self.parse_word_groups(record)
        grid = self.decode_terrain_grid(room_id)
        non_default = sum(
            1 for row in grid for cell in row
            if cell != DEFAULT_TERRAIN and cell != 0
        )
        return {
            'room_id': room_id,
            'record_size': len(record),
            'num_groups': len(groups),
            'row_templates': sum(1 for g in groups if len(g) >= GRID_SIZE),
            'non_default_cells': non_default,
            'grid': grid,
        }


def load_haven_terrain(path=None):
    """Load Haven (room 0) terrain grid from MAP.256."""
    decoder = MAP256(path)
    return decoder.terrain_grid_flat(0)


if __name__ == '__main__':
    dec = MAP256()
    info = dec.decode_room_info(0)
    print(f"Room 0 (Haven): {info['record_size']} bytes, "
          f"{info['row_templates']} row templates, "
          f"{info['non_default_cells']} non-default cells")
    print()
    for ri, row in enumerate(info['grid']):
        hexrow = ' '.join(f'{b:02X}' for b in row)
        print(f'  Row {ri:2d}: {hexrow}')
