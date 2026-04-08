# satochip-signer 仓库说明

## 当前正式入口

以后如果只是想直接用，不要先翻源码，按这个顺序做就行：

1. 先去 GitHub Releases 下载当前推荐正式包
2. 先看 [离线签名器一页备忘](docs/离线签名器一页备忘.zh-CN.md) 或 [快速开始](docs/快速开始.zh-CN.md)
3. 下载前先看 [官方程序下载验真与校验](docs/官方程序下载验真与校验.zh-CN.md)
4. 真要重建正式版时，再看 [固定正式发布重建入口](docs/固定正式发布重建入口.zh-CN.md)

以后如果让新的 AI 继续维护，也不要让它自己猜 tag、猜分支、猜命令。
先让它看：

- [release-manifest.json](release-manifest.json)
- [固定正式发布重建入口](docs/固定正式发布重建入口.zh-CN.md)
- [固件与源码对应关系](docs/固件与源码对应关系.zh-CN.md)

当前该下载的 release：

- 树莓派当前固件：
  看 [版本时间线与发布入口](docs/版本时间线与发布入口.zh-CN.md)
- 安卓正式钱包：
  [wallet-android-20260403-0.1.3](https://github.com/akg5188/satochip-signer/releases/tag/wallet-android-20260403-0.1.3)
- 安卓智能卡 App：
  [smartcard-app-android-20260330](https://github.com/akg5188/satochip-signer/releases/tag/smartcard-app-android-20260330)
- 智能卡 applet：
  改用上游官方 release，看 [官方程序下载验真与校验](docs/官方程序下载验真与校验.zh-CN.md)

以后如果让 AI 重建正式发布版，先跑这几条，不要自己猜 tag：

```bash
bash scripts/rebuild_official_release.sh --list
bash scripts/rebuild_official_release.sh firmware-clean
bash scripts/rebuild_official_release.sh wallet-release
```

对应说明：

- [固定正式发布重建入口](docs/固定正式发布重建入口.zh-CN.md)
- [固件与源码对应关系](docs/固件与源码对应关系.zh-CN.md)
- [版本时间线与发布入口](docs/版本时间线与发布入口.zh-CN.md)

这个项目现在更适合叫 `satochip-signer`。

仓库旧名是：

- `tp-satochip-signer`

按现在源码里的真实状态，它主要维护 4 条主线，另保留 1 份离线初始化工具备份：

- `seedsigner-os/` 与 `dist/`
  树莓派 `Pi Zero` 离线签名器固件与镜像备份
- `app/`
  安卓“智能卡”App，负责 `TokenPocket` 请求扫码、智能卡签名，也能把 TP 动态码转成树莓派更容易扫的静态码
- `wallet/`
  安卓高安全观察钱包，当前主打 `Arbitrum One` 观察地址、`WalletConnect v2` 协调、树莓派离线签名，以及 `BTC xpub/ypub/zpub` 观察账户原型
- `backups/satochip-utils/`
  `Tails` 离线卡初始化工具备份

先看这些入口，别先翻源码：

- [一页式总导航](docs/一页式总导航.zh-CN.md)
- [快速开始](docs/快速开始.zh-CN.md)
- [官方程序下载验真与校验](docs/官方程序下载验真与校验.zh-CN.md)
- [SeedKeeper 与 SatochipApplet 分工指南](docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md)
- [固定正式发布重建入口](docs/固定正式发布重建入口.zh-CN.md)
- [非 GitHub 关键备份清单](docs/非GitHub关键备份清单.zh-CN.md)
- [版本时间线与发布入口](docs/版本时间线与发布入口.zh-CN.md)
- [当前正式发布说明](docs/当前正式发布说明.zh-CN.md)
- [真机全套回归清单](docs/真机全套回归清单.zh-CN.md)
- [离线签名器一页备忘](docs/离线签名器一页备忘.zh-CN.md)
- [离线签名器使用教程](docs/离线签名器使用教程.zh-CN.md)
- [离线熵创建助记词教程](docs/离线熵创建助记词教程.zh-CN.md)
- [BIP85子助记词使用教程](docs/BIP85子助记词使用教程.zh-CN.md)
- [钛板打孔备份助记词教程](docs/钛板打孔备份助记词教程.zh-CN.md)
- [长期维护总入口](docs/长期维护总入口.zh-CN.md)
- [固件与源码对应关系](docs/固件与源码对应关系.zh-CN.md)

## 现在该用什么

| 你要做的事 | 该看哪里 | 当前产物/入口 |
| --- | --- | --- |
| 给 `TokenPocket` 做手机端扫码与智能卡签名 | `app/` | `bash scripts/build_tp_relay_apk.sh` |
| 用自己的安卓观察钱包发起 EVM / BTC 冷签 | `wallet/` | `bash scripts/build_wallet_release.sh` |
| 想用骰子 / 扑克牌 / 16进制自己离线创建助记词 | 树莓派离线签名器 | [离线熵创建助记词教程](docs/离线熵创建助记词教程.zh-CN.md) |
| 给 `BlueWallet` 做 `BTC PSBT` 冷签 | 树莓派离线签名器 | [离线签名器使用教程](docs/离线签名器使用教程.zh-CN.md) |
| 想系统搞懂 `BIP85` 子助记词 | 树莓派离线签名器 | [BIP85子助记词使用教程](docs/BIP85子助记词使用教程.zh-CN.md) |
| 想把助记词做成钛板/钢板备份 | 树莓派离线签名器 | [钛板打孔备份助记词教程](docs/钛板打孔备份助记词教程.zh-CN.md) |
| 刷树莓派固件 | `dist/` | `system-update-card-entropy-test.img.xz` |
| 给智能卡刷官方 applet | 官方 release | [官方程序下载验真与校验](docs/官方程序下载验真与校验.zh-CN.md) |
| 在 `Tails` 里初始化 `Satochip` 卡、设 PIN、导助记词 | `backups/satochip-utils/` | 对应中文教程 |

## 两张最重要的树莓派镜像

仓库和 GitHub 现在主要保留两张树莓派镜像：

- `dist/system-update-card-entropy-test.img.xz`
  这是现在优先推荐直接刷的本机功能测试包。
  GitHub 当前公开下载入口使用同内容的公开文件名：
  `system-update-seedkeeper-suite-test.img.xz`
  已确认支持：
  - 自有安卓钱包扫码签名
  - `BlueWallet` 的 `BTC PSBT`
  - `TokenPocket` 中转场景
  - 助记词/BIP39 序号查看、原始熵二维码复核、`BIP85` 子助记词、钢板数字流程、智能卡工具、固件完整性自检
  - 当前助记词与 `BIP85` 子助记词写入 `SatochipApplet / SeedKeeper`
  - `助记词工具` 里的 `智能卡真随机创建助记词`
  - 智能卡工具里的 `SeedKeeper` 功能入口和 `Satochip` 功能入口
  - `SeedKeeper` 里保存二次加密后的假助记词，并可重新加载回树莓派继续二次还原
  - 分开的 `更改 Satochip PIN / 更改 SeedKeeper PIN`
  - 分开的 `重置 Satochip / 重置 SeedKeeper`
  - 开机 `4-12` 位数字登录密码
  - 交易详情核对页 + 单次 PIN 流程
  注意：
  - 这张是当前功能版，不是 clean 逐字节复现基线
  - 当前长期建议是 `一张卡只装一个程序`
  - `重置 Satochip / 重置 SeedKeeper` 只建议在专用单程序卡上使用
  - 如果同一张卡还装了另一个 applet，不要在固件里做恢复出厂
  - build info 在：
    `dist/system-update-card-entropy-test.build-info.txt`
  - `sha256 = 4b04c5fe4f07eb759c5c40c1809cae57216b2a215d90e1081121fd3ccc873100`

- `dist/system-update-latest.img.xz`
  这是保留的 clean 正式基线。
  用途：
  - 以后严格重建并校验哈希
  - 做长期基线留档
  - 不再作为当前首先推荐下载的固件

怎么对应源码，看这里：

- [固件与源码对应关系](docs/固件与源码对应关系.zh-CN.md)
- [当前测试固件功能与验证范围](docs/当前测试固件功能与验证范围.zh-CN.md)

## 当前主界面长什么样

树莓派开机后的首页不是旧文档里的 `TP only mode` 了。

当前源码里的首页标题就是：

- `离线签名器`

在真正进入主页前，还会先出现：

- `设备登录`

首次刷机后会强制设置 `4-12` 位数字登录密码；以后每次开机先输入它，才会进入真正的离线签名器界面。

首页 4 个入口：

- `扫码签名`
- `助记词工具`
- `固件完整性自检`
- `智能卡工具`

## 三条常用使用链路

### 1. 自己的安卓钱包 `satochip-wallet-release.apk`

1. 手机生成待签名二维码
2. 树莓派进 `扫码签名`
3. 输入智能卡 `PIN`
4. 树莓派显示签名结果
5. 手机扫回并人工确认广播

### 2. `BlueWallet`

1. `BlueWallet` 显示 `BTC PSBT` 动态二维码
2. 树莓派进 `扫码签名`
3. 输入智能卡 `PIN`
4. 树莓派回显结果二维码
5. `BlueWallet` 扫回并广播

当前固件已接入：

- `BBQR`
- `UR`
- 常见 `PSBT` 回传格式

### 3. `TokenPocket`

有两条路：

- 手机直接用 `app/` 里的“智能卡”App 扫 `TP` 请求并配合智能卡签名
- 或者先用这款 App 把 `TP` 动态码转成树莓派更容易扫的静态码，再让树莓派签名

所以 `app/` 不是独立钱包，也不只是“给 Pi 的中转器”，它现在同时承担：

- `TP` 请求解析
- `NFC / USB-OTG` 智能卡签名
- 可选的树莓派静态中转二维码生成
- 结果二维码回传

## 最常用构建命令

以后如果是“重建正式发布版”，不要自己猜 tag，直接用统一入口：

```bash
bash scripts/rebuild_official_release.sh --list
bash scripts/rebuild_official_release.sh firmware-clean
bash scripts/rebuild_official_release.sh wallet-release
```

这 3 条命令的意义是：

- `--list`
  先列出当前官方正式发布件和对应源码冻结 tag
- `firmware-clean`
  用官方固定源码重建当前正式固件，并自动验包
- `wallet-release`
  用官方固定源码重建当前正式钱包 APK，并自动验包

以后只要先跑这套脚本，就不会再靠记忆去猜：

- 该 checkout 哪个 tag
- 该用哪条构建命令
- 这次重建到底是不是官方那一版

### 树莓派固件

```bash
bash scripts/build_pi_firmware_from_snapshot.sh
bash scripts/check_release_artifacts.sh
```

### 安卓智能卡 App

```bash
bash scripts/build_tp_relay_apk.sh
```

### 安卓观察钱包

```bash
bash scripts/build_wallet_release.sh
```

## 最容易写错的地方

- `wallet/` 当前不是内置 `Hyperliquid` 浏览器钱包。
- `wallet/` 现在是高安全观察钱包 + `WalletConnect` 协调器。
- `app/` 不是独立钱包，它是 `TokenPocket` 配套的智能卡签名/中转 App。
- `SeedKeeper` 和 `SatochipApplet` 不是同一个 applet。
- 技术上同一张 `J3R180` 卡也可以同时装这两个 applet，但当前长期建议已经改成：`一张卡只装一个程序`。
- 如果你手里已经是双 applet 共卡，日常查看/导入/签名还可以继续用，但不要在固件里做恢复出厂。
- 当前官方 `SeedSigner` 固件和本仓库树莓派固件都不能直接给卡刷 applet。
- `backups/satochip-utils/` 当前讲的是 `Satochip` 卡初始化，不是白卡来回切换 `SeedKeeper / SatochipApplet`。
- 树莓派首页已经不是 `TP only mode`，也没有“官方模式”入口了。
- 仓库和 GitHub Releases 里不再保留一堆旧测试 firmware 包；当前只保留当前推荐包和 clean 基线，避免拿错。
- 当前推荐 clean 包的精确源码不要拿 `main` 猜，必须看 [固件与源码对应关系](docs/固件与源码对应关系.zh-CN.md)。

## 文档入口

- [快速开始](docs/快速开始.zh-CN.md)
- [两个安卓 APK 说明](docs/两个安卓APK说明.zh-CN.md)
- [仓库结构说明](docs/仓库结构说明.zh-CN.md)
- [版本时间线与发布入口](docs/版本时间线与发布入口.zh-CN.md)
- [官方程序下载验真与校验](docs/官方程序下载验真与校验.zh-CN.md)
- [固定正式发布重建入口](docs/固定正式发布重建入口.zh-CN.md)
- [非 GitHub 关键备份清单](docs/非GitHub关键备份清单.zh-CN.md)
- [固件下载与写入指南](docs/固件下载与写入指南.zh-CN.md)
- [安卓构建环境准备](docs/安卓构建环境准备.zh-CN.md)
- [离线签名器一页备忘](docs/离线签名器一页备忘.zh-CN.md)
- [离线签名器使用教程](docs/离线签名器使用教程.zh-CN.md)
- [SeedKeeper 与 SatochipApplet 分工指南](docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md)
- [树莓派固件构建与备份](docs/树莓派固件构建与备份.zh-CN.md)
- [固件与源码对应关系](docs/固件与源码对应关系.zh-CN.md)
- [长期维护总入口](docs/长期维护总入口.zh-CN.md)
