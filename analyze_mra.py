"""
MRA.EXE Binary Analysis Script
Analyzes game data processing for Mystic Realms of Alhanzar client.
Focuses on command byte 0x21 (enter game) and map/room data flow.
"""

import struct
import re
import sys

EXE_PATH = r"MRA.EXE"
IMAGE_BASE = 0x400000

# Key memory addresses from prior analysis
ADDRESSES = {
    0x461C80: "Game data buffer (copied to 0x461C2D on next loop)",
    0x461C2D: "State byte (game flow control)",
    0x44E808: "SGN payload buffer pointer",
    0x460F43: "Sub-command byte location",
    0x4490C4: "Guard flag (enables game data processing)",
}

# Search strings related to map/room/rendering
SEARCH_STRINGS = [
    "room", "area", "zone", "haven", "enter", "load", "draw",
    "render", "display", "screen", "view", "viewport", "paint",
    "map", "tile", "world", "level", "terrain", "sector",
]

def read_exe(path):
    with open(path, "rb") as f:
        return f.read()

def parse_pe_headers(data):
    """Parse PE headers to get section info for VA<->file offset conversion."""
    # DOS header
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    print(f"[PE] e_lfanew (PE header offset): 0x{e_lfanew:X}")
    
    # PE signature
    pe_sig = struct.unpack_from("<I", data, e_lfanew)[0]
    assert pe_sig == 0x4550, f"Not a PE file: sig=0x{pe_sig:X}"
    
    # COFF header
    coff_offset = e_lfanew + 4
    num_sections = struct.unpack_from("<H", data, coff_offset + 2)[0]
    opt_hdr_size = struct.unpack_from("<H", data, coff_offset + 16)[0]
    
    # Optional header
    opt_offset = coff_offset + 20
    magic = struct.unpack_from("<H", data, opt_offset)[0]
    entry_point = struct.unpack_from("<I", data, opt_offset + 16)[0]
    image_base = struct.unpack_from("<I", data, opt_offset + 28)[0]
    section_alignment = struct.unpack_from("<I", data, opt_offset + 32)[0]
    file_alignment = struct.unpack_from("<I", data, opt_offset + 36)[0]
    
    print(f"[PE] Magic: 0x{magic:X} ({'PE32' if magic == 0x10B else 'PE32+' if magic == 0x20B else 'Unknown'})")
    print(f"[PE] Entry point RVA: 0x{entry_point:X} (VA: 0x{image_base + entry_point:X})")
    print(f"[PE] Image base: 0x{image_base:X}")
    print(f"[PE] Section alignment: 0x{section_alignment:X}")
    print(f"[PE] File alignment: 0x{file_alignment:X}")
    print(f"[PE] Number of sections: {num_sections}")
    
    # Parse sections
    sections_offset = opt_offset + opt_hdr_size
    sections = []
    print(f"\n{'Name':<10} {'VirtAddr':<12} {'VirtSize':<12} {'RawOffset':<12} {'RawSize':<12}")
    print("-" * 60)
    for i in range(num_sections):
        sec_off = sections_offset + i * 40
        name = data[sec_off:sec_off+8].rstrip(b'\x00').decode('ascii', errors='replace')
        virt_size = struct.unpack_from("<I", data, sec_off + 8)[0]
        virt_addr = struct.unpack_from("<I", data, sec_off + 12)[0]
        raw_size = struct.unpack_from("<I", data, sec_off + 16)[0]
        raw_offset = struct.unpack_from("<I", data, sec_off + 20)[0]
        characteristics = struct.unpack_from("<I", data, sec_off + 36)[0]
        
        sections.append({
            'name': name,
            'virt_addr': virt_addr,
            'virt_size': virt_size,
            'raw_offset': raw_offset,
            'raw_size': raw_size,
            'characteristics': characteristics,
        })
        print(f"{name:<10} 0x{virt_addr:08X}   0x{virt_size:08X}   0x{raw_offset:08X}   0x{raw_size:08X}")
    
    return image_base, sections

def va_to_file_offset(va, image_base, sections):
    """Convert virtual address to file offset."""
    rva = va - image_base
    for sec in sections:
        if sec['virt_addr'] <= rva < sec['virt_addr'] + sec['virt_size']:
            return rva - sec['virt_addr'] + sec['raw_offset']
    return None

def file_offset_to_va(offset, image_base, sections):
    """Convert file offset to virtual address."""
    for sec in sections:
        if sec['raw_offset'] <= offset < sec['raw_offset'] + sec['raw_size']:
            rva = offset - sec['raw_offset'] + sec['virt_addr']
            return image_base + rva
    return None

