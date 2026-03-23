# seedsigner-os 说明

这个目录对应的是树莓派固件。

## 作用

- 提供树莓派设备侧系统
- 提供运行环境、构建环境和镜像相关内容
- 给树莓派签名器和界面运行做底座

## 这个目录不是干什么的

它不是：

- 智能卡固件
- 独立钱包安卓 APK
- TP 签名中转安卓 APK

## 你以后一般怎么用

如果你只是要记住仓库结构：

- `seedsigner-os` 就是“树莓派固件”

如果你以后只是想：

- 找固件下载位置
- 校验镜像
- 烧录 TF 卡

直接看：

- [固件下载与写入指南](../docs/固件下载与写入指南.zh-CN.md)
- [树莓派固件 GitHub Releases 页面](https://github.com/akg5188/tp-satochip-signer/releases)

如果你要继续研究原始构建方式：

- 先看 [README.md](README.md)

## 对应关系

- `card-applet` = `J3R180` 智能卡固件
- `seedsigner-os` = 树莓派固件
- `wallet` = 独立钱包安卓 APK
- `app` = 给 TokenPocket 用的“智能卡”安卓软件
- `backups/satochip-utils` = `J3R180` 卡初始化工具备份
