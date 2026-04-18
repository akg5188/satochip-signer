# satochip-signer 仓库说明

## 当前正式入口

以后如果只是想直接用，不要先翻源码，按这个顺序做就行：

1. 先看 [版本时间线与发布入口](docs/版本时间线与发布入口.zh-CN.md)，确认当前正式件和公开下载 tag
2. 完全没接触过这套东西时，先看 [零基础第一次上手教程](docs/零基础第一次上手教程.zh-CN.md)
3. 想先认页面结构，可以先看 [逐屏真实 UI 截图版第一次上手教程](docs/逐屏截图版第一次上手教程.zh-CN.md)
4. 如果以后还想补设备外观和手机实拍，再看 [真机实拍逐屏截图采集清单](docs/真机实拍逐屏截图采集清单.zh-CN.md)
5. 再看 [离线签名器一页备忘](docs/离线签名器一页备忘.zh-CN.md) 或 [快速开始](docs/快速开始.zh-CN.md)
6. 下载前先看 [官方程序下载验真与校验](docs/官方程序下载验真与校验.zh-CN.md)
7. 真要重建正式版时，再看 [固定正式发布重建入口](docs/固定正式发布重建入口.zh-CN.md)

以后如果让新的 AI 继续维护，也不要让它自己猜 tag、猜分支、猜命令。
先让它看：

- [release-manifest.json](release-manifest.json)
- [固定正式发布重建入口](docs/固定正式发布重建入口.zh-CN.md)
- [固件与源码对应关系](docs/固件与源码对应关系.zh-CN.md)

当前公开下载入口：

- 树莓派当前固件：
  看 [版本时间线与发布入口](docs/版本时间线与发布入口.zh-CN.md)
  当前公开 tag：`offline-signer-firmware-20260410b-clean`
- 安卓正式钱包：
  看 [版本时间线与发布入口](docs/版本时间线与发布入口.zh-CN.md)
  当前公开 tag：`wallet-android-20260408-0.1.4`
- 安卓智能卡 App：
  如需 `TokenPocket` 路线，再看 [版本时间线与发布入口](docs/版本时间线与发布入口.zh-CN.md)
  当前可用 tag：`smartcard-app-android-20260330`
- 智能卡 applet：
  改用上游官方 release，看 [官方程序下载验真与校验](docs/官方程序下载验真与校验.zh-CN.md)

以后如果让 AI 重建正式发布版，先跑这几条，不要自己猜 tag：

```bash
bash scripts/rebuild_official_release.sh --list
bash scripts/rebuild_official_release.sh firmware-clean
bash scripts/rebuild_official_release.sh wallet-release
```

现在这几条的含义要记住：

- `firmware-clean`：跟随当前 `HEAD` 重建 clean 固件，不再回到旧的 `offline-signer-clean-source-20260410b`
- `wallet-release`：仍然按冻结 release source tag 重建
- 如果以后真要重建旧的 `20260410b` 固件，改用 `firmware-public-20260410b-clean`
- 如果当前工作区还有未提交的源码/脚本改动，`firmware-clean` 会直接拒绝，避免你以为编到的是“最新功能”但实际只拿了旧 `HEAD`

如果要的是“当前工作区最新固件”，而且连未提交改动也要一起带进包里，就不要只跑上面那条 `firmware-clean`。

直接用：

```bash
bash scripts/build_current_firmware.sh
```

这条命令会直接刷新：

- `dist/system-update-latest.img.xz`
- `dist/system-update-latest.img.xz.sha256`
- `dist/system-update-latest.build-info.txt`

并清掉旧的 `system-update-current-test-*` / `system-update-current-latest*` 测试包，避免再混到老产物。

区别一句话记住：

- `bash scripts/build_current_firmware.sh`：当前工作区最新，允许带未提交改动
- `bash scripts/rebuild_official_release.sh firmware-clean`：当前 `HEAD` 的 clean 固件
- 如果 `firmware-clean` 提示“还有未提交的构建相关改动”，那就说明它在帮你拦截“误编成旧版本”

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
  安卓高安全观察钱包，当前主打 `Arbitrum One` 观察地址、`WalletConnect v2` 协调、树莓派离线签名、`BTC xpub/ypub/zpub` 观察账户原型，以及 `OKX Wallet / Bitget Wallet` Web3 二维码桥接
- `backups/satochip-utils/`
  `Tails` 离线卡初始化工具备份

先看这些入口，别先翻源码：

