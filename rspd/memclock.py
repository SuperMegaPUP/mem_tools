"""Живое измерение частоты памяти счётчиками производительности IMC.

uncore_imc/clockticks считает тики с удвоенной частотой шины DRAM
(4× такту памяти для HSW/BDW-EP: 3733 МГц тиков = DDR3-1866).
Требуется root и perf.
"""
import re
import subprocess


def measure_memclock(seconds=2):
    env = {"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    r = subprocess.run(
        ["perf", "stat", "-a", "-e", "uncore_imc/clockticks/",
         "sleep", str(seconds)],
        capture_output=True, text=True, env=env,
    )
    txt = r.stderr.replace("\u202f", "")  # узкий неразрывный пробел в group-сепараторах
    m_cnt = re.search(r"([\d., ]+?)\s+uncore_imc/clockticks/", txt)
    m_t = re.search(r"([\d.,]+)\s+seconds time elapsed", txt)
    if not (m_cnt and m_t):
        return None
    ticks = float(m_cnt.group(1).replace(" ", "").replace(",", "."))
    elapsed = float(m_t.group(1).replace(",", "."))
    if elapsed <= 0:
        return None
    ticks_per_s = ticks / elapsed
    # На HSW/BDW-EP счётчик тикает на 4× такта DRAM = 2× скоростях передачи:
    # 3733.3 МГц тиков = 933.3 МГц такт = DDR-1866 MT/s. Проверено на E5 v4.
    return round(ticks_per_s / 1e6 / 2.0, 1)  # MT/s
