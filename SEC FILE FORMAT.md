## 13. SEC FILE FORMAT

**[VERIFIED]** by SCB.exe FUN_00405854 (load), FUN_0040659a (save), FUN_0040a068
(palette paint), FUN_00407a34 (palette label lookup), and by inspection of the
three uploaded MRC files (EWGB290321b.SEC, EWGB322353b.SEC, EWGB322353c.SEC).

**This section supersedes Rev 1/2/3's prior claim about record layout.**

### Per-sector file set

Each sector is **three files** sharing one base filename, distinguished only by
extension. SCB always loads and saves all three together. **[VERIFIED]** —
extensions read directly from SCB.exe `.data` segment at the addresses below
(bytes contain ASCII + null padding to 8 bytes each):

| Slot | Ext     | Load addr      | Save addr      | Size / format                                  |
|------|---------|----------------|----------------|------------------------------------------------|
| A    | `.SEC`  | `0x0041a2c0`   | `0x0041a3a4`   | Fixed 6534 bytes — the 33×33×6 tile grid       |
| B    | `.MSG`  | `0x0041a2cc`   | `0x0041a398`   | Null-terminated ASCII strings → pointer table at `DAT_004225e0` (256 entries) |
| C    | `.CRT`  | `0x0041a2d8`   | `0x0041a364`   | Records `[6-byte header][N × 24-byte attr]` where `N = record[5]`, indexed by `DAT_0042a840` |

`.SEC` is short for "sector". `.MSG` is messages — the names/text strings shown
when a player looks at or interacts with an entity. `.CRT` is critters — the
structured records holding entity attributes (HP, behavior, teleport
destinations, etc.). The `.CRT` extension explains the MRA.exe client string
`" Critter buffer overflow"` (§15) — it's the in-memory buffer for parsed
.CRT contents.

### Load vs save order — defensive sequencing

`FUN_00405854` loads in the order **A → B → C** (tile grid first, then
messages, then critters). `FUN_0040659a` saves in the **reverse order
C → B → A** (critters first, messages second, tile grid LAST). This is
deliberate: if SCB crashes mid-save, the `.SEC` is the file that gets
sacrificed because the tile grid is fully visible in the editor and can be
re-painted, while the `.CRT` records hold non-visible state (critter
attribute values, teleport destinations) that would take much longer to
reconstruct.

The server should mirror this discipline when persisting world state: write
all critter/message state to disk before touching the tile grid.

### Slot A (.SEC) layout

- **33 rows × 33 cols × 6 bytes/record = 6534 bytes total**
- Effective playable area is **32×32**: the 33rd row and 33rd column are
  padding, always all-zero. SCB's render loop iterates `for (r=0; r<0x20; r++)`
  and `for (c=0; c<0x20; c++)`. Confirmed empirically by all three uploaded
  files: row 32 = 33 zero bytes, col 32 = 33 zero bytes.
- Record offset within file: `(row * 33 + col) * 6`. Row 0 = north, col 0 = west
  per the SCB editor display orientation.

### Per-record layout (6 bytes)

| Byte | Field        | Source / SCB write target                               |
|------|--------------|---------------------------------------------------------|
| 0    | Terrain      | SCB paint cat 1 → `DAT_0041e020`. Sent verbatim in 0x3d |
| 1    | Object       | SCB paint cat 4 → `DAT_0041e021`. Decorations, portals  |
| 2-3  | Wall + door bits (little-endian u16) — see bit layout below |
| 4    | West-edge door bits — see bit layout below              |
| 5    | Entity index | 1-based index into the `.MSG` name table and the `.CRT` record table; 0 = no entity |

### Bytes 2-3 + byte 4 bit layout

From `FUN_0040a068` paint categories 2 (walls) and 3 (doors). All edge bits are
stored ON THE CELL THAT OWNS THE EDGE; e.g. a wall along the north edge of cell
(r,c) is stored in that cell's byte 2-3 bits 0-4, and the same wall is also
visible to cell (r-1,c) as its south edge.

```
bytes 2-3 (little-endian u16):
  bits  0..4   north wall  (5 bits, wall type 0..31; 0 = no wall)
  bits  5..9   west wall   (5 bits)
  bits 10..13  north door  (4 bits, door type 0..15; only valid if N wall != 0)
  bits 14..15  unknown / reserved

byte 4:
  bit  0       unknown
  bits 1..4    west door   (4 bits; only valid if W wall != 0)
  bits 5..7    unknown
```

