"""
SCB .SEC sector decoder for MRA.

Format (reverse-engineered from scb/MAPS/*.SEC, all 6534 bytes):

  33 x 33 grid of 6-byte cells, row-major, no header.
    total = 33 * 33 * 6 = 6534
    row stride = 33 * 6 = 198

  Each 6-byte cell:
    byte 0: terrain / floor type   (0x2B floor, 0x2E path, 0x00 void, ...)
    byte 1: wall overlay graphic   (0x47 = wall on that edge column)
    byte 2: edge / direction marker (0x08 north edge, 0xE0 east boundary)
    byte 3: west-wall / connector flag (0x01)
    bytes 4-5: unused in observed sectors (reserved: critter/message link)

These are SCB editor sectors (server-side map source). Byte 0 is the
renderable terrain type; bytes 1-3 are wall/overlay attributes that the
client would resolve into the object array. The grid is larger than the
client's 13x13 viewport, so a sub-window is extracted for room injection.
"""

import os
import struct

GRID = 33
CELL = 6
ROW_STRIDE = GRID * CELL          # 198
SECTOR_SIZE = GRID * ROW_STRIDE   # 6534
VIEW = 13                         # client viewport is 13x13

# Cell field offsets
F_TERRAIN = 0
F_WALL = 1
F_EDGE = 2
F_FLAG = 3


class Sector:
    """Parser for a single .SEC sector file."""

    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            self.data = f.read()
        if len(self.data) != SECTOR_SIZE:
            raise ValueError(
                f'{path}: expected {SECTOR_SIZE} bytes, got {len(self.data)}'
            )

    def cell(self, row, col):
        """Return the 6-byte cell at (row, col)."""
        off = row * ROW_STRIDE + col * CELL
        return self.data[off:off + CELL]

    def field(self, row, col, field):
        """Return one field byte of a cell."""
        return self.data[row * ROW_STRIDE + col * CELL + field]

    def terrain_grid(self):
        """Return the full 33x33 terrain-type grid (byte 0 of each cell)."""
        return [
            [self.field(r, c, F_TERRAIN) for c in range(GRID)]
            for r in range(GRID)
        ]

    def bounds(self):
        """Return (min_row, min_col, max_row, max_col) of non-empty cells."""
        rows = [r for r in range(GRID)
                if any(self.field(r, c, F_TERRAIN) for c in range(GRID))]
        cols = [c for c in range(GRID)
                if any(self.field(r, c, F_TERRAIN) for r in range(GRID))]
        if not rows or not cols:
            return (0, 0, GRID - 1, GRID - 1)
        return (min(rows), min(cols), max(rows), max(cols))

    def viewport(self, center_row, center_col, size=VIEW):
        """Extract a size x size terrain window centered on (row, col).

        Cells outside the sector are returned as 0x00 (void).
        Returns a flat row-major bytes object of length size*size.
        """
        half = size // 2
        out = bytearray(size * size)
        for vr in range(size):
            sr = center_row - half + vr
            if not (0 <= sr < GRID):
                continue
            for vc in range(size):
                sc = center_col - half + vc
                if not (0 <= sc < GRID):
                    continue
                out[vr * size + vc] = self.field(sr, sc, F_TERRAIN)
        return bytes(out)

    def ascii_map(self):
        """Return a human-readable ASCII rendering of the terrain grid."""
        lines = []
        for r in range(GRID):
            row = ''
            for c in range(GRID):
                b = self.field(r, c, F_TERRAIN)
                row += f'{b:02X}' if b else ' .'
                row += ' '
            lines.append(row.rstrip())
        return '\n'.join(lines)


def list_sectors(maps_dir):
    """Return sorted .SEC paths under a MAPS directory (recursive)."""
    found = []
    for root, _dirs, files in os.walk(maps_dir):
        for name in files:
            if name.lower().endswith('.sec'):
                found.append(os.path.join(root, name))
    return sorted(found)


if __name__ == '__main__':
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else 'scb/MAPS/ucm1.SEC'
    s = Sector(target)
    print(f'{target}: {len(s.data)} bytes, bounds={s.bounds()}')
    print(s.ascii_map())
