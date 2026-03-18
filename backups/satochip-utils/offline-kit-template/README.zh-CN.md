# Tails 离线工具包模板

这个目录放的是一个建议模板，用来帮助你以后重新整理 `Tails OS` 下的 `Satochip-Utils` 离线工具包。

它不是源码本体，也不包含真正的 Linux 可执行文件和 `.deb` 包。

你需要把下面这些文件和本目录里的脚本放在同一个文件夹里：

- `Satochip-Utils-linux-x86_64-0.3.0-beta`
- `libpcsclite1_2.3.3-1_amd64.deb`
- `libccid_1.6.2-1_amd64.deb`
- `pcscd_2.3.3-1_amd64.deb`

建议目录结构：

```text
tails智能卡设置/
├── Satochip-Utils-linux-x86_64-0.3.0-beta
├── libccid_1.6.2-1_amd64.deb
├── libpcsclite1_2.3.3-1_amd64.deb
├── pcscd_2.3.3-1_amd64.deb
├── SHA256SUMS.txt
├── 01-set-scale-100.sh
├── 02-install-smartcard-debs.sh
├── 03-run-satochip-utils.sh
└── 04-check-sha256.sh
```

使用顺序：

1. 先校验 `SHA256`
2. 把缩放改成 `100%`
3. 安装 3 个 `.deb`
4. 运行 `Satochip-Utils`

推荐这样运行脚本：

```bash
bash 04-check-sha256.sh
bash 01-set-scale-100.sh
bash 02-install-smartcard-debs.sh
bash 03-run-satochip-utils.sh
```

这样即使 U 盘文件系统不保留执行权限，也不影响使用。

更完整的正式教程看：

- [../Tails-离线使用教程.zh-CN.md](../Tails-离线使用教程.zh-CN.md)
