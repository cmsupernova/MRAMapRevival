# TELEPORTAL SUBSYSTEM — Implementation Plan & Reference

**Status:** **RUDIMENTARY TP SHIPPED 2026-07-19 (commit `0f90f50`).** MEMORIZE
(`0x38`) / FORGET (`0x39`) / TP + RETURN (`0x3a`) / the step-on blackout / `§SAVE`
persistence / login bulk-splice are LIVE in `mra_stub.py` behind `MRA_TP*` env
kill-switches (all default ON; wire framing VERIFIED). `tests/test_teleportal.py`
green; full regression 70/70. RECALL (`0x5a`) was already shipped by the §DEATH
work. The off-teleportal gate + RETURN's half-STA/KAR/MAN DAMAGE toll are also
SHIPPED (§13/§14, `MRA_TP_STRICT`). The (T)-list is **PER-CHARACTER** (§15, owner
confirmed — an earlier per-account pass was rolled back; `memorized_tps` + `last_tp`
both ride the character save blob) and sorted **newest-memorized-first** (RETURN
pinned; VERIFIED). Still OPEN:
green-room ownership, `level_req` gating, RETURN's "in sight of hostiles" (uses the
combat-visible proxy), arrival anti-stack scatter, the 10 unnamed Haven TP cells.
**Target:** `mra_stub.py` teleportal subsystem (MEMORIZE / FORGET / TP / RETURN / RECALL).
**Cardinal rule honored throughout:** no destination, opcode, or wire byte is
fabricated. Every unknown is an explicit `OPEN`/`LOST`, never a guess.

Evidence grades (per CLAUDE.md §0): `VERIFIED` · `RE-AUTHORED` · `DERIVED` ·
`DOMAIN/DOC` · `OPEN` · `LOST`. Authority: binary > ITEMS.TXT > manuals > wiki.

---

## 0. Scope & guiding decision

Teleportals are MRA's fast-travel network. The player-facing behavior is fully
documented and the *list-management* protocol is now fully recovered from the
client binary. **But the per-tile travel DESTINATIONS are `LOST`:** they live in
unrecovered `.CRT` companion files (indexed by SEC object record byte-5), and a
scan of every surviving teleportal cell shows `byte5 == 0` — the destination
index does not even survive locally. Example: the Haven sector `EWGB194225b`
("W Haven") holds 6 blue teleportal cells, all `byte5 == 0`.

**Spine (per MD/MRA_GROUND_TRUTH.md §13b): detect → log → FREEZE. Never guess a
jump target.** What is implementable now is the entire *name-bookkeeping +
tile-detection* layer; the actual jump is wired but gated so it can only ever
fire to a *known* destination (of which there are currently zero).

---

## 1. Evidence-graded behavior spec

| Rule | Detail | Source | Grade |
|---|---|---|---|
| MEMORIZE / MEM | Must stand ON a teleportal; new entry goes to **top** of the (T) list | wiki `gameplay:commands.html`; `ognall/HELP.TXT:244-252`; `ognall/MANUAL.TXT:522-531` | DOMAIN/DOC |
| FORGET `<name>` | Forget a memorized TP; arg-less while on a TP forgets that TP | wiki commands; `MANUAL.TXT` | DOMAIN/DOC |
| TP `<name>` | Must be on a teleport AND have memorized `<name>` at its location | `HELP.TXT:244-248`; wiki | DOMAIN/DOC |
| TP RETURN | Usable **anywhere**; returns to last-used TP; costs half remaining endurance; blocked in combat | `HELP.TXT:248-250`; `MANUAL.TXT:532-534` | DOMAIN/DOC |
| RECALL | Death self-rescue → revive at the **church in Haven**; lose 1% exp+TRP; only works on the dead | `MANUAL.TXT:2177-2181`; wiki RECALL | DOMAIN/DOC |
| Green TP | Room teleport — **only the room owner** may memorize | `HELP.TXT:246-247` | DOMAIN/DOC |
| Blue TP | Public — **anyone** may memorize (the screenshot tile) | `HELP.TXT:247` | DOMAIN/DOC |
| Red TP | College → Inn in Haven (one fixed destination) | `HELP.TXT:675` | DOMAIN/DOC |
| List cap | Client enforces a ceiling: "Your TP list is too big. Forget some." | client string `@0x44a198` | VERIFIED |
| RETURN auto-entry | Client auto-prepends "RETURN" to the list at login; server never sends it | `FUN_004089dd` (RETURN copy) | VERIFIED |
| Host-down respawn | Server moves every player to their **last-used teleportal** on a host restart | `MANUAL.TXT:651-654`; `MD/MRA_GAMEPLAY_LOGIC_FROM_MANUALS.md:77` | DOMAIN/DOC |

### 1.1 Two documented conflicts — resolved

