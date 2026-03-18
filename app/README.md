# 智能卡 App（TP 签名中转）

这个目录对应的是给 `TokenPocket` 商业钱包配套使用的安卓工程。

它不是独立钱包。

## 作用

- 手机先扫 TP 动态二维码
- 再把静态中转码给树莓派扫描
- 专门用于 TP 商业钱包签名中转

## 对应 APK

- [TP 签名中转 Release 页面](https://github.com/akg5188/tp-satochip-signer/releases/tag/tp-relay-android-20260316)
- [TP 签名中转 APK](https://github.com/akg5188/tp-satochip-signer/releases/download/tp-relay-android-20260316/tp-qr-relay-android-latest.apk)

## 不要混用

如果你要找的是：

- 资产页
- 转账
- Hyperliquid
- 独立钱包

那应该去看：

- [../wallet/README.md](../wallet/README.md)
