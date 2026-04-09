# Satochip-Utils 备份说明

这个目录对应的是 `Satochip-Utils` 的离线备份。

它的用途很明确：

- 给已经安装好 `SatochipApplet` 的 `J3R180` 卡设置 `PIN`
- 给这张 `Satochip` 卡导入或生成 `BIP39` 助记词
- 适合在 `Tails OS` 这种离线环境中使用

它不是：

- `J3R180` 卡固件
- `SeedKeeper` applet 安装工具
- 树莓派固件
- 安卓 APK

## 目录内容

- `Satochip-Utils-backup-20260303.bundle`
  上游仓库的离线 git bundle 备份
- `README-BUNDLE.md`
  bundle 恢复命令
- [Tails-离线使用教程.zh-CN.md](Tails-离线使用教程.zh-CN.md)
  在 `Tails OS` 里安装依赖、设置 100% 显示缩放、运行工具、设置 `PIN` 和助记词的完整教程
- [offline-kit-template/README.zh-CN.md](offline-kit-template/README.zh-CN.md)
  用来重新整理离线工具包目录的模板和脚本

## 你实际使用时建议准备的离线套件

如果你是像现在这样在 `Tails OS` 离线电脑上直接操作，建议单独准备一个文件夹，例如：

```text
~/下载/tails智能卡设置/
├── Satochip-Utils-linux-x86_64-0.3.0-beta
├── libccid_1.6.2-1_amd64.deb
├── libpcsclite1_2.3.3-1_amd64.deb
├── pcscd_2.3.3-1_amd64.deb
└── 教程
```

这套东西里：

- `Satochip-Utils-linux-x86_64-0.3.0-beta`
  是直接运行的 Linux 可执行程序
- `libpcsclite1_2.3.3-1_amd64.deb`
  是 `PC/SC` 库
- `libccid_1.6.2-1_amd64.deb`
  是读卡器驱动
- `pcscd_2.3.3-1_amd64.deb`
  是智能卡服务

也就是说，你平时离线使用最重要的是这 4 个文件；本目录里的 `bundle` 更偏向源码备份和以后维护恢复。

## 上游与备份来源

- 上游项目：`Toporin/Satochip-Utils`
- 上游地址：`https://github.com/Toporin/Satochip-Utils`
- 备份仓库：`akg5188/satochip-utils-backup`
- 备份地址：`https://github.com/akg5188/satochip-utils-backup`

## 什么时候看这里

如果你当前要做的是：

- 用读卡器连接 `J3R180`
- 初始化卡
- 设置 `PIN`
- 导入 12/24 词助记词

那就看这里。

如果你要做的是：

- 给卡写入 applet 固件
- 搞清楚 `SeedKeeper` 和 `SatochipApplet` 的区别

那去看：

- [../../docs/官方程序下载验真与校验.zh-CN.md](../../docs/官方程序下载验真与校验.zh-CN.md)
- [../../docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md](../../docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md)

## 离线恢复

如果以后上游仓库没了，仍然可以用本目录里的 bundle 恢复源码。

最简单的恢复命令：

```bash
git clone Satochip-Utils-backup-20260303.bundle Satochip-Utils-restore
```

更完整的说明见：

- [README-BUNDLE.md](README-BUNDLE.md)
