"""Представление результатов: человекочитаемая таблица и JSON."""
import json


def _line(label, value, w=26):
    print(f"  {label:<{w}} {value}")


def _fmt_ns(v):
    return f"{v:.3f} ns"


def render_text(dimms, show_hex=False):
    for i, (spd, dec) in enumerate(dimms):
        print(f"=== DIMM {i}: {spd.label} — {spd.kind} ({spd.type_name}) ===")
        if "error" in dec and len(dec) == 1:
            print(f"  ! {dec['error']}")
            continue

        _line("Тип модуля:", dec.get("module_type", "?") +
              f", SPD rev {dec.get('spd_revision', '?')}")
        if "module_manufacturer" in dec:
            v = dec["module_manufacturer"]
            if "dram_manufacturer" in dec:
                v += f"  (чипы: {dec['dram_manufacturer']})"
            _line("Производитель:", v)
        if "part_number" in dec:
            extra = ""
            if "serial" in dec:
                extra += f"  S/N {dec['serial']}"
            if "manufacturing_date" in dec:
                extra += f"  {dec['manufacturing_date']}"
            _line("Партномер:", dec["part_number"] + extra)
        if "size_mb" in dec:
            _line("Объём:", f"{dec['size_mb']} MB "
                  f"({dec.get('ranks', '?')} ранк., x{dec.get('device_width_bits', '?')}, "
                  f"{dec.get('bus_width_bits', '?')} бит"
                  + (", ECC" if dec.get("bus_width_extension") else "") + ")")

        print("  --- Частота и напряжение ---")
        if "speed_mts" in dec:
            _line("Макс. скорость (SPD):", f"{dec['speed_mts']} MT/s ({dec['pcn_rating']})")
        volts = dec.get("operable_voltages")
        if volts:
            _line("Напряжения (SPD):", ", ".join(volts))
        for key, lbl in (("vdd_nominal_v", "VDD (DDR4):"),
                         ("vddq_nominal_v", "VDDQ (DDR4):"),
                         ("vpp_nominal_v", "VPP (DDR4):")):
            if key in dec:
                _line(lbl, f"{dec[key]} V")

        print("  --- Тайминги JEDEC ---")
        if "timings_at_speeds" in dec and dec["timings_at_speeds"]:
            for speed in sorted(dec["timings_at_speeds"],
                                key=lambda s: int(s.split("-")[1]), reverse=True):
                _line(speed, dec["timings_at_speeds"][speed] + "  (CL-tRCD-tRP-tRAS)")
        elif "core_timings" in dec:
            _line("tCL-tRCD-tRP-tRAS:", dec["core_timings"])
        if "cas_supported" in dec:
            _line("CAS поддерживаемые:",
                  ", ".join(str(c) for c in dec["cas_supported"]))
        tn = dec.get("timings_ns", {})
        if tn:
            _line("tCK min:", _fmt_ns(tn["tCK"]))
            core = "  ".join(f"{k} {_fmt_ns(tn[k])}"
                             for k in ("tAA", "tRCD", "tRP", "tRAS") if k in tn)
            _line("Основные (ns):", core)
            rest = "  ".join(f"{k} {_fmt_ns(v)}" for k, v in tn.items()
                             if k not in ("tCK", "tAA", "tRCD", "tRP", "tRAS"))
            if rest:
                _line("Прочие (ns):", rest)

        xmp = dec.get("xmp")
        if xmp:
            print("  --- Intel XMP ---")
            hdr = xmp["header"]
            _line("Версия XMP:", f"{hdr['version']}, профилей: {len(xmp['profiles'])}")
            for p in xmp["profiles"]:
                _line(f"Профиль {p['profile']}:",
                      f"DDR3-{p['speed_mts']}  {p['timings']}  @ {p['voltage_v']} V")

        if "crc" in dec:
            c = dec["crc"]
            _line(f"CRC SPD (байты {c['cover']}):",
                  "OK" if c["ok"] else f"ОШИБКА (в SPD {c['stored']}, посчитан {c['calc']})")
        if show_hex:
            data = spd.data
            print("  --- Raw hex ---")
            for off in range(0, len(data), 16):
                row = " ".join(f"{x:02X}" for x in data[off:off + 16])
                print(f"  {off:04X}: {row}")
        print()


