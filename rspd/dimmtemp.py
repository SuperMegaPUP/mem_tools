"""Температура модулей памяти: TSOD / PECI DTS / IPMI / SuperIO.

HWiNFO на Windows читает per-DIMM температуру через PECI DTS (её ring0
драйвер сам включает OS-PECI). В Linux те же данные приходят из:

  1. peci-dimmtemp hwmon  — temp1..N = DTS каждого DIMM (основной путь на
     Intel, когда в ядре есть x86-мост PECI);
  2. SuperIO-сенсоров с меткой *Dimm* (NCT67xx/IT87xx заводят DIMM DTS);
  3. IPMI/BMC — `ipmitool sdr type Temperature` (серверные платы);
  4. i2c TSOD hwmon (tsod/tmp513/tmp112/...) — платы, где память на SMBus ОС.

Классификация простая: любой hwmon-сенсор, у которого имя контроллера или
метка содержит "dimm", считается температурой модуля. Если ничего не
найдено (плата прячет память за ME/SMLink, а OS-PECI-моста в ядре нет —
как на Huananzhi X99-T8), возвращаем пустой список; отдельно отдаём
температуру пакета CPU (в неё входит встроенный контроллер памяти) как
косвенную оценку.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess

_HWMON_GLOB = "/sys/class/hwmon/hwmon*"
_TSOD_NAMES = ("tsod", "tmp513", "tmp112", "tmp102", "mcp980", "jc42",
               "spd5118", "tsens")


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _hwmon_sensors() -> list[dict]:
    out = []
    for h in sorted(glob.glob(_HWMON_GLOB)):
        name = _read(os.path.join(h, "name"))
        for inp in sorted(glob.glob(os.path.join(h, "temp*_input"))):
            base = inp[: -len("_input")]
            raw = _read(inp)
            if not raw:
                continue
            try:
                milli = int(raw)
            except ValueError:
                continue
            out.append({
                "hwmon": os.path.basename(h),
                "chip": name,
                "label": _read(base + "_label") or os.path.basename(base),
                "c": round(milli / 1000.0, 1),
            })
    return out


def read_dimm_temps() -> list[dict]:
    """Список {'label','c','chip','connected'} для DIMM-сенсоров.

    connected=False — сенсор найден, но читает ровно 0 (SuperIO-DIMM,
    который BIOS не развёл, или PECI-DTS без данных). Такие не показываем
    как реальную температуру, но упоминаем в примечании."""
    temps = []
    for s in _hwmon_sensors():
        blob = (s["chip"] + " " + s["label"]).lower()
        if "dimm" in blob or any(t in s["chip"].lower() for t in _TSOD_NAMES):
            temps.append({"label": s["label"], "c": s["c"], "chip": s["chip"],
                          "connected": s["c"] > 0.0})
    temps += _ipmi_dimm_temps()
    return temps


def _ipmi_dimm_temps() -> list[dict]:
    """DIMM-температуры из IPMI, если есть BMC и ipmitool."""
    if not os.path.exists("/dev/ipmi0") and not os.path.exists("/dev/ipmi/0"):
        return []
    try:
        r = subprocess.run(["ipmitool", "sdr", "type", "Temperature"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in r.stdout.splitlines():
        if not re.search(r"dimm|mem", line, re.I):
            continue
        m = re.search(r"(\d+(?:\.\d+)?)\s*degrees\s*C", line, re.I)
        if m:
            name = line.split("|")[0].strip()
            out.append({"label": name, "c": float(m.group(1)),
                        "chip": "ipmi", "connected": True})
    return out


def cpu_package_c() -> float | None:
    """Температура пакета CPU (внутри — контроллер памяти): coretemp
    'Package id', иначе thermal_zone x86_pkg_temp, иначе PECI Agent."""
    for s in _hwmon_sensors():
        if s["chip"] == "coretemp" and "package" in s["label"].lower():
            return s["c"]
    for z in glob.glob("/sys/class/thermal/thermal_zone*"):
        if "pkg" in _read(os.path.join(z, "type")).lower():
            t = _read(os.path.join(z, "temp"))
            if t.isdigit():
                return round(int(t) / 1000.0, 1)
    for s in _hwmon_sensors():
        if "peci agent" in s["label"].lower():
            return s["c"]
    return None


def collect() -> dict:
    """Собираем температуры: сначала регистры Thermal Control контроллера
    памяти Xeon EP (работают даже когда память спрятана за ME — они в
    ECAM), затем переносимые пути (peci-dimmtemp/SuperIO/TSOD/IPMI)."""
    temps: list[dict] = []
    try:
        from . import epmc
        temps = epmc.read_dimm_temps()
    except Exception:
        temps = []
    if not temps:
        temps = read_dimm_temps()
    return {"dimm_temps": temps, "cpu_package_c": cpu_package_c()}