def disasm_hint(data, offset, context=""):
    """Provide basic instruction identification for x86 at given offset."""
    if offset < 0 or offset >= len(data):
        return "OUT_OF_BOUNDS"
    b = data[offset]
    
    # Common x86 instruction patterns
    hints = []
    
    # MOV instructions
    if b == 0xA1:  # MOV EAX, [imm32]
        if offset + 5 <= len(data):
            addr = struct.unpack_from("<I", data, offset + 1)[0]
            hints.append(f"MOV EAX, [0x{addr:08X}]")
    elif b == 0xA3:  # MOV [imm32], EAX
        if offset + 5 <= len(data):
            addr = struct.unpack_from("<I", data, offset + 1)[0]
            hints.append(f"MOV [0x{addr:08X}], EAX")
    elif b == 0x8B:  # MOV r32, r/m32
        if offset + 1 < len(data):
            modrm = data[offset + 1]
            mod = (modrm >> 6) & 3
            reg = (modrm >> 3) & 7
            rm = modrm & 7
            regs = ['EAX','ECX','EDX','EBX','ESP','EBP','ESI','EDI']
            if mod == 0 and rm == 5:  # [disp32]
                if offset + 6 <= len(data):
                    addr = struct.unpack_from("<I", data, offset + 2)[0]
                    hints.append(f"MOV {regs[reg]}, [0x{addr:08X}]")
    elif b == 0x89:  # MOV r/m32, r32
        if offset + 1 < len(data):
            modrm = data[offset + 1]
            mod = (modrm >> 6) & 3
            reg = (modrm >> 3) & 7
            rm = modrm & 7
            regs = ['EAX','ECX','EDX','EBX','ESP','EBP','ESI','EDI']
            if mod == 0 and rm == 5:  # [disp32]
                if offset + 6 <= len(data):
                    addr = struct.unpack_from("<I", data, offset + 2)[0]
                    hints.append(f"MOV [0x{addr:08X}], {regs[reg]}")
    elif b == 0xC7:  # MOV r/m32, imm32
        if offset + 1 < len(data):
            modrm = data[offset + 1]
            mod = (modrm >> 6) & 3
            rm = modrm & 7
            if mod == 0 and rm == 5:  # [disp32]
                if offset + 10 <= len(data):
                    addr = struct.unpack_from("<I", data, offset + 2)[0]
                    imm = struct.unpack_from("<I", data, offset + 6)[0]
                    hints.append(f"MOV DWORD [0x{addr:08X}], 0x{imm:08X}")
    elif b == 0xC6:  # MOV r/m8, imm8
        if offset + 1 < len(data):
            modrm = data[offset + 1]
            mod = (modrm >> 6) & 3
            rm = modrm & 7
            if mod == 0 and rm == 5:  # [disp32]
                if offset + 7 <= len(data):
                    addr = struct.unpack_from("<I", data, offset + 2)[0]
                    imm = data[offset + 6]
                    hints.append(f"MOV BYTE [0x{addr:08X}], 0x{imm:02X}")
    
    # CMP instructions
    elif b == 0x80:  # CMP r/m8, imm8 (when reg field = 7)
        if offset + 1 < len(data):
            modrm = data[offset + 1]
            mod = (modrm >> 6) & 3
            reg = (modrm >> 3) & 7
            rm = modrm & 7
            ops = ['ADD','OR','ADC','SBB','AND','SUB','XOR','CMP']
            if mod == 0 and rm == 5:
                if offset + 7 <= len(data):
                    addr = struct.unpack_from("<I", data, offset + 2)[0]
                    imm = data[offset + 6]
                    hints.append(f"{ops[reg]} BYTE [0x{addr:08X}], 0x{imm:02X}")
    elif b == 0x83:  # CMP r/m32, imm8
        if offset + 1 < len(data):
            modrm = data[offset + 1]
            mod = (modrm >> 6) & 3
            reg = (modrm >> 3) & 7
            rm = modrm & 7
            ops = ['ADD','OR','ADC','SBB','AND','SUB','XOR','CMP']
            if mod == 0 and rm == 5:
                if offset + 7 <= len(data):
                    addr = struct.unpack_from("<I", data, offset + 2)[0]
                    imm = data[offset + 6]
                    hints.append(f"{ops[reg]} DWORD [0x{addr:08X}], 0x{imm:02X}")
    elif b == 0x81:  # CMP r/m32, imm32 (reg=7)
        if offset + 1 < len(data):
            modrm = data[offset + 1]
            mod = (modrm >> 6) & 3
            reg = (modrm >> 3) & 7
            rm = modrm & 7
            ops = ['ADD','OR','ADC','SBB','AND','SUB','XOR','CMP']
            if mod == 0 and rm == 5:
                if offset + 10 <= len(data):
                    addr = struct.unpack_from("<I", data, offset + 2)[0]
                    imm = struct.unpack_from("<I", data, offset + 6)[0]
                    hints.append(f"{ops[reg]} DWORD [0x{addr:08X}], 0x{imm:08X}")
    
    # PUSH/POP with memory
    elif b == 0xFF:
        if offset + 1 < len(data):
            modrm = data[offset + 1]
            mod = (modrm >> 6) & 3
            reg = (modrm >> 3) & 7
            rm = modrm & 7
            if mod == 0 and rm == 5:
                if offset + 6 <= len(data):
                    addr = struct.unpack_from("<I", data, offset + 2)[0]
                    ops = {2: 'CALL', 4: 'JMP', 6: 'PUSH'}
                    if reg in ops:
                        hints.append(f"{ops[reg]} [0x{addr:08X}]")
    
    # CALL rel32
    elif b == 0xE8:
        if offset + 5 <= len(data):
            rel = struct.unpack_from("<i", data, offset + 1)[0]
            hints.append(f"CALL +0x{rel:X} (relative)")
    
    # JMP rel32
    elif b == 0xE9:
        if offset + 5 <= len(data):
            rel = struct.unpack_from("<i", data, offset + 1)[0]
            hints.append(f"JMP +0x{rel:X} (relative)")
    
    # Conditional jumps
    elif b == 0x0F:
        if offset + 1 < len(data):
            b2 = data[offset + 1]
            if 0x80 <= b2 <= 0x8F:
                jcc = ['JO','JNO','JB','JNB','JZ','JNZ','JBE','JA',
                       'JS','JNS','JP','JNP','JL','JGE','JLE','JG']
                if offset + 6 <= len(data):
                    rel = struct.unpack_from("<i", data, offset + 2)[0]
                    hints.append(f"{jcc[b2-0x80]} +0x{rel:X} (relative)")
            elif b2 == 0xB6:  # MOVZX
                if offset + 2 < len(data):
                    modrm = data[offset + 2]
                    mod = (modrm >> 6) & 3
                    reg = (modrm >> 3) & 7
                    rm = modrm & 7
                    regs = ['EAX','ECX','EDX','EBX','ESP','EBP','ESI','EDI']
                    if mod == 0 and rm == 5:
                        if offset + 7 <= len(data):
                            addr = struct.unpack_from("<I", data, offset + 3)[0]
                            hints.append(f"MOVZX {regs[reg]}, BYTE [0x{addr:08X}]")
            elif b2 == 0xBE:  # MOVSX
                if offset + 2 < len(data):
                    modrm = data[offset + 2]
                    mod = (modrm >> 6) & 3
                    reg = (modrm >> 3) & 7
                    rm = modrm & 7
                    regs = ['EAX','ECX','EDX','EBX','ESP','EBP','ESI','EDI']
                    if mod == 0 and rm == 5:
                        if offset + 7 <= len(data):
                            addr = struct.unpack_from("<I", data, offset + 3)[0]
                            hints.append(f"MOVSX {regs[reg]}, BYTE [0x{addr:08X}]")
    
    # 0xA0, 0xA2 - MOV AL
    elif b == 0xA0:
        if offset + 5 <= len(data):
            addr = struct.unpack_from("<I", data, offset + 1)[0]
            hints.append(f"MOV AL, [0x{addr:08X}]")
    elif b == 0xA2:
        if offset + 5 <= len(data):
            addr = struct.unpack_from("<I", data, offset + 1)[0]
            hints.append(f"MOV [0x{addr:08X}], AL")
    
    # FLD/FST with memory
    elif b == 0x38:  # CMP r/m8, r8
        if offset + 1 < len(data):
            modrm = data[offset + 1]
            mod = (modrm >> 6) & 3
            reg = (modrm >> 3) & 7
            rm = modrm & 7
            regs8 = ['AL','CL','DL','BL','AH','CH','DH','BH']
            if mod == 0 and rm == 5:
                if offset + 6 <= len(data):
                    addr = struct.unpack_from("<I", data, offset + 2)[0]
                    hints.append(f"CMP BYTE [0x{addr:08X}], {regs8[reg]}")
    elif b == 0x3A:  # CMP r8, r/m8
        if offset + 1 < len(data):
            modrm = data[offset + 1]
            mod = (modrm >> 6) & 3
            reg = (modrm >> 3) & 7
            rm = modrm & 7
            regs8 = ['AL','CL','DL','BL','AH','CH','DH','BH']
            if mod == 0 and rm == 5:
                if offset + 6 <= len(data):
                    addr = struct.unpack_from("<I", data, offset + 2)[0]
                    hints.append(f"CMP {regs8[reg]}, BYTE [0x{addr:08X}]")
    elif b == 0x3B:  # CMP r32, r/m32
        if offset + 1 < len(data):
            modrm = data[offset + 1]
            mod = (modrm >> 6) & 3
            reg = (modrm >> 3) & 7
            rm = modrm & 7
            regs = ['EAX','ECX','EDX','EBX','ESP','EBP','ESI','EDI']
            if mod == 0 and rm == 5:
                if offset + 6 <= len(data):
                    addr = struct.unpack_from("<I", data, offset + 2)[0]
                    hints.append(f"CMP {regs[reg]}, DWORD [0x{addr:08X}]")
    elif b == 0x3D:  # CMP EAX, imm32
        pass  # No memory reference
    
    if not hints:
        return f"[opcode 0x{b:02X}]"
    return " | ".join(hints)