The "door requires wall" constraint is enforced by SCB itself at paint time:
the category-3 paint branch checks `(wall bits != 0)` before writing door bits.

### Removed: the entity_flag == 0x3d claim from Rev 1-3

The earlier claim that record byte 1 == 0x3d means "entity spawns here" was
wrong. Byte 1 holds the **object palette byte**, and 0x3d in byte 1 is the
palette index for "Small Tree" (`FUN_00407a34` at X=0x248, Y=0x146; index
formula `((X-0x1f3)/0x11) + ((Y-0xcf)/0x11)*8 = 5+7*8 = 0x3d`). The uploaded
MRC bay file `EWGB290321b.SEC` has byte 0 = 0x14 (grass) in 272 cells AND
byte 1 = 0x3d (Small Tree) in exactly those same 272 cells — they're literal
trees on the grass, not entity spawn markers. Entity spawning is governed by
record byte 5 (the `.CRT` record index), not byte 1.

---

## 13a. TERRAIN BYTE REFERENCE (record byte 0)

**[VERIFIED]** Source: `FUN_00407a34` label dispatcher + `FUN_0040a068` paint
dispatcher. Each label is extracted from the string literal that the function
copies into the tooltip buffer. The palette is on a 17-pixel grid; cat 1 origin
is `(X=0x18b, Y=0x47)` with 6 columns, so byte value =
`((X-0x18b)/0x11) + ((Y-0x47)/0x11)*6`.

| Byte | SCB label                  | Notes                                |
|------|----------------------------|--------------------------------------|
| 0x00 | CLEAR All                  | Void (default). Black, impassable    |
| 0x02 | No see through             |                                      |
| 0x03 | Veil of Darkness (po)      | Hard sector boundary; impassable     |
| **0x04** | **Go to sector below** | **Layer transition: load (letter-1).SEC** |
| **0x05** | **Go to sector above** | **Layer transition: load (letter+1).SEC** |
| 0x06 | Indoor Air (fall through)  | Player drops to layer below          |
| 0x07 | Outdoor Air (fall through) | Player drops to layer below          |
| 0x0f | Shallow Water              | "Waterr" — sic in binary             |
| 0x10 | Wood Panel Floor           |                                      |
| 0x11 | Light Wood Panel Floor     |                                      |
| 0x12 | Stone Floor                |                                      |
| 0x13 | Marble Floor               |                                      |
| 0x14 | Grass                      |                                      |
| 0x15 | Deep Water                 | Not walkable                         |
| 0x16 | Solid Wood Floor           |                                      |
| 0x17 | Darkened Stone Floor       |                                      |
| 0x18 | Dark Wood Panel Floor      |                                      |
| 0x19 | Styled White Floor         |                                      |
| 0x1a | Styled Pub Floor           |                                      |
| 0x1b | Cave Stone Floor           |                                      |
| 0x1c | **Dirt**                   | Read at `0x0041a5cc`. Dominant tile in MRC c-layer (697/1089 cells in `EWGB322353c.SEC` — see §13c interpretation) |
| 0x1d | Refuse Hole                |                                      |
| 0x1e, 0x1f | Plowed Ground        | (two adjacent variants)              |
| 0x20 | Do NOT use                 | SCB warns against painting this      |
| 0x21 | Blackened Marble Floor     |                                      |
| 0x22 | Blackened Wood Floor       |                                      |
| 0x23 | Marsh                      |                                      |
| 0x24 | Shallow Swamp Water        |                                      |
| 0x25 | Deep Swamp Water           |                                      |
| 0x26 | Blue Sky Grass             |                                      |
| 0x27..0x29 | Wood Panel Floor    | (three adjacent variants)            |
| 0x30..0x33 | Stairs              |                                      |
| 0x34 | Stairs Landing             |                                      |
| 0x35..0x37 | Marketplace Pool    |                                      |
| 0x38, 0x39 | Stone Floor         |                                      |
| 0x3c | Brick Floor                |                                      |
| 0x3d | Standing Water             | (note: 0x3d in byte 1 is Small Tree — different palette) |
| 0x3e | **Moss**                   | Read at `0x0041a72c` |
| 0x78 | Marsh with Fog             |                                      |
| 0x79 | Swamp with Fog             |                                      |
| 0x7a | Dirt with LimVis           | Limited visibility                   |
| 0x7b | Gravel with LimVis         |                                      |
| 0x7c | Moss with LimVis           |                                      |
| 0x7e | Dark Stone (No Exit Game)  |                                      |
| 0x7f | Light Wood (No Exit Game)  |                                      |
| 0x80 | Stone (No NPC Move)        |                                      |
| 0x81 | Wood (No NPC Move)         |                                      |
| 0x82 | No Restore Loss            |                                      |
| 0x83 | Stone PvP                  |                                      |
| 0x84 | Grass PvP                  |                                      |
| 0x85 | Wood PvP                   |                                      |
| 0x86 | Dirt PvP                   |                                      |
| 0x87 | Wood Party Brawl           |                                      |
| 0x88 | Pub Flor Party Brawl       |                                      |
| 0x89 | Light Wood Party Brawl     |                                      |
| 0x8a..0x8c | Reserved            |                                      |

