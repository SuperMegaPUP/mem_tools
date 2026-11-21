// SPDX-License-Identifier: GPL-2.0
/*
 * mchbar.c — дамп окна MCHBAR (Memory Controller Hub BAR) через
 * /proc/mchbar. На потребительских Intel (LGA1700 и др.) регистры
 * контроллера памяти видны только там; /dev/mem перекрыт
 * IO_STRICT_DEVMEM. Только чтение.
 *
 * Сборка:  make -C /lib/modules/$(uname -r)/build M=$PWD modules
 * Использование: sudo insmod mchbar.ko && cat /proc/mchbar > dump.txt
 *                sudo rmmod mchbar
 */
#include <linux/init.h>
#include <linux/io.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>

#define WIN 0x40000  /* реальное пространство DRAMC на LGA1700 — 256 КБ */
#define NDWORD (WIN / 4)

static u64 base_override;
module_param(base_override, ullong, 0444);
MODULE_PARM_DESC(base_override, "физический адрес окна (0 = из конфига 0x40)");

static void __iomem *regs;
static struct proc_dir_entry *pde;

static void *m_start(struct seq_file *s, loff_t *pos)
{
	return *pos < NDWORD ? pos : NULL;
}

static void *m_next(struct seq_file *s, void *v, loff_t *pos)
{
	++*pos;
	return m_start(s, pos);
}

static void m_stop(struct seq_file *s, void *v)
{
}

static int m_show(struct seq_file *s, void *v)
{
	loff_t idx = *(loff_t *)v;

	seq_printf(s, "%05x: %08x\n", (u32)(idx * 4),
		   readl(regs + idx * 4));
	return 0;
}

static const struct seq_operations m_ops = {
	.start = m_start, .next = m_next, .stop = m_stop, .show = m_show,
};

static int m_open(struct inode *inode, struct file *file)
{
	return seq_open(file, &m_ops);
}

static const struct proc_ops m_pops = {
	.proc_open = m_open,
	.proc_read = seq_read,
	.proc_lseek = seq_lseek,
	.proc_release = seq_release,
};

static int __init mchbar_init(void)
{
	struct pci_dev *pdev;
	u32 lo, hi;
	phys_addr_t base;

	pdev = pci_get_domain_bus_and_slot(0, 0, PCI_DEVFN(0, 0));
	if (!pdev)
		return -ENODEV;
	if (base_override) {
		base = (phys_addr_t)base_override;
	} else {
		pci_read_config_dword(pdev, 0x40, &lo);
		pci_read_config_dword(pdev, 0x44, &hi);
		if (!(lo & 1)) {
			pr_err("mchbar: окно не включено в BIOS\n");
			return -ENXIO;
		}
		base = ((phys_addr_t)hi << 32) | (lo & 0xfffff000);
	}
	regs = ioremap(base, WIN);
	if (!regs)
		return -EIO;
	pde = proc_create("mchbar", 0444, NULL, &m_pops);
	pr_info("mchbar: base 0x%llx window 0x%x (только чтение)\n",
		(u64)base, WIN);
	return 0;
}

static void __exit mchbar_exit(void)
{
	remove_proc_entry("mchbar", NULL);
	iounmap(regs);
}

module_init(mchbar_init);
module_exit(mchbar_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("MCHBAR read-only dump via /proc/mchbar");
