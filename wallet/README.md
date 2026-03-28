# Satochip High-Security Watch Wallet (Android)

这是仓库里 `wallet/` 目录对应的安卓观察钱包源码。

如果你要找的是整仓库其他模块，比如树莓派离线签名器、系统镜像或主仓库级发布脚本，不要只看这里，请回到仓库根目录：

- [仓库首页说明](../README.md)

当前这版 `wallet` 的定位已经固定为：

- `Arbitrum One` 高安全观察钱包
- 手机端 DApp / WalletConnect 协调器
- 树莓派离线签名请求二维码生成器
- 树莓派签名结果回传后的人工确认广播器
- `BTC` 观察账户原型入口

它不是热钱包，也不在手机里保存私钥。

## 现在能做什么

- 添加多个 `EVM` 观察地址并切换当前地址
- 查看 `Arbitrum One` 上的 `ETH / USDC / USDT` 余额和美元估值
- 构造转账请求，生成给树莓派扫描的签名二维码
- 扫描树莓派返回的签名结果，并在手机上人工确认后广播
- 通过 `WalletConnect v2`、二维码或手动粘贴原始请求来协调 `DApp` 签名
- 导入 `BTC xpub / ypub / zpub` 观察账户，并准备 `BTC` 转账冷签请求

## 明确不做什么

- 不内置 `Hyperliquid` 或其他 DApp 浏览器
- 不在手机上保存私钥或直接热签名
- 不自动信任所有 DApp
- 不在锁屏后保留活跃 DApp 会话
- 不自动从系统剪贴板读取敏感请求

## 主要安全策略

- 强制使用强生物识别进入钱包和执行关键动作
- 如果检测到 `ADB / USB 调试`、开发者选项、`Root / Magisk / Hook`、`test-keys` 系统镜像、调试器连接，会阻止启动高安全界面
- `WalletConnect` 只接受已验证、`HTTPS` 且主机合法的 DApp
- DApp 信任范围按 `主机 + 链 + 地址` 绑定，并且 `24 小时` 过期
- 手机锁屏或 App 退后台后，会主动清空敏感状态并断开 DApp 会话
- 关键联网主机已做白名单和证书 pinning

## 文档入口

- [用户使用教程](docs/使用教程.zh-CN.md)
- [开发维护指南](docs/开发维护指南.zh-CN.md)
- [固定构建与验包流程](docs/固定构建与验包流程.zh-CN.md)
- [扩展到 BTC 与闪电网络方案](../docs/独立钱包扩展到BTC与闪电网络方案.zh-CN.md)
- [安卓构建环境准备](../docs/安卓构建环境准备.zh-CN.md)

## 本地产物位置

当前目录下的本地构建产物约定为：

- `dist/satochip-wallet-release.apk`
- `dist/satochip-wallet-release.apk.sha256`
- `dist/satochip-wallet-release.build-info.txt`

这些产物默认是本机构建快照，不会自动成为 GitHub Release 页面上的正式发布包。

## 推荐构建方式

优先使用仓库根目录的标准脚本：

```bash
bash scripts/build_wallet_release.sh
```

或者在 `wallet/` 目录下直接用：

```bash
./scripts/build_local_ascii.sh release
```

如果工程路径有中文、空格或其他容易让 Gradle 出问题的字符，优先使用第二种，它会复制到纯英文临时路径再构建。

## 环境要求

- `JDK 17`
- `Android SDK 34`
- `Android Build Tools 35.0.0`
- Linux / Ubuntu 优先

## 发布签名说明

当前 `release` 构建已经禁止回退到 `debug` 签名。

这意味着：

- 你必须准备 `wallet/keystore.properties`
- 例子见 `wallet/keystore.properties.example`
- 以后想让新包覆盖旧包，必须一直使用同一套长期保存的发布 keystore

如果换机器、换 keystore 或把 keystore 弄丢，后续新包会无法覆盖安装旧包。

## 让下次编译保持稳定的关键点

以后只要同时固定下面 4 件事，结果就会稳定很多：

1. 固定源码提交
2. 固定 `JDK / SDK / Build Tools` 版本
3. 固定构建命令
4. 固定同一套发布 keystore

具体操作请直接看：

- [固定构建与验包流程](docs/固定构建与验包流程.zh-CN.md)