Bytes not listed here either fall outside the palette's clickable area
(returning early from `FUN_00407a34`) or are explicitly marked "Do NOT use" in
SCB. The server should treat any non-listed byte as opaque/impassable.

---

## 13b. OBJECT BYTE REFERENCE (record byte 1)

**[VERIFIED]** Source: `FUN_00407a34` object dispatcher. Cat 4 palette origin
is `(X=0x1f3, Y=0xcf)` with 8 columns, so byte value =
`((X-0x1f3)/0x11) + ((Y-0xcf)/0x11)*8`. Object byte 0 = no object.

| Byte | SCB label              | Significance                                |
|------|------------------------|---------------------------------------------|
| 0x01 | Teleportal             | Destination in `.CRT`; needs companion files |
| 0x02 | Room Teleportal        | Teleport to named room                       |
| 0x03 | Instant Teleportal     | No fade/delay                                |
| 0x04 | Invisible Teleportal   | Hidden warp                                  |
| 0x05 | Special Function       | Scripted action                              |
| 0x06 | Marsh Fog              | Visual effect overlay                        |
| 0x07 | **Hole**               | Read at `0x0041aa1c`. Likely a passable pit (player falls through to layer below) |
| 0x09 | LimVis                 | Limited visibility marker                    |
| 0x0e | Counter N              | NPC counter (shop counter, north-facing)     |
| 0x0f | Counter E              |                                              |
| 0x10 | Counter S              |                                              |
| 0x11 | Counter W              |                                              |
| 0x12 | Table w/ Bench N       |                                              |
| 0x13 | Table w/ Bench E       |                                              |
| 0x18 | Table w/ Bench S       |                                              |
| 0x19 | Table w/ Bench W       |                                              |
| 0x1a | Bar N                  |                                              |
| 0x1b | Bar S                  |                                              |
| 0x1e | Chair N                |                                              |
| 0x1f | Chair E                |                                              |
| 0x20 | Chair S                |                                              |
| 0x21 | Chair W                |                                              |
| 0x22 | Locker N               |                                              |
| 0x23 | Locker E               |                                              |
| 0x28 | Locker S               |                                              |
| 0x29 | Locker W               |                                              |
| 0x2a | Table w/ Book N        |                                              |
| 0x2b | Table w/ Book E        |                                              |
| 0x30 | Table w/ Book W        |                                              |
| 0x31 | Desk N                 |                                              |
| 0x32 | Desk E                 |                                              |
| 0x33 | Desk W                 |                                              |
| 0x37 | Bed against West Wall  |                                              |
| 0x38 | Bed against East Wall  |                                              |
| 0x39 | Throne N               |                                              |
| 0x3a | Throne S               |                                              |
| 0x3b..0x3c | (unnamed)        |                                              |
| 0x3d | **Small Tree**         | **Decoration. NOT an entity flag**           |
| 0x40 | Straw bed (variant 1)  |                                              |
| 0x41 | Straw bed (variant 2)  |                                              |
| 0x42 | Graffiti N Wall        |                                              |
| 0x43 | Graffiti E Wall        |                                              |
| 0x44 | Graffiti W Wall        |                                              |
| 0x45 | Plaque                 |                                              |
| 0x46 | Gravestone             |                                              |

Walls (record bytes 2-3) and Doors (record byte 4) use their own separate
palettes — see §13 bit layout. Their byte values index into wall-type and
door-type tables that aren't directly written into record bytes by name.

---

## 13c. LAYER TRANSITIONS AND SECTOR TRIPLETS

**[VERIFIED]** Source: SCB tile labels `0x04 = "Go to sector below"`,
`0x05 = "Go to sector above"` at `FUN_00407a34`.

### Filename convention

`<4-letter region prefix><Y_start><Y_end><layer>.SEC`, e.g. `EWGB322353b.SEC`.

