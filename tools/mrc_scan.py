#!/usr/bin/env python3
"""Поиск в физическом RAM структуры MRC по подписи таймингов.

tCL=13 tRCD=13 tRP=13 tRAS=31 tRC=44 -> байты 0d 0d 0d 1f 2c.
Соседи найденной структуры = остальные тайминги (tCWL, tRRD, tWTR...).
"""
import mmap
import re
import sys

PAT = re.compile(rb"\x0d\x0d\x0d\x1f\x2c", re.S)
PAT4 = re.compile(rb"\x0d\x0d\x0d\x1f", re.S)
CHUNK = 64 << 20
OVER = 8

def main():
    limit = int(sys.argv[1], 0) if len(sys.argv) > 1 else 4 << 30
    f = open("/dev/mem", "rb", 0)
    hits = 0
    for base in range(0, limit, CHUNK):
        size = min(CHUNK, limit - base)
        try:
            mm = mmap.mmap(f.fileno(), size, mmap.MAP_SHARED,
                           mmap.MAP_PRIVATE, offset=base)
            data = mm[:]
            mm.close()
        except OSError:
            continue  # MMIO-дыра на этом участке
        for pat, name in ((PAT, "5B"), (PAT4, "4B")):
            for m in pat.finditer(data):
                off = base + m.start()
                # контекст 128 байт вокруг
                s = max(0, m.start() - 32)
                ctx = data[s:m.start() + 96]
                print(f"=== {name} hit phys 0x{off:x} ===")
                for i in range(0, len(ctx), 16):
                    row = ctx[i:i+16]
                    print(f"  {off-32+i:010x}: {row.hex(' ')}")
                hits += 1
                if hits > 40:
                    print("хватит, слишком много ложных")
                    return
    print(f"hits={hits}")

if __name__ == "__main__":
    main()