def search_address_references(data, target_va, image_base, sections, label):
    """Search for all references to a virtual address in the binary."""
    # The address in little-endian
    needle = struct.pack("<I", target_va)
    results = []
    
    start = 0
    while True:
        pos = data.find(needle, start)
        if pos == -1:
            break
        
        va = file_offset_to_va(pos, image_base, sections)
        
        # Show context: look back to find the instruction start
        # Most x86 instructions referencing [imm32] are 5-7 bytes
        # The address is typically at offset +1, +2, or +3 from instruction start
        
        context_before = max(0, pos - 30)
        context_after = min(len(data), pos + 4 + 30)
        
        # Try to identify the instruction by checking bytes before the address
        instr_hints = []
        for back in range(1, 8):
            check_pos = pos - back
            if check_pos < 0:
                continue
            hint = disasm_hint(data, check_pos)
            if target_va_in_hint(hint, target_va):
                instr_hints.append((back, check_pos, hint))
        
        results.append({
            'file_offset': pos,
            'va': va,
            'context_bytes_before': data[context_before:pos],
            'context_bytes_after': data[pos+4:context_after],
            'instruction_hints': instr_hints,
            'raw_context': data[context_before:context_after],
            'context_start_offset': context_before,
        })
        
        start = pos + 1
    
    return results