- **Prefix**: 4 alphabetic chars. Regional grouping per the community map.
  **[UNVERIFIED]** — no code in any binary we have access to constructs prefixes
  from coordinates.
- **Y_start, Y_end**: pair of numbers whose difference is always 31, e.g.
  130-161, 162-193, 290-321, 322-353. The stride of 32 between consecutive
  ranges matches the 32×32 effective playable area per file. **[UNVERIFIED]** —
  this is observed but not binary-confirmed.
- **Layer**: single letter `a`, `b`, or `c`.

### Layer letter semantics

Layer letters are altitude-ordered: `a` is below `b` is below `c`. The two
binary-confirmed pieces of evidence are:

1. SCB terrain byte 0x04 carries the literal label "Go to sector below"
2. SCB terrain byte 0x05 carries the literal label "Go to sector above"

These bytes paint as ordinary terrain tiles. Stepping onto a 0x04 tile triggers
loading of `(same_base_name)(letter-1).SEC`; stepping onto 0x05 triggers
`(letter+1).SEC`. **[UNVERIFIED — but consistent]** The exact server behavior
on layer transition is not in any binary we have. The emulator must implement
this; the most defensible behavior is:

```
on player step onto cell where slot_A[byte 0] == 0x04:
    new_layer = chr(ord(current_layer) - 1)         # b -> a, c -> b
    if file (base + new_layer + '.SEC') exists:
        unload current SEC; load new SEC at same (row, col)
    else:
        ignore; player stays where they were
```

And symmetrically for 0x05.

### Layer semantics — refined by the 0x1c=Dirt discovery

What `a`, `b`, `c` actually represent in practice is now better grounded. With
tile byte `0x1c` confirmed as "Dirt", the MRC bay c-layer
(`EWGB322353c.SEC`) is no longer "an unidentified dense interior" as we
thought in Rev 4 — it is **mostly outdoor dirt terrain** (697 of 1089 cells =
64% dirt, with Stone Floor 108, Deep Water 93, Wood Panel Floor 70, Veil 32,
Void only 65). That matches an elevated outdoor area such as a campus quad,
hillside, or balcony overlooking the bay.

Compare:

- `EWGB322353b.SEC` (level b): outdoor waterfront — Grass 303, Deep Water
  109, Veil 25, Void 652. A coastal scene where most of the sector is the
  bay itself and the unbuildable area beyond the Veil.
- `EWGB322353c.SEC` (level c): mostly outdoor Dirt at higher elevation —
  Dirt 697, Stone Floor 108, Deep Water 93, Wood Panel Floor 70, Veil 32,
  Void only 65. A walkable elevated platform where the playable area is
  substantially **larger** than at level b (because at this altitude the area
  extends out over what was bay at level b).

The pattern that "every non-void cell of b is also non-void in c" now makes
physical sense: wherever there is solid ground at the waterfront level, there
is also walkable terrain at the elevated level — and additionally, the
elevated level extends out over the bay.

So the working interpretation, supported but not proven, is:

- **`a` is one altitude below `b`** — cellars, basements, caves
- **`b` is "ground level" for that area** — most surface play happens here
- **`c` is one altitude above `b`** — upper floors, hillsides, balconies

The alphabetical-altitude convention is consistent with SCB's labels for
the transition tiles: `0x04 = "Go to sector below"` decrements the letter,
`0x05 = "Go to sector above"` increments it.

Stacks of more than three layers do not occur in any filename in
`sec_list.txt`: only the letters `a`, `b`, `c` appear. So three is the
maximum altitude span for any single sector column in the world.

### The four Teleportal object types

Independent of layer transitions, record byte 1 values 0x01..0x04 are the four
Teleportal types. Their destinations are stored in `.CRT` records indexed via
record byte 5. **Until `.MSG`/`.CRT` companion files are recovered for the sector
the player is in, the server cannot resolve teleport destinations.** The
emulator should detect teleport tiles, log them, and freeze the player rather
than guess a destination.

### Layer-changing mechanisms summary

| Mechanism                  | Trigger             | Destination source        |
|----------------------------|---------------------|---------------------------|
| Sector layer below         | byte 0 == 0x04      | filename letter -1        |
| Sector layer above         | byte 0 == 0x05      | filename letter +1        |
| Indoor / Outdoor Air       | byte 0 == 0x06/0x07 | filename letter -1 (fall) |
| Stairs                     | byte 0 in 0x30..0x33| **[UNCONFIRMED]** likely same as 0x04/0x05 with direction implied by stair tile orientation |
| Hole (object)              | byte 1 == 0x07      | **[UNCONFIRMED]** likely same as Indoor/Outdoor Air — player falls to letter -1 |
| Teleportal (4 variants)    | byte 1 in 0x01..0x04| .CRT record at byte-5 index — **requires companion files** |
| Special Function           | byte 1 == 0x05      | scripted; .CRT record   |

