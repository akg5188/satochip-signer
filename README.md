# TP Satochip Signer

这个仓库现在一共分成五个核心部分，后面维护时请按用途区分，不要混用。

如果你以后只想最快找到“该下载什么、该进哪个目录、该怎么重新编译”，先看：

- [docs/一页式总导航.zh-CN.md](docs/一页式总导航.zh-CN.md)
- [docs/长期维护总入口.zh-CN.md](docs/长期维护总入口.zh-CN.md)

## 1. `card-applet`

用途：

- `J3R180` 智能卡固件
- 负责卡片里的签名相关逻辑

入口：

- [card-applet/](card-applet/)
- [card-applet 中文说明](card-applet/README.zh-CN.md)
- [J3R180 卡固件 Release 页面](https://github.com/akg5188/tp-satochip-signer/releases/tag/j3r180-card-firmware-20260318)

## 2. `seedsigner-os`

用途：

- 树莓派固件
- 负责树莓派设备侧系统、界面和运行环境

入口：

- [seedsigner-os/](seedsigner-os/)
- [seedsigner-os 中文说明](seedsigner-os/README.zh-CN.md)
- [树莓派固件 Release 页面](https://github.com/akg5188/tp-satochip-signer/releases/tag/pi-signer-firmware-20260318)

## 3. `wallet`

用途：

- 独立钱包安卓 APK
- `Arbitrum One` 观察钱包
- 资产查看
- 转账二维码签名
- 内置 `Hyperliquid`

源码入口：

- [wallet/](wallet/README.md)

下载入口：

- [独立钱包 Release 页面](https://github.com/akg5188/tp-satochip-signer/releases/tag/wallet-android-20260318-1717)
- [独立钱包 APK](https://github.com/akg5188/tp-satochip-signer/releases/download/wallet-android-20260318-1717/satochip-wallet-release.apk)

## 4. `app`

用途：

- 安卓软件，中文名就是“智能卡”
- 专门配合 `TokenPocket` 商业钱包使用
- 手机扫 TP 动态二维码，再中转给树莓派签名
- 不是独立钱包

源码入口：

- [app/](app/README.md)

下载入口：

- [TP 签名中转 Release 页面](https://github.com/akg5188/tp-satochip-signer/releases/tag/tp-relay-android-20260318-1956)
- [TP 签名中转 APK](https://github.com/akg5188/tp-satochip-signer/releases/download/tp-relay-android-20260318-1956/tp-qr-relay-android-latest.apk)
- 仓库内稳定文件名：`dist/tp-qr-relay-android-latest.apk`

## 5. `backups/satochip-utils`

用途：

- `J3R180` 卡初始化工具的离线备份
- 用来在 `Tails OS` 里设置卡的 `PIN`
- 用来导入或生成助记词
- 不是固件，也不是安卓 APK

入口：

- [backups/satochip-utils/README.zh-CN.md](backups/satochip-utils/README.zh-CN.md)
- [Tails OS 离线使用教程](backups/satochip-utils/Tails-离线使用教程.zh-CN.md)

## 总结

以后只要记住这五个角色就不会乱：

- `card-applet` = 智能卡固件
- `seedsigner-os` = 树莓派固件
- `wallet` = 独立钱包安卓 APK
- `app` = 给 TokenPocket 用的“智能卡”安卓软件
- `backups/satochip-utils` = 设置 `J3R180` 卡 PIN 和助记词的离线工具备份

详细说明：

- [docs/一页式总导航.zh-CN.md](docs/一页式总导航.zh-CN.md)
- [docs/仓库结构说明.zh-CN.md](docs/仓库结构说明.zh-CN.md)
- [docs/两个安卓APK说明.zh-CN.md](docs/两个安卓APK说明.zh-CN.md)
- [docs/固件下载与写入指南.zh-CN.md](docs/固件下载与写入指南.zh-CN.md)
- [docs/长期维护总入口.zh-CN.md](docs/长期维护总入口.zh-CN.md)
