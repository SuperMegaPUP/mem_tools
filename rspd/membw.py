"""Тест пропускной способности DRAM (STREAM-подобный) для ramspd.

Собирает tools/membw.c при первом запуске (кэш в каталоге утилиты),
запускает пять классических ядер (Read/Copy/Scale/Add/Triad) и
сопоставляет результат с теоретическим пиком каналов памяти.

Теоретический пик = MT/s × 8 байт × число каналов (64 бита данных
на канал). Для 4-канальной DDR3-1866: 1866.67 × 8 × 4 = 59.7 GB/s.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "tools" / "membw.c"
_BIN = _SRC.with_name("membw")
KERNELS = ("Read", "Write", "Copy", "Scale", "Add", "Triad")


def _compile() -> Path:
    """Собрать membw, если бинарник старше исходника. -march=native
    включает AVX2 streaming-сторы (vmovntpd) — без них Copy/Triad
    занижены на треть из-за RFO-трафика."""
    if _BIN.exists() and _BIN.stat().st_mtime >= _SRC.stat().st_mtime:
        return _BIN
    cc = os.environ.get("CC", "cc")
    for flags in (["-O3", "-march=native"], ["-O3"], ["-O2"]):
        cmd = [cc, *flags, "-pthread", "-o", str(_BIN) + ".tmp", str(_SRC)]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            os.replace(str(_BIN) + ".tmp", _BIN)
            return _BIN
        except subprocess.CalledProcessError:
            continue
    raise RuntimeError(f"не удалось собрать {_SRC.name}: нужен рабочий cc")


def _physical_cores() -> int:
    try:
        out = subprocess.run(
            ["lscpu", "-p=Core"],
            capture_output=True, text=True, check=True).stdout
        cores = {ln.split(",")[0].strip() for ln in out.splitlines()
                 if ln and not ln.startswith("#")}
        if cores:
            return len(cores)
    except Exception:
        pass
    return os.cpu_count() or 4


def run(threads: int | None = None, iters: int = 8,
        size_mib: int = 512) -> dict:
    """Запустить бенчмарк. size_mib — размер ОДНОГО массива (×3 всего)."""
    binp = _compile()
    threads = threads or min(_physical_cores(), 64)
    out = subprocess.run([str(binp), str(threads), str(iters), str(size_mib)],
                         capture_output=True, text=True, check=True)
    res = {"threads": threads, "iters": iters, "size_mib": size_mib,
           "kernels": {}}
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] in KERNELS:
            res["kernels"][parts[0]] = {"best": float(parts[1]),
                                        "avg": float(parts[2])}
    return res


def theoretical_gbs(mtps: float | None, channels: int) -> float | None:
    if not mtps or channels < 1:
        return None
    return round(mtps * 8.0 * channels / 1000.0, 1)


def count_channels(devices: list[dict]) -> int:
    """Каналы из локаторов DIMM_A1/DIMM_B2/CHANNEL0: буква/номер канала,
    слот (вторая цифра) не учитывается. DIMM_A1 и DIMM_A2 — один канал."""
    import re
    chans = set()
    for d in devices:
        loc = (d.get("locator") or "").upper()
        m = (re.search(r"CHANNEL[_ ]?([A-Z0-9])", loc)
             or re.search(r"DIMM[_ ]?([A-Z0-9])\d*", loc)
             or re.match(r"([A-Z])\d+[A-Z]?\d*$", loc))
        if m:
            chans.add(m.group(1))
    return len(chans) or 1