---

## 13d. WORLD MAP STATUS

The mapping from `(world_X, world_Y, layer)` to SEC filename is **not in any
binary we have access to**. It lived in the (now-lost) MRA server binary. The
client (MRA.exe) never opens SEC files; the editor (SCB.exe) takes filenames
as user-typed input. We have only:

- The actual SEC files (currently 3 valid uploads, ~130 referenced in
  `sec_list.txt`)
- The community-maintained `sector_map_xls_-_Sheet1.csv` / `MRA_map.ods`
  showing where each filename sits in the world

The community map cites the readme statement that "Verbonic is MP505050,
dead center" and that MP coordinates step by 5 per sector from 10 to 100.
Neither of these is binary-corroborated.

**Recommended server design:**

The emulator should load a `world_map.json` sidecar derived from the community
CSV, structured as:

```json
{
  "_provenance": "[UNVERIFIED — derived from sector_map_xls_-_Sheet1.csv, community-derived, no binary corroboration]",
  "sectors": {
    "EWGB322353b": {
      "world_y_range": [322, 353],
      "world_x_range": [..., ...],
      "region": "Mystic Realms College",
      "neighbors": { "n": "EWGB290321b", "s": "...", "e": "...", "w": "..." }
    }
  }
}
```

Every consumer of `world_map.json` in the codebase must repeat the
`[UNVERIFIED — community-derived]` provenance comment per §17 rule 2.

---

## 13e. DOOR OPEN/CLOSE MECHANISM

**[VERIFIED]** Source: FUN_00405b6f (atlas load), FUN_004309d8 (atlas
index math), FUN_00434459 (band-selection render gate), FUN_004141da
(client-side passability), FUN_00410e86 case 0x34..0x54 (command parser),
CMDList table at 0x0043f358 (command codes and direction labels), and
FUN_00419c07 cases 0x41/0x42 (server→client door grid transport).

### Door type values

The runtime door grid stores a single byte per cell-edge. Valid values
form two bands of three types each, plus zero for "no door":

| Value | Band   | Atlas | Render |
|-------|--------|-------|--------|
| 0x00  | —      | —     | no door at this edge |
| 0x01  | closed | WOODD | wooden door, closed |
| 0x02  | closed | IROND | iron door, closed |
| 0x03  | closed | BLACKD | black door, closed |
| 0x11  | open   | WOODD | wooden door, open (band-2 frames) |
| 0x12  | open   | IROND | iron door, open |
| 0x13  | open   | BLACKD | black door, open |

The atlas mapping (1→WOODD, 2→IROND, 3→BLACKD) comes from the load
order in `FUN_00405b6f`: WOODD is read first, then IROND, then BLACKD,
into a single contiguous buffer at `DAT_0044ee3c` of size
`3 * DAT_0044c836`. `FUN_004309d8` then indexes via
`(type - 1) * stride` for closed types and `(type - 0x11) * stride`
for open types — both select the same atlas because the offset (open
- closed) is exactly 0x10.

### Render branch selection — FUN_00434459

The closed-band render fires under the gate:
```c
if ((DAT_004496d5 != 0) &&
    (((DAT_00443d0d == 4 && (DAT_0044718c < 0x10)) ||
      (DAT_0044efa4 != '\0'))))
```
where `DAT_0044718c` is the door grid value at the cell being rendered.
The `< 0x10` test routes closed types (1/2/3) into the closed-band
sprite call (`FUN_004309d8(value, ...)`). Values >= 0x10 fall through
to a later open-band branch in the same function. So the +0x10
transformation is sufficient on its own to change visual state.

The `DAT_0044efa4` flag is an alternate path that forces the open-band
render regardless of grid value. It is cleared by the 0x3c sector
reset. Its setter is NOT TRACED — it's not set by any of the
0x41/0x42 handlers or by the 0x3d tile-paint loop in `FUN_00419c07`.
Likely set by some specific server packet we haven't identified, or by
a client-side event tied to entering an open doorway. Implementing
door open/close without `DAT_0044efa4` produces correct visuals at a
distance; the only missing polish is the "player walking in the open
doorway" side-view animation when standing directly under a door.

