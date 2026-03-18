# 智能卡 App（TP 签名中转）

这个目录对应的是给 `TokenPocket` 商业钱包配套使用的安卓工程。

它不是独立钱包。

## 作用

- 手机先扫 TP 动态二维码
- 再把静态中转码给树莓派扫描
- 专门用于 TP 商业钱包签名中转

## 对应 APK

- [TP 签名中转 Release 页面](https://github.com/akg5188/tp-satochip-signer/releases/tag/tp-relay-android-20260318-1956)
- [TP 签名中转 APK](https://github.com/akg5188/tp-satochip-signer/releases/download/tp-relay-android-20260318-1956/tp-qr-relay-android-latest.apk)
- 仓库内稳定文件名：`dist/tp-qr-relay-android-latest.apk`

## 重新编译

1. 在仓库根目录复制配置文件

```bash
cp local.properties.example local.properties
```

2. 把 `local.properties` 里的 `sdk.dir` 改成你机器上的 Android SDK 路径

3. 构建 release APK

```bash
./gradlew :app:assembleRelease --console=plain
```

输出路径：

```text
app/build/outputs/apk/release/app-release.apk
```

如果你只是下载现成包，不需要自己编译，优先去上面的 GitHub Release 页面。

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
