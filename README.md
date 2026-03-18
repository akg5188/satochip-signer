# TP Satochip Signer

这个仓库里现在有两个不同用途的安卓 APK，请不要混用。

## 两个安卓 APK 的区别

### 1. TP 签名中转 APK

用途：

- 专门给 `TokenPocket` 商业钱包做二维码中转签名
- 手机先扫 TP 的动态码
- 再把静态中转码给树莓派扫描
- 不负责独立钱包资产管理

下载入口：

- [TP 签名中转 APK](dist/tp-qr-relay-android-latest.apk)
- [TP 签名中转 APK sha256](dist/tp-qr-relay-android-latest.apk.sha256)

对应源码入口：

- [`app/`](app)

### 2. 独立钱包 APK

用途：

- `Arbitrum One` 观察钱包
- 资产查看
- 转账二维码签名
- 内置 `Hyperliquid` 官方网页
- 指纹解锁启动

下载入口：

- [独立钱包 Release 页面](https://github.com/akg5188/tp-satochip-signer/releases/tag/wallet-android-20260318-1717)
- [独立钱包 APK](https://github.com/akg5188/tp-satochip-signer/releases/download/wallet-android-20260318-1717/satochip-wallet-release.apk)
- [独立钱包 APK sha256](https://github.com/akg5188/tp-satochip-signer/releases/download/wallet-android-20260318-1717/satochip-wallet-release.apk.sha256)

对应源码入口：

- [`wallet/`](wallet/README.md)

## 其他目录

- [智能卡 / JavaCard 相关](card-applet/)
- [树莓派 UI 相关](pi-appliance/)
- [树莓派签名器相关](pi-signer/), [pi-signer-py/](pi-signer-py/)
- [固件与镜像相关](seedsigner-os/)

## 建议

如果你以后只是要维护你现在这个独立钱包，直接从 [`wallet/`](wallet/README.md) 开始。  
如果你以后要继续给 TP 商业钱包做扫码签名中转，再看根目录下的 `app/` 和 `dist/tp-qr-relay-android-latest.apk`。