def target_va_in_hint(hint, target_va):
    """Check if the disassembly hint references our target address."""
    return f"0x{target_va:08X}" in hint.upper() or f"0x{target_va:X}" in hint.upper()


def hexdump(data, start_offset=0, highlight_offset=None, highlight_len=4):
    """Pretty hex dump with optional highlighting."""
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_parts = []
        for j, b in enumerate(chunk):
            abs_off = start_offset + i + j
            if highlight_offset is not None and highlight_offset <= abs_off < highlight_offset + highlight_len:
                hex_parts.append(f"[{b:02X}]")
            else:
                hex_parts.append(f" {b:02X} ")
        hex_str = "".join(hex_parts)
        ascii_str = "".join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f"  {start_offset+i:08X}: {hex_str}  |{ascii_str}|")
    return "\n".join(lines)


def search_strings(data, image_base, sections):
    """Search for relevant strings in the binary."""
    results = []
    
    for search_term in SEARCH_STRINGS:
        # Search both ASCII and case variations
        pattern = search_term.encode('ascii')
        pattern_upper = search_term.upper().encode('ascii')
        pattern_title = search_term.title().encode('ascii')
        
        for pat in set([pattern, pattern_upper, pattern_title]):
            start = 0
            while True:
                # Case insensitive search
                pos = data.lower().find(pat.lower(), start)
                if pos == -1:
                    break
                
                # Extract the full string around this position
                str_start = pos
                while str_start > 0 and 32 <= data[str_start-1] < 127:
                    str_start -= 1
                str_end = pos
                while str_end < len(data) and 32 <= data[str_end] < 127:
                    str_end += 1
                
                full_string = data[str_start:str_end].decode('ascii', errors='replace')
                if len(full_string) >= 3:  # Minimum meaningful string
                    va = file_offset_to_va(pos, image_base, sections)
                    results.append({
                        'search_term': search_term,
                        'file_offset': str_start,
                        'va': file_offset_to_va(str_start, image_base, sections),
                        'string': full_string,
                        'length': len(full_string),
                    })
                
                start = pos + len(pat)
    
    # Deduplicate by file offset
    seen = set()
    unique = []
    for r in results:
        if r['file_offset'] not in seen:
            seen.add(r['file_offset'])
            unique.append(r)
    
    unique.sort(key=lambda x: x['file_offset'])
    return unique


def find_command_dispatch(data, image_base, sections):
    """Look for command byte 0x21 dispatch logic - comparisons with 0x21."""
    results = []
    
    # Pattern: CMP reg, 0x21 (various encodings)
    # CMP AL, 0x21 = 3C 21
    # CMP r/m8, 0x21 = 80 F? 21 (where ? encodes the register)
    # CMP r/m32, 0x21 = 83 F? 21 
    
    patterns = [
        (b'\x3C\x21', "CMP AL, 0x21"),
        (b'\x3C\x20', "CMP AL, 0x20"),
        (b'\x3C\x22', "CMP AL, 0x22"),
    ]
    
    # Also look for CMP with memory operand containing 0x21
    for i in range(len(data) - 2):
        b0 = data[i]
        if b0 == 0x3C and data[i+1] == 0x21:
            va = file_offset_to_va(i, image_base, sections)
            ctx_start = max(0, i - 20)
            ctx_end = min(len(data), i + 20)
            results.append({
                'file_offset': i,
                'va': va,
                'instruction': "CMP AL, 0x21",
                'context': data[ctx_start:ctx_end],
                'context_start': ctx_start,
            })
        elif b0 == 0x80 and i + 2 < len(data):
            modrm = data[i+1]
            reg = (modrm >> 3) & 7
            if reg == 7 and data[i+2] == 0x21:  # CMP with imm8 = 0x21
                va = file_offset_to_va(i, image_base, sections)
                ctx_start = max(0, i - 20)
                ctx_end = min(len(data), i + 20)
                results.append({
                    'file_offset': i,
                    'va': va,
                    'instruction': f"CMP BYTE [...], 0x21 (ModRM=0x{modrm:02X})",
                    'context': data[ctx_start:ctx_end],
                    'context_start': ctx_start,
                })
        elif b0 == 0x83 and i + 2 < len(data):
            modrm = data[i+1]
            reg = (modrm >> 3) & 7
            if reg == 7 and data[i+2] == 0x21:  # CMP DWORD with imm8 = 0x21
                va = file_offset_to_va(i, image_base, sections)
                ctx_start = max(0, i - 20)
                ctx_end = min(len(data), i + 20)
                results.append({
                    'file_offset': i,
                    'va': va,
                    'instruction': f"CMP DWORD [...], 0x21 (ModRM=0x{modrm:02X})",
                    'context': data[ctx_start:ctx_end],
                    'context_start': ctx_start,
                })
    
    return results