- [零基础第一次上手教程](docs/零基础第一次上手教程.zh-CN.md)
- [逐屏真实 UI 截图版第一次上手教程](docs/逐屏截图版第一次上手教程.zh-CN.md)
- [真机实拍逐屏截图采集清单](docs/真机实拍逐屏截图采集清单.zh-CN.md)
- [全功能操作总手册](docs/全功能操作总手册.zh-CN.md)
- [第一次小额测试完整流程](docs/第一次小额测试完整流程.zh-CN.md)
- [树莓派菜单逐项说明](docs/树莓派菜单逐项说明.zh-CN.md)
- [常见故障一问一答](docs/常见故障一问一答.zh-CN.md)
- [三条常用流程速查卡](docs/三条常用流程速查卡.zh-CN.md)
- [一页式总导航](docs/一页式总导航.zh-CN.md)
- [快速开始](docs/快速开始.zh-CN.md)
- [官方程序下载验真与校验](docs/官方程序下载验真与校验.zh-CN.md)
- [SeedKeeper 与 SatochipApplet 分工指南](docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md)
- [固定正式发布重建入口](docs/固定正式发布重建入口.zh-CN.md)
- [非 GitHub 关键备份清单](docs/非GitHub关键备份清单.zh-CN.md)
- [版本时间线与发布入口](docs/版本时间线与发布入口.zh-CN.md)
- [真机全套回归清单](docs/真机全套回归清单.zh-CN.md)
- [离线签名器一页备忘](docs/离线签名器一页备忘.zh-CN.md)
- [离线签名器使用教程](docs/离线签名器使用教程.zh-CN.md)
- [离线熵创建助记词教程](docs/离线熵创建助记词教程.zh-CN.md)
- [BIP85子助记词使用教程](docs/BIP85子助记词使用教程.zh-CN.md)
- [父助记词分仓到多张子卡操作手册](docs/父助记词分仓到多张子卡操作手册.zh-CN.md)
- [父助记词分仓执行清单](docs/父助记词分仓执行清单.zh-CN.md)
- [父助记词分仓模板-3张卡](docs/父助记词分仓模板-3张卡.zh-CN.md)
- [父助记词分仓模板-4张卡](docs/父助记词分仓模板-4张卡.zh-CN.md)
- [钛板打孔备份助记词教程](docs/钛板打孔备份助记词教程.zh-CN.md)
- [长期维护总入口](docs/长期维护总入口.zh-CN.md)
- [固件与源码对应关系](docs/固件与源码对应关系.zh-CN.md)

## 现在该用什么

| 你要做的事 | 该看哪里 | 当前产物/入口 |
| --- | --- | --- |
| 给 `TokenPocket` 做手机端扫码与智能卡签名 | `app/` | `bash scripts/build_tp_relay_apk.sh` |
| 用自己的安卓观察钱包发起 EVM / BTC 冷签 | `wallet/` | `bash scripts/build_wallet_release.sh` |
| 给 `OKX Wallet / Bitget Wallet` 做 Web3 二维码桥接 | `wallet/` | `DApp -> Web3 钱包桥接` |
| 想用骰子 / 扑克牌 / 16进制自己离线创建助记词 | 树莓派离线签名器 | [离线熵创建助记词教程](docs/离线熵创建助记词教程.zh-CN.md) |
| 给 `BlueWallet` 做 `BTC PSBT` 冷签 | 树莓派离线签名器 | [离线签名器使用教程](docs/离线签名器使用教程.zh-CN.md) |
| 想系统搞懂 `BIP85` 子助记词 | 树莓派离线签名器 | [BIP85子助记词使用教程](docs/BIP85子助记词使用教程.zh-CN.md) |
| 想把父助记词拆成多张子卡分仓 | 树莓派离线签名器 | [父助记词分仓到多张子卡操作手册](docs/父助记词分仓到多张子卡操作手册.zh-CN.md) |
| 想照着打勾执行分仓 | 树莓派离线签名器 | [父助记词分仓执行清单](docs/父助记词分仓执行清单.zh-CN.md) |
| 想直接套 3 张卡模板 | 树莓派离线签名器 | [父助记词分仓模板-3张卡](docs/父助记词分仓模板-3张卡.zh-CN.md) |
| 想直接套 4 张卡模板 | 树莓派离线签名器 | [父助记词分仓模板-4张卡](docs/父助记词分仓模板-4张卡.zh-CN.md) |
| 想把助记词做成钛板/钢板备份 | 树莓派离线签名器 | [钛板打孔备份助记词教程](docs/钛板打孔备份助记词教程.zh-CN.md) |
| 刷树莓派固件 | `dist/` | `system-update-latest.img.xz` |
| 给智能卡刷官方 applet | 官方 release | [官方程序下载验真与校验](docs/官方程序下载验真与校验.zh-CN.md) |
| 在 `Tails` 里初始化 `Satochip` 卡、设 PIN、导助记词 | `backups/satochip-utils/` | 对应中文教程 |

## 当前最重要的树莓派正式镜像

当前默认固件出口就是：

- `dist/system-update-latest.img.xz`
- `dist/system-update-latest.img.xz.sha256`
- `dist/system-update-latest.build-info.txt`
- 当前 clean 固件入口：
  `bash scripts/rebuild_official_release.sh firmware-clean`
- 当前最新工作区入口：
  `bash scripts/build_current_firmware.sh`
- 历史 `20260410b` 冻结固件入口：
  `bash scripts/rebuild_official_release.sh firmware-public-20260410b-clean`

默认规则现在是：

