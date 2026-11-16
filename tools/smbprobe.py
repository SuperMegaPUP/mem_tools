#!/usr/bin/env python3
"""Опрос SMBus-устройств (только чтение): поиск VRM/EEPROM/TSOD на шине 0."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from rspd.transport import SmbusBus, NackError

bus = SmbusBus(0)
for addr in range(0x20, 0x70):
    try:
        b = bus.read_byte(addr)
    except Exception:
        continue
    if b is None:
        continue
    d1 = bus.rdwr(addr, b"\x00", 16)
    print(f"0x{addr:02x}: recv={b:02x}  rd[0..16]={d1.hex(' ') if d1 else None}")
bus.close()