def find_game_data_range_checks(data, image_base, sections):
    """Look for range checks 0x20-0x7E (game data command range)."""
    results = []
    
    # CMP AL, 0x20 / CMP AL, 0x7E patterns
    for i in range(len(data) - 2):
        b0 = data[i]
        # JB/JA after CMP typically indicate range checks
        if b0 == 0x3C:
            val = data[i+1]
            if val in (0x20, 0x7E, 0x7F):
                va = file_offset_to_va(i, image_base, sections)
                ctx_start = max(0, i - 10)
                ctx_end = min(len(data), i + 15)
                results.append({
                    'file_offset': i,
                    'va': va,
                    'instruction': f"CMP AL, 0x{val:02X}",
                    'context': data[ctx_start:ctx_end],
                    'context_start': ctx_start,
                })
    return results


def analyze_surrounding_code(data, offset, image_base, sections, window=100):
    """Analyze code around a reference to understand the flow."""
    start = max(0, offset - window)
    end = min(len(data), offset + window)
    
    # Look for known addresses in this region
    found_refs = []
    for addr, label in ADDRESSES.items():
        needle = struct.pack("<I", addr)
        pos = start
        while pos < end:
            found = data.find(needle, pos, end)
            if found == -1:
                break
            found_refs.append((found, addr, label))
            pos = found + 1
    
    found_refs.sort()
    return found_refs