- **RETURN cost.** `HELP.TXT` (2008): "half of your remaining **endurance**."
  Wiki (15.3-era): "half of your remaining **Stamina, Karma, Mana**." The live
  15.3 UI shows three bars (STAMINA/KARMA/MANA). **Resolution (UPGRADED — SHIPPED
  2026-07-19):** the stub models all three pools with the same three-band shape
  (max/deficit/fatigue), so RETURN charges **half of remaining Stamina AND Karma
  AND Mana** — the full wiki reading. "endurance" = the umbrella for the three
  bars. **BAND corrected 2026-07-19 (owner `DOMAIN` testimony: "TP RETURN is
  damage, not fatigue"):** the toll lands on the **permanent DEFICIT/stress band**
  (`_deficit`, == `mra_combat.Pool.stress`, must be HEALED) — **NOT** the
  recoverable FATIGUE band (`stamina_damage`/`karma_fatigue`/`mana_fatigue`, which
  ticks back via FRR). A last-resort escape should leave a lasting wound, not a few
  seconds of tiredness. `_tp_return_cost` hits `_deficit`; `remaining = max −
  deficit − fatigue`. Grade: `RE-AUTHORED` (½ fraction + three pools = `DOMAIN/DOC`
  wiki; band = owner `DOMAIN`; enforcement/magnitude were server-side → `LOST`).
- **RETURN block condition — `VERIFIED-DOC`, SHIPPED.** `MANUAL.TXT:532-534`
  (verbatim): *"You can also TP to the teleportal you last used regardless of where
  you are by entering 'TP RETURN' (however, **this will not work if you are
  currently engaged in combat** and there will be a loss of endurance)."* Wiki adds
  "in sight of hostile critters" (supersets the manual). **Resolution:** block when
  any hostile is in sight — the shared `_combat_visible_near` check at the top of
  `handle_tp` gates RETURN too (a combat-blocked RETURN charges **no** damage — you
  did not teleport). Grade: `VERIFIED-DOC` (manual) / `DOMAIN/DOC` (in-sight arm).

### 1.2 The four teleportal object subtypes

SEC object record **byte-1** values `0x01..0x04` (`VERIFIED FUN_00407a34`;
`MD/MRA_GROUND_TRUTH.md:1063-1066`):

| byte-1 | Type | Color (DERIVED) | Memorize gate |
|---|---|---|---|
| `0x01` | Teleportal | blue (public) | anyone |
| `0x02` | Room Teleportal | green | owner-only |
| `0x03` | Instant Teleportal | — | (public; no owner type) |
| `0x04` | Invisible Teleportal | — | (public; hidden) |

The blue↔`0x01` binding is `DERIVED` (all 6 Haven cells are `0x01`, and HELP.TXT
says blue=public). Pixel-level color↔byte confirmation is `OPEN` (cosmetic).

---

## 2. Wire protocol — recovered this session

### 2.1 C2S command opcodes — `VERIFIED` (CMDList)

CMDList lives at `~0x44a320` (15.3 layout), entry stride `[opcode][subcode][keyword\0]`.
Re-confirmed this session by the keyword anchors:

| Command | Opcode | Wire | Anchor |
|---|---|---|---|
| MEMORIZE / MEM | `0x38` | standalone | keyword `MEMORIZE`@0x44a3f3 (opcode 2 bytes prior) |
| FORGET | `0x39` | `[name]` UPPERCASED | keyword `FORGET`@0x44a3fe |
| RECALL | `0x5a` | standalone | `MD/MRA_GROUND_TRUTH.md:227` |
| (reference) WIELD | `0x55` | standalone | keyword `WIELD`@0x44a407 |
| **TP** | **`0x3a`** | `[name ASCII, uppercased]`; RETURN = plain arg | **VERIFIED 2× 2026-07-16**: live capture (`type=0x3a` "HAV_INN"/"RETURN") + CMDList bytes `3a 00 "TP"` @0x44a924 (`MD/CMDLIST_153_COMPLETE.md`) |

### 2.2 S2C list delivery — `VERIFIED` (decompiled 12.5h client this session)

Persisted as decompiler comments in the Ghidra DB (entry `0x004089dd`, `0x00420ba8`,
`0x004208ed`).

- **Bulk @ login** — `FUN_004089dd` (login/post-login init, =15.3 `FUN_0040743c` region):
  the login-success packet is opcode `0x21` with body
  `[4-byte char# bias-0xe base-0xf1][name\0][name\0]…[\0 terminator][post-status byte]`.
  The handler walks the NUL-terminated names into the (T)-list buffer
  `DAT_00453560`, client-**prepending** "RETURN". The 4-byte char# uses the same
  `(b-0x0e)+(b-0x0e)*0xf1+…` encoding the stub's `encode_world()` already emits.
  > In the stub, the reply to C2S `0x2e` (WORLD REQUEST) is this packet. **STALE
  > correction (2026-07-16):** the earlier text here said the payload was
  > `encode_world(1) + b'\x00\x00\x00'` — that predates the death-session's login
  > work. The **actual current** stub reply (the `0x21` handler, symbol-anchored:
  > `_land_tok`/`world_payload`) is
  > `encode_world(1) + b'\x00' + _land_tok + b'\x00' + b'\x00'` where
  > `_land_tok = bytes([0x31, land_count+0x0e, 0x0e])` (the land-count token). The
  > **TP-list tail is the single `b'\x00'` immediately after `encode_world(1)`**
  > (empty list; first NUL terminates it); the two trailing NULs are the
  > stat-substream terminator + entry display-mode. Bulk names splice at that
  > single NUL: `encode_world(1) + b''.join(n.encode('latin1')+b'\x00' for n in names) + b'\x00' + _land_tok + b'\x00' + b'\x00'`.

- **Incremental add** — `FUN_00420ba8` case `0x35` (`@0x422f80`): payload =
  `[0x35][name NUL-terminated]` — **no length prefix, no bias/encoding on the
  name.** Client `strlen`s the name, and if it fits (`list_end + len+1 <
  buffer_end 0x454561`) does a `memmove`-shift of the whole list down and copies
  the new name in at `DAT_00453567` (= buffer base `0x453560` + 7, i.e. **right
  after the pinned `"RETURN\0"` slot** → newest-at-top), else prints the overflow
  line; then colour code 1 (blue) + prints `"You now know " + name`.
  **15.3 framing VERIFIED 2026-07-16** — decompiled directly from the *15.3*
  `FUN_00420ba8` this session (not carried from 12.5h); byte-identical to the
  12.5h decode.

- **Incremental forget** — `FUN_00420ba8` case `0x36` (`@0x4230cd` in 15.3):
  payload = `[0x36][name\0]`; client `strncmp`-walks the list from base
  `0x453560`, `memmove`-deletes the match, prints `"You have forgotten " + name`.
  **15.3 framing VERIFIED 2026-07-16.**

- **Buffer cap** — `DAT_00453560 .. DAT_00454561` = `0x1001` bytes. Overflow →
  client prints `"Your TP list is too big. Forget some."`

- **No separate MEMORIZE confirmation string exists** (`VERIFIED` 2026-07-16
  `list_strings` sweep — only `"You now know "` @0x44a174 and
  `"You have forgotten "` @0x44a184). **The MEMORIZE player-confirmation IS the
  `0x35` "You now know" push.** Corollary from the live capture: C2S MEMORIZE
  (`0x38`) carries an **empty payload** — the client sends "memorize whatever I'm
  on", NOT a name; the server owns tile→name resolution and echoes it via `0x35`.

**Direction note (no conflict):** C2S `0x35/0x36/0x37` = OPEN/CLOSE/UNLOCK (door
commands, client→server). The `0x35/0x36` above are the **opposite** direction
(server→client, `MAGIC_SERVER`). Same byte, different channel.

**Caveat for the PUSH paths — UPGRADED 2026-07-16:** the `0x35`/`0x36` add/forget
framing is now read from the **15.3** `FUN_00420ba8` directly (not carried from
12.5h) → **VERIFIED**. The remaining live-test-only item is confirming the client
actually renders the pushed name in the (T) pulldown end-to-end (vs the wire being
accepted) + the bulk-`0x21` name-tail interleave; those stay **gated default-OFF**
(`MRA_TP_PUSH`/`MRA_TP_BULK`) per the live-test-loop discipline (CLAUDE.md §2),
but the wire format itself is no longer a guess (see §7 live-test checklist).

This independently confirms `teleporter_names.json`'s provenance ("bulk-loaded at
login via packet 0x21; incrementally added via 0x35 'You now know'").

---

## 3. OPEN / LOST inventory

| Item | State | Unblock |
|---|---|---|
| C2S **TP command opcode** | **CLOSED 2026-07-16: `0x3a`** (`VERIFIED` 2×: live capture + full CMDList hex dump) | `handle_tp` can register on `0x3a`; RETURN rides as a plain text arg |
| Per-tile **destinations** | `LOST` | `.CRT` companion files unrecovered; byte5=0 everywhere (§6c may confirm permanent) |
| `HAV_INN` exact cell `(x,y)` | **PINNED 2026-07-16** (`DERIVED`) | intra (3,6) = world(99,200,b) in `EWGB194225b` — the "sector-level" report's coordinate is itself a `b1==1` cell (raw `17 01 e0 00 00 00` @1206), i.e. it was an exact-tile recording. In `mra_teleportal_registry.json` |
| Church-in-Haven cell (RECALL dest) | **PINNED 2026-07-16** (`DERIVED`) | `HAV_CHURCH` intra (8,25) = world(104,187,b) in `EWGB162193b` (raw `10 01 00 00 00 00` @4998), live-recorded standing on the church tile. RECALL→this tile = `RE-AUTHORED` (docs name the church, not a cell). In `mra_teleportal_registry.json` (`recall_destination`) |
| Green TP room-ownership | `OPEN` | no room-owner model; refuse green for now |
| RETURN Karma/Mana cost arms | `OPEN` | no Karma/Mana pools modeled; only Stamina is real |
| 15.3 framing of `0x35`/`0x36` add/forget | **VERIFIED 2026-07-16** (decompiled 15.3 `FUN_00420ba8`) | — |
| 15.3 bulk-`0x21` name-tail render end-to-end | `OPEN` (framing known; interleaves `_land_tok`) | one live test (§7) |
| Color↔byte at pixel level | `OPEN` (cosmetic) | OBJ.256 loader `FUN_00405b6f` |
| `teleporter_names.json` name→tile binding | `OPEN` by design | it is vocabulary only (its `_NOT_a_tile_binding` field) |

---

## 4. Data model

### 4.1 New `Player` fields

- `memorized_tps: list[str]` — ordered, index 0 = most-recent (newest-at-top).
  Names UPPERCASE (matches the `0x39` FORGET arg form).
- `last_tp: str | None` — last teleport USED; backs TP RETURN + host-down respawn.
  `None` until a real jump occurs (none can today). Never seed with a guess.
- `on_teleportal: dict | None` — cached "TP under me this frame" for cheap
  MEMORIZE / arg-less FORGET; refreshed on the movement tail + world entry.

### 4.2 Registry file — `mra_teleportal_registry.json` (**CREATED 2026-07-16**, repo root)

A separate JSON (NOT edited into authoritative data). Seeded **only** with known
bindings; every unknown field is JSON `null` = `OPEN`, which consumers MUST treat
as "unknown → refuse honestly," never a default.

```jsonc
{
  "_provenance": "[DESIGN] name -> tile/dest binding. Seeded ONLY with VERIFIED/known bindings. null = OPEN (refuse, never default). Destinations live in unrecovered .CRT (SEC object byte-5); OPEN/LOST for all but partial bindings below.",
  "_schema": {
    "sector_base": "str|null  SEC base name; null = OPEN",
    "x": "int|null  intra-sector col 0..31; null = OPEN",
    "y": "int|null  intra-sector row 0..31; null = OPEN",
    "color": "'blue'|'green'|'red'|null",
    "subtype": "int|null  SEC byte-1 in {1,2,3,4}",
    "level_req": "int|null  travel.html level gate",
    "dest": "{sector_base,x,y,layer}|null  JUMP target; null = OPEN/LOST"
  },
  "teleportals": {
    "HAV_INN": {
      "sector_base": null,   // sector EWGB194225b (W Haven, world ~99,200,b) is VERIFIED,
                             // but the exact (x,y) cell is OPEN -> stays null
      "x": null, "y": null,
      "color": "blue",       // DERIVED (all 6 Haven cells are byte-1=0x01)
      "subtype": 1,
      "level_req": null,
      "dest": null           // OPEN/LOST (.CRT)
    }
  },
  "_haven_sector_scan": "EWGB194225b holds 6 byte-1=0x01 teleportal cells at intra-sector (x,y): (3,6),(26,8),(22,14),(31,19),(21,21),(30,21); all byte-5=0. Which is HAV_INN: OPEN.",
  "_level_table_DOMAIN_DOC": "see §8 — the travel.html level gates; reference only, NOT a tile binding"
}
```

- **Two rows are pinned in the shipped file: `HAV_INN` and `HAV_CHURCH`** (tile
  bindings only; every `dest` stays `null` = LOST). The shipped file extends this
  schema with a per-row `world {x,y,layer}` convenience field (stub world coords,
  ready for direct `player.x/y/layer` assignment) and a top-level
  `recall_destination: "HAV_CHURCH"` pointer for the `0x5a` handler; its
  `_haven_sector_scan` now covers BOTH Haven ground sectors (12 `b1==1` cells,
  all `byte5==0`). The other 351 names are vocabulary (§4.3), not bindings — no rows.
- Loader: `_load_teleportal_registry()` (cached, env-gated `MRA_TP_REGISTRY`,
  default on) + `tp_registry_lookup(name) -> dict|None`. Cross-check every key
  against `teleporter_names.json` valid_names; log mismatches.

### 4.3 Relationship to `teleporter_names.json`

353 names from 3 live client TP-list dumps (`VERIFIED-OBSERVED`), **not a binding**.
Two roles: (1) validation/autocomplete vocabulary — a FORGET/TP arg matching a
valid name is real, not a typo; (2) the optional login bulk roster (§5.3).
`HAV_INN` is in the vocabulary. The 4 travel.html names absent from the dumps
(`ORCS_G1, OMR_3B, DOC_1, PRG_2`) are observation gaps, not contradictions.

---

## 5. Component specs

### 5.1 Tile detection

`teleportal_under(world, player) -> {subtype, name, byte5, x, y, layer} | None`:
read SEC record byte-1 (object) via `world.tile_at(x, y, layer, byte_offset=1)`;
if in `{0x01..0x04}`, also read byte-5. Pure, no I/O beyond the cached sector.
Refresh `player.on_teleportal` on the movement tail and at world-entry; log the
transition onto a TP (`detect+log`). `VERIFIED` accessor (`tile_at`, `SEC_RECORD_SIZE=6`).

### 5.2 Command handlers (recv-loop branches, gated by `MRA_TP`)

- **`0x38` MEMORIZE** — on-tile check; green→refuse (owner-only, unmodeled);
  resolve cell→name (`OPEN` for every live cell → honest refuse); on a known name,
  dedup + `insert(0, name)`; push `0x35` add if `MRA_TP_PUSH`.
- **`0x39` FORGET** — decode `[name]` uppercased; arg-less ⇒ TP-under-player
  (same `OPEN` cell→name ceiling); remove from list; push `0x36` if `MRA_TP_PUSH`.
- **`0x5a` RECALL** — combat-in-sight block; church cell now **PINNED**
  (registry `recall_destination` → `HAV_CHURCH` = world(104,187,b), landing cell
  `RE-AUTHORED`); the death-state model is still `OPEN` ⇒ until death exists,
  acknowledge + log + freeze; once modeled, relocate via `teleport_jump` to the
  registry cell.
- **`handle_tp(... arg)`** — TP `<name>` / RETURN logic, written but **UNREGISTERED**
  (opcode `OPEN`). Validates (on-tile + memorized for `<name>`; anywhere +
  last_tp + Stamina-half cost + combat-block for RETURN), then refuses because
  every `dest` is `OPEN`. Ready to wire the instant §6a lands.

Name-arg decode (mirrors the verified `parse_take_arg`):
`bytes(pb).split(b'\x00',1)[0].decode('latin-1').strip().upper()`.

### 5.3 Transport + login bulk-push

- `teleport_jump(conn, prefix, world, player, dest, used_name)` — set
  `player.x/y/layer = dest`, `last_move_dir = -1`, then `send_world_update(...,
  force_full_render=True)`. Cross-sector change auto-prepends the `0x3c` RESET
  (the verified "teleport / new sector" full-grid-clear path). Updates `last_tp`.
  **Callers pass only a non-null known dest — never a guess.** Today unreachable
  in production (no known dest); unit-testable with a synthetic dest row.
- **Login bulk** — splice the roster into the existing `0x2e`→`0x21` reply at the
  **single TP-list NUL** after `encode_world(1)` (NOT a trailing `\x00\x00\x00` —
  see the §2.2 stale correction; the real tail interleaves `_land_tok`):
  `encode_world(1) + b''.join(n.encode('latin1')+b'\x00' for n in names) + b'\x00' + _land_tok + b'\x00' + b'\x00'`.
  Identical to current behavior when the roster blob is empty. Also seed
  `player.memorized_tps` to the pushed set so server/client agree. Gated
  `MRA_TP_BULK`, default OFF. Quiet (no per-name message), unlike the `0x35` path.

### 5.4 Env flags

| Flag | Default | Effect |
|---|---|---|
| `MRA_TP` | **on** | the whole subsystem (state + detection + handlers + logging). Emits NO client packets on its own → cannot disturb the live client. |
| `MRA_TP_PUSH` | **off** | enable S2C `0x35`/`0x36` client pushes (VERIFIED decode; live-test pending). |
| `MRA_TP_BULK` | **off** | splice the known roster into the login `0x21` + seed `memorized_tps`. |
| `MRA_TP_REGISTRY` | on | load `mra_teleportal_registry.json`. |

Default behavior = full server-side subsystem with logging, **zero client
packets** — safe to run against the live client.

---

## 6. Ghidra investigation targets

Ordered. Items (b) are **already done this session** (kept here for the record).

- **(a) — C2S TP opcode `[DONE 2026-07-16 — 0x3a, VERIFIED 2×]`.** Closed by the
  full CMDList hex dump (`3a 00 "TP"` @0x44a924, `MD/CMDLIST_153_COMPLETE.md`)
  AND an independent live capture (`RECV type=0x3a payload="HAV_INN"` /
  `"RETURN"`). RETURN is a **plain text argument**, not a subcode. The same dump
  byte-confirmed **RECALL 15.3 = `0x5a 00` @0x44a448** (also live-captured) and
  **MEMORIZE `0x38` live**. `handle_tp` is unblocked — register on `0x3a`.
- **(b) — S2C add/forget/bulk wire `[VERIFIED — done this session]`.** Recovered:
  bulk `0x21` body (`FUN_004089dd`), incremental `0x35`/`0x36` (`FUN_00420ba8`),
  cap buffer (`0x1001`). Remaining minor: the exact numeric cap *count* (vs the
  byte size) if ever needed.
- **(c) — destination resolution `[likely LOST]`.** Confirm whether the running
  15.3 build resolves a dest from SEC byte-5 at all (scan shows byte5=0
  everywhere → dest lived entirely in `.CRT`, which is `LOST`). Closing this as
  `LOST` makes detect-log-freeze permanent and correct.
- **(d) — color↔subtype `[OPEN, cosmetic]`.** OBJ.256 loader `FUN_00405b6f` +
  slot table `DAT_0044f7a0` if pixel confirmation of blue=`0x01` is ever wanted.

---

## 7. Phasing & live-test

Commit order (each independently testable; new `test_teleportal.py`, run as
`python3 test_teleportal.py` per CLAUDE.md §2):

1. **State + detection** — Player fields + `teleportal_under()` + refresh hooks +
   log. Test: returns subtype `0x01` on the 6 `EWGB194225b` Haven cells, `None`
   elsewhere (real SEC fixture).
2. **Registry + loader** — `mra_teleportal_registry.json` (HAV_INN, mostly null)
   + loaders + vocab cross-check. Test: loads, HAV_INN `subtype==1`/`color=='blue'`,
   all dest `null`; loader treats null as OPEN.
3. **MEMORIZE/FORGET/RECALL handlers** — recv-loop branches + list management +
   RECALL combat-block. Test: insert-top ordering, dedup, removal, arg-less FORGET
   refuses without a bound name, RECALL refuses when hostiles in sight. (Server
   state only; pushes gated off.)
4. **RETURN + `teleport_jump`** — Stamina-half cost + in-sight block + dest-OPEN
   refuse; `teleport_jump` with a synthetic dest row (assert coords/layer set,
   `last_tp` updated, cross-sector `0x3c`).
5. **(after §6a) Wire the TP opcode + enable pushes** — register `handle_tp`;
   `MRA_TP_PUSH`/`MRA_TP_BULK` live tests below.

Full regression (all `test_*.py`) before each commit. Commits 1–4 ship
independently of the `OPEN` TP opcode.

### Live-test checklist (you run, against the 15.3 client)

- `MRA_TP_PUSH=1` → from a server console, send a `0x35` add with a test name →
  expect the client to print **"You now know <name>"** and the name to appear in
  the **(T)** pulldown. Send `0x36` → **"You have forgotten <name>"**, name gone.
- `MRA_TP_BULK=1` → reconnect → expect the **(T)** pulldown to populate with the
  roster (RETURN auto-prepended by the client). If "Your TP list is too big"
  appears, the cap is hit — the server already logs what it dropped.
- These confirm the 15.3 framing of the VERIFIED-decode packets. If confirmed,
  flip `MRA_TP_PUSH`/`MRA_TP_BULK` defaults on.

---

## 8. Reference: travel.html level gates (`DOMAIN/DOC`)

From `mra.wikidot.com/gameplay:travel.html` — Runes and TPs with level
requirements. Reference only; **not** a tile binding. Stored for `level_req` UI/
validation.

```
Valley of the Krell  Rune  Special*      Dunsmore   Rune  GP        BKE        Rune  6
Grave of Krell Heroes Rune 7             Orc Fortress Rune 7        Orcs_1     TP    7
REM   Rune 8     BKE-* TP 9     REM_1 TP 10    Orcs_G1 TP 11    Maranda Rune 13
Krell_G4 TP 13   REM_2 TP 13    THF_2 TP 14    Mar East TP 15   Mar West TP 16
OMR Rune 17  OMR_1 TP 17  Persepolis Rune 17  Per_W TP 17?  IUN Rune ??  THF_AC TP 18
OMR_3B TP 19  Per_K TP 19  Per_M TP 19  Per_MK TP 21  IUN1 TP 22  PER_SW TP 22
DOC Rune&TP 23  DOC_1 TP 23  DOC_2 TP 26  DOC_3* TP 26  DOC_4 TP 28  APH_* TP 29
GOM1_NE/SE TP 29  PRG 1 Rune 29  DOA_2 TP 30  GOM1_W TP 30  PRG_2 TP 30  GOM Rune 31
GOM2/2B TP 31  GOM2_C TP 32  GOM3_NE/SE TP 33  Jalzabad Rune 33  GOM3_W TP 34
Jal_FE TP 34  BT_* (L1) TP 35  Jal Elite Rune 36  JAL_TF* TP 36  Jal_Bun* TP 38
JAL_KF* TP 40  JAL_EW TP 42  JAL_EM TP 44  JAL_EK TP 46  Jal_Pal2 Rune 46
BT_* (L7) TP 47  Jal_P1* TP 48  Jal_Pal2 TP 50  Jal_P2* TP 50  Baralza Rune 50
Baralza TP 51  Bar_Arena TP 52  MND-3/4 TP 52  Val_MC TP 54  Val_2 TP 54
MND-4B TP 54  MND-5 TP 55  Val_3* TP 56  Val_4* TP 58  MND-6 TP 62  VRG_M1 TP 62
Val_RG* TP 62  MND-6B TP 65  MND-7 TP 67  VAL_MC5* TP 64
(* a starred prefix = all TPs sharing that prefix are the same level.)
```

---

## 9. Integration anchors (symbol-based; line numbers drift — re-verify before editing)

`mra_stub.py` is under concurrent edit; prefer symbol names over line numbers.

- Tile accessor: `WorldMap.tile_at(world_x, world_y, layer, byte_offset)`; consts
  `SEC_GRID_DIM=33`, `SEC_PLAY_DIM=32`, `SEC_RECORD_SIZE=6`.
- Player fields: end of `Player.__init__` (after the per-turn-flag block).
- Dispatch ladder: the `if/elif pkt_type == …` chain in `handle_mra`; insert new
  branches near the `0x5d`/`0x4e` name-arg handlers. `player` is created at the
  top of `handle_mra`. `pb = payload or b''`.
- Name-arg model: `parse_take_arg`.
- Relocate: `send_world_update(conn, magic, prefix, world, player,
  force_full_render=...)` (auto `0x3c` on sector/layer change); `encode_world(n)`.
- Bulk-push splice point: the `0x2e` (WORLD REQUEST) handler.
- Combat block: `combat_adjacent_hostiles(world, player)`.
- Login bulk handler (client): Ghidra `FUN_004089dd`; S2C add/forget dispatcher:
  `FUN_00420ba8`; (T)-list reader / TP-opcode TODO: `FUN_004208ed`.
- Objects already render via `build_object_grid` (`0x3e`) — **no change needed**.

---

## 10. What this plan does NOT do

- Does not fabricate the TP opcode, any destination, or the 15.3 push framing.
- Does not model room ownership, death-state, or Karma/Mana pools (all `OPEN`).
- Does not enable any client-facing packet by default (everything gated until a
  live test confirms 15.3 framing).

---

## 11. ADDENDUM 2026-07-16 — Increment-1 scope + new recoveries

### 11.1 New recoveries (2026-07-16 session; registry shipped in `99e77d4`)

- **TP arrival line = player-result table idx `0x3b`** — *"You feel like you've
  been picked up by a tornado."* (`VERIFIED` string+index: 12.5h `@0x44001b`,
  `MD/COMBAT_RESULT_TEXT.md:206`; the 15.3 image shares the table/indices per the
  ranged determination in that file). Rendered **BLUE** in a live-era screenshot
  (user archive, posted 2026-07-16) that also shows a green room-TP rendered in an
  inn room and the combat block firing. Emit mechanism = the shipped twinge
  pattern: `build_packet(MAGIC_SERVER, <channel>, bytes([0x3b]))`
  (`drain_bind_twinge` precedent, `[0x31][0x3e]` green). **Channel RESOLVED:
  emit `[0x30][0x3b]`** — colour rides the CHANNEL byte and channel `'0'` (0x30)
  → colour code 1 = blue, per the already-established determination in
  `MD/COMBAT_RESULT_TEXT.md` §"Player-own result channel — RESOLVED", now
  **re-verified on the 15.3 image** (composer `FUN_0042700a` decompiled
  2026-07-16: table select + full colour chain `'/'`→0 `'1'`→2-green `'2'`→4
  `'Q'`→8 `'3'`→0xc `'R'`→0xf default→1-blue). An earlier §11.1 revision
  floated `0x29`/`0x2d` "candidates" — that conflated the server-composed-text
  class bytes with the templated-channel model; superseded. (The screenshot's
  near-black "You parry." vs blue tornado is logged as an era-variance note in
  COMBAT_RESULT_TEXT.md; stub combat emit stays `0x30`.)
