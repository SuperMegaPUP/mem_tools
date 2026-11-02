#!/usr/bin/env python3
"""Сверка моего декодера с оракулом decode-dimms на реальном дампе DDR3."""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rspd import ddr3  # noqa: E402

_ref = os.path.join(os.path.dirname(__file__), "..", "_refs", "myspd.bin")
if not os.path.exists(_ref):
    print("ПРОПУСК: нет локального дампа _refs/myspd.bin (приватные данные)")
    sys.exit(0)
data = open(_ref, "rb").read()
d = ddr3.decode(data)

# hexdump в формате decode-dimms (группы по 2 байта, big-endian слова)
lines = []
for off in range(0, len(data), 16):
    row = data[off:off + 16]
    groups = [f"{row[i]:02x}{row[i + 1]:02x}" for i in range(0, len(row), 2)]
    lines.append(f"{off:08x}: " + " ".join(groups))
open("/tmp/oracle_check.txt", "w").write("\n".join(lines) + "\n")

try:
    out = subprocess.run(["decode-dimms", "-x", "/tmp/oracle_check.txt"],
                         capture_output=True, text=True).stdout
except FileNotFoundError:
    print("ПРОПУСК: утилита decode-dimms (lm-sensors) не установлена")
    sys.exit(0)

def oracle_val(pat):
    m = re.search(pat, out)
    return m.group(1).strip() if m else None

checks = [
    ("Module Type", oracle_val(r"Module Type\s+(.+)"), d["module_type"]),
    ("SPD Revision", oracle_val(r"SPD Revision\s+(.+)"), d["spd_revision"]),
    ("Speed", oracle_val(r"Maximum module speed\s+(\d+)"), str(d["speed_mts"])),
    ("PC3", oracle_val(r"Maximum module speed.*\((PC3-\d+)\)"), d["pcn_rating"]),
    ("Size MB", oracle_val(r"Size\s+(\d+) MB"), str(d["size_mb"])),
    ("BxRx CxB", oracle_val(r"Banks x Rows x Columns x Bits\s+(.+)"),
     f"{d['banks']} x {d['rows']} x {d['columns']} x {d['bus_width_bits']}"),
    ("Ranks", oracle_val(r"Ranks\s+(\d+)"), str(d["ranks"])),
    ("Core", oracle_val(r"tCL-tRCD-tRP-tRAS\s+(\S+)"), d["core_timings"]),
    ("CAS", oracle_val(r"Supported CAS Latencies \(tCL\)\s+(.+)"),
     ", ".join(f"{c}T" for c in d["cas_supported"])),
    ("tCK", oracle_val(r"Minimum Cycle Time \(tCK\)\s+(.+)"), f"{d['timings_ns']['tCK']:.3f} ns"),
    ("tAA", oracle_val(r"Minimum CAS Latency Time \(tAA\)\s+(.+)"), f"{d['timings_ns']['tAA']:.3f} ns"),
    ("tWR", oracle_val(r"Minimum Write Recovery time \(tWR\)\s+(.+)"), f"{d['timings_ns']['tWR']:.3f} ns"),
    ("tRCD", oracle_val(r"Minimum RAS# to CAS# Delay \(tRCD\)\s+(.+)"), f"{d['timings_ns']['tRCD']:.3f} ns"),
    ("tRRD", oracle_val(r"Minimum Row Active to Row Active Delay \(tRRD\)\s+(.+)"), f"{d['timings_ns']['tRRD']:.3f} ns"),
    ("tRP", oracle_val(r"Minimum Row Precharge Delay \(tRP\)\s+(.+)"), f"{d['timings_ns']['tRP']:.3f} ns"),
    ("tRAS", oracle_val(r"Minimum Active to Precharge Delay \(tRAS\)\s+(.+)"), f"{d['timings_ns']['tRAS']:.3f} ns"),
    ("tRC", oracle_val(r"Minimum Active to Auto-Refresh Delay \(tRC\)\s+(.+)"), f"{d['timings_ns']['tRC']:.3f} ns"),
    ("tRFC", oracle_val(r"Minimum Recovery Delay \(tRFC\)\s+(.+)"), f"{d['timings_ns']['tRFC']:.3f} ns"),
    ("tWTR", oracle_val(r"Minimum Write to Read CMD Delay \(tWTR\)\s+(.+)"), f"{d['timings_ns']['tWTR']:.3f} ns"),
    ("tRTP", oracle_val(r"Minimum Read to Pre-charge CMD Delay \(tRTP\)\s+(.+)"), f"{d['timings_ns']['tRTP']:.3f} ns"),
    ("tFAW", oracle_val(r"Minimum Four Activate Window Delay \(tFAW\)\s+(.+)"), f"{d['timings_ns']['tFAW']:.3f} ns"),
    ("Voltages", oracle_val(r"Operable voltages\s+(.+)"), "1.5V"),
    ("CRC", "OK" if d["crc"]["ok"] else "Bad", oracle_val(r"EEPROM CRC of bytes 0-\d+\s+(\w+)")),
    ("Mfr", oracle_val(r"Module Manufacturer\s+(.+)"), d["module_manufacturer"]),
    ("DRAM", oracle_val(r"DRAM Manufacturer\s+(.+)"), d["dram_manufacturer"]),
    ("Serial", oracle_val(r"Assembly Serial Number\s+(.+)"), d["serial"]),
    ("Part", oracle_val(r"Part Number\s+(.+)"), d["part_number"]),
    ("Rev", oracle_val(r"Revision Code\s+(.+)"), d["revision"]),
]

# тайминги на скоростях
for m in re.finditer(r"tCL-tRCD-tRP-tRAS as (DDR3-\d+)\s+(\S+)", out):
    speed, val = m.group(1), m.group(2)
    mine = d["timings_at_speeds"].get(speed)
    checks.append((f"Timings {speed}", val, mine))

fails = 0
for name, oracle, mine in checks:
    ok = str(oracle) == str(mine)
    if not ok:
        fails += 1
    print(f"{'OK ' if ok else 'FAIL'} {name:22s} oracle={oracle!r} mine={mine!r}")

print(f"\n{len(checks) - fails}/{len(checks)} совпадений")
sys.exit(1 if fails else 0)
