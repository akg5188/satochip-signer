# 两个安卓 APK 说明

这个仓库里有两个不同用途的安卓 APK。

## 1. TP 签名中转 APK

文件：

- `dist/tp-qr-relay-android-latest.apk`

用途：

- 配合 `TokenPocket` 商业钱包使用
- 手机先扫 TP 动态二维码
- 手机再展示给树莓派扫描的中转二维码
- 主要是“扫码中转器”，不是独立观察钱包

## 2. 独立钱包 APK

文件：

- GitHub Release 里的 `satochip-wallet-release.apk`

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

如果你要：

- 独立钱包
- 资产页面
- Hyperliquid
- 转账

就用：

- `satochip-wallet-release.apk`