- **TP combat-refusal wording RECOVERED verbatim** from the same screenshot:
  *"You cannot teleport while engaged in combat."* — rendered **GREEN**. Absent
  from every recovered client string table → server-composed text (green class
  `0x2a` precedent: flower-bed msg). Wording `DOMAIN/DOC-RECOVERED`; transport
  `RE-AUTHORED` (§14 text path). Strengthened 2026-07-16: a `list_strings`
  filter sweep of the 15.3 Ghidra image finds **no** "cannot teleport" string →
  server-composed confirmed to the limit of the defined-strings coverage.
- **TELEPORT is a SPELL, distinct from the TP travel command** (`VERIFIED`
  2026-07-16): the 15.3 CMDList holds a glued defined string `"a.TELEPORT"
  @0x44a765` — printable header bytes fused onto the keyword by the strings
  analyzer, i.e. **opcode `0x61` (spells) subcode `0x2e`, keyword `TELEPORT`
  @0x44a767**. Do not conflate with `TP <name>` (opcode still `OPEN`; its
  header bytes are unprintable — subcode `0x00` — so no glue trick; §6a GUI
  read or the §11.4 live capture remains the unblock).
- **RECALL 15.3 opcode CONFIRMED `0x5a`** (was: keyword-only @0x44a44a): the full
  CMDList hex dump reads `5a 00` @0x44a448, and a live `RECALL` keystroke arrived
  as `type=0x5a payload=[]` (2026-07-16). The 12.5h→15.3 carry-over is now
  `VERIFIED` on both channels.
