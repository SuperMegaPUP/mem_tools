/*
 * smupeek — SMU mailbox через PCI-порт AMD: конфиг-регистры
 * dev 00:00.2, индекс 0x60, данные 0x440 (тот же механизм, что у
 * десктопных SMU-утилит). Режимы:
 *   smupeek dump                 — нетривиальные байты конфига 00:00.2
 *   smupeek r <hex_smn_addr> [n] — n даблслов по адресам SMU/SMN
 * Только чтение (индексный регистр — write-only порт).
 */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define DEVPATH "/sys/bus/pci/devices/0000:00:00.2/config"
#define IDX 0x60
#define DAT 0x440

static int cfg;

static uint32_t rd(int off)
{
    uint32_t v = 0xdeadbeefu;
    if (pread(cfg, &v, 4, off) != 4) {
        perror("pread");
        exit(2);
    }
    return v;
}

static void wr(int off, uint32_t v)
{
    if (pwrite(cfg, &v, 4, off) != 4) {
        perror("pwrite");
        exit(2);
    }
}

static uint32_t smu_r(uint32_t addr)
{
    wr(IDX, addr);
    return rd(DAT);
}

int main(int argc, char **argv)
{
    cfg = open(DEVPATH, O_RDWR);
    if (cfg < 0) {
        perror("open " DEVPATH " (root?)");
        return 1;
    }
    if (argc > 1 && !strcmp(argv[1], "dump")) {
        uint8_t b[4096];
        if (pread(cfg, b, sizeof b, 0) < 64) {
            perror("cfg dump");
            return 2;
        }
        printf("vendor/device: %02x%02x:%02x%02x\n", b[1], b[0], b[3], b[2]);
        for (int off = 0; off < 4096; off += 16) {
            int quiet = 1;
            for (int i = 0; i < 16; i++)
                if (b[off + i])
                    quiet = 0;
            if (quiet && off >= 64)
                continue;
            printf("%04x:", off);
            for (int i = 0; i < 16; i++)
                printf(" %02x", b[off + i]);
            printf("\n");
        }
        return 0;
    }
    if (argc > 2 && !strcmp(argv[1], "r")) {
        uint32_t addr = (uint32_t)strtoul(argv[2], NULL, 0);
        int n = argc > 3 ? atoi(argv[3]) : 1;
        if (n < 1)
            n = 1;
        if (n > 64)
            n = 64;
        for (int i = 0; i < n; i++)
            printf("%08x: %08x\n", addr + i * 4u, smu_r(addr + i * 4u));
        return 0;
    }
    fprintf(stderr, "usage: %s dump | r <addr> [n]\n", argv[0]);
    return 1;
}
