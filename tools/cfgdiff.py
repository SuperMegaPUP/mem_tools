#!/usr/bin/env python3
"""Diff двух снимков PCI config (4K) всех устройств 00ff — найти регистры,
зависящие от конфигурации памяти (частота/тайминги)."""
import struct, sys, glob, os

def load_snap(d):
    out = {}
    for f in glob.glob(os.path.join(d, "0000:ff:*.bin")):
        name = os.path.basename(f).replace(".bin", "")
        out[name] = open(f, "rb").read(4096)
    return out

a = load_snap(sys.argv[1])
b = load_snap(sys.argv[2])
total = 0
for dev in sorted(set(a) & set(b)):
    da, db = a[dev], b[dev]
    n = min(len(da), len(db))
    diffs = []
    for off in range(0, n - 3, 4):
        va, vb = struct.unpack_from("<I", da, off)[0], struct.unpack_from("<I", db, off)[0]
        if va != vb:
            diffs.append((off, va, vb))
    if diffs:
        total += len(diffs)
        print(f"=== {dev} ({len(diffs)} изменений) ===")
        for off, va, vb in diffs:
            print(f"  {off:04x}: {va:08x} -> {vb:08x}   (XOR {va ^ vb:08x})")
print(f"\nВсего изменений: {total}")
