#!/usr/bin/env python3
"""Тесты rspd/sensors.py на фиктивном выводе ipmitool/nvidia-smi."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rspd import sensors  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}")
    if not ok:
        print(f"       got={got!r}\n      want={want!r}")
        FAILS.append(name)


ELIST = """CPU0_TEMP        | 01h | ok  |  3.1 | 29 degrees C
DIMMG0_TEMP      | 04h | ok  | 66.1 | 27 degrees C
CPU0_FAN         | 20h | ok  | 29.1 | 900 RPM
SYS_FAN3         | 23h | ns  | 29.4 | No Reading
P_12V            | 40h | ok  |  7.1 | 12.22 Volts
P0_VDDCR_CPU     | 41h | ok  |  7.2 | 0.74 Volts
VR_DIMMG0_VOUT   | 55h | ok  |  7.16 | 1.25 Volts
VR_DIMMG1_VOUT   | 57h | ok  |  7.17 | 1.26 Volts
VR_DIMMG0_IOUT   | 82h | ok  |  7.12 | 15 Amps
VR_DIMMG1_IOUT   | 83h | nc  |  7.13 | 15 Amps
CPU0_Status      | 02h | ok  |  3.0 | Presence detected
SYS_POWER        | 33h | ns  | 10.1 | No Reading
M2_G0_AMB_TEMP   | 1Ch | ok  | 11.1 | 34 degrees C
"""

s = sensors.parse_elist(ELIST)
check("числовые сенсоры отобраны (дискретные/ns — нет)", len(s), 10)
check("группа temp", [x["name"] for x in s if x["group"] == "temp"],
      ["CPU0", "DIMMG0", "M2_G0_AMB"])
check("суффикс _TEMP снят", all("_TEMP" not in x["name"] for x in s), True)
check("fan", [(x["name"], x["v"]) for x in s if x["group"] == "fan"],
      [("CPU0_FAN", 900.0)])
check("volt", [x["name"] for x in s if x["group"] == "volt"],
      ["P_12V", "P0_VDDCR_CPU", "VR_DIMMG0_VOUT", "VR_DIMMG1_VOUT"])
check("amp + статус nc сохранён",
      [(x["name"], x["status"]) for x in s if x["group"] == "amp"],
      [("VR_DIMMG0_IOUT", "ok"), ("VR_DIMMG1_IOUT", "nc")])

p = sensors.derive_power(s)
check("мощность V×I по парам", [(x["name"], x["w"]) for x in p],
      [("DIMMG0", 18.8), ("DIMMG1", 18.9)])

# GPU: monkeypatch _run (N/A-строки должны отбрасываться)
_run_orig = sensors._run
sensors._run = lambda cmd, timeout=8: (
    "NVIDIA CMP 50HX, 25, 0.87, 225.00\n"
    "NVIDIA H100, [N/A], 120.5, 350\n"
    "NVIDIA CMP 50HX, 27, 8.42, 225.00\n")
g = sensors.read_gpus()
check("GPU csv, N/A пропущен", [(x["name"], x["c"], x["w"]) for x in g],
      [("NVIDIA CMP 50HX", 25.0, 0.87), ("NVIDIA CMP 50HX", 27.0, 8.42)])
sensors._run = _run_orig

# amdgpu hwmon: фиктивное дерево с edge/junction/mem
import tempfile  # noqa: E402
tmp = tempfile.mkdtemp()
hw = os.path.join(tmp, "hwmon0")
os.makedirs(hw)
with open(os.path.join(hw, "name"), "w") as f:
    f.write("amdgpu\n")
for i, (lbl, v) in enumerate([("edge", 38000), ("junction", 39000),
                              ("mem", 40000)], 1):
    with open(os.path.join(hw, f"temp{i}_input"), "w") as f:
        f.write(str(v))
    with open(os.path.join(hw, f"temp{i}_label"), "w") as f:
        f.write(lbl)
for fn, v in (("power1_average", "23000000"), ("power1_cap", "132000000")):
    with open(os.path.join(hw, fn), "w") as f:
        f.write(v)
_glob_orig = sensors._HWMON_GLOB
sensors._HWMON_GLOB = os.path.join(tmp, "hwmon*")
g = sensors.read_amd_gpus()
check("amdgpu edge/junction/mem",
      [(x.get("c"), x.get("junction"), x.get("mem")) for x in g],
      [(38.0, 39.0, 40.0)])
check("amdgpu мощность µW→Вт", [(g[0]["w"], g[0]["cap"])], [(23.0, 132.0)])
sensors._HWMON_GLOB = _glob_orig

print(f"\n{'ВСЕ ТЕСТЫ СЕНСОРОВ ПРОЙДЕНЫ' if not FAILS else 'ПРОВАЛЕНО: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
