/*
 * smnpeek — чтение SMN (System Management Network) на AMD Zen через
 * северный мост: PCI 00:00.0, конфиг-регистр 0x60 = индекс SMN-адреса,
 * 0x64 = данные. Так же работает официальный драйвер ryzen_smu.
 *
 * РЕЖИМ ТОЛЬКО ЧТЕНИЕ. Через SMN живёт SMU (управляющий контроллер
 * памяти) — ошибки обращения могут подвесить шину, поэтому сначала
 * читаем заведомо безопасные адреса.
 *
 * Сборка:  cc -O2 -o smnpeek smnpeek.c
 * Запуск:  sudo ./smnpeek 0x05a30000 [кол-во_двойных_слов]
 */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#define SMN_INDEX 0x60
#define SMN_DATA  0x64

static int cfg = -1;

static int smn_open(void)
{
    cfg = open("/sys/bus/pci/devices/0000:00:00.0/config", O_RDWR);
    if (cfg < 0) {
        perror("open cfg (root?)");
        return -1;
    }
    return 0;
}

static uint32_t smn_read(uint32_t addr)
{
    uint32_t idx = addr, val = 0xffffffffu;
    if (pwrite(cfg, &idx, 4, SMN_INDEX) != 4 ||
        pread(cfg, &val, 4, SMN_DATA) != 4) {
        perror("smn xfer");
        exit(2);
    }
    return val;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <hex_addr> [count(dwords)]\n", argv[0]);
        return 1;
    }
    if (smn_open())
        return 1;
    uint32_t addr = (uint32_t)strtoul(argv[1], NULL, 0);
    int n = argc > 2 ? atoi(argv[2]) : 1;
    if (n < 1)
        n = 1;
    if (n > 256)
        n = 256;
    for (int i = 0; i < n; i++) {
        uint32_t v = smn_read(addr + i * 4u);
        printf("%08x: %08x\n", addr + i * 4u, v);
        fflush(stdout);
    }
    return 0;
}
