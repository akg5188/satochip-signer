# 两个安卓 APK 说明

这个仓库里只有两个安卓 APK，需要分清。

`BlueWallet` 不在这个仓库里，它是外部钱包。

## 一眼区分

| APK | 源码目录 | 当前定位 |
| --- | --- | --- |
| `tp-qr-relay-android-latest.apk` | `app/` | `TokenPocket` 配套的智能卡签名/中转 App |
| `satochip-wallet-release.apk` | `wallet/` | 高安全观察钱包 |

## 1. `tp-qr-relay-android-latest.apk`

标准构建命令：

```bash
bash scripts/build_tp_relay_apk.sh
```

构建产物：

- `dist/tp-qr-relay-android-latest.apk`
- `dist/tp-qr-relay-android-latest.apk.sha256`
- `dist/tp-qr-relay-android-latest.build-info.txt`

当前真实能力：

- 扫 `TokenPocket` 动态二维码
- 解析 `TP` 的 `signTransaction / personalSign / signTypedData`
- 输入 `PIN` 后用 `NFC` 或 `USB-OTG + ACR39U` 配合智能卡直接签名
- 显示回扫给 `TP` 的结果二维码
- 也可以把 `TP` 动态码转成树莓派更容易扫的静态码

它不是：

- 独立钱包
- 资产页 App
- `BlueWallet` 兼容层

签名说明：

- `app/` 的 `release` 构建如果没有配置 `keystore.properties`，会回退到 `debug` 签名
- 如果你想长期平滑升级，最好尽早配置自己的正式 keystore

## 2. `satochip-wallet-release.apk`

标准构建命令：

```bash
bash scripts/build_wallet_release.sh
```

构建产物：

- `dist/satochip-wallet-release.apk`
- `dist/satochip-wallet-release.apk.sha256`
- `dist/satochip-wallet-release.build-info.txt`

当前真实能力：

- `Arbitrum One` 观察地址与资产查看
- 生成给树莓派扫描的签名请求二维码
- 扫描树莓派签名结果并人工确认广播
- 高安全 `WalletConnect v2` 协调
- `BTC xpub / ypub / zpub` 观察账户导入、同步与 `PSBT` 冷签请求准备

它不是：

- 热钱包
- 内置 `Hyperliquid` 浏览器
- 手机本地私钥钱包

签名说明：

- `wallet/` 的 `release` 构建必须配置 `wallet/keystore.properties`
- 没有 keystore，`release` 构建会直接失败

## 3. 外部钱包怎么归类

- `BlueWallet`
  外部 `BTC` 钱包，直接配合树莓派离线签名器使用
- `TokenPocket`
  外部 EVM 钱包，需要配合 `app/` 里的安卓“智能卡”App

## 4. 最常见误解

- 想看资产、地址、活动、DApp，就去 `wallet/`
- 想处理 `TokenPocket` 动态码，就去 `app/`
- 想给 `BlueWallet` 签 `PSBT`，直接用树莓派，不要装 TP 中转 App
