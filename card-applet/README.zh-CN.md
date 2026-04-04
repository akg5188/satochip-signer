# card-applet 说明

这个目录对应的是 `J3R180` 智能卡固件相关内容。

先记住最短结论：

- 这里当前整理的是 `SatochipApplet` 这条线
- 不是 `SeedKeeper` applet 的完整离线工具包
- 当前官方 `SeedSigner` 固件和本仓库树莓派固件都不能直接给卡刷 applet

## 这个目录里有什么

- `SatochipApplet/`
  上游 Satochip JavaCard applet 源码快照
- `prebuilt/`
  已编译好的 CAP 固件文件
- `CAP_BUILD_AND_INSTALL.zh-CN.md`
  编译和写卡说明
- `J3R180刷SatochipApplet与SeedKeeper.zh-CN.md`
  把两种 applet 的刷卡命令整理成可直接复制粘贴的教程
- `TAILS_SATOCHIP_UTILS_OFFLINE_GUIDE.zh-CN.md`
  旧版 Tails 使用说明，已迁移到新的统一入口

## 你以后一般怎么用

如果你只是要：

- 给 `J3R180` 卡写入固件

优先看：

- [CAP_BUILD_AND_INSTALL.zh-CN.md](CAP_BUILD_AND_INSTALL.zh-CN.md)
- [J3R180刷SatochipApplet与SeedKeeper.zh-CN.md](J3R180刷SatochipApplet与SeedKeeper.zh-CN.md)
- [prebuilt/README.md](prebuilt/README.md)
- [../docs/固件下载与写入指南.zh-CN.md](../docs/固件下载与写入指南.zh-CN.md)
- [J3R180 卡固件 Release 页面](https://github.com/akg5188/satochip-signer/releases/tag/j3r180-card-firmware-20260318)

如果你要：

- 在 `Tails OS` 里给卡设置 `PIN`
- 导入或生成助记词

请看新的统一入口：

- [../backups/satochip-utils/README.zh-CN.md](../backups/satochip-utils/README.zh-CN.md)
- [../backups/satochip-utils/Tails-离线使用教程.zh-CN.md](../backups/satochip-utils/Tails-离线使用教程.zh-CN.md)
- [../docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md](../docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md)

如果你要：

- 改智能卡 applet 源码

再看：

- [SatochipApplet/README.md](SatochipApplet/README.md)
- [J3R180刷SatochipApplet与SeedKeeper.zh-CN.md](J3R180刷SatochipApplet与SeedKeeper.zh-CN.md)

## 作用定位

这里是“智能卡固件”这一层，不是：

- 树莓派固件
- 独立钱包安卓 APK
- TP 签名中转安卓 APK

## 最容易混淆的点

- `SatochipApplet` 和 `SeedKeeper` 不是同一个 applet
- 当前目录里给你的是 `SatochipApplet`
- `backups/satochip-utils/` 主要是 `Satochip` 卡初始化/导种流程
- 如果你以后想做“两张卡方案”，建议一张 `SeedKeeper`、一张 `Satochip`
- 不建议拿同一张卡来回刷两种 applet

## 对应关系

- `card-applet` = `J3R180` 智能卡固件
- `seedsigner-os` = 树莓派固件
- `wallet` = 独立钱包安卓 APK
- `app` = 给 TokenPocket 用的“智能卡”安卓软件
- `backups/satochip-utils` = `J3R180` 卡离线初始化工具备份
