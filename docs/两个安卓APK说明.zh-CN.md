# 两个安卓 APK 说明

这个项目当前有两条安卓 App 产品线，需要分清。

`BlueWallet` 不在这个仓库里，它是外部钱包。

## 一眼区分

| APK | 源码目录 | 当前定位 |
| --- | --- | --- |
| `tp-qr-relay-android-latest.apk` | `app/` | `TokenPocket` 配套的智能卡签名/中转 App |
| `satochip-wallet-release.apk` | `wallet/` | 高安全观察钱包 + `OKX Wallet / Bitget Wallet` Web3 二维码桥接 |

当前公开下载 tag 统一看：

- [版本时间线与发布入口](版本时间线与发布入口.zh-CN.md)

## 1. `tp-qr-relay-android-latest.apk`

定位：

- 这是 `TokenPocket` 路线的可选配套 APK
- 按需构建，不保证长期常驻当前仓库 `dist/`

标准构建命令：

```bash
bash scripts/build_tp_relay_apk.sh
```

构建产物：

- `dist/tp-qr-relay-android-latest.apk`
- `dist/tp-qr-relay-android-latest.apk.sha256`
- `dist/tp-qr-relay-android-latest.build-info.txt`

补充说明：

- 这组产物是按需构建的
- 当前仓库的 `dist/` 不保证长期一直保留这 3 个文件
- 如果你本地没看到，先运行上面的构建脚本再找

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

当前仓库保留基线 release：

- `current-head-wallet-release`

当前工作区最新构建命令：

```bash
bash scripts/build_current_wallet_apk.sh
```

构建产物：

- `dist/satochip-wallet-worktree-latest.apk`
- `dist/satochip-wallet-worktree-latest.apk.sha256`
- `dist/satochip-wallet-worktree-latest.build-info.txt`

如果你要重建当前 clean 正式版，才用：

```bash
bash scripts/rebuild_official_release.sh wallet-release
```

正式版产物：

- `dist/satochip-wallet-release.apk`
- `dist/satochip-wallet-release.apk.sha256`
- `dist/satochip-wallet-release.build-info.txt`

当前仓库里这份正式钱包基线对应：

- 源码提交：
  `979f58d3ad5cecdfec319e14681cde006c7073ab`
- `SHA256`：
  `246e0faf04b071877466da25716dbf0e9ac0d578a2f5ac68d25f9de948865f96`

历史公开稳定钱包仍然另算：

- `wallet-android-20260408-0.1.4`

当前真实能力：

- `Arbitrum One` 观察地址与资产查看
- 生成给树莓派扫描的签名请求二维码
- 扫描树莓派签名结果并人工确认广播
- 高安全 `WalletConnect v2` 协调
- Web3 连接二维码改由树莓派首页 `连接钱包` 直接显示
- 安卓只把高密度 Web3 签名请求中转成树莓派能扫的低密度二维码
- 扫 Web3 钱包签名请求，再转成树莓派中转二维码
- 树莓派签完后，直接让原钱包扫描树莓派结果码
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
- `OKX Wallet / Bitget Wallet`
  外部 Web3 钱包，需要配合 `wallet/` 里的安卓观察钱包做二维码桥接

## 4. 最常见误解

- 想看资产、地址、活动、DApp，就去 `wallet/`
- 想处理 `TokenPocket` 动态码，就去 `app/`
- 想给 `BlueWallet` 签 `PSBT`，直接用树莓派，不要装 TP 中转 App
- 想连接 `OKX Wallet / Bitget Wallet`，连接码走树莓派 `连接钱包 -> Web3钱包`，签名请求太密时才用 `wallet/` 中转
- `current-head-wallet-release` 是当前仓库保留的正式钱包基线，不等于历史公开稳定 tag `wallet-android-20260408-0.1.4`