### Client → server commands

CMDList byte-table excerpt from 0x0043f402 (dumped via Ghidra Listing
view in Rev 8 session):
```
0043f402  35 00  "OPEN\0"     code = 0x35, subcode = 0x00
0043f409  36 00  "CLOSE\0"    code = 0x36, subcode = 0x00
0043f411  37 00  "UNLOCK\0"   code = 0x37, subcode = 0x00
```

All three codes are consumed by the same parser branch — FUN_00410e86
case `0x34..0x54` (which also handles CLIMB 0x34 and PEEK 0x54). The
branch writes the matched command code as the packet type, then scans
the CMDList for an argument matching a direction label (codes 0..7).

Wire format:
```
[pkt_type=0x35|0x36|0x37][arg]
```
where `arg` is one of:

| arg byte | Meaning |
|----------|---------|
| 0x20 | direction NW |
| 0x21 | direction N  |
| 0x22 | direction NE |
| 0x23 | direction W  |
| 0x24 | direction E  |
| 0x25 | direction SW |
| 0x26 | direction S  |
| 0x27 | direction SE |
| 0x60 | no direction was typed (parser writes literal 0x60) |

The direction byte is exactly `dir + 0x20` with `dir` matching the
ee30 movement encoding. Verified from the first eight CMDList
entries:
```
0043f358  01 00 "N\0"     0043f368  00 00 "NW\0"
0043f35c  03 00 "W\0"     0043f36d  02 00 "NE\0"
0043f360  04 00 "E\0"     0043f372  05 00 "SW\0"
0043f364  06 00 "S\0"     0043f377  07 00 "SE\0"
```

### Server → client transport

When door state changes, the server emits a fresh 0x41 (N-doors) and
0x42 (W-doors) packet covering the 14×14 edge grid centered on the
player. The packet payload format is verified from `FUN_00419c07`
cases 0x41 and 0x42:

```
[0x41][type1+0x0e][cell1+0x0e][type2+0x0e][cell2+0x0e]...[0x00]
```

The handler loop reads pairs of (type, cell) bytes and writes
`type - 0x0e` to the N-door grid (0x41) or W-door grid (0x42) at the
decoded cell position. The 0x00 terminator ends the stream.

A wire byte of `0x0e` (decoded to 0) clears any existing door entry —
the handler stores it unconditionally without a "non-zero" check. We
rely on this to clear stale grid entries when the visible window
shifts via per-step movement; see "Stale-data handling" in
`build_wall_door_payloads` in `mra_stub.py`.

### Walking through a closed door

Each cardinal case in `FUN_004141da` includes a door-grid override
clause that lets the move packet through any door edge, whether
closed or open. Specifically:

| Direction | Door grid checked | Cell |
|-----------|-------------------|------|
| 1 (N)     | DAT_004491a0 (N-doors) | dest_row+1 = source_row |
| 6 (S)     | DAT_004491a0 (N-doors) | source_row+1 = dest_row |
| 3 (W)     | DAT_00446e60 (W-doors) | dest_col+1 = source_col |
| 4 (E)     | DAT_00446e60 (W-doors) | source_col+1 = dest_col |

A non-zero door grid value at the relevant edge passes the client's
local move check, so the move packet always reaches the server when
the player tries to cross a doorway — regardless of whether the door
is currently closed (1..3) or open (0x11..0x13). The server thus has
full authority over whether to actually advance the player position
and whether to transition the door state.

### Auto-close, locked doors, keys

NOT IMPLEMENTED and NOT VERIFIABLE from MRA.exe. These lived on the
lost server binary. Specifically:

- Auto-close (door re-closes after N seconds or N steps): nothing in
  MRA.exe drives a closed→open transition automatically, so the
  reverse must have been server-driven. No traces in the client.
- Locked doors: the 0x37 UNLOCK command exists (CMDList 0043f411)
  and follows the same wire format as OPEN/CLOSE. But the client
  does not store lock state per door, and no client packet handler
  acts on locked-vs-unlocked. Lock/key state was authoritative on
  the server.
- Key inventory checks: items 0x40..0x46 in the OBJECT byte
  reference (§13b) include "key" items, but matching keys to doors
  would have been a server-side decision.

The mra_stub server stub treats 0x37 as a recognized-but-no-op
packet; UNLOCK acknowledgements pass through but cause no state
mutation. Doors flagged "locked" by any future implementation must
gate OPEN through that check.

---