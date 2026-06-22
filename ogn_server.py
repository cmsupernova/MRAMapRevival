"""
OGN Protocol Emulator v10 - MRA Launch
Port 1111

Binary patches in OGN.EXE:
  - Code cave at 0x77B9: skips splash redraw after first call
  - Code cave sets [0x441528]=4, returns if [0x441528]!=0
  - State=2 forced at 0x11BA
  - Version check bypassed at 0x8B37

Protocol:
  payload[8] is the command byte stored at [0x441528]
  The protocol handler (0xB096) dispatches based on this byte.
  
  Command values:
    0x04 = version OK (passes version polling loop)
    0x0F = set state 'e' 
    0x0E = set state 2
    0x08 = set state 'x' (via [0x441528] check at 0xA144)
    0x1F = set state 'x' (launch MRA) via protocol handler
           payload[9] = server number ('0'-'9')
    0x26 = timer/window setup

  Server flow:
    1. Send handshake: payload[8]=0x04 (version OK)
    2. Client enters state 2, shows login prompt
    3. Client sends credentials
    4. Respond: payload[8]=0x1F, payload[9]=0x30 (launch MRA, server 0)
    5. Client sets state 'x' -> CreateProcessA("MRA.EXE")
"""

import socket
import sys
import time
import threading
from datetime import datetime

HOST = '0.0.0.0'
PORT = 1111
LOG_FILE = 'ogn_protocol_log.txt'

def hex_dump(data, prefix='  '):
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_part = ' '.join(f'{b:02X}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f'{prefix}{i:04X}: {hex_part:<48} {ascii_part}')
    return '\n'.join(lines)

def log(msg, logfile=None):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    line = f'[{timestamp}] {msg}'
    print(line)
    if logfile:
        logfile.write(line + '\n')
        logfile.flush()

def build_sgn_message(type_byte, payload):
    """Build SGN protocol message: 'SGN' + type + length(base94) + payload"""
    length = len(payload)
    low = (length % 94) + 32
    high = (length // 94) + 32
    header = bytes([0x53, 0x47, 0x4E, type_byte, low, high])
    return header + payload

def build_launch_response():
    """Build the MRA launch command: payload[8]=0x1F (cmd), payload[9]=0x30 (server '0')"""
    payload = bytearray(32)
    payload[8] = 0x1F   # Command 0x1F = launch MRA.EXE
    payload[9] = 0x30   # Server number '0' (ASCII digit)
    return build_sgn_message(0xAF, bytes(payload))

def build_version_ok():
    """Build version OK response: payload[8]=0x04"""
    payload = bytearray(32)
    payload[8] = 0x04   # Version OK
    return build_sgn_message(0xAF, bytes(payload))

def handle_client(conn, addr, logfile, conn_num):
    log(f'*** CONNECTION #{conn_num} from {addr[0]}:{addr[1]} ***', logfile)
    conn.settimeout(120.0)
    
    time.sleep(0.3)
    
    # Phase 1: Send initial handshake with payload[8]=0x04 (version OK)
    # This sets [0x441528]=4 which exits the polling loop in 0x77B9
    msg = build_version_ok()
    log(f'Sent handshake ({len(msg)} bytes) payload[8]=0x04 (version OK)', logfile)
    conn.send(msg)
    
    # Now listen for client messages
    # Packet 1 from client: version/info check -> respond with version OK
    # Packet 2+: login or other -> respond with launch MRA command
    total_recv = 0
    pkt = 0
    try:
        while True:
            try:
                data = conn.recv(4096)
                if not data:
                    log(f'  Conn #{conn_num}: client disconnected', logfile)
                    break
                pkt += 1
                total_recv += len(data)
                log(f'  Conn #{conn_num} RECV #{pkt} ({len(data)} bytes):', logfile)
                dump = hex_dump(data)
                print(dump)
                if logfile:
                    logfile.write(dump + '\n')
                    logfile.flush()
                
                # Parse any SGN messages from client
                idx = 0
                while idx < len(data) - 5:
                    sgn_pos = data.find(b'SGN', idx)
                    if sgn_pos == -1 or sgn_pos + 6 > len(data):
                        break
                    ctype = data[sgn_pos+3]
                    clow = data[sgn_pos+4]
                    chigh = data[sgn_pos+5]
                    clen = max(0, (clow - 32) + (chigh - 32) * 94)
                    log(f'  Client SGN: type=0x{ctype:02X}, payload_len={clen}', logfile)
                    if sgn_pos + 6 + clen <= len(data):
                        client_payload = data[sgn_pos+6:sgn_pos+6+clen]
                        if clen > 0:
                            log(f'  Payload:', logfile)
                            pdump = hex_dump(client_payload, '    ')
                            print(pdump)
                            if logfile:
                                logfile.write(pdump + '\n')
                                logfile.flush()
                    idx = sgn_pos + 6 + clen
                
                # Decide response based on packet number
                try:
                    if pkt == 1:
                        # First client packet: reinforce version OK
                        resp = build_version_ok()
                        conn.send(resp)
                        log(f'  Sent response #{pkt}: version OK (payload[8]=0x04)', logfile)
                    else:
                        # Packet 2+: send MRA launch command
                        resp = build_launch_response()
                        conn.send(resp)
                        log(f'  Sent response #{pkt}: LAUNCH MRA (payload[8]=0x1F, server=0)', logfile)
                except Exception as e:
                    log(f'  Send error: {e}', logfile)
                    
            except socket.timeout:
                log(f'  Conn #{conn_num}: timeout ({total_recv} bytes total)', logfile)
                break
            except (ConnectionResetError, ConnectionAbortedError) as e:
                log(f'  Conn #{conn_num}: {e}', logfile)
                break
    except Exception as e:
        log(f'  Conn #{conn_num} error: {e}', logfile)
    finally:
        conn.close()
        log(f'  Conn #{conn_num} closed ({total_recv} bytes, {pkt} pkts)', logfile)

def main():
    print('=' * 60)
    print('  OGN Server Emulator v10 - MRA Launch')
    print(f'  Port: {PORT}')
    print('=' * 60)
    print()
    print('Handshake: payload[8]=0x04 (version OK)')
    print('Login response: payload[8]=0x1F (launch MRA), payload[9]=0x30 (server 0)')
    print()
    
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
    except OSError as e:
        print(f'ERROR: {e}')
        sys.exit(1)
    
    server.listen(5)
    print(f'Listening on {HOST}:{PORT}')
    print()
    print('Launch OGN.EXE -> "Connect to OGN"')
    print('Press Ctrl+C to stop')
    print()
    
    logfile = open(LOG_FILE, 'a')
    log('=== Session v10 started ===', logfile)
    
    conn_count = 0
    try:
        while True:
            conn, addr = server.accept()
            conn_count += 1
            t = threading.Thread(
                target=handle_client, 
                args=(conn, addr, logfile, conn_count)
            )
            t.daemon = True
            t.start()
    except KeyboardInterrupt:
        print('\nShutting down...')
    finally:
        server.close()
        logfile.close()

if __name__ == '__main__':
    main()
