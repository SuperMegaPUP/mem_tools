#!/usr/bin/env python3
"""Декодер MCHBAR (LGA1700): разбор дампа и валидация таймингов.

Якоря — два BIOS-diff раунда на Gigabyte B760M (G.Skill DDR4-4266):
раунд 1: 17-20-20-40, tFAW 16, tRFC(поле BIOS 504) @3600;
раунд 2: 16-18-22-38, tFAW 18, tRFC(поле BIOS 512), tREFI 65534 @3200.
Фикстура — второй раунд (все значения разные).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rspd import mchbar  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"[{'OK ' if ok else 'FAIL'}] {name}: {got!r}")
    if not ok:
        print(f"       ожидалось: {want!r}")
        FAILS.append(name)


DUMP = """2e070: 0e100020
2e53c: 12131211
2e000: 16418016
2e004: 0090982a
2e008: 18049412
2e43c: 0800fffe
2e0a8: 03240040
мусорная строка
2e001: не-шестнадцатеричное
"""

vals = mchbar.parse_dump(DUMP)
check("parse_dump, мусорные строки отброшены", len(vals), 7)
check("parse_dump, значение 0x2e004", vals[0x2E004], 0x0090982A)

d = mchbar.decode(vals)
check("tCL (якорь 16)", d["tCL"], 16)
check("tRCD (якорь 18)", d["tRCD"], 18)
check("tRP (якорь 22)", d["tRP"], 22)
check("tRAS (якорь 38, 6-бит)", d["tRAS"], 38)
check("tFAW (якорь 18)", d["tFAW"], 18)
check("tRFC1 (804 tCK @3200 = поле BIOS 512 нс)", d["tRFC"], 804)
check("tREFI (якорь 65534)", d["tREFI"], 65534)

# негативные проверки
check("пустой дамп → None", mchbar.decode({}), None)
check("FF-окно → None", mchbar.decode(
    {0x2E070: 0xFFFFFFFF, 0x2E53C: 0xFFFFFFFF,
     0x2E000: 0xFFFFFFFF, 0x2E004: 0xFFFFFFFF}), None)
check("tRAS < tCL → None", mchbar.decode(
    {0x2E070: 0x0E1E0020, 0x2E53C: 0x12131211,   # tCL=30
     0x2E000: 0x16418016, 0x2E004: 0x0090502A}), None)  # tRAS=20
_proc_orig = mchbar.PROC
mchbar.PROC = "/nonexistent-mchbar"
check("read() без /proc → None", mchbar.read(), None)
mchbar.PROC = _proc_orig

print(f"\n{'ВСЕ ТЕСТЫ MCHBAR ПРОЙДЕНЫ' if not FAILS else 'ПРОВАЛЕНО: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
