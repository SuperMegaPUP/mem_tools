#!/usr/bin/env python3
"""ramspd — чтение SPD EEPROM модулей RAM напрямую через SMBus/I2C.

Показывает для каждого DIMM: тип, объём, производителя, партномер,
максимальную частоту (MT/s), тайминги JEDEC (ns и в тактах на стандартных
скоростях), напряжения и профили Intel XMP (DDR3).

Требования: Linux, Python 3.8+, доступ на чтение к /dev/i2c-N
(см. setup_permissions.sh). Без сторонних зависимостей.

Примеры:
  sudo ./setup_permissions.sh          # однократно
  python3 ramspd.py                    # все DIMM, человекочитаемо
  python3 ramspd.py --json             # машинночитаемо
  python3 ramspd.py --bus 0 --hex      # шина 0 + hex-дамп SPD
  python3 ramspd.py --from-file spd.bin
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rspd import ddr3, ddr4  # noqa: E402
from rspd.report import render_json, render_live, render_text  # noqa: E402
from rspd.spd import Spd, probe_dimms, scan_all  # noqa: E402
from rspd.transport import SmbusError  # noqa: E402


def collect_live():
    from rspd import dimmtemp, dmi, ecc, epmc, memclock
    info = dmi.parse_dmi()
    try:
        info["live_clock_mts"] = memclock.measure_memclock()
    except (FileNotFoundError, PermissionError, OSError):
        info["live_clock_mts"] = None
    try:
        info["dramc"] = epmc.read_dramc()
    except OSError:
        info["dramc"] = None
    try:
        info["ecc"] = ecc.collect()
    except OSError:
        info["ecc"] = None
    try:
        info["dimm_temp"] = dimmtemp.collect()
    except OSError:
        info["dimm_temp"] = None
    for dev in info["devices"]:
        db = dmi.lookup_part(dev.get("part_number"))
        if db:
            dev["part_db"] = db
    return info


def decode_spd(spd):
    if spd.kind == "DDR3":
        return ddr3.decode(spd.data)
    if spd.kind == "DDR4":
        return ddr4.decode(spd.data)
    return {"error": f"декодер для {spd.kind} не реализован "
                     f"(тип распознан, данные прочитаны: {len(spd.data)} байт)"}


def load_hexdump(path):
    """Читает hexdump-совместимый дамп (форматы hexdump -C / decode-dimms)."""
    data = bytearray()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.match(r"^\s*([0-9a-fA-F]{4,8}):?\s+((?:[0-9a-fA-F]{2}\s*)+)", line)
            if not m:
                continue
            off = int(m.group(1), 16)
            vals = [int(x, 16) for x in m.group(2).split()]
            for i, v in enumerate(vals):
                if off + i >= len(data):
                    data.extend(b"\x00" * (off + i - len(data) + 1))
                data[off + i] = v
    return bytes(data)


def load_file(path):
    raw = open(path, "rb").read()
    if len(raw) >= 3 and all(c in b"0123456789abcdefABCDEF \n\r\t:xX*" for c in raw[:200]):
        # похоже на текстовый hexdump
        txt = load_hexdump(path)
        if len(txt) >= 128:
            raw = txt
    if len(raw) < 64:
        sys.exit(f"{path}: слишком короткий файл ({len(raw)} байт)")
    b2 = raw[2] if len(raw) > 2 else 0
    b1 = raw[1] if len(raw) > 1 else 0
    kind = {0x0B: "DDR3", 0x0F: "DDR3", 0x0C: "DDR4", 0x0E: "DDR4",
            0x10: "DDR4", 0x11: "DDR4", 0x12: "DDR5", 0x13: "DDR5",
            0x08: "DDR2"}.get(b2)
    if kind is None and b1 == 0x12:
        kind = "DDR5"
    return Spd(-1, os.path.basename(path), 0, kind or f"Unknown(0x{b2:02x})", raw)


def main():
    ap = argparse.ArgumentParser(
        description="Чтение SPD EEPROM модулей RAM через SMBus: "
                    "частота, тайминги, напряжение, XMP.")
    ap.add_argument("--bus", type=int, help="только шина /dev/i2c-N")
    ap.add_argument("--addr", help="адреса DIMM, напр. 0x50 или 0x50-0x53")
    ap.add_argument("--json", action="store_true", help="вывод в JSON")
    ap.add_argument("--hex", action="store_true", help="hex-дамп SPD (текст-режим)")
    ap.add_argument("--dump-dir", metavar="DIR",
                    help="сохранить сырые SPD в бинарники <dir>/dimm-<bus>-<addr>.bin")
    ap.add_argument("--from-file", metavar="FILE",
                    help="декодировать из файла (.bin или hexdump), шина не нужна")
    ap.add_argument("--live", action="store_true",
                    help="DMI + измерение частоты счётчиками IMC (когда SPD недоступны)")
    ap.add_argument("--no-live", action="store_true",
                    help="не переключаться в live-режим автоматически")
    ap.add_argument("--bw", action="store_true",
                    help="тест пропускной способности DRAM (STREAM-подобный, "
                         "несколько секунд, нагрузка на память)")
    ap.add_argument("--bw-threads", type=int, metavar="N",
                    help="потоки для --bw (по умолчанию = физ. ядра)")
    args = ap.parse_args()

    if args.live or args.bw:
        info = collect_live()
        if args.bw:
            from rspd import membw
            try:
                info["bandwidth"] = membw.run(threads=args.bw_threads)
                info["bandwidth"]["theoretical_gbs"] = membw.theoretical_gbs(
                    (info.get("dramc") or {}).get("mtps")
                    or max((d.get("configured_speed_mts") or 0
                            for d in info.get("devices", [])), default=0) or None,
                    membw.count_channels(info.get("devices", [])))
            except (RuntimeError, OSError) as e:
                info["bandwidth"] = {"error": str(e)}
        render_live(info, as_json=args.json)
        return

    addrs = range(0x50, 0x58)
    if args.addr:
        if "-" in args.addr:
            lo, hi = args.addr.split("-")
            addrs = range(int(lo, 0), int(hi, 0) + 1)
        else:
            addrs = [int(args.addr, 0)]

    if args.from_file:
        spd = load_file(args.from_file)
        dimms = [(spd, decode_spd(spd))]
    else:
        try:
            if args.bus is not None:
                dimms = [(s, decode_spd(s)) for s in probe_dimms(args.bus)]
            else:
                found, buses = scan_all(addrs)
                dimms = [(s, decode_spd(s)) for s in found]
                if not dimms and not args.json and not args.no_live:
                    print("DIMM на SMBus не найдено (шины:",
                          ", ".join(f"{n} ({nm})" for n, nm in buses) or "нет", ")")
                    print("На серверных платах SPD часто подключены к SMLink/ME,")
                    print("невидимому из ОС. Переключаюсь в live-режим "
                          "(DMI + частота по счётчикам IMC)...\n")
                    info = collect_live()
                    render_live(info, as_json=False)
                    return
        except PermissionError:
            sys.exit("Нет доступа к /dev/i2c-*: добавьте себя в группу i2c "
                     "(./setup_permissions.sh от root + перелогин) "
                     "или запустите через sudo.")
        except SmbusError as e:
            sys.exit(f"Ошибка i2c: {e}")

        if args.dump_dir:
            os.makedirs(args.dump_dir, exist_ok=True)
            for spd, _ in dimms:
                p = os.path.join(args.dump_dir, f"dimm-{spd.bus_nr}-0x{spd.addr:02x}.bin")
                with open(p, "wb") as f:
                    f.write(spd.data)
                print(f"Сохранён дамп: {p}", file=sys.stderr)

    if args.json:
        render_json(dimms)
    else:
        if not dimms:
            print("DIMM не найдено.")
            sys.exit(1)
        render_text(dimms, show_hex=args.hex)


if __name__ == "__main__":
    main()
