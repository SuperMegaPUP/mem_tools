// SPDX-License-Identifier: GPL-2.0
// Дамп 4K ECAM-конфига всех устройств шины 0xff (Xeon EP uncore) + MSR 0xF0 (MCHBAR).
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/io.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/acpi.h>
#include <linux/unaligned.h>
#include <asm/msr.h>

#define ECAM_BUS_SIZE 0x100000UL   /* 1 MB на шину */
static u64 ecam_base;

static int __init ecamdump_init(void)
{
	struct acpi_table_header *hdr;
	void __iomem *bus;
	char path[] = "/tmp/ecam_ff.bin";
	struct file *f;
	loff_t pos = 0;
	int busn, dev, fn, rc = 0;
	u32 msr_lo = 0, msr_hi = 0;
	static u8 buf[4096];

	if (ACPI_FAILURE(acpi_get_table(ACPI_SIG_MCFG, 0, &hdr))) {
		pr_err("ecamdump: no MCFG\n");
		return -ENODEV;
	}
	/* struct acpi_table_mcfg в заголовках ядра не содержит массив entries;
	 * первая запись идёт сразу за 44-байтовым заголовком. */
	ecam_base = get_unaligned_le64((u8 *)hdr + 44);
	pr_info("ecamdump: MCFG base 0x%llx\n", ecam_base);
	acpi_put_table(hdr);

	f = filp_open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (IS_ERR(f))
		return PTR_ERR(f);

	for (busn = 0xf8; busn <= 0xff; busn++) {
		bus = ioremap(ecam_base + ((u64)busn << 20), ECAM_BUS_SIZE);
		if (!bus) { rc = -ENOMEM; goto out; }
		for (dev = 0; dev < 32; dev++) {
			for (fn = 0; fn < 8; fn++) {
				void __iomem *cfg = bus + (dev << 15) + (fn << 12);
				u32 hdr32[4];
				if (readl(cfg) == 0xffffffffu)
					continue;
				memcpy_fromio(buf, cfg, 4096);
				hdr32[0] = busn; hdr32[1] = dev; hdr32[2] = fn; hdr32[3] = 0xfeed;
				kernel_write(f, (char *)hdr32, 16, &pos);
				kernel_write(f, buf, 4096, &pos);
			}
		}
		iounmap(bus);
	}
out:
	filp_close(f, NULL);
	if (rdmsr_safe(0xf0, &msr_lo, &msr_hi) == 0)
		pr_info("ecamdump: MSR_F0_MCHBAR = %08x%08x\n", msr_hi, msr_lo);
	else
		pr_info("ecamdump: MSR_F0 read failed\n");
	pr_info("ecamdump: done rc=%d\n", rc);
	return rc;
}

static void __exit ecamdump_exit(void) { pr_info("ecamdump: bye\n"); }

module_init(ecamdump_init);
module_exit(ecamdump_exit);
MODULE_LICENSE("GPL");