- `firmware-clean` 跟随当前 `HEAD`
- `build_current_firmware.sh` 跟随当前工作区，允许带未提交改动
- 旧的 `20260410b` 只有在显式选择历史 profile 时才会重建

当前主线固件已经把这次最重要的修复和验证一起带上：

- 小屏 UI 全面收口，长内容优先改成摇杆上下滚动，不再频繁硬拆分页
- 签名后先看人能读懂的摘要，再决定是否显示二维码
- 写卡后自动回读核验，检查指纹、`xpub / zpub`、首个地址和测试签名
- 修复 `查看助记词` 滚到底部容易贴住按钮的问题
- 修复 `拍照创建助记词` 后查看原始熵不显示的问题
- 固件 smoke、桌面模拟、真实 UI 截图和模块导入检查一起补齐

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
- `智能卡工具`
- `固件自检`

## 四条常用使用链路

### 1. 自己的安卓钱包 `satochip-wallet-release.apk`

1. 手机生成待签名二维码
2. 树莓派进 `扫码签名`
3. 输入智能卡 `PIN`
4. 树莓派先显示签名摘要
5. 确认后点 `显示签名二维码`
6. 手机扫回并人工确认广播

### 2. `BlueWallet`

1. `BlueWallet` 显示 `BTC PSBT` 动态二维码
2. 树莓派进 `扫码签名`
3. 输入智能卡 `PIN`
4. 树莓派先显示签名摘要
5. 确认后点 `显示签名二维码`
6. `BlueWallet` 扫回并广播

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

如果 `TokenPocket` 显示的签名请求二维码太密，当前实测可以先用这个办法顶住：

1. 先让 `TP` 把签名二维码完整显示出来，并录屏几秒
2. 打开相册里的这段录屏
3. 播放录屏时双指稍微放大，让二维码尽量铺满屏幕，但四边不要被裁掉
4. 保持手机亮度较高，再让树莓派或安卓中转 App 去扫这段放大后的录屏

注意：

- 如果是动态二维码，不要截成单张图；要让录屏里的二维码完整循环播放
- 放大时只做适度放大，四个角必须都还在屏幕里

### 4. `OKX Wallet / Bitget Wallet`

这条线走 `wallet/`，不是 `app/`。

1. 安卓观察钱包进 `DApp -> Web3 钱包桥接`
2. 确认首页已经添加并选中观察地址
3. 点 `绑定观察地址`，树莓派扫描后核对并导出公开 Web3 账户
4. 手机点 `显示连接码`
5. `OKX Wallet / Bitget Wallet` 扫手机连接码
6. Web3 钱包发起签名时，手机点 `扫码签名请求`
7. 手机把高密度请求码转成树莓派更容易扫的中转码
8. 树莓派签名后，直接显示原钱包可扫的结果码
9. `OKX Wallet / Bitget Wallet` 直接扫树莓派结果码继续广播或完成签名

注意：

- 只有第 `3` 步绑定观察地址时，手机需要扫回树莓派导出的公开账户码
- 真正签名时，结果不再扫回手机，而是原钱包直接扫树莓派结果码

如果 `Bitget Wallet` 的签名请求二维码太密，当前也可以直接套用上面的“先录屏、再放大播放录屏”办法，再让安卓观察钱包或树莓派去扫。

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

如果要的是当前工作区最新树莓派固件，而不是固定正式版，用下面这条：

```bash
bash scripts/build_current_firmware.sh
```

它会把 `dist/system-update-latest.img.xz` 更新成当前工作区最新固件。

### 树莓派固件

```bash
bash scripts/build_pi_firmware_from_snapshot.sh
bash scripts/check_release_artifacts.sh
```

### 安卓智能卡 App

```bash
bash scripts/build_tp_relay_apk.sh
```

这组 APK 按需构建，不保证长期常驻仓库 `dist/`。

### 安卓观察钱包

```bash
bash scripts/build_wallet_release.sh
```

## 最容易写错的地方

- `wallet/` 当前不是内置 `Hyperliquid` 浏览器钱包。
- `wallet/` 现在是高安全观察钱包 + `WalletConnect` 协调器 + `OKX Wallet / Bitget Wallet` Web3 桥接。
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

- [零基础第一次上手教程](docs/零基础第一次上手教程.zh-CN.md)
- [逐屏真实 UI 截图版第一次上手教程](docs/逐屏截图版第一次上手教程.zh-CN.md)
- [真机实拍逐屏截图采集清单](docs/真机实拍逐屏截图采集清单.zh-CN.md)
- [全功能操作总手册](docs/全功能操作总手册.zh-CN.md)
- [第一次小额测试完整流程](docs/第一次小额测试完整流程.zh-CN.md)
- [树莓派菜单逐项说明](docs/树莓派菜单逐项说明.zh-CN.md)
- [常见故障一问一答](docs/常见故障一问一答.zh-CN.md)
- [三条常用流程速查卡](docs/三条常用流程速查卡.zh-CN.md)
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
