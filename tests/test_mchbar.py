#!/usr/bin/env python3
"""Декодер MCHBAR (LGA1700): разбор дампа и валидация таймингов.

Якоря — из BIOS-diff на Gigabyte B760M: tCL=17, tRAS=40, tRCD=tRP=20,
tRFC1=632 tCK при 3600 MT/s.
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


DUMP = """00318: 14140000
234c0: 00090278
239f4: 89832811
28e74: 89832811
мусорная строка
00319: не-шестнадцатеричное
"""

vals = mchbar.parse_dump(DUMP)
check("parse_dump, мусорные строки отброшены", len(vals), 4)
check("parse_dump, значение 0x239f4", vals[0x239F4], 0x89832811)

d = mchbar.decode(vals)
check("tCL (якорь BIOS 17)", d["tCL"], 17)
check("tRAS (якорь BIOS 40)", d["tRAS"], 40)
check("tRCD/tRP (якорь BIOS 20/20)", (d["tRCD"], d["tRP"]), (20, 20))
check("tRFC1 (632 tCK ≈ 351 нс)", d["tRFC"], 632)

# негативные проверки: пустое окно / FF / невозможные тайминги
check("пустой дамп → None", mchbar.decode({}), None)
check("FF-окно → None", mchbar.decode(
    {0x318: 0xFFFFFFFF, 0x239F4: 0xFFFFFFFF}), None)
check("tRAS < tCL → None", mchbar.decode(
    {0x318: 0x14140000, 0x239F4: 0x89831019}), None)  # tCL=25, tRAS=16
_proc_orig = mchbar.PROC
mchbar.PROC = "/nonexistent-mchbar"
check("read() без /proc → None", mchbar.read(), None)
mchbar.PROC = _proc_orig

print(f"\n{'ВСЕ ТЕСТЫ MCHBAR ПРОЙДЕНЫ' if not FAILS else 'ПРОВАЛЕНО: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
