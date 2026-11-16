"""Сенсоры сервера: BMC/IPMI SDR + GPU (только чтение).

BMC отдаёт список сенсоров командой `ipmitool sdr elist`; группировка
по единицам измерения (°C / RPM / Volts / Amps / Watts) работает для
любого вендора без предзнания имён. Мощность выводится из V×I для пар
VR_*_VOUT / VR_*_IOUT — так видно реальное энергопотребление памяти
там, где процессорный счётчик (RAPL) его не даёт.
"""
from __future__ import annotations

import os
import re
import subprocess

# единица SDR -> группа (с равной по смыслу подписью в отчёте)
_UNIT2GROUP = {"degrees c": "temp", "rpm": "fan", "volt": "volt",
               "amp": "amp", "watt": "watt"}
_VAL_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s+(.+?)$")


def _run(cmd: list[str], timeout: int = 8) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _bmc_present() -> bool:
    return (os.path.exists("/dev/ipmi0") or os.path.exists("/dev/ipmi/0")
            or os.path.exists("/dev/ipmi-0"))


def parse_elist(text: str) -> list[dict]:
    """Строки `ipmitool sdr elist` → сенсоры только с числовым значением."""
    out = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue
        name, status, val = parts[0], parts[2].lower(), parts[4]
        m = _VAL_RE.match(val)
        if not m:
            continue                       # дискретные (Presence, 0x..)
        unit = m.group(2).lower().rstrip("s")
        grp = _UNIT2GROUP.get(unit)
        if not grp:
            continue
        out.append({"name": name.removesuffix("_TEMP"), "group": grp,
                    "v": float(m.group(1)), "status": status})
    return out


def derive_power(sensors: list[dict]) -> list[dict]:
    """Для каждой шины VOUT с парным IOUT — мощность в ваттах."""
    by = {s["name"]: s for s in sensors}
    out = []
    for s in sensors:
        if s["group"] != "volt" or not s["name"].endswith("_VOUT"):
            continue
        cur = by.get(s["name"][:-len("_VOUT")] + "_IOUT")
        if cur is not None:
            out.append({"name": s["name"][:-len("_VOUT")].removeprefix("VR_"),
                        "w": round(s["v"] * cur["v"], 1),
                        "v": s["v"], "a": cur["v"]})
    return out


def read_gpus() -> list[dict]:
    """Температура/мощность NVIDIA GPU через nvidia-smi (csv)."""
    out = _run(["nvidia-smi",
                "--query-gpu=name,temperature.gpu,power.draw,power.limit",
                "--format=csv,noheader,nounits"], timeout=6)
    gpus = []
    for line in out.splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) < 4:
            continue
        try:
            gpus.append({"name": p[0], "c": float(p[1]),
                         "w": float(p[2]), "cap": float(p[3])})
        except ValueError:
            continue                       # [N/A] на пассивных картах
    return gpus


def collect() -> dict | None:
    """Всё вместе; None — если сенсоров нет вовсе (десктоп без BMC)."""
    sensors = parse_elist(_run(["ipmitool", "sdr", "elist"])) if _bmc_present() else []
    gpus = read_gpus()
    if not sensors and not gpus:
        return None
    return {"sensors": sensors, "power": derive_power(sensors), "gpus": gpus}
