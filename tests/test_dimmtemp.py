#!/usr/bin/env python3
"""Тесты классификации DIMM-температур (rspd/dimmtemp) на фиктивной
hwmon-иерархии: PECI dimmtemp, SuperIO с меткой Dimm, TSOD (jc42),
фильтр «сенсор есть, но 0», CPU package. Без железа.
Запуск: python3 tests/test_dimmtemp.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rspd import dimmtemp  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK' if ok else 'FAIL'}] {name}"
          + ("" if ok else f": получили {got!r}, ждали {want!r}"))
    if not ok:
        FAILS.append(name)


def build(tmp, chip, sensors):
    """sensors: список (idx, label|None, millideg)."""
    h = os.path.join(tmp, chip)
    os.makedirs(h)
    with open(os.path.join(h, "name"), "w") as f:
        f.write(chip)
    for idx, label, milli in sensors:
        with open(os.path.join(h, f"temp{idx}_input"), "w") as f:
            f.write(str(milli))
        if label:
            with open(os.path.join(h, f"temp{idx}_label"), "w") as f:
                f.write(label)


tmp = tempfile.mkdtemp()
# PECI dimmtemp: 2 DIMM по индексу, без меток
build(tmp, "peci-dimmtemp", [(1, None, 45000), (2, None, 47000)])
# SuperIO: системный (не DIMM) + живой Dimm + мёртвый Dimm (0)
build(tmp, "nct6793", [(1, "SYSTIN", 40000),
                       (2, "Agent0 Dimm0", 52000),
                       (3, "Agent0 Dimm1", 0)])
# TSOD-чип (память на SMBus ОС)
build(tmp, "jc42", [(1, None, 43000)])
# coretemp: пакет CPU
build(tmp, "coretemp", [(1, "Package id 0", 39000), (2, "Core 0", 37000)])

dimmtemp._HWMON_GLOB = os.path.join(tmp, "*")

temps = dimmtemp.read_dimm_temps()
got = sorted((t["label"], t["c"], t["connected"]) for t in temps)
check("PECI+SuperIO+TSOD собраны", got, [
    ("Agent0 Dimm0", 52.0, True),
    ("Agent0 Dimm1", 0.0, False),          # мёртвый сенсор
    ("temp1", 43.0, True),                 # jc42 tsod
    ("temp1", 45.0, True),                 # peci-dimmtemp idx1
    ("temp2", 47.0, True),                 # peci-dimmtemp idx2
])
check("SYSTIN не попал (не DIMM)",
      any(t["label"] == "SYSTIN" for t in temps), False)
check("CPU package", dimmtemp.cpu_package_c(), 39.0)

# только мёртвые сенсоры → connected все False
tmp2 = tempfile.mkdtemp()
build(tmp2, "nct6793", [(2, "Agent0 Dimm0", 0)])
dimmtemp._HWMON_GLOB = os.path.join(tmp2, "*")
check("все мёртвые", [t["connected"] for t in dimmtemp.read_dimm_temps()],
      [False])

# --- EP MC Thermal Control: фиктивное sysfs config-пространство ---
from rspd import epmc  # noqa: E402

tmp3 = tempfile.mkdtemp()


def mk_cfg(slot, t150, t154, vendor=0x8086):
    os.makedirs(os.path.join(tmp3, slot), exist_ok=True)
    cfg = bytearray(0x200)
    cfg[0:2] = vendor.to_bytes(2, "little")
    if t150:
        cfg[0x150] = t150
    if t154:
        cfg[0x154] = t154
    with open(os.path.join(tmp3, slot, "config"), "wb") as f:
        f.write(cfg)


mk_cfg("14.0", 45, 49)   # канал A: 45/49
mk_cfg("14.1", 47, 51)   # канал B
mk_cfg("17.0", 44, 48)   # канал C
mk_cfg("17.1", 46, 0)    # канал D: второй слот пуст → фильтруется
epmc.SYSFS = os.path.join(tmp3, "{slot}") + "/config"
got = epmc.read_dimm_temps()
check("EP: 7 показаний из 8 слотов", len(got), 7)
check("EP: метки/значения",
      [(t["label"], t["c"]) for t in got[:2]] + [got[-1]["label"]],
      [("DIMM_A1", 45.0), ("DIMM_A2", 49.0), "DIMM_D1"])
# не-Intel конфиг отбрасывается
mk_cfg("14.0", 45, 49, vendor=0x10DE)
check("EP: чужой vendor → слот пропущен",
      len([t for t in epmc.read_dimm_temps() if t["label"].startswith("DIMM_A")]), 0)

print(f"\n{'ВСЕ ТЕСТЫ DIMMTEMP ПРОЙДЕНЫ' if not FAILS else 'ПРОВАЛЕНО: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