def render_json(dimms):
    out = []
    for spd, dec in dimms:
        out.append({
            "bus": spd.bus_nr,
            "bus_name": spd.bus_name,
            "address": f"0x{spd.addr:02X}",
            "kind": spd.kind,
            "type": spd.type_name,
            "decoded": dec,
        })
    print(json.dumps({"dimm_count": len(out), "dimms": out},
                     ensure_ascii=False, indent=2))


def _rule(title):
    line = f"─── {title} "
    print("\n" + line + "─" * max(0, 72 - len(line)))


def _frame(title, lines, inner):
    """Односторочный 'фрейм' из текста; для вывода рядом с другим."""
    out = ["┌─ " + title + " " + "─" * max(0, inner - len(title) - 1) + "┐"]
    out += ["│ " + l.ljust(inner) + " │" for l in lines]
    out.append("└" + "─" * (inner + 2) + "┘")
    return out


def _frames_side_by_side(left, right, gap=2):
    w = max(len(left), len(right))
    left = left + [""] * (w - len(left))
    right = right + [""] * (w - len(right))
    for a, b in zip(left, right):
        print(a + " " * gap + b)


def render_live(info, as_json=False):
    """Живой режим: структурированный отчёт по блокам."""
    if as_json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return
    devs = info.get("devices", [])
    d = info.get("dramc") or {}
    dt = info.get("dimm_temp") or {}
    mtps = d.get("mtps") or info.get("live_clock_mts")
    tck = 2000.0 / mtps if mtps else None
    ecc_mode = next((a.get("ecc") for a in info.get("arrays", [])
                     if a.get("ecc")), None)

    # ═══ шапка: общий конфиг ═══
    total = int(sum(x.get("size_mb") or 0 for x in devs)) // 1024
    parts = {x.get("part_number") for x in devs if x.get("part_number")}
    mfrs = {x.get("manufacturer") for x in devs if x.get("manufacturer")}
    db0 = devs[0].get("part_db") if devs else None
    kind = (db0 or {}).get("kind") or \
        ((devs[0].get("type") or "?") + " " + (devs[0].get("form_factor") or "")
         if devs else "?")
    volts = {x.get("voltage_configured_v")
             or (x.get("part_db") or {}).get("voltage_v") for x in devs}
    volts.discard(None)
    speeds_r = {x.get("speed_mts") for x in devs if x.get("speed_mts")}
    rated = next(iter(speeds_r)) if len(speeds_r) == 1 else None
    over = bool(rated and mtps and mtps > rated * 1.02)
    print("═" * 72)
    head = f"  ОЗУ: {total} GB"
    if devs:
        head += f"  ·  {len(devs)} × {int(devs[0].get('size_mb') or 0) // 1024} GB"
        if len(mfrs) == 1 and len(parts) == 1:
            head += (f"  ·  {next(iter(mfrs))} {next(iter(parts))}")
    print(head)
    mode = f"  {kind.strip()}"
    spd_hdr = rated or mtps
    if spd_hdr:
        mode += f" · {spd_hdr:g} MT/s" + (" (штатно)" if over else "")
    if len(volts) == 1:
        mode += f" · {next(iter(volts))} V"
    if ecc_mode:
        mode += f" · ECC: {ecc_mode}"
    print(mode)
    print("═" * 72)

    # ─── контроллер и режим ───
    if d or mtps:
        _rule("КОНТРОЛЛЕР И РЕЖИМ")
        if mtps:
            src = "замер perf uncore IMC" if info.get("live_clock_mts") else "регистры"
            _line("Частота:", f"{mtps:g} MT/s"
                  + (f" (tCK {tck:.4f} нс)" if tck else "") + f"  [{src}]")
        if over:
            _line("Профиль:", f"⚡ разгон: +{(mtps / rated - 1) * 100:.0f}% "
                              f"к штатным {rated:g} MT/s")
        if d:
            _line("Множитель:", f"{d['ratio']} × BCLK {d['bclk_mhz']} МГц")
            _line("Тайминги:", f"{d['tCL']}-{d['tRCD']}-{d['tRP']}-{d['tRAS']} "
                               f"(CL-tRCD-tRP-tRAS)")
            _line("", f"tRC {d.get('tRC', '?')} · tRFC {d.get('tRFC', '?')}"
                  + (f" ({d['tRFC'] * tck:.0f} нс)"
                     if d.get("tRFC") and tck else ""))
            sub = []
            for key, lbl in (("tWR", "tWR"), ("tFAW", "tFAW"), ("tCWL", "tCWL"),
                             ("tRRD_tWTR_tRTP", "tRRD/tWTR/tRTP"),
                             ("tMOD", "tMOD")):
                if d.get(key):
                    sub.append(f"{lbl} {d[key]}")
            if d.get("tREFI"):
                sub.append(f"tREFI {d['tREFI']}"
                           + (f" (~{d['tREFI'] * tck / 1000:.2f} мкс)" if tck else ""))
            if sub:
                _line("Подтайминги:", " · ".join(sub))
            _line("Источник:", f"регистры DRAMC {d['source']} (только чтение)")

    # ─── температура + пропускная способность (фреймы рядом) ───
    valid = [t for t in dt.get("dimm_temps", []) if t.get("connected")]
    dead = [t for t in dt.get("dimm_temps", []) if not t.get("connected")]
    bw = info.get("bandwidth")
    bw_k = bw.get("kernels") if bw else None

    tl = None
    if valid:
        tl = []
        for t in sorted(valid, key=lambda t: t["label"]):
            n = max(1, min(12, round((t["c"] - 25) / 65 * 12)))
            tl.append(f"{t['label']:<9} {t['c']:>3.0f} °C  "
                      + "█" * n + "░" * (12 - n))
        cs = [t["c"] for t in valid]
        hi = max(valid, key=lambda t: t["c"])
        tl.append("─" * 30)
        tl.append(f"сред {sum(cs) / len(cs):.0f}° · макс {hi['c']:.0f}° "
                  f"{hi['label']}")
        tl.append("предел 85 °C")
    bl = None
    if bw_k:
        theo = bw.get("theoretical_gbs")
        bl = [f"{bw['threads']} потоков · массив {bw['size_mib']} MiB×3"]
        for name in ("Read", "Write", "Copy", "Scale", "Add", "Triad"):
            k = bw_k.get(name)
            if not k:
                continue
            pct = k["best"] / theo * 100 if theo else 0
            n = max(0, min(8, round(pct / 100 * 8)))
            bl.append(f"{name:<6} {k['best']:>5.1f} GB/s "
                      + "█" * n + "░" * (8 - n) + f" {pct:>2.0f}%")
        if theo:
            bl.append("─" * 34)
            bl.append(f"теор. пик {theo:g} GB/s")
    if not tl:
        if dead:
            pkg = dt.get("cpu_package_c")
            print("\n  Сенсор найден (" + dead[0]["chip"] + "), но BIOS не "
                  "выводит данные"
                  + (f"; CPU (с IMC): {pkg:.0f}°C" if pkg else ""))
        elif dt.get("cpu_package_c"):
            print(f"\n  TSOD/PECI недоступны ОС; косвенно — CPU с IMC: "
                  f"{dt['cpu_package_c']:.0f}°C")
    if tl or bl:
        print()
        if tl and bl:
            w = max(len(tl), len(bl))
            tl += [""] * (w - len(tl))
            bl += [""] * (w - len(bl))
            _frames_side_by_side(_frame("ТЕМПЕРАТУРА МОДУЛЕЙ", tl, 30),
                                 _frame("ПРОПУСКНАЯ СПОСОБНОСТЬ", bl, 34))
        elif tl:
            for ln in _frame("ТЕМПЕРАТУРА МОДУЛЕЙ", tl, 30):
                print(ln)
        else:
            for ln in _frame("ПРОПУСКНАЯ СПОСОБНОСТЬ", bl, 34):
                print(ln)

    # ─── ECC и надёжность ───
    e = info.get("ecc")
    if e:
        _rule("ECC И НАДЁЖНОСТЬ")
        if ecc_mode:
            _line("Режим:", ecc_mode)
        if e.get("delta_24h"):
            dl = e["delta_24h"]
            win = (f"{dl['window_h'] * 60:.0f} мин" if dl["window_h"] < 1
                   else f"{dl['window_h']:.0f} ч")
            _line(f"Ошибки за {win}:", f"CE {dl['ce']} · UE {dl['ue']}")
        up = e.get("uptime_h")
        _line("С загрузки" + (f" ({up:.0f} ч)" if up else "") + ":",
              f"CE {e['ce_total']} · UE {e['ue_total']}")
        bad = e.get("bad_dimms") or {}
        if bad:
            _line("Подозрительные:", ", ".join(
                f"{k}: CE{v['ce']}/UE{v['ue']}" for k, v in bad.items()))
        j = e.get("journal")
        if j:
            parts_j = []
            if j["mce"]:
                parts_j.append(f"MCE {j['mce']}")
            if j["edac"]:
                parts_j.append(f"EDAC {j['edac']}")
            if j["aer_corr"] or j["aer_uncorr"]:
                parts_j.append(f"PCIe AER корр {j['aer_corr']} / некорр "
                               f"{j['aer_uncorr']} — шина NVMe/GPU, не память")
            if parts_j:
                _line("Журнал (24 ч):", "; ".join(parts_j))
        if not e["ce_total"] and not e["ue_total"] and not bad:
            _line("Вердикт:", "✅ ни одной ошибки ECC")
        elif e["ue_total"]:
            _line("Вердикт:", f"⚠ {e['ue_total']} неисправимых ошибок — "
                              f"проверьте модули!")

    # ─── модули ───
    if devs:
        _rule("МОДУЛИ")
        same = len(parts) <= 1
        if same and db0 and db0.get("note"):
            print(f"  Все модули одинаковые: {db0['note']}")
        hdr = (f"  {'Локатор':<9} {'Объём':<6} {'Ранги':<5} "
               f"{'Работает':<9} {'Заявлено':<9} ")
        hdr += "S/N" if same else f"{'Партномер':<22} S/N"
        print(hdr)
        for x in devs:
            size = f"{int(x.get('size_mb') or 0) // 1024} GB"
            cfg = (f"{x['configured_speed_mts']:.0f} MT/s"
                   if x.get("configured_speed_mts") else "?")
            sp = f"{x['speed_mts']:.0f} MT/s" if x.get("speed_mts") else "?"
            rk = f"{x['ranks']}R" if x.get("ranks") else "?"
            row = (f"  {(x.get('locator') or '?'):<9} {size:<6} {rk:<5} "
                   f"{cfg:<9} {sp:<9} ")
            row += (x.get("serial") or "-") if same else \
                f"{(x.get('part_number') or '-'):<22} {x.get('serial') or '-'}"
            print(row)

    print("\n  Источники: SMBIOS/DMI · регистры DRAMC и Thermal Control "
          "(PCI 0xff,")
    print("  только чтение) · EDAC sysfs · journalctl · perf uncore IMC. "
          "SPD EEPROM")
    print("  ОС недоступны (SMLink/ME) — как всё это читается: "
          "docs/AGENT-HOWTO-READ-TIMINGS.md")