def main():
    print("=" * 80)
    print("MRA.EXE Binary Analysis - Mystic Realms of Alhanzar Client")
    print("=" * 80)
    
    data = read_exe(EXE_PATH)
    print(f"\nFile size: {len(data)} bytes (0x{len(data):X})")
    
    # Parse PE headers
    print("\n" + "=" * 80)
    print("PE HEADER ANALYSIS")
    print("=" * 80)
    image_base, sections = parse_pe_headers(data)
    
    # Verify image base matches expected
    if image_base != IMAGE_BASE:
        print(f"\n*** WARNING: Image base 0x{image_base:X} != expected 0x{IMAGE_BASE:X} ***")
        print(f"    Using actual image base: 0x{image_base:X}")
    
    # =========================================================================
    # SECTION 1: Search for references to key addresses
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 1: CROSS-REFERENCES TO KEY MEMORY ADDRESSES")
    print("=" * 80)
    
    for target_va, label in ADDRESSES.items():
        print(f"\n{'-' * 70}")
        print(f"Target: 0x{target_va:08X} - {label}")
        print(f"Byte pattern (LE): {' '.join(f'{b:02X}' for b in struct.pack('<I', target_va))}")
        print(f"{'-' * 70}")
        
        refs = search_address_references(data, target_va, image_base, sections, label)
        
        if not refs:
            print("  No references found!")
            continue
        
        print(f"  Found {len(refs)} reference(s):\n")
        
        for idx, ref in enumerate(refs):
            va_str = f"0x{ref['va']:08X}" if ref['va'] else "UNKNOWN_VA"
            print(f"  [{idx+1}] File offset: 0x{ref['file_offset']:08X} | VA: {va_str}")
            
            # Show instruction hints
            if ref['instruction_hints']:
                best = ref['instruction_hints'][0]
                back, check_pos, hint = best
                instr_va = file_offset_to_va(check_pos, image_base, sections)
                instr_va_str = f"0x{instr_va:08X}" if instr_va else "?"
                print(f"       Instruction at VA {instr_va_str} (offset 0x{check_pos:08X}):")
                print(f"       >>> {hint}")
            
            # Show hex context
            print(f"       Context (60 bytes around reference):")
            print(hexdump(ref['raw_context'], ref['context_start_offset'],
                         highlight_offset=ref['file_offset'], highlight_len=4))
            
            # Show other address references nearby
            nearby = analyze_surrounding_code(data, ref['file_offset'], image_base, sections, window=60)
            if nearby:
                print(f"       Nearby address references:")
                for noff, naddr, nlabel in nearby:
                    if noff != ref['file_offset']:
                        nva = file_offset_to_va(noff, image_base, sections)
                        print(f"         0x{noff:08X} (VA 0x{nva:08X}): -> 0x{naddr:08X} ({nlabel})")
            print()
    
    # =========================================================================
    # SECTION 2: Command byte 0x21 dispatch
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 2: COMMAND BYTE 0x21 DISPATCH LOCATIONS")
    print("=" * 80)
    
    cmd_refs = find_command_dispatch(data, image_base, sections)
    print(f"\nFound {len(cmd_refs)} comparison(s) with 0x21:\n")
    
    for idx, ref in enumerate(cmd_refs):
        va_str = f"0x{ref['va']:08X}" if ref['va'] else "UNKNOWN"
        print(f"  [{idx+1}] File: 0x{ref['file_offset']:08X} | VA: {va_str} | {ref['instruction']}")
        print(hexdump(ref['context'], ref['context_start']))
        
        # Check for nearby key address references
        nearby = analyze_surrounding_code(data, ref['file_offset'], image_base, sections, window=100)
        if nearby:
            print(f"       Nearby key addresses:")
            for noff, naddr, nlabel in nearby:
                nva = file_offset_to_va(noff, image_base, sections)
                print(f"         0x{noff:08X} (VA 0x{nva:08X}): -> 0x{naddr:08X} ({nlabel})")
        print()
    
    # =========================================================================
    # SECTION 3: Game data range checks (0x20-0x7E)
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 3: GAME DATA RANGE CHECKS (CMP AL, 0x20/0x7E/0x7F)")
    print("=" * 80)
    
    range_refs = find_game_data_range_checks(data, image_base, sections)
    print(f"\nFound {len(range_refs)} range check(s):\n")
    
    for idx, ref in enumerate(range_refs):
        va_str = f"0x{ref['va']:08X}" if ref['va'] else "UNKNOWN"
        print(f"  [{idx+1}] File: 0x{ref['file_offset']:08X} | VA: {va_str} | {ref['instruction']}")
        print(hexdump(ref['context'], ref['context_start']))
        
        nearby = analyze_surrounding_code(data, ref['file_offset'], image_base, sections, window=80)
        if nearby:
            print(f"       Nearby key addresses:")
            for noff, naddr, nlabel in nearby:
                nva = file_offset_to_va(noff, image_base, sections)
                print(f"         0x{noff:08X} (VA 0x{nva:08X}): -> 0x{naddr:08X} ({nlabel})")
        print()
    
    # =========================================================================
    # SECTION 4: String search
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 4: RELEVANT STRING SEARCH")
    print("=" * 80)
    
    strings = search_strings(data, image_base, sections)
    print(f"\nFound {len(strings)} relevant string(s):\n")
    
    for s in strings:
        va_str = f"0x{s['va']:08X}" if s['va'] else "UNKNOWN"
        # Truncate very long strings
        display_str = s['string'][:120]
        if len(s['string']) > 120:
            display_str += "..."
        print(f"  File: 0x{s['file_offset']:08X} | VA: {va_str} | [{s['search_term']}] \"{display_str}\"")
    
    # =========================================================================
    # SECTION 5: Deep analysis - trace game data flow from 0x461C80
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 5: DEEP FLOW ANALYSIS - GAME DATA BUFFER 0x461C80")
    print("=" * 80)
    
    # Find all writes to 0x461C80
    write_needle = struct.pack("<I", 0x461C80)
    pos = 0
    write_sites = []
    while True:
        found = data.find(write_needle, pos)
        if found == -1:
            break
        
        # Check if this is a write instruction (MOV [addr], ...)
        for back in range(1, 8):
            check = found - back
            if check < 0:
                continue
            b = data[check]
            # A3 = MOV [imm32], EAX
            # A2 = MOV [imm32], AL
            # C6 05 = MOV BYTE [imm32], imm8
            # C7 05 = MOV DWORD [imm32], imm32
            # 88/89 with ModRM 05 = MOV [imm32], reg
            # 0F B6/BE with ModRM 05 = MOVZX/MOVSX from [imm32]
            if back == 1 and b in (0xA2, 0xA3):
                va = file_offset_to_va(check, image_base, sections)
                hint = disasm_hint(data, check)
                write_sites.append((check, va, hint, "direct"))
                break
            elif back == 2 and b in (0xC6, 0xC7, 0x88, 0x89, 0x8A, 0x8B):
                if data[check+1] == 0x05:  # ModRM for [disp32]
                    va = file_offset_to_va(check, image_base, sections)
                    hint = disasm_hint(data, check)
                    write_sites.append((check, va, hint, "modrm"))
                    break
            elif back == 2 and b in (0x80, 0x81, 0x83):
                modrm = data[check+1]
                if (modrm & 0xC7) == 0x05:  # mod=00, rm=101
                    va = file_offset_to_va(check, image_base, sections)
                    hint = disasm_hint(data, check)
                    write_sites.append((check, va, hint, "alu"))
                    break
            elif back == 3 and b == 0x0F:
                b2 = data[check+1]
                if b2 in (0xB6, 0xBE) and data[check+2] == 0x05:
                    va = file_offset_to_va(check, image_base, sections)
                    hint = disasm_hint(data, check)
                    write_sites.append((check, va, hint, "movzx"))
                    break
        
        pos = found + 1
    
    print(f"\nIdentified instruction sites referencing 0x461C80:")
    for off, va, hint, itype in write_sites:
        va_str = f"0x{va:08X}" if va else "?"
        print(f"  Offset 0x{off:08X} | VA {va_str} | {hint} [{itype}]")
    
    # Same for 0x461C2D
    print(f"\n--- References to state byte 0x461C2D ---")
    write_needle2 = struct.pack("<I", 0x461C2D)
    pos = 0
    state_sites = []
    while True:
        found = data.find(write_needle2, pos)
        if found == -1:
            break
        for back in range(1, 8):
            check = found - back
            if check < 0:
                continue
            b = data[check]
            if back == 1 and b in (0xA0, 0xA1, 0xA2, 0xA3):
                va = file_offset_to_va(check, image_base, sections)
                hint = disasm_hint(data, check)
                state_sites.append((check, va, hint))
                break
            elif back == 2 and b in (0xC6, 0xC7, 0x88, 0x89, 0x8A, 0x8B, 0x80, 0x81, 0x83, 0x38, 0x3A, 0x3B):
                if data[check+1] in (0x05, 0x0D, 0x15, 0x1D, 0x25, 0x2D, 0x35, 0x3D):
                    va = file_offset_to_va(check, image_base, sections)
                    hint = disasm_hint(data, check)
                    state_sites.append((check, va, hint))
                    break
            elif back == 3 and b == 0x0F:
                b2 = data[check+1]
                if b2 in (0xB6, 0xBE):
                    va = file_offset_to_va(check, image_base, sections)
                    hint = disasm_hint(data, check)
                    state_sites.append((check, va, hint))
                    break
        pos = found + 1
    
    for off, va, hint in state_sites:
        va_str = f"0x{va:08X}" if va else "?"
        print(f"  Offset 0x{off:08X} | VA {va_str} | {hint}")
    
    # =========================================================================
    # SECTION 6: Look for the copy from 0x461C80 to 0x461C2D
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 6: BUFFER-TO-STATE COPY (0x461C80 -> 0x461C2D)")
    print("=" * 80)
    
    # Look for code regions that reference both addresses close together
    needle_80 = struct.pack("<I", 0x461C80)
    needle_2D = struct.pack("<I", 0x461C2D)
    
    refs_80 = set()
    pos = 0
    while True:
        found = data.find(needle_80, pos)
        if found == -1:
            break
        refs_80.add(found)
        pos = found + 1
    
    refs_2D = set()
    pos = 0
    while True:
        found = data.find(needle_2D, pos)
        if found == -1:
            break
        refs_2D.add(found)
        pos = found + 1
    
    print(f"\nLooking for code regions with both 0x461C80 and 0x461C2D within 100 bytes...")
    pairs = []
    for r80 in refs_80:
        for r2D in refs_2D:
            if abs(r80 - r2D) <= 100:
                pairs.append((min(r80, r2D), max(r80, r2D), r80, r2D))
    
    pairs.sort()
    seen_ranges = set()
    for pmin, pmax, r80, r2D in pairs:
        # Dedup overlapping ranges
        key = (pmin // 50, pmax // 50)
        if key in seen_ranges:
            continue
        seen_ranges.add(key)
        
        start = max(0, pmin - 20)
        end = min(len(data), pmax + 20)
        va_start = file_offset_to_va(start, image_base, sections)
        va_str = f"0x{va_start:08X}" if va_start else "?"
        
        print(f"\n  Region at file offset 0x{start:08X} (VA ~{va_str}):")
        print(f"    0x461C80 ref at offset 0x{r80:08X}, 0x461C2D ref at offset 0x{r2D:08X}")
        print(hexdump(data[start:end], start))
        
        # Try to identify instructions in this region
        print("    Instruction scan:")
        scan_start = max(0, pmin - 10)
        scan_end = min(len(data), pmax + 10)
        i = scan_start
        while i < scan_end:
            hint = disasm_hint(data, i)
            if hint != f"[opcode 0x{data[i]:02X}]" or i in (r80-1, r80-2, r2D-1, r2D-2):
                iva = file_offset_to_va(i, image_base, sections)
                iva_str = f"0x{iva:08X}" if iva else "?"
                if "0x0046" in hint.upper():  # Only show hints with our target range
                    print(f"      {iva_str}: {hint}")
            i += 1

    # =========================================================================
    # SECTION 7: SGN payload pointer 0x44E808 analysis
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 7: SGN PAYLOAD BUFFER POINTER 0x44E808 ANALYSIS")
    print("=" * 80)
    
    needle_sgn = struct.pack("<I", 0x44E808)
    pos = 0
    sgn_refs = []
    while True:
        found = data.find(needle_sgn, pos)
        if found == -1:
            break
        va = file_offset_to_va(found, image_base, sections)
        
        # Show wider context for SGN refs
        ctx_start = max(0, found - 40)
        ctx_end = min(len(data), found + 44)
        
        # Identify instruction
        instr_hint = None
        for back in range(1, 8):
            check = found - back
            if check < 0:
                continue
            hint = disasm_hint(data, check)
            if "0x44E808" in hint.upper() or "0x0044E808" in hint.upper():
                instr_va = file_offset_to_va(check, image_base, sections)
                instr_hint = (check, instr_va, hint)
                break
        
        sgn_refs.append({
            'offset': found,
            'va': va,
            'instruction': instr_hint,
            'context': data[ctx_start:ctx_end],
            'context_start': ctx_start,
        })
        
        pos = found + 1
    
    print(f"\nFound {len(sgn_refs)} reference(s) to 0x44E808:\n")
    for idx, ref in enumerate(sgn_refs):
        va_str = f"0x{ref['va']:08X}" if ref['va'] else "?"
        print(f"  [{idx+1}] File: 0x{ref['offset']:08X} | VA: {va_str}")
        if ref['instruction']:
            off, iva, hint = ref['instruction']
            iva_str = f"0x{iva:08X}" if iva else "?"
            print(f"       Instruction at {iva_str}: {hint}")
        print(hexdump(ref['context'], ref['context_start'],
                      highlight_offset=ref['offset'], highlight_len=4))
        
        # Check for nearby key address references
        nearby = analyze_surrounding_code(data, ref['offset'], image_base, sections, window=80)
        if nearby:
            print(f"       Nearby key addresses:")
            for noff, naddr, nlabel in nearby:
                nva = file_offset_to_va(noff, image_base, sections)
                if noff != ref['offset']:
                    print(f"         0x{noff:08X} (VA 0x{nva:08X}): -> 0x{naddr:08X} ({nlabel})")
        print()
    
    # =========================================================================
    # SECTION 8: Sub-command byte 0x460F43
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 8: SUB-COMMAND BYTE 0x460F43 ANALYSIS")
    print("=" * 80)
    
    needle_sub = struct.pack("<I", 0x460F43)
    pos = 0
    sub_refs = []
    while True:
        found = data.find(needle_sub, pos)
        if found == -1:
            break
        va = file_offset_to_va(found, image_base, sections)
        ctx_start = max(0, found - 30)
        ctx_end = min(len(data), found + 34)
        
        instr_hint = None
        for back in range(1, 8):
            check = found - back
            if check < 0:
                continue
            hint = disasm_hint(data, check)
            if "0x460F43" in hint.upper() or "0x00460F43" in hint.upper():
                instr_va = file_offset_to_va(check, image_base, sections)
                instr_hint = (check, instr_va, hint)
                break
        
        sub_refs.append({
            'offset': found,
            'va': va,
            'instruction': instr_hint,
            'context': data[ctx_start:ctx_end],
            'context_start': ctx_start,
        })
        pos = found + 1
    
    print(f"\nFound {len(sub_refs)} reference(s) to 0x460F43:\n")
    for idx, ref in enumerate(sub_refs):
        va_str = f"0x{ref['va']:08X}" if ref['va'] else "?"
        print(f"  [{idx+1}] File: 0x{ref['offset']:08X} | VA: {va_str}")
        if ref['instruction']:
            off, iva, hint = ref['instruction']
            iva_str = f"0x{iva:08X}" if iva else "?"
            print(f"       Instruction at {iva_str}: {hint}")
        print(hexdump(ref['context'], ref['context_start'],
                      highlight_offset=ref['offset'], highlight_len=4))
        
        nearby = analyze_surrounding_code(data, ref['offset'], image_base, sections, window=80)
        if nearby:
            print(f"       Nearby key addresses:")
            for noff, naddr, nlabel in nearby:
                nva = file_offset_to_va(noff, image_base, sections)
                if noff != ref['offset']:
                    print(f"         0x{noff:08X} (VA 0x{nva:08X}): -> 0x{naddr:08X} ({nlabel})")
        print()

    # =========================================================================
    # SECTION 9: Summary
    # =========================================================================
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"""
Key findings:
- Total file size: {len(data)} bytes
- Image base: 0x{image_base:X}
- References to 0x461C80 (game buffer): {len(list(refs_80))} raw occurrences
- References to 0x461C2D (state byte): {len(list(refs_2D))} raw occurrences  
- References to 0x44E808 (SGN payload): {len(sgn_refs)} occurrences
- References to 0x460F43 (sub-command): {len(sub_refs)} occurrences
- Command 0x21 comparisons: {len(cmd_refs)} found
- Relevant strings: {len(strings)} found
- Nearby-pair regions (buffer+state): {len(pairs)} found
""")


if __name__ == "__main__":
    main()
