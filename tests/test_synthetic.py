#!/usr/bin/env python3
"""Синтетические тесты декодеров (без железа):
  1) DDR3L с XMP — собираем SPD с заведомыми значениями и проверяем round-trip.
  2) DDR4 — собираем SPD с CRC и проверяем объём/частоту/тайминги/напряжение.
  3) Реальный дамп myspd.bin — базовые инварианты.
Запуск: python3 tests/test_synthetic.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rspd import ddr3, ddr4  # noqa: E402
from rspd.common import crc16_ccitt  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"{'OK ' if ok else 'FAIL'} {name}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(name)


def crc_byte_parity(count):
    """JEP106 count byte with odd parity."""
    b = count
    p = bin(b).count("1") & 1
    return b | (0 if p else 0x80) if count else 0x80


# ---------------------------------------------------------------- DDR3L+XMP
b = bytearray(256)
b[0] = 0x93            # 512B EEPROM, CRC cover 0-116
b[1] = 0x13            # SPD rev 1.3
b[2] = 0x0B            # DDR3
b[3] = 0x02            # UDIMM
b[4] = 0x14            # density code 4 (4Gb), banks enc 1 -> 16 banks
b[5] = 0x21            # rows ((0x21>>3)&31)+12 = 16, cols (1)+9 = 10
b[6] = 0x02            # 1.35V tolerant (DDR3L)
b[7] = 0x09            # device x8, 2 ranks
b[8] = 0x03            # 64-bit bus
b[9] = 0x52            # FTB 5/2 = 2.5ps
b[10], b[11] = 1, 8    # MTB 0.125ns
b[12] = 10             # tCK LSB: 10*0.125 = 1.25ns -> DDR3-1600
b[14] = 0x80           # CAS mask bit7 -> CL11
b[16] = 110            # tAA 13.75ns
b[17] = 120            # tWR 15ns
b[18] = 110            # tRCD 13.75
b[19] = 48             # tRRD 6ns
b[20] = 110            # tRP 13.75
b[21] = 0x10           # tRAS hi=0, tRC hi=1
b[22] = 230            # tRAS 28.75ns
b[23] = 84             # tRC: 256+84=340 -> 42.5ns
b[24], b[25] = 0xC0, 0x08   # tRFC 2240*0.125=280ns
b[26] = 60             # tWTR 7.5
b[27] = 60             # tRTP 7.5
b[28], b[29] = 1, 0x68 # tFAW 360*0.125=45ns
b[30] = 0x02           # RZQ/7
b[33] = 0x01           # monolithic
b[41] = 0x08           # MAC unlimited
b[60] = 0x0F           # height 30mm
b[61] = 0x22
b[62] = 0x00           # ref A
# mfg
b[117] = crc_byte_parity(0)
b[118] = 0x2C          # Micron
b[119] = ord("A")
b[120], b[121] = 0x24, 0x10   # 2024-W10
b[122:126] = bytes([0xDE, 0xAD, 0xBE, 0xEF])
part = b"SYNTH-DDR3L-1600".ljust(18, b"\x20")
b[128:146] = part
b[146], b[147] = 0x01, 0x00
b[148] = crc_byte_parity(0)
b[149] = 0x2C
# CRC
crc = crc16_ccitt(bytes(b[:117]))
b[126], b[127] = crc & 0xFF, crc >> 8
# XMP: DDR3-1866 CL13-13-13-31 @1.35V, MTB = 1071/1000 ns
b[176], b[177] = 0x0C, 0x4A
b[178] = 0x01          # P1 enabled
b[179] = 0x13          # XMP 1.3
b[180], b[181] = 1, 14          # MTB = 1/14 ns = 0.0714
b[185] = (1 << 5) | (3 << 1) | 1     # 1.35V
b[186] = 15            # tCK = 15 mtb = 1.0714ns -> DDR3-1866
b[187] = 195           # tAA = 195 mtb = 13.93ns -> CL13
b[188] = 0             # CL 4-11: нет
b[189] = 1 << (13 - 12)  # CL13 во втором байте битмапа
b[190] = 195           # tCWL
b[191] = 195           # tRP
b[192] = 195           # tRCD
b[193] = 210           # tWR 15ns
b[194] = 0x21          # tRAS hi=1, tRC hi=2
b[195] = 0xD1          # tRAS = 0x1D1 = 465 mtb -> 31 clocks
b[196] = 0x58          # tRC = 0x258 = 600 mtb
b[199], b[200] = 0x38, 0x0E   # tRFC 3640 mtb = 260ns
b[201] = 105           # tRTP 7.5ns
b[202] = 84            # tRRD 6ns
b[203] = 1
b[204] = 0xA4          # tFAW = 0x1A4 = 420 mtb = 30ns

d3 = ddr3.decode(bytes(b))
check("DDR3 module_type", d3["module_type"], "UDIMM")
check("DDR3 speed", d3["speed_mts"], 1600)
check("DDR3 pcn", d3["pcn_rating"], "PC3-12800")
check("DDR3 size", d3["size_mb"], 8192)
check("DDR3 banks", d3["banks"], 16)
check("DDR3 core", d3["core_timings"], "11-11-11-23")
check("DDR3 voltages", d3["operable_voltages"], ["1.5 V", "1.35 V"])
check("DDR3 nominal V", d3["voltage_nominal_v"], 1.35)
check("DDR3 tRC", d3["timings_ns"]["tRC"], 42.5)
check("DDR3 tRFC", d3["timings_ns"]["tRFC"], 280.0)
check("DDR3 tFAW", d3["timings_ns"]["tFAW"], 45.0)
check("DDR3 CRC ok", d3["crc"]["ok"], True)
check("DDR3 mfr", d3["module_manufacturer"], "Micron Technology")
check("DDR3 dram", d3["dram_manufacturer"], "Micron Technology")
check("DDR3 serial", d3["serial"], "0xDEADBEEF")
check("DDR3 date", d3["manufacturing_date"], "2024-W10")
check("DDR3 part", d3["part_number"], "SYNTH-DDR3L-1600")
check("DDR3 at 1600", d3["timings_at_speeds"].get("DDR3-1600"), "11-11-11-23")
x = d3["xmp"]["profiles"][0]
check("XMP speed", x["speed_mts"], 1866)
check("XMP voltage", x["voltage_v"], 1.35)
check("XMP timings", x["timings"], "13-13-13-31")

# ---------------------------------------------------------------- DDR4
c = bytearray(512)
c[0] = 0x22            # 2x256 pages, 256 bytes written
c[1] = 0x14            # rev 1.4
c[2] = 0x0C            # DDR4
c[3] = 0x02            # UDIMM
c[4] = 0x15            # density code 5 (8Gb), bank groups enc 1 -> 8 banks
c[5] = 0x21            # rows 16, cols 10
c[6] = 0x00            # monolithic, 1 die
c[7] = 0x08            # MAC unlimited
c[11] = 0x01           # Vdd 1.2V
c[12] = 0x09           # x8, 2 ranks
c[13] = 0x03           # 64-bit
c[18] = 10             # tCK 10*125ps=1.25ns -> 1600
c[19] = 15             # tCKmax 1.875ns
c[20] = 0x10           # CAS bit4 -> CL11 (base 7)
c[24] = 110            # tAA 13.75ns
c[25] = 110            # tRCD
c[26] = 110            # tRP
c[27] = 0x10           # tRAS hi 0, tRC hi 1
c[28] = 230            # tRAS 28.75
c[29] = 84             # tRC 42.5
c[30], c[31] = 0xF0, 0x0A   # tRFC1 2800*.125=350ns
c[36], c[37] = 1, 0x40      # tFAW 320*.125=40ns
c[38] = 40             # tRRD_S 5ns
c[39] = 80             # tRRD_L 10ns
c[40] = 80             # tCCD_L 10ns
c[41], c[42] = 0, 120  # tWR 15ns
c[43], c[44], c[45] = 0, 20, 80  # tWTR_S 2.5, tWTR_L 10
c[11] = 0x01
c[14] = 0x80           # thermal sensor
c[132], c[133], c[134] = 0, 0, 0
c[128] = 0x0F          # height 30
c[129] = 0x22
c[130] = 0x00
# CRC over 128..253
crc = crc16_ccitt(bytes(c[128:254]))
c[254], c[255] = crc & 0xFF, crc >> 8
# mfg page 2
c[320] = crc_byte_parity(0)
c[321] = 0x2C          # Micron
c[322] = ord("B")
c[323], c[324] = 0x25, 0x05
c[325:329] = bytes([0x12, 0x34, 0x56, 0x78])
c[329:349] = b"SYNTH-DDR4-1600CL11".ljust(20, b"\x20")
c[349] = 0x01
c[350] = crc_byte_parity(0)
c[351] = 0x2C

d4 = ddr4.decode(bytes(c))
check("DDR4 module_type", d4["module_type"], "UDIMM")
check("DDR4 speed", d4["speed_mts"], 1600)
check("DDR4 pcn", d4["pcn_rating"], "PC4-12800")
check("DDR4 size", d4["size_mb"], 16384)
check("DDR4 banks", d4["banks"], 8)
check("DDR4 core", d4["core_timings"], "11-11-11-23")
check("DDR4 tRC", d4["timings_ns"]["tRC"], 42.5)
check("DDR4 tRFC1", d4["timings_ns"]["tRFC1"], 350.0)
check("DDR4 tRRD_S", d4["timings_ns"]["tRRD_S"], 5.0)
check("DDR4 tWTR_S", d4["timings_ns"]["tWTR_S"], 2.5)
check("DDR4 voltage", d4["operable_voltages"], ["1.2 V"])
check("DDR4 CRC ok", d4["crc"]["ok"], True)
check("DDR4 mfr", d4["module_manufacturer"], "Micron Technology")
check("DDR4 part", d4["part_number"], "SYNTH-DDR4-1600CL11")
check("DDR4 serial", d4["serial"], "0x12345678")
check("DDR4 at 1600", d4["timings_at_speeds"].get("DDR4-1600"), "11-11-11-23")

# ---------------------------------------------------------------- реальный дамп
_ref = os.path.join(os.path.dirname(__file__), "..", "_refs", "myspd.bin")
if os.path.exists(_ref):
    real = open(_ref, "rb").read()
    dr = ddr3.decode(real)
    check("REAL speed", dr["speed_mts"], 1333)
    check("REAL core", dr["core_timings"], "9-9-9-24")
    check("REAL xmp speed", dr["xmp"]["profiles"][0]["speed_mts"], 1866)
    check("REAL xmp timings", dr["xmp"]["profiles"][0]["timings"], "9-9-9-27")
else:
    print("ПРОПУСК: нет локального дампа _refs/myspd.bin (приватные данные)")

print(f"\n{'ВСЕ ТЕСТЫ ПРОЙДЕНЫ' if not FAILS else 'ПРОВАЛЕНО: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
