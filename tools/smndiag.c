/*
 * smndiag — диагностика SMN-доступа (AMD Zen): проверять по шагам,
 * жив ли индекс/дата-регистр PCI 00:00.0:0x60/0x64 и какие адреса
 * SMN отвечают. ТОЛЬКО ЧТЕНИЕ (запись только в индекс-регистр).
 */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#define SMN_INDEX 0x60
#define SMN_DATA  0x64

static int cfg = -1;

static uint32_t cfg_r(int off)
{
    uint32_t v = 0xdeadbeefu;
    if (pread(cfg, &v, 4, off) != 4) {
        perror("cfg read");
        exit(2);
    }
    return v;
}

static void cfg_w(int off, uint32_t v)
{
    if (pwrite(cfg, &v, 4, off) != 4) {
        perror("cfg write");
        exit(2);
    }
}

static uint32_t smn_r(uint32_t addr)
{
    cfg_w(SMN_INDEX, addr);
    return cfg_r(SMN_DATA);
}

int main(void)
{
    cfg = open("/sys/bus/pci/devices/0000:00:00.0/config", O_RDWR);
    if (cfg < 0) {
        perror("open cfg (root?)");
        return 1;
    }
    /* 1. индекс-регистр: пишем паттерн, читаем обратно */
    cfg_w(SMN_INDEX, 0x12345678u);
    printf("[1] индекс 0x60: записано 12345678, прочитано %08x %s\n",
           cfg_r(SMN_INDEX), cfg_r(SMN_INDEX) == 0x12345678u ? "OK" : "МЁРТВ?");
    /* 2. дата при заведомо мусорном индексе */
    printf("[2] data при индексе 12345678: %08x\n", cfg_r(SMN_DATA));
    /* 3. самотест: SMN 0x60 должен быть зеркалом того же индекса */
    printf("[3] SMN 0x60 (самозеркало): %08x (ожидаем 12345678)\n",
           smn_r(0x60u));
    /* 4. кандидаты баз SMU + соседние регионы */
    const uint32_t probe[] = {
        0x00000000u, 0x00001000u, 0x05980000u, 0x05990000u,
        0x05a30000u, 0x05a40000u, 0x05a30060u, 0x05980060u,
    };
    for (unsigned i = 0; i < sizeof(probe) / sizeof(probe[0]); i++)
        printf("[4] SMN %08x: %08x\n", probe[i], smn_r(probe[i]));
    /* 5. текущее состояние индекса/даты */
    printf("[5] итог: 0x60=%08x 0x64=%08x\n", cfg_r(SMN_INDEX), cfg_r(SMN_DATA));
    return 0;
}