- **`mra_teleportal_registry.json` now EXISTS** (repo root) with `HAV_CHURCH`
  world(104,187,b) and `HAV_INN` world(99,200,b) pinned + `recall_destination`
  → `HAV_CHURCH` (see §3/§4.2 updates).

### 11.2 TP `<name>` needs NO per-tile dest — scope upgrade over §5.2

§5.2's "refuses because every dest is `OPEN`" conflated two lookups. The `LOST`
`.CRT` byte-5 data is the **cell→name/record** binding (needed for MEMORIZE on an
arbitrary cell, and for fixed-destination red/instant portals). The TP command
itself needs only **name→tile** — *"TP followed by the name of the teleportal"*
takes you to the named portal (`DOMAIN/DOC`, HELP.TXT:242-252) — and that is
exactly what the registry rebuilds. **With two rows pinned, `TP HAV_CHURCH` ↔
`TP HAV_INN` is a real, non-fabricated jump** (dest = the named row's own tile,
`world {x,y,layer}` field, ready for `teleport_jump`). `TP RETURN` = `last_tp`.
Unpinned names → honest refuse (name valid per vocabulary, tile `OPEN`).

### 11.3 NEW behavior — step-on-teleportal BLACKOUT (user testimony)

- **Behavior:** while the player stands ON a teleportal tile, the view blacks
  out except the teleportal tile itself. Grade: `DOMAIN` — ex-player firsthand
  recall (the project's established testimony precedent); no manual/wiki
  corroboration found (swept HELP/MANUAL/wiki travel+commands+interface pages);
  the 2026-07-16 screenshot does not evidence it either way (player not on the TP).
- **Mechanism `RE-AUTHORED`, server-side** (the client does no LOS; fog-hiding is
  entirely server-side, CLAUDE.md §7): one gate in `compute_visibility` — if the
  player's own cell object byte ∈ {0x01..0x04} → return `{player cell}` only.
  Every emitter already threads its visible/lit set from `compute_visibility`
  (terrain `0x3d` via `build_tile_grid` masking, objects `0x3e`, edges, floor
  items, critters `0x47`/`0x48` lit-gating), so the restriction propagates with
  **zero new packets**; unlit cells render as void via the existing per-step
  `0x3c` tile-clear + omission. The `rowΔ==100` minimap caveat
  (`MD/MOVEMENT_PROTOCOL.md`) does not apply (no full-clear involved).
- **Gate:** `MRA_TP_BLACKOUT`, default **on** (pure emission-shaping; `0` restores
  current behavior). Open detail: whether the original blackout kept the player's
  own wall/door edges visible — start with `{player cell}` only, tune against
  testimony.

### 11.4 TP-opcode unblock — DONE 2026-07-16 (live capture + hex dump)

Executed same-day: `TP HAV_INN` → `RECV type=0x3a payload="HAV_INN"`;
`TP RETURN` → `type=0x3a payload="RETURN"` (plain arg, not a subcode);
`RECALL` → `type=0x5a` (sent even while alive; the stub's death-session build
already answered "RECALL (0x5a) while alive — no-op"); `MEMORIZE` → `type=0x38`.
Cross-checked against the full CMDList GUI hex dump the same day — both
channels agree. **Complete table decode: `MD/CMDLIST_153_COMPLETE.md`** (also
closes: CI = 15.3 keyword `0x56`; DUMP = `0x4e`; the @0x44a9d0/0x44aa58 menu
tables; the TUNE colour table @0x44a990).

### 11.5 Persistence (gap in §4.1/§7)

`memorized_tps` + `last_tp` must round-trip through `save_character_state` /
`restore_player_state` (§SAVE) with backward-compatible defaults (`[]` / `None`),
the malformed-blob guard, and uppercase stored names. Add a save→reload
round-trip assertion to §7 step 1's test.

### 11.6 MEMORIZE on the 10 unnamed Haven cells

Registry reverse-lookup (sector_base,x,y)→name resolves for the 2 pinned rows
only; the other 10 `VERIFIED` `b1==1` cells get an honest refusal whose log line
doubles as the pin-workflow prompt (`[tp] MEMORIZE on unnamed TP cell
world(x,y,layer) — walk-and-record to pin, see registry _haven_sector_scan`).

### 11.7 Increment-1 commit order (adjusts §7) + SEQUENCING CONSTRAINT

1. State + detection + **persistence** (11.5) — no client packets.
2. Registry loader + vocab cross-check (file exists; 2 rows pinned).
3. MEMORIZE `0x38` / FORGET `0x39` handlers + **blackout gate** (11.3) +
   arrival/refusal text plumbing (11.1) — behind `MRA_TP`; pushes stay
   `MRA_TP_PUSH`-gated.
4. TP live-capture session (11.4, user-run) → register `handle_tp`;
   `TP HAV_CHURCH ↔ HAV_INN` becomes the first real jump (11.2); `TP RETURN`.
5. §7 live-test checklist for `0x35`/`0x36`/bulk-`0x21`; flip push defaults on
   green.

**SEQUENCING:** `mra_stub.py` is under active edit by the death/RECALL session
(git `M mra_stub.py` + untracked `MD/PLAYER_DEATH_RECALL_RAISE.md`, 2026-07-16).
Steps 1–3 must NOT be implemented from a second session until that work commits
(CLAUDE.md §2.1 one-session-per-tree). RECALL (`0x5a`) itself stays with that
session; its destination is served by the registry's `recall_destination`.

---

## 12. WIRING READINESS — the 5 rudimentary-TP questions answered (2026-07-16)

Read-only surface map (4-agent sweep + Ghidra) answering "what else do we need."
All primitives exist; the gap is code at pinned sites. **`mra_stub.py` is under the
death/RECALL session's active WIP (`git status` = `M`) — symbol-anchor everything;
do NOT edit until that lands.** The death session already built the load-bearing
precedents: `execute_recall`, `emit_player_result`, `_church_cell_from_registry`.

### 12.1 MEM → (T) dropdown — what's needed (Q1/Q4)

The client mechanism is fully `VERIFIED` (15.3 `FUN_00420ba8`, §2.2). C2S MEMORIZE
`0x38` carries an **empty payload** (live-captured) — the client sends "memorize
what I'm on", the **server** resolves tile→name and echoes S2C `0x35 [name\0]`,
which the client inserts at list-top and prints "You now know \<name\>". **There is
no separate memorize string — that push IS the confirmation** (Q4 answered).

Gap list (HAVE / NEED), symbol-anchored:
1. NEED `elif pkt_type == 0x38:` branch — today `0x38` hits the terminal
   unhandled `else` ("cmd 0x38 … resending world"). Slot beside the RECALL branch.
2. HAVE on-tile detect: `world.tile_at(player.x, player.y, player.layer, byte_offset=1)`
   ∈ {1,2,3,4}. NEED to call it in the branch.
3. NEED tile→name reverse lookup. HAVE the registry + load precedent
   (`_church_cell_from_registry`). Reverse dict `{(w.x,w.y,w.layer): name}` over rows
   with non-null `world` resolves **exactly HAV_CHURCH + HAV_INN**; every other
   `b1∈{1..4}` cell → `None` → **honest refuse** (name binding LOST; never default).
4. NEED `player.memorized_tps` field (grep = zero today) in `Player.__init__`;
   MEM = dedup + `insert(0, name)`.
5. NEED the S2C `0x35` push: `conn.sendall(build_packet(MAGIC_SERVER, 0x35, name.encode('latin1','replace') + b'\x00'))`
   — precedent `drain_bind_twinge`. Gate `MRA_TP_PUSH` (default OFF).
6. NEED (relog persistence) `memorized_tps` in `serialize_player_state` /
   `restore_player_state` (transient class, like pools).
7. NEED (optional) login bulk splice — §5.3 (corrected tail).

**Minimal "MEM adds to dropdown on click" = items 1+2+3+4+5.**

### 12.2 Enumerating every blue TP on the current map (Q2)

WorldMap lazy-loads SEC bytes per base into `_sec_cache`; `tile_at(...,byte_offset=1)`
= object byte; family `b1∈{1..4}` (1=blue/public, 2=room/green, 3=instant,
4=invisible), blue-only = `b1==1`. Natural granularity = **per-sector** (the
player's current sector via `current_sector_key` → `lookup_base`), which is what the
client can reach and usually already cached. Recipe (model on the spawn breathing-
room scan, which already does the full-sector iterate + intra→world inversion):

```
data = world.load_sec(base)                       # 6534 bytes or None
x0 = sect['x_block']*SEC_PLAY_DIM ; y0 = world.y_axis_ranges[sect['y_block']][0]
for iy in range(SEC_PLAY_DIM):                     # 0..31
  for ix in range(SEC_PLAY_DIM):
    b1 = data[(iy*SEC_GRID_DIM + ix)*SEC_RECORD_SIZE + 1]
    if b1 == 1:  hits.append((x0+ix, y0+iy, sect['layer']))   # or 1<=b1<=4 for the family
```

Confirmed byte-for-byte against the registry `_haven_sector_scan` (6 cells each in
EWGB162193b / EWGB194225b). A global sweep = `for base,s in world.sectors.items()`
but force-loads all **117 mapped** sectors (the 12 unmapped `.SEC` on disk are
unreachable via WorldMap). New free fn `scan_teleportals(world, base)` near
`build_object_grid`/`probe_tile`.

### 12.3 Blackout when standing on a blue TP (Q3) — YES, understood

Single gate, `SUFFICIENT`: inside `compute_visibility`, right after the player cell
is seeded (`visible.add((PLAYER_SCREEN_ROW, PLAYER_SCREEN_COL))`), early-return
`{(PLAYER_SCREEN_ROW, PLAYER_SCREEN_COL)}` when
`world.tile_at(player.x,player.y,player.layer,byte_offset=1) in {1,2,3,4}`
(null-check first). **Must live in `compute_visibility`, not the main emit path** —
because `build_critter_packet` (0x47/0x48) re-derives visibility by calling
`compute_visibility` itself; a main-path-only gate would leak critters/peers. Every
per-step emitter (terrain 0x3d, objects 0x3e, edges 0x3f-0x42, floor 0x44,
critters 0x47/0x48) masks by the set → omitted cells stay 0 → render as void via
the per-frame `0x3c` tile-clear. Caveats: (a) gate only fires when `FOV_ENABLED`
(default on) — for FOV-independent blackout add a parallel `MRA_TP_BLACKOUT` gate in
BOTH the main path and `build_critter_packet`; (b) `emit_world_floor_cell` (combat-
event single-cell 0x44) doesn't mask — a corpse/ammo drop at a non-player cell
during combat-on-a-TP could leak one cell until the next step (narrow); (c) confirm
the object-byte 0x01..0x04 TP semantics (byte_offset=1) vs the *terrain* stair
codes 0x04/0x05 at byte_offset=0 — different layers, don't conflate.

### 12.4 The actual jump + tornado print (Q5) — proven precedent exists

`execute_recall` already does exactly the relocation this needs. TP `<name>`:
1. Parse arg: `bytes(pb).split(b'\x00',1)[0].decode('latin-1').strip().upper()`
   (client already uppercases; registry keys are uppercase).
2. Registry lookup (`_church_cell_from_registry` pattern): `dest = reg['teleportals'][name]['world']`
   → `(x,y,layer)`. Only HAV_CHURCH/HAV_INN have non-null `world`; **NO coordinate
   conversion** — registry `world{}` IS player coords.
3. `player.x, player.y, player.layer = dest` (do NOT call `maybe_layer_transition`
   — that's for stair terrain; TP sets layer explicitly).
4. **Two sends** (the load-bearing detail, per `execute_recall`):
   `send_world_and_critters(...)` first (consumes the cross-sector `0x3c` RESET,
   which carries no `0x4a`), then `send_world_update(..., force_full_render=True)`
   (same-sector now → emits the `0x4a` that forces the sprite repaint). One call
   alone leaves the new sector unpainted.
5. Tornado: `conn.sendall(emit_player_result(0x3b))` — `emit_player_result` builds
   `build_packet(MAGIC_SERVER, 0x30, bytes([0x3b]))` = blue "picked up by a
   tornado." (Q5 print answered; `emit_player_result` already exists.)
6. Optional: `mp_broadcast_move` so peers see arrival.
Handler slots as `elif pkt_type == 0x3a:` before the unhandled `else`.
**`TP HAV_CHURCH ↔ TP HAV_INN` works end-to-end today with zero fabrication**;
every other name refuses honestly (dest OPEN). **SHIPPED since (§13):** the
on-teleportal + memorized gates (`MRA_TP_STRICT`) and RETURN's half-STA/KAR/MAN
toll. Open extras: `level_req` gating (null for both), arrival anti-stack scatter
(unmodelled), green-TP owner gate.

---

## 13. DETERMINATION — off-teleportal gate + the RETURN toll (2026-07-19)

**Question (user):** is TP RETURN the ONLY TP variant executable while NOT standing
on a teleportal, and is that why it costs 50% endurance?

**Answer: YES on both, confirmed from three independent angles — SHIPPED.**

1. **`HELP.TXT:244-252` (on-disk creator help, `VERIFIED-DOC`), verbatim:** *"The
   Teleport command (TP) will move you from one teleport to another. However, to TP
   to any teleport you must memorize that teleport at it's location. … You must be
   on a teleport to use the TP command **unless you use TP RETURN, which may be used
   anywhere**, and will return you to the last teleport you used, **but will cost you
   half of your remaining endurance**."* The causal link the user proposed is the
   sentence's own grammar — "may be used anywhere … **but** will cost … half."
2. **Wiki `gameplay:commands` (15.3-era, `DOMAIN/DOC`), verbatim:** *"You can also
   use TP RETURN, which can be used anywhere; this will return you to the last
   teleport you used, but will cost you half of your remaining **Stamina, Karma,
   Mana** (this is typically used as a **last resort, or if you get stuck
   somewhere**)."* Makes the design intent explicit: RETURN is the escape hatch; the
   toll is the price of the anywhere-convenience.
3. **Binary, `VERIFIED`-by-absence (15.3 `list_strings`):** the ONLY "teleport"
   string in the client is `"a.TELEPORT"` (the TELEPORT *spell* keyword). There is
   **no** "must be on a teleport" refusal, **no** memorize-requirement string, **no**
   cost message — so the on-tile gate, the memorize requirement, AND the toll were
   all **server-side and are `LOST`** (matches the live capture: the client sends
   `TP 0x3a` unconditionally). Re-authored server-side here.

**Shipped consequences (commit follows §12; `tests/test_teleportal.py` green,
regression 70/70):**
- `TP <name>` now requires standing **on a teleportal** AND having **memorized** the
  name (both `VERIFIED-DOC`), gated by `MRA_TP_STRICT` (default **on**;
  `MRA_TP_STRICT=0` relaxes both for testing). No client refusal string exists, so a
  failed precondition refuses **silently** (server-side log only) — never a
  fabricated line.
- `TP RETURN` is the sole off-tile variant (no on-tile gate) and pays
  `_tp_return_cost` = **half of remaining Stamina + Karma + Mana** (§1.1, upgraded
  from stamina-only now that all three pools are modeled).
- Still `OPEN`: RETURN's "in sight of hostiles" block currently uses the
  combat-visible proxy; green-room ownership; `level_req` gating.

---

## 14. REFINEMENTS 2026-07-19 (owner corrections) — RETURN damage band + combat gate

Two owner corrections to §13, both determined and shipped:

1. **RETURN's cost is DAMAGE, not fatigue.** Owner `DOMAIN` testimony: "TP RETURN is
   damage, not fatigue." The stub's pools carry two afflliction bands (per
   `mra_combat.Pool`): a recoverable **FATIGUE** band (`stamina_damage` /
   `karma_fatigue` / `mana_fatigue`; FRR-recovered) and a permanent **STRESS/DEFICIT**
   band (`stamina_deficit` / `karma_deficit` / `mana_deficit`; healed, not ticked
   back). §13 first shipped the toll on the fatigue band; corrected to the **deficit
   band** — a last-resort escape leaves a lasting wound. `_tp_return_cost` now hits
   `_deficit`; the fatigue bands are left untouched (asserted in `test_return_cost`).
   (Note the historical field-name inversion flagged at `mra_stub.py` Player.__init__:
   `stamina_damage` is the *fatigue* band despite its name — the wire slot the client
   labels "DAMAGE" is the recoverable band. The player-facing "damage" the owner means
   is the *deficit/stress* band.)

2. **TP RETURN IS combat-gated — `VERIFIED-DOC`.** `MANUAL.TXT:533-534`: RETURN "will
   not work if you are currently engaged in combat." Already implemented (the shared
   `_combat_visible_near` gate at the top of `handle_tp` precedes the RETURN branch),
   now cited + covered by a RETURN-specific combat-block test (no move, green refusal,
   and **no damage charged** since no teleport occurred). Same green "You cannot
   teleport while engaged in combat." line as `TP <name>`.

Regression 70/70; `tests/test_teleportal.py` green (RETURN cost asserts the deficit
band + untouched fatigue; combat block covers both TP <name> and TP RETURN).

**3. Wire-flush fix (2026-07-19) — "only stamina was damaged."** The cost is
`remaining // 2` **per pool** (owner examples: full 144 → 72; a pool already at a
remaining of 100 → 50 — i.e. half of CURRENT remaining, not of max), applied to each
pool's `_deficit`. But live, only the stamina bar moved: `send_world_update` re-emits
the **stamina** substream (on `stamina_dirty`) yet **never** the karma/mana substream
— those only ride `_flush_player_endurance`, gated on `karma_dirty`/`mana_dirty`.
`_tp_return_cost` was charging all three deficits but marking none dirty, so
karma/mana never reached the client (stamina showed only because `stamina_dirty` was
incidentally set by prior movement). Fix: `_tp_return_cost` now sets
`stamina_dirty = karma_dirty = mana_dirty = True`, so the RETURN branch's
`_flush_player_stamina` + `_flush_player_endurance` transmit all three deficit bands
(`test_return_cost_formula` + `test_return_cost_flushes_all_bars`).

---

## 15. DETERMINATION 2026-07-19 — (T)-list storage scope + sort order

**Q1: is the memorized (T)-list saved PER-ACCOUNT or PER-CHARACTER?**

**PER-CHARACTER** — owner confirmed 2026-07-19. (An earlier pass shipped it
per-account on a first owner recollection; that was **rolled back** the same day when
the owner corrected it. History kept here so the account model is not re-introduced.)

This was never independently verifiable from surviving sources — the server-side
storage schema is `LOST`; `HELP.TXT`/`MANUAL.TXT`/wiki make no explicit statement; and
the 3 live TP-list dumps can't disambiguate (unknown whether any share an account). The
one adjacent datum — wiki "the **character records** are saved" on host-down — mildly
*leaned* per-character, and the owner's corrected firsthand testimony (`DOMAIN`) settles
it: **per-character.**

**SHIPPED (per-character):** `memorized_tps` AND `last_tp` both ride the active
character's `save` blob (`serialize_player_state` -> `restore_player_state`), so each
character keeps its own list; a different character on the same account does NOT inherit
it (`test_per_character_tp_list`). No account-level TP storage exists. Grade: `DOMAIN`
(scope, owner-confirmed) / `RE-AUTHORED` (storage; original schema `LOST`).

**Q2: what order is the (T)-list sorted in?**

**Newest-memorized at the TOP (recency / insertion order), with `RETURN` pinned first —
NOT alphabetical, NOT by level.** Well-determined:
- `VERIFIED` (binary): `FUN_00420ba8` case `0x35` inserts a newly-memorized name at the
  TOP of the list buffer (right after the client-pinned `RETURN`) — §2.2.
- `DOMAIN/DOC`: wiki "**newly memorized teleportals are placed at the top of your list**";
  the `FORGET`-then-re-`MEMORIZE` "move to top" idiom (`MANUAL.TXT:4333`, wiki) only makes
  sense for a manually-orderable recency list — an auto-sorted list couldn't be reordered
  that way.
- Red herring: the wiki's "listed in order of level" is the **travel-page's own table**
  of TPs by level requirement, NOT the in-client (T) dropdown.

**EMPIRICALLY CONFIRMED 2026-07-19** from the 3 live-character TP dumps
(`reference/dumps/DUMP`, `DUMP (1)`, `DUMP (2)` — md5-matched live captures). Names
extracted in raw byte order (offset 13, after the `SGN` header):
- **NOT alphabetical** — adjacent-ascending fraction 39–41% (random ≈ 50%; sorted = 100%).
- **Recency, newest-at-top** — in ALL three dumps the Haven/start-town TPs (HAV_*, plus
  SANCTUARY/VERBONIC/GREENWOOD) cluster near the BOTTOM (mean normalized position
  0.65 / 0.65 / 0.73) vs other TPs (0.47 / 0.49 / 0.38). Haven is where every character
  starts, so its teleportals are the OLDEST memorizations -> they sink to the bottom,
  while late-game high-level areas (Baralza/Jalzabad/deep dungeons) sit at the top. A
  level spot-check rules out level-sorting (BAR_PUB L51 -> VAL_1 L54 -> JAL_P3S L48 is
  non-monotonic). **RETURN is NOT in the stored list** (client prepends it at display
  time; the dump names start at the first memorized name).
- Triangulated: binary (`FUN_00420ba8` 0x35 insert-at-top) + wiki ("placed at the top")
  + this live data all agree -> `VERIFIED`.

Already implemented correctly: MEMORIZE does `insert(0, name)` (newest-at-top); the login
`tp_bulk_blob` sends names newest-first (reproducing the dump's front=newest layout under
the append model); the client prepends `RETURN`. (Whether the client APPENDS vs PREPENDS on
bulk walk-in stays the one `MRA_TP_BULK` live-test detail; newest-first is the safe choice
matching both the dumps and the VERIFIED incremental insert-at-top.)

---

## 16. REFINEMENT 2026-07-19 — re-MEMORIZE of a known TP is a NO-OP (dedup)

Owner-reported: MEMORIZE-ing the same teleportal repeatedly appended a DUPLICATE to
the (T) list each time. Root cause: `handle_memorize` pushed S2C `0x35` on *every*
MEMORIZE, and the client's `0x35` handler does **no** dedup (it blindly `memmove`-inserts
at the top), so each redundant MEMORIZE added another copy. (The server also wrongly
moved the entry to the top.)

