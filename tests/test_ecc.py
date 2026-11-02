#!/usr/bin/env python3
"""Тесты ECC-логики (без железа): дельта накопительных счётчиков EDAC
по снапшот-кэшу и разбор журнала. Запуск: python3 tests/test_ecc.py
"""
import json
import os
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rspd import ecc  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK' if ok else 'FAIL'}] {name}"
          + ("" if ok else f": получили {got!r}, ждали {want!r}"))
    if not ok:
        FAILS.append(name)


def with_state(snapshots):
    """Подменить кэш на временный с готовыми снапшотами (age_s, ce, ue)."""
    d = tempfile.mkdtemp()
    ecc._STATE = pathlib.Path(d) / "s.json"
    now = time.time()
    ecc._STATE.write_text(json.dumps(
        [{"ts": now - age, "ce": ce, "ue": ue} for age, ce, ue in snapshots]))


# 1) нормальная дельта: база 5 ч назад CE=3, сейчас CE=5 → +2
with_state([(5 * 3600, 3, 0)])
d = ecc._delta_24h(5, 0)
check("дельта за 5ч", (d["ce"], d["ue"], round(d["window_h"])), (2, 0, 5))

# 2) слишком свежая база (<30 мин) игнорируется
with_state([(120, 3, 0)])
check("свежая база → None", ecc._delta_24h(5, 0), None)

# 3) счётчики упали (перезагрузка) → None, а не отрицательная дельта
with_state([(5 * 3600, 9, 0)])
check("после ребута → None", ecc._delta_24h(5, 0), None)

# 4) база старше суток игнорируется
with_state([(30 * 3600, 3, 0)])
check("база >24ч → None", ecc._delta_24h(5, 0), None)

# 5) несколько снапшотов: берётся самый старый в окне суток
with_state([(20 * 3600, 1, 0), (10 * 3600, 2, 0), (1 * 3600, 4, 0)])
d = ecc._delta_24h(6, 0)
check("самый старый в окне", (d["ce"], round(d["window_h"])), (5, 20))

# 6) UE тоже считается
with_state([(8 * 3600, 0, 1)])
d = ecc._delta_24h(0, 4)
check("дельта UE", (d["ce"], d["ue"]), (0, 3))

# 7) разбор журнала: MCE/EDAC/AER не путаются
lines = "\n".join([
    "mce: [Hardware Error]: Machine check events logged",
    "EDAC MC0: 1 CE on page failure",
    "nvme: PCIe Bus Error: severity=Correctable, type=Physical Layer",
    "nvme: PCIe Bus Error: severity=Correctable, type=Data Link",
    "pcieport: PCIe Bus Error: severity=Fatal",
    "обычная строка без ошибок",
])
import re  # noqa: E402
ev = {k: 0 for k in ecc._PAT}
for line in lines.splitlines():
    for k, pat in ecc._PAT.items():
        if pat.search(line):
            ev[k] += 1
            break
check("журнал mce", ev["mce"], 1)
check("журнал edac", ev["edac"], 1)
check("журнал aer_corr", ev["aer_corr"], 2)
check("журнал aer_uncorr", ev["aer_uncorr"], 1)

print(f"\n{'ВСЕ ТЕСТЫ ECC ПРОЙДЕНЫ' if not FAILS else 'ПРОВАЛЕНО: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
