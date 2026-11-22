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
2e000: 16418016
2e004: 0090982a
2e008: 18049412
2e43c: 0800fffe
2e4c0: 00000210
мусорная строка
2e001: не-шестнадцатеричное
"""

vals = mchbar.parse_dump(DUMP)
check("parse_dump, мусорные строки отброшены", len(vals), 6)
check("parse_dump, значение 0x2e004", vals[0x2E004], 0x0090982A)

d = mchbar.decode(vals)
check("tCL (якорь 16)", d["tCL"], 16)
check("tRCD (якорь 18, 6-бит [24:19])", d["tRCD"], 18)
check("tRP (якорь 22)", d["tRP"], 22)
check("tRAS (якорь 38, 6-бит [15:10])", d["tRAS"], 38)
check("tFAW (якорь 18)", d["tFAW"], 18)
check("tCWL (byte3 0x2e070, =tCL−2=14)", d["tCWL"], 14)
check("tRRD_L ([13:9] 0x2e008, якорь 10)", d["tRRD_L"], 10)
check("tRFC (поле BIOS 512 + 10нс = 528 @3200)", d["tRFC"], 528)
check("tREFI (якорь 65534)", d["tREFI"], 65534)

# r9: ОДИНОЧНАЯ смена tRRD_L 10→9 @4133 (0x2e008 ...9410→...9210 в 4
# зеркалах) — чистейший якорь 5-битного поля [13:9], поверх байта 1
d9 = mchbar.decode(mchbar.parse_dump(
    "2e070: 10120020\n2e000: 16418016\n"
    "2e004: 00b0a82c\n2e008: 18049210\n"))
check("r9 tRRD_L (якорь 9)", d9["tRRD_L"], 9)
check("r9 tCWL (=tCL−2=16)", d9["tCWL"], 16)
check("r9 tFAW (16, не поехал)", d9["tFAW"], 16)

# негативные проверки
check("пустой дамп → None", mchbar.decode({}), None)
check("FF-окно → None", mchbar.decode(
    {0x2E070: 0xFFFFFFFF, 0x2E004: 0xFFFFFFFF,
     0x2E000: 0xFFFFFFFF}), None)
check("tRAS < tCL → None", mchbar.decode(
    {0x2E070: 0x0E1E0020,                    # tCL=30
     0x2E000: 0x16418016,
     0x2E004: 0x0090502A}), None)            # tRAS=20
_proc_orig = mchbar.PROC
mchbar.PROC = "/nonexistent-mchbar"
check("read() без /proc → None", mchbar.read(), None)
mchbar.PROC = _proc_orig

print(f"\n{'ВСЕ ТЕСТЫ MCHBAR ПРОЙДЕНЫ' if not FAILS else 'ПРОВАЛЕНО: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
