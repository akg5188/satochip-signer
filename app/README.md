# 智能卡 App（TokenPocket 配套）

这个目录对应安卓“智能卡”App。

按当前源码，它不是独立钱包，而是一个离线冷签辅助工具：

- 扫描 `TokenPocket` 请求二维码
- 配合智能卡直接签名
- 显示回扫给 `TP` 的结果二维码
- 可选把 `TP` 动态码转成树莓派更容易扫的静态码

当前 App 不申请 `INTERNET` 权限。

## 主要能力

- 支持 `NFC` 贴卡签名
- 支持 `USB-OTG + ACR39U` 读卡器签名
- 支持 `signTransaction`
- 支持 `personalSign`
- 支持 `signTypedData / signTypeDataV4`
- 支持把 `TP` 动态请求拆成树莓派静态中转二维码

## 不负责什么

- 不做资产页
- 不做观察钱包
- 不保存助记词
- 不替代 `BlueWallet`

## 标准构建

```bash
bash scripts/build_tp_relay_apk.sh
```

输出：

- `dist/tp-qr-relay-android-latest.apk`
- `dist/tp-qr-relay-android-latest.apk.sha256`
- `dist/tp-qr-relay-android-latest.build-info.txt`

这些是本机构建产物。它们会在你本地 `dist/` 里生成，但不代表仓库里一定长期保留同名文件。

## 签名说明

当前 `app/build.gradle.kts` 的规则是：

- 有 `keystore.properties` 就用正式 keystore
- 没有就回退到 `debug` 签名

另外，旧式数组型 `signTypedDataLegacy` 目前仍不支持；`TP` 当前这条链路里沿用的是 `signTypeDataV4` 这个历史拼写。

所以它适合自己安装测试，但如果你想长期平滑升级，最好尽早换成自己的正式 keystore。

## 文档入口

- [使用教程](docs/使用教程.zh-CN.md)
- [开发维护指南](docs/开发维护指南.zh-CN.md)
- [安卓构建环境准备](../docs/安卓构建环境准备.zh-CN.md)

## 如果你要的是观察钱包

那应该去：

- [../wallet/README.md](../wallet/README.md)
