#!/usr/bin/env python3
"""Сравнение двух дампов MCHBAR (формат /proc/mchbar: 'offset: value').

Ключевая эвристика: тайминги в регистрах IMC хранятся в тактах памяти.
При смене частоты их числовое значение масштабируется как tCK_new/tCK_old
(нансекунды постоянны), а «константные» регистры (адресация, режимы)
не меняются вовсе. Флаг --ratio = old_mtps/new_mtps включает поиск
таких масштабирующихся полей внутри изменившихся dword-ов (по байтам).
"""
import argparse
import re
import sys


def load(path):
    vals = {}
    with open(path) as f:
        for line in f:
            m = re.match(r"([0-9a-f]+):\s+([0-9a-f]{8})", line)
            if m:
                vals[int(m.group(1), 16)] = int(m.group(2), 16)
    return vals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump1")
    ap.add_argument("dump2")
    ap.add_argument("--ratio", type=float, default=0.0,
                    help="old_mtps/new_mtps, например 4133/3600=1.148")
    args = ap.parse_args()
    a, b = load(args.dump1), load(args.dump2)

    changed = [(off, a[off], b[off]) for off in sorted(a)
               if off in b and a[off] != b[off]]
    print(f"изменилось регистров: {len(changed)} из {len(a)}")
    for off, v1, v2 in changed:
        note = ""
        if args.ratio > 0:
            # посовещаем байты: какой при масштабировании перекочевал?
            marks = []
            for i in range(4):
                b1 = (v1 >> (8 * i)) & 0xFF
                b2 = (v2 >> (8 * i)) & 0xFF
                if b1 != b2 and b1 and b2:
                    scaled = abs(b1 / args.ratio - b2) <= 1.5  # ±1.5 LSB
                    marks.append(f"байт{i}:{b1}->{b2}"
                                 + ("~ns-константа!" if scaled else ""))
            note = "  [" + ", ".join(marks) + "]" if marks else ""
        print(f"{off:05x}: {v1:08x} -> {v2:08x}{note}")


if __name__ == "__main__":
    sys.exit(main())