**Correct handling — `VERIFIED-DOC` `HELP.TXT:899-903`:** *"…FORGETting and then
reMEMORIZing a teleportal effectively moving that TP to the top of your list. Note that
you must TP to the teleport in question before doing this…"* The ONLY documented way to
move a TP to the top is **FORGET-then-reMEMORIZE** — which is only meaningful *because a
bare re-MEMORIZE of an already-known TP is inert*. So:
- MEMORIZE a **not-yet-known** TP -> insert at top + push `0x35` ("You now know").
- MEMORIZE an **already-known** TP -> **NO-OP**: no duplicate, no move-to-top, no `0x35`
  push. **Silent — `VERIFIED`-by-absence 2026-07-19:** an exhaustive 15.3 `list_strings`
  sweep (`already` / `know` / `memoriz`) finds NO "already memorized" message. The client's
  ENTIRE teleportal string set is three: `"You now know "` @0x44a174, `"You have forgotten "`
  @0x44a184, `"Your TP list is too big. Forget some."` @0x44a198. (A server-composed line
  would be possible — as with the combat-refusal — but there is zero evidence of one; do not
  fabricate wording. If owner testimony surfaces a message, add it at their wording.)
- Move-to-top = FORGET (`0x36` removes) then MEMORIZE (`0x35` re-adds at top).

Fixed in `handle_memorize` (`if name in tps: <no-op + log>`). Guards:
`test_memorize_named` (re-MEM leaves the list unchanged + no `0x35`; N× MEM -> one
entry) and `test_forget_then_memorize_moves_to_top` (the idiom still works).

**Sort-order answer (does the impl match §15 Q2?):** newest-at-top is correct
(`insert(0)`); the ONE thing that was wrong — a bare re-MEMORIZE moving/duplicating — is
now fixed to the no-op the docs require.
