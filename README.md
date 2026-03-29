# TP Satochip Signer

这个仓库不是单一项目，而是同一套方案下的 5 个部分。

以后时间久了忘了，不要先翻源码，先看下面这 3 个入口：

- [一页式总导航](docs/一页式总导航.zh-CN.md)
- [长期维护总入口](docs/长期维护总入口.zh-CN.md)
- [安卓构建环境准备](docs/安卓构建环境准备.zh-CN.md)
- [固件下载与写入指南](docs/固件下载与写入指南.zh-CN.md)

如果以后要把独立钱包扩到 `BTC` 或闪电网络，先看：

- [独立钱包扩展到BTC与闪电网络方案](docs/独立钱包扩展到BTC与闪电网络方案.zh-CN.md)

## 我现在要做什么

| 现在要做的事 | 去哪个目录 | 看哪份说明 | 下载入口 |
| --- | --- | --- | --- |
| 给 `TokenPocket` 商业钱包做签名中转 | `app/` | [app/README.md](app/README.md) | 对应 Release，或本地执行 `bash scripts/build_tp_relay_apk.sh` 现编 |
| 用独立钱包看资产、转账、连 `Hyperliquid` | `wallet/` | [wallet/README.md](wallet/README.md) | 对应 Release，或本地执行 `bash scripts/build_wallet_release.sh` 生成 `dist/satochip-wallet-release.apk` |
| 给 `J3R180` 卡设置 `PIN` 和助记词 | `backups/satochip-utils/` | [Tails 离线使用教程](backups/satochip-utils/Tails-离线使用教程.zh-CN.md) | 本仓库离线备份 |
| 下载或写入 `J3R180` 卡固件 | `card-applet/` | [card-applet 中文说明](card-applet/README.zh-CN.md) | [卡固件 Release](https://github.com/akg5188/tp-satochip-signer/releases/tag/j3r180-card-firmware-20260318) |
| 下载或写入树莓派固件 | `seedsigner-os/` 和 `dist/` | [seedsigner-os 中文说明](seedsigner-os/README.zh-CN.md) | [树莓派固件稳定备份](dist/system-update-latest.img.xz) |

## 下载总表

| 内容 | 文件名 | 推荐下载位置 | 仓库内稳定备份 |
| --- | --- | --- | --- |
| TP 签名中转安卓 APK | `tp-qr-relay-android-latest.apk` | 对应 Release，或本地执行 `bash scripts/build_tp_relay_apk.sh` 现编 | 默认不回填到 `dist/` 快照 |
| 独立钱包安卓 APK | `satochip-wallet-release.apk` | 对应 Release，或本地生成后回填 `dist/satochip-wallet-release.apk` | `dist/satochip-wallet-release.apk` |
| `J3R180` 卡固件 | `SatoChip-3.0.4.cap` | [j3r180-card-firmware-20260318](https://github.com/akg5188/tp-satochip-signer/releases/tag/j3r180-card-firmware-20260318) | `card-applet/prebuilt/SatoChip-3.0.4.cap` |
| 树莓派固件 | `system-update-latest.img.xz` | 仓库里的稳定文件名 `dist/system-update-latest.img.xz` | `dist/system-update-latest.img.xz` |
| `Tails` 离线卡初始化工具 | `Satochip-Utils-linux-x86_64-0.3.0-beta` 等 | 本地离线包和 `backups/satochip-utils/` | `backups/satochip-utils/` |

## 五个核心部分

| 目录 | 它是什么 | 主要用途 | 不要和什么混用 |
| --- | --- | --- | --- |
| `card-applet` | `J3R180` 智能卡固件 | 卡内签名逻辑、卡固件文件 | 树莓派固件、安卓 APK |
| `seedsigner-os` | 树莓派固件源码 | 设备系统、运行环境、镜像相关 | 卡固件、安卓 APK |
| `wallet` | 独立钱包安卓工程 | 观察钱包、资产、转账、`Hyperliquid` | TP 中转 App |
| `app` | TP 配套安卓工程 | 手机扫码中转签名 | 独立钱包 |
| `backups/satochip-utils` | 离线桌面工具备份 | 设置 `PIN`、导入助记词 | 固件、安卓 APK |

## 两个安卓 APK 一眼区分

| APK | 用途 | 源码目录 |
| --- | --- | --- |
| `tp-qr-relay-android-latest.apk` | 给 `TokenPocket` 商业钱包做签名中转 | `app/` |
| `satochip-wallet-release.apk` | 独立钱包，带资产、转账和 `Hyperliquid` | `wallet/` |

详细说明：

- [两个安卓APK说明](docs/两个安卓APK说明.zh-CN.md)

## 最常用重新编译命令

### 重新编独立钱包

首次换机器前，先看：
[安卓构建环境准备](docs/安卓构建环境准备.zh-CN.md)

```bash
bash scripts/build_wallet_release.sh
```

输出：

```text
dist/satochip-wallet-release.apk
dist/satochip-wallet-release.apk.sha256
```

### 重新编 TP 签名中转 App

首次换机器前，先看：
[安卓构建环境准备](docs/安卓构建环境准备.zh-CN.md)

```bash
bash scripts/build_tp_relay_apk.sh
```

输出：

```text
dist/tp-qr-relay-android-latest.apk
dist/tp-qr-relay-android-latest.apk.sha256
dist/tp-qr-relay-android-latest.build-info.txt
```

### 重新生成树莓派运行时镜像

```bash
bash scripts/build_pi_firmware_from_snapshot.sh
bash scripts/check_release_artifacts.sh
```

### 卡固件优先直接用预编译文件

```text
card-applet/prebuilt/SatoChip-3.0.4.cap
```

## 最短维护顺序

1. 先看 [一页式总导航](docs/一页式总导航.zh-CN.md)，确认这次要动哪一块。
2. 源码和文档先提交成一个干净 commit。
3. 用这个干净 commit 重新编译或重新打包正式产物。
4. 跑 `bash scripts/check_release_artifacts.sh`，确认 `build-info` 里的 `repo_head`、`repo_dirty`、`sha256` 都正确。
5. 再单独提交 `dist/` 里的稳定备份文件。
6. 上传到 GitHub Release 时，以 `build-info` 里的 `repo_head` 对应提交或 tag 作为源码基准。

## 配套文档

- [一页式总导航](docs/一页式总导航.zh-CN.md)
- [长期维护总入口](docs/长期维护总入口.zh-CN.md)
- [安卓构建环境准备](docs/安卓构建环境准备.zh-CN.md)
- [仓库结构说明](docs/仓库结构说明.zh-CN.md)
- [两个安卓APK说明](docs/两个安卓APK说明.zh-CN.md)
- [固件下载与写入指南](docs/固件下载与写入指南.zh-CN.md)
- [3D 打印外壳改造方案](docs/3D打印外壳改造方案.zh-CN.md)
- [快速开始](docs/快速开始.zh-CN.md)
- [维护说明](docs/维护说明.zh-CN.md)
- [树莓派固件构建与备份](docs/树莓派固件构建与备份.zh-CN.md)
