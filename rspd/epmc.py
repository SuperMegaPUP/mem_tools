"""Чтение живых таймингов DRAMC с Intel Xeon EP (Haswell-EP/Broadwell-EP,
напр. X99 + E5 v3/v4) напрямую из конфигурационного пространства uncore
(шина PCI 0xff, ECAM). SPD EEPROM на этих платах к i801 SMBus не подключён,
зато контроллер памяти отдаёт актуальные настройки из своих регистров.

Проверено на Huananzhi X99-T8 V6.0 / Xeon E5-2696 v4 / 8×DDR3L-1866:
  ff:13.0 (8086:6fa8, MC0 global; зеркало MC1 = ff:16.0/6f68)
    +0x104[4:0]    tRAS
    +0x108[15:12]  множитель DRAM (× BCLK 133.33 МГц)
  ff:13.1 (8086:6f71, MC0 timing; зеркало MC1 = ff:16.1/6f79)
    +0x180[7:0]/[15:8]/[23:16]  tCL/tRCD/tRP (кодировка: значение − 6)

Регистры найдены эмпирически: значения идентичны на зеркалах MC0/MC1,
совпадают с профилем JEDEC DDR3-1866 (13-13-13-31) и с независимым
измерением частоты через perf uncore_imc clockticks.
"""
from __future__ import annotations

import os

SYSFS = "/sys/bus/pci/devices/0000:ff:{slot}/config"

# (основной слот, зеркало) — CF8-нумерация sysfs
MC_GLOBAL = ("13.0", "16.0")   # 6fa8 / 6f68
MC_TIMING = ("13.1", "16.1")   # 6f71 / 6f79

BCLK = 133.333  # базовая тактовая частота EP (МГц)

# Thermal Control-блоки (pci.ids: "Memory Controller N - Channel M Thermal
# Control"). Температура найдена холод/горячим диффом ECAM (idle 43-49°C ->
# стресс 75°C) и подтверждена обратимостью при остывании.
#   ff:14.0 (6fb0, MC0 Ch0 = канал A)   ff:14.1 (6fb1, MC0 Ch1 = канал B)
#   ff:17.0 (6fd0, MC1 Ch0 = канал C)   ff:17.1 (6fd1, MC1 Ch1 = канал D)
#   +0x150[7:0] / +0x154[7:0] — температура DIMM0/DIMM1 канала, °C.
# Нумерация каналов A..D и слотов 1/2 внутри канала — разумное допущение
# (MC0 = ближние каналы); значения при этом настоящие, из кремния.
MC_THERMAL = (("14.0", "A"), ("14.1", "B"), ("17.0", "C"), ("17.1", "D"))


def _read_cfg(slot: str, length: int = 0x400) -> bytes | None:
    path = SYSFS.format(slot=slot)
    try:
        with open(path, "rb", 0) as f:
            data = f.read(length)
    except OSError:
        return None
    if len(data) < 0x110:
        return None
    return data


def _read_any(slots, length=0x400):
    for s in slots:
        d = _read_cfg(s, length)
        if d is not None:
            ven, dev = int.from_bytes(d[0:2], "little"), int.from_bytes(d[2:4], "little")
            if ven == 0x8086:
                return s, d
    return None, None


def ep_supported() -> bool:
    _, g = _read_any(MC_GLOBAL)
    _, t = _read_any(MC_TIMING)
    return g is not None and t is not None


def read_dimm_temps() -> list[dict]:
    """Температура каждого DIMM из Thermal Control-регистров MC (Xeon EP).

    [{"label": "DIMM_A1", "c": 45.0, "chip": "epmc", "connected": True}, ...]
    в порядке каналы A..D, внутри слоты 1,2. Пустой список — не EP или нет
    прав (sysfs отдаёт >64 байт конфига только root). Нулевые значения
    (незаполненные каналы) отбрасываются."""
    out = []
    for slot, ch in MC_THERMAL:
        d = _read_cfg(slot, 0x160)
        if d is None or len(d) < 0x158:
            continue
        if int.from_bytes(d[0:2], "little") != 0x8086:
            continue
        for i, off in ((1, 0x150), (2, 0x154)):
            t = d[off]
            if 0 < t < 125:
                out.append({"label": f"DIMM_{ch}{i}", "c": float(t),
                            "chip": "epmc", "connected": True})
    return out


def read_dramc() -> dict | None:
    """Живые настройки DRAM из регистров контроллера. None — если не EP."""
    gs, g = _read_any(MC_GLOBAL)
    ts, t = _read_any(MC_TIMING)
    if g is None or t is None:
        return None
    u = lambda d, o: int.from_bytes(d[o:o + 4], "little")
    ras_reg = u(g, 0x104)
    ratio_reg = u(g, 0x108)
    cl_reg = u(t, 0x180)
    ratio = (ratio_reg >> 12) & 0xF
    if ratio == 0 or ratio > 31:
        return None
    cl = (cl_reg & 0xFF) + 6
    rcd = ((cl_reg >> 8) & 0xFF) + 6
    rp = ((cl_reg >> 16) & 0xFF) + 6
    tras = ras_reg & 0x1F
    trfc = (u(g, 0x11C) >> 16) & 0xFF
    if not (5 <= cl <= 31 and 5 <= rcd <= 31 and 5 <= rp <= 31):
        return None
    # подтайминги: значения в тактах; кодировка — обычные поля регистров.
    # Каждый кандидат прошёл проверку зеркалом MC0/MC1 и совпал с
    # JEDEC-значением для DDR3-1866 (tCK=1.0714нс). tCWL=10 — стандартная
    # пара CL13@1866 (альтернативное чтение того же поля: tMRD=10).
    twr = (ras_reg >> 12) & 0xF
    tfaw = (u(g, 0x108) >> 16) & 0xFF
    trefi_x32 = u(t, 0x274) & 0xFF
    tcwl = (u(g, 0x11C) >> 16) & 0xF
    trrd = (u(g, 0x190) >> 24) & 0xFF
    tmod = (u(g, 0x10C) >> 20) & 0xF
    return {
        "tCL": cl,
        "tRCD": rcd,
        "tRP": rp,
        "tRAS": tras,
        "tRC": tras + rp,
        "tRFC": trfc if 50 <= trfc <= 400 else None,
        "tWR": twr if 5 <= twr <= 31 else None,
        "tFAW": tfaw if 4 <= tfaw <= 63 else None,
        "tCWL": tcwl if 4 <= tcwl <= 16 else None,
        "tRRD_tWTR_tRTP": trrd if 3 <= trrd <= 16 else None,
        "tREFI": trefi_x32 * 32 if 64 <= trefi_x32 <= 255 else None,
        "tMOD": tmod if 4 <= tmod <= 31 else None,
        "ratio": ratio,
        "bclk_mhz": round(BCLK, 3),
        "mtps": round(ratio * BCLK, 1),  # MT/s = множитель × BCLK напрямую
        "source": f"ff:{gs}+ff:{ts}",
    }
