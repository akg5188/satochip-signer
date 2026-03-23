# 智能卡 App（TP 签名中转）

这个目录对应的是给 `TokenPocket` 商业钱包配套使用的安卓工程。

它不是独立钱包。

## 作用

- 手机先扫 TP 动态二维码
- 再把静态中转码给树莓派扫描
- 专门用于 TP 商业钱包签名中转

## 对应 APK

- 仓库内稳定文件名：`dist/tp-qr-relay-android-latest.apk`
- 对应校验文件：`dist/tp-qr-relay-android-latest.apk.sha256`
- 对应构建信息：`dist/tp-qr-relay-android-latest.build-info.txt`

## 文档入口

- [使用教程](docs/使用教程.zh-CN.md)
- [开发维护指南](docs/开发维护指南.zh-CN.md)
- [安卓构建环境准备](../docs/安卓构建环境准备.zh-CN.md)

## 标准构建

优先使用仓库根目录下的标准脚本：

```bash
bash scripts/build_tp_relay_apk.sh
```

输出路径：

```text
dist/tp-qr-relay-android-latest.apk
dist/tp-qr-relay-android-latest.apk.sha256
```

如果你只是想在当前机器上快速直编，也可以：

```bash
cp local.properties.example local.properties
./gradlew :app:assembleRelease --console=plain
```

直编输出：

```text
app/build/outputs/apk/release/app-release.apk
```

## 环境要求

- JDK 17
- Android SDK 34
- Android Build Tools 35.0.0
- Android 5.0 及以上设备

第一次换机器时，优先看：

- [../docs/安卓构建环境准备.zh-CN.md](../docs/安卓构建环境准备.zh-CN.md)

## 当前签名说明

- 当前 `release` 仍使用调试签名，适合你自己安装、备份和继续维护
- 如果以后换了电脑或调试 keystore 变了，覆盖安装旧包可能失败，需要先卸载再装
- 如果你要长期平滑升级，建议尽早换成自己的正式 keystore
- 仓库根目录已经提供 `keystore.properties.example`

如果以后只是忘了整个项目怎么维护，直接看：

- [../docs/长期维护总入口.zh-CN.md](../docs/长期维护总入口.zh-CN.md)

## 不要混用

如果你要找的是：

- 资产页
- 转账
- Hyperliquid
- 独立钱包

那应该去看：

- [../wallet/README.md](../wallet/README.md)
