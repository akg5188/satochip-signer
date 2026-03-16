# TP Satochip Signer

一个给 `TokenPocket` 观察钱包使用的离线签名项目。

当前仓库里已经包含：

- 安卓中转 App 源码与最新 APK
- `wallet` 目录里的独立安卓钱包工程备份
- 树莓派离线签名固件源码
- 树莓派最新固件分片
- 重打镜像、重组固件、后续维护用脚本

## 入口

- [wallet](/home/ak/树莓派/tp-satochip-signer/wallet): 单独备份出来的安卓钱包工程，打开仓库首页就能看到

## 最新可直接使用的文件

安卓 APK：

- [dist/tp-qr-relay-android-latest.apk](/home/ak/树莓派/tp-satochip-signer/dist/tp-qr-relay-android-latest.apk)
- [dist/tp-qr-relay-android-latest.apk.sha256](/home/ak/树莓派/tp-satochip-signer/dist/tp-qr-relay-android-latest.apk.sha256)

树莓派固件：

- [dist/system-update-latest.img.xz](/home/ak/树莓派/tp-satochip-signer/dist/system-update-latest.img.xz)
- [dist/system-update-latest.img.xz.sha256](/home/ak/树莓派/tp-satochip-signer/dist/system-update-latest.img.xz.sha256)

## 文档

- [快速开始](/home/ak/树莓派/tp-satochip-signer/docs/快速开始.zh-CN.md)
- [维护说明](/home/ak/树莓派/tp-satochip-signer/docs/维护说明.zh-CN.md)

## 仓库结构

- [app](/home/ak/树莓派/tp-satochip-signer/app): 安卓中转 App
- [wallet](/home/ak/树莓派/tp-satochip-signer/wallet): 独立安卓钱包工程备份与维护文档
- [pi-signer-py](/home/ak/树莓派/tp-satochip-signer/pi-signer-py): Python CLI 签名器
- [pi-signer](/home/ak/树莓派/tp-satochip-signer/pi-signer): Kotlin CLI 签名器
- [pi-appliance](/home/ak/树莓派/tp-satochip-signer/pi-appliance): 树莓派独立 UI 组件
- [seedsigner-os](/home/ak/树莓派/tp-satochip-signer/seedsigner-os): 固件底座与 overlay
- [card-applet](/home/ak/树莓派/tp-satochip-signer/card-applet): Satochip JavaCard applet 相关文件
- [scripts](/home/ak/树莓派/tp-satochip-signer/scripts): 打包、重组、监控脚本

## 当前已验证

- TP EVM 转账签名
- TP `personalSign`
- TP `signTypedData` / `signTypedDataV4`
- 安卓中转静态二维码给 Pi Zero 扫描

## 当前不做的事

- 直接让 Pi Zero 扫 TP 高频动态码
- `signTypedDataLegacy` 数组格式
- BTC / Tron / Solana 等非 EVM 链
