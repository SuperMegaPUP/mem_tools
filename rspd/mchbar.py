"""Потребительские Intel LGA1700 (ADL/RPL): живые тайминги из окна DRAMC.

На серверах тайминги лежат в ECAM на шине 0xff (см. epmc.py), на
десктопах их заменяет окно MCHBAR: на этой платформе реальное окно
оказалось в 0xfeda0000 (BAR в конфиг-регистре 0x68, а не 0x40) и
пространно 256 КБ. /dev/mem закрыт IO_STRICT_DEVMEM, поэтому снимок
снимается read-only модулем tools/mchbar и читается из /proc/mchbar.

Карта регистров получена методом BIOS-diff (Gigabyte B760M, DDR4:
tCL=17, tRAS=40, tRCD=tRP=20, частота 4133→3600 — см. docs §6.6):
  0x00318 [31:24] [23:16] — tRCD, tRP (порядок байт уточняется: в
                            валидационном заходе они были равны);
  0x239F4 [7:0] [15:8]    — tCL, tRAS (канал A; зеркало канала +0x5480);
  0x234C0 [15:0]          — tRFC1 в tCK, реплицируется каждые 0x100.
"""
from __future__ import annotations

import re

PROC = "/proc/mchbar"

_OFF_TRCDTRP = 0x00318
_OFF_TCLTRAS = 0x239F4
_OFF_TRFC1 = 0x234C0
_MIRROR = 0x5480
_LINE_RE = re.compile(r"^([0-9a-f]+):\s*([0-9a-f]{8})\s*$")


def parse_dump(text: str) -> dict[int, int]:
    """Текст /proc/mchbar ('смещение: dword') → {смещение: значение}."""
    out = {}
    for line in text.splitlines():
        m = _LINE_RE.match(line)
        if m:
            out[int(m.group(1), 16)] = int(m.group(2), 16)
    return out


def decode(vals: dict[int, int]) -> dict | None:
    """Первичные тайминги из дампа; None, если окно не похоже на DRAMC."""
    a = vals.get(_OFF_TRCDTRP)
    b = vals.get(_OFF_TCLTRAS)
    if a is None or b is None:
        return None
    t_rcd, t_rp = (a >> 24) & 0xFF, (a >> 16) & 0xFF
    t_cl, t_ras = b & 0xFF, (b >> 8) & 0xFF
    if not (5 <= t_cl <= 40 and 5 <= t_rcd <= 40 and 5 <= t_rp <= 40):
        return None
    if not (t_cl <= t_ras <= 90):
        return None
    out = {"tCL": t_cl, "tRCD": t_rcd, "tRP": t_rp, "tRAS": t_ras,
           "source": "0xfeda0000 (LGA1700), карта BIOS-diff"}
    r = vals.get(_OFF_TRFC1)
    if r is not None and 100 <= (r & 0xFFFF) <= 4000:
        out["tRFC"] = r & 0xFFFF
    return out


def read() -> dict | None:
    """Читает /proc/mchbar (нужен загруженный tools/mchbar) и декодирует."""
    try:
        with open(PROC) as f:
            text = f.read()
    except OSError:
        return None
    return decode(parse_dump(text))
