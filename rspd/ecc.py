"""ECC-статистика памяти: счётчики EDAC + события журнала за сутки.

Источники:
- /sys/devices/system/edac/mc/mc*/ — накопительные счётчики CE/UE
  (сбрасываются при перезагрузке);
- снапшот-кэш ~/.cache/ramspd/ecc_state.json — чтобы из накопительных
  счётчиков получить дельту именно за последние 24 часа;
- journalctl -k — события MCE и PCIe AER за окно (AER считается
  отдельно: это ошибки шины NVMe/GPU, а не памяти).
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

EDAC_ROOT = Path("/sys/devices/system/edac")
_STATE = (Path.home() / ".cache" / "ramspd" / "ecc_state.json")
_DAY = 24 * 3600
_MIN_BASE = 30 * 60  # базе дельты исполняется минимум столько

_PAT = {
    "mce": re.compile(r"mce:.*Hardware Error|Machine check", re.I),
    "edac": re.compile(r"EDAC.*(page failure|Uncorrected|Corrected"
                       r"|Error|error)"),
    "aer_corr": re.compile(r"severity=Correctable"),
    "aer_uncorr": re.compile(r"severity=(Uncorrectable|Fatal)"),
}


def _read_int(p: Path) -> int | None:
    try:
        return int(p.read_text().strip())
    except (OSError, ValueError):
        return None


def read_edac() -> dict | None:
    """Текущие накопительные счётчики EDAC (с момента загрузки)."""
    if not EDAC_ROOT.is_dir():
        return None
    mcs = []
    for mc in sorted(EDAC_ROOT.glob("mc/mc[0-9]*")):
        ce = (_read_int(mc / "ce_count") or 0) + \
             (_read_int(mc / "ce_noinfo_count") or 0)
        ue = (_read_int(mc / "ue_count") or 0) + \
             (_read_int(mc / "ue_noinfo_count") or 0)
        dimms = {}
        for d in sorted(mc.glob("dimm[0-9]*")):
            ce_d, ue_d = _read_int(d / "ce_count"), _read_int(d / "ue_count")
            if ce_d is not None or ue_d is not None:
                dimms[d.name] = {"ce": ce_d or 0, "ue": ue_d or 0}
        mcs.append({"mc": mc.name, "ce": ce, "ue": ue, "dimms": dimms})
    if not mcs:
        return None
    bad = {f"{m['mc']}/{dn}": v for m in mcs
           for dn, v in m["dimms"].items() if v["ce"] or v["ue"]}
    return {"mcs": mcs,
            "ce_total": sum(m["ce"] for m in mcs),
            "ue_total": sum(m["ue"] for m in mcs),
            "bad_dimms": bad}


def _delta_24h(ce: int, ue: int) -> dict | None:
    """Дельта накопительных счётчиков за ~24 ч по снапшот-кэшу.

    Снимки копятся при каждом запуске; база — самый старый снимок окна
    суток, но не моложе MIN_BASE_AGE (иначе дельта бессмысленна: «за 0
    минут»). None — полезной базы нет; отчёт тогда показывает итоги с
    загрузки. Перезагрузка (счётчики упали) базу обнуляет."""
    try:
        hist = json.loads(_STATE.read_text())
    except (OSError, ValueError):
        hist = []
    now = time.time()
    hist = [h for h in hist if now - h["ts"] <= 7 * _DAY]
    base = next((h for h in hist
                 if now - h["ts"] <= _DAY and now - h["ts"] >= _MIN_BASE),
                None)
    hist.append({"ts": now, "ce": ce, "ue": ue})
    try:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        _STATE.write_text(json.dumps(hist[-64:]))
    except OSError:
        pass
    if base is None or ce < base["ce"] or ue < base["ue"]:
        return None
    return {"ce": ce - base["ce"], "ue": ue - base["ue"],
            "window_h": round((now - base["ts"]) / 3600, 1)}


def journal_events(hours: int = 24) -> dict | None:
    """События ядра за окно: MCE, EDAC, PCIe AER (корр/некорр)."""
    try:
        r = subprocess.run(
            ["journalctl", "-k", "--since", f"{hours} hours ago",
             "-q", "--no-pager"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not r.stdout:
        return None
    ev = {k: 0 for k in _PAT}
    for line in r.stdout.splitlines():
        for k, pat in _PAT.items():
            if pat.search(line):
                ev[k] += 1
                break
    return ev


def uptime_hours() -> float | None:
    try:
        return round(float(Path("/proc/uptime").read_text().split()[0]) / 3600, 1)
    except (OSError, ValueError, IndexError):
        return None


def collect() -> dict | None:
    edac = read_edac()
    j = journal_events()
    if edac is None and j is None:
        return None
    res: dict = {}
    if edac:
        res.update(edac)
        res["delta_24h"] = _delta_24h(edac["ce_total"], edac["ue_total"])
        res["uptime_h"] = uptime_hours()
    if j:
        res["journal"] = j
    return res
