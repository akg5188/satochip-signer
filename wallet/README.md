# Satochip Arbitrum Wallet (Android)

这是一个给树莓派离线签名器配套使用的安卓观察钱包。

当前这版的定位很明确：

- 只支持 `Arbitrum One`
- 手机里不保存私钥
- 负责看资产、发起转账、展示签名二维码、接收树莓派签名结果
- 内置 `Hyperliquid` 官方网页，并通过注入钱包完成连接和签名
- 支持指纹解锁启动

## 现在能做什么

- 添加多个观察地址，并切换当前地址
- 查看 `ETH / USDC / USDT` 余额和美元估值
- 构造转账请求，生成给树莓派扫描的动态二维码
- 扫描树莓派签名结果并广播交易
- 扫描外部 DApp / WalletConnect / 二维码签名请求
- 在内置 `Hyperliquid` 页面里连接 `Satochip Wallet`

## 文档入口

- [用户使用教程](docs/使用教程.zh-CN.md)
- [开发维护指南](docs/开发维护指南.zh-CN.md)

## 直接下载 APK

- [release APK](https://github.com/akg5188/tp-satochip-signer/releases/download/wallet-android-20260318-1717/satochip-wallet-release.apk)
- [release APK sha256](https://github.com/akg5188/tp-satochip-signer/releases/download/wallet-android-20260318-1717/satochip-wallet-release.apk.sha256)

## 直接编译

1. 复制配置文件

```bash
cp local.properties.example local.properties
```

2. 把 `local.properties` 里的 `sdk.dir` 改成你机器上的 Android SDK 路径

3. 构建 release APK

```bash
./gradlew assembleRelease --console=plain
```

输出路径：

```text
app/build/outputs/apk/release/app-release.apk
```

## 英文路径构建脚本

如果你的工程路径里有中文，或者 Gradle / Android SDK 在中文路径下不稳定，可以直接用：

```bash
./scripts/build_local_ascii.sh release
```

输出路径：

```text
dist/satochip-wallet-release.apk
dist/satochip-wallet-release.apk.sha256
```

## 环境要求

- JDK 17
- Android SDK 34
- Android Build Tools 35.0.0
- Android 8.0 及以上设备

## 当前说明

- 当前 release APK 使用调试签名，适合你自己安装、备份和继续维护
- 如果以后要正式分发或上架，再换成你自己的正式 keystore
