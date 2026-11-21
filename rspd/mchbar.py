"""Потребительские Intel LGA1700 (ADL/RPL): живые тайминги из окна DRAMC.

На серверах тайминги лежат в ECAM на шине 0xff (см. epmc.py), на
десктопах их заменяет окно MCHBAR: на этой платформе реальное окно
оказалось в 0xfeda0000 (BAR в конфиг-регистре 0x68, а не 0x40) и
пространно 256 КБ. /dev/mem закрыт IO_STRICT_DEVMEM, поэтому снимок
снимается read-only модулем tools/mchbar и читается из /proc/mchbar.

Карта привязана ДВУМЯ BIOS-diff раундами (Gigabyte B760M: 17-20-20-40
tFAW16 tRFC(504ns) @3600 → 16-18-22-38 tFAW18 tRFC(512ns) @3200; см.
docs §6.6). Настоящий блок таймингов — 0x2e000 (канал A) и зеркала
0x2f000 / 0x3e000 / 0x3f000 (шаг +0x10000):
  0x2e070 [23:16]  — tCL;
  0x2e53c [15:8]   — tRCD;
  0x2e000 [7:0]    — tRP;
  0x2e004 [16:10]  — tRAS (6-битное поле);
  0x2e008 [7:0]    — tFAW;
  0x2e43c [15:0]   — tREFI (raw, BIOS 65535 → регистр 65535);
  0x2e0a8 [31:16]  — tRFC1 в тактах памяти; поле tRFC в BIOS Gigabyte
                     задаётся в НАНСЕКУНДАХ (504→900 @3600, 512→804
                     @3200 — округления и дерейт рангов).
Ловушки (обженились дважды): блок 0x23xxx/0x20xxx — тренировочный,
перезаписывается каждую загрузку, значения там совпадают с таймингами
случайно (0x239f4=17/40, 0x2d07c=503 — совпадения раунда 1); поле
0x318 не двигалось вообще — тоже константа.
"""
from __future__ import annotations

import re

PROC = "/proc/mchbar"

_OFF_TCL = 0x2E070      # [23:16]
_OFF_TRCD = 0x2E53C     # [15:8]
_OFF_TRP = 0x2E000      # [7:0]
_OFF_TRAS = 0x2E004     # [16:10] 6-бит
_OFF_TFAW = 0x2E008     # [7:0]
_OFF_TREFI = 0x2E43C    # [15:0]
_OFF_TRFC1 = 0x2E0A8    # [31:16]
_MIRROR = 0x10000
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
    a = vals.get(_OFF_TCL)
    b = vals.get(_OFF_TRCD)
    c = vals.get(_OFF_TRP)
    d = vals.get(_OFF_TRAS)
    if a is None or b is None or c is None or d is None:
        return None
    t_cl = (a >> 16) & 0xFF
    t_rcd = (b >> 8) & 0xFF
    t_rp = c & 0xFF
    t_ras = (d >> 10) & 0x3F
    if not (5 <= t_cl <= 40 and 5 <= t_rcd <= 40 and 5 <= t_rp <= 40):
        return None
    if not (t_cl <= t_ras <= 63):
        return None
    out = {"tCL": t_cl, "tRCD": t_rcd, "tRP": t_rp, "tRAS": t_ras,
           "source": "0xfeda0000 (LGA1700), карта BIOS-diff 2 раунда"}
    f = vals.get(_OFF_TFAW)
    if f is not None and 4 <= (f & 0xFF) <= 64:
        out["tFAW"] = f & 0xFF
    r = vals.get(_OFF_TRFC1)
    if r is not None and 100 <= (r >> 16) <= 4000:
        out["tRFC"] = (r >> 16) & 0xFFFF
    t = vals.get(_OFF_TREFI)
    if t is not None and (t & 0xFFFF) >= 1000:
        out["tREFI"] = t & 0xFFFF
    return out


def read() -> dict | None:
    """Читает /proc/mchbar (нужен загруженный tools/mchbar) и декодирует."""
    try:
        with open(PROC) as f:
            text = f.read()
    except OSError:
        return None
    return decode(parse_dump(text))
