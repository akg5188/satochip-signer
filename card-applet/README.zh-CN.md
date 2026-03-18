# card-applet 说明

这个目录对应的是 `J3R180` 智能卡固件相关内容。

## 这个目录里有什么

- `SatochipApplet/`
  上游 Satochip JavaCard applet 源码快照
- `prebuilt/`
  已编译好的 CAP 固件文件
- `CAP_BUILD_AND_INSTALL.zh-CN.md`
  编译和写卡说明

## 你以后一般怎么用

如果你只是要：

- 给 `J3R180` 卡写入固件

优先看：

- [CAP_BUILD_AND_INSTALL.zh-CN.md](CAP_BUILD_AND_INSTALL.zh-CN.md)
- [prebuilt/README.md](prebuilt/README.md)

如果你要：

- 改智能卡 applet 源码

再看：

- [SatochipApplet/README.md](SatochipApplet/README.md)

## 作用定位

这里是“智能卡固件”这一层，不是：

- 树莓派固件
- 独立钱包安卓 APK
- TP 签名中转安卓 APK

## 对应关系

- `card-applet` = `J3R180` 智能卡固件
- `seedsigner-os` = 树莓派固件
- `wallet` = 独立钱包安卓 APK
- `app` = 给 TokenPocket 用的“智能卡”安卓软件
