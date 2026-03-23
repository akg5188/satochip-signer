# 两个安卓 APK 说明

这个仓库里有两个不同用途的安卓 APK。

## 1. TP 签名中转 APK

文件：

- `dist/tp-qr-relay-android-latest.apk`
- `dist/tp-qr-relay-android-latest.apk.sha256`
- `dist/tp-qr-relay-android-latest.build-info.txt`
- GitHub Release：`tp-relay-android-20260318-1956`
- 源码目录：`app/`
- 标准构建命令：`bash scripts/build_tp_relay_apk.sh`

用途：

- 配合 `TokenPocket` 商业钱包使用
- 手机先扫 TP 动态二维码
- 手机再展示给树莓派扫描的中转二维码
- 主要是“扫码中转器”，不是独立观察钱包

## 2. 独立钱包 APK

文件：

- 目标稳定文件名：`dist/satochip-wallet-release.apk`
- 对应校验文件：`dist/satochip-wallet-release.apk.sha256`
- GitHub Release：`wallet-android-20260318-1717`
- 源码目录：`wallet/`
- 标准构建命令：`bash scripts/build_wallet_release.sh`

如果仓库里当前没有这两个文件，先本地运行标准构建命令生成。

共同环境准备看：

- [安卓构建环境准备](安卓构建环境准备.zh-CN.md)

用途：

- `Arbitrum One` 观察钱包
- 查看资产
- 发起转账
- 处理签名请求
- 内置 `Hyperliquid`

源码：

- `wallet/`

## 3. 不要混用

如果你只是要：

- 给 TP 商业钱包做签名中转

就用：

- `tp-qr-relay-android-latest.apk`
- `app/`

如果你要：

- 独立钱包
- 资产页面
- Hyperliquid
- 转账

就用：

- `satochip-wallet-release.apk`
- `wallet/`
