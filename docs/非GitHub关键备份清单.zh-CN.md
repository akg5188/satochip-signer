# 非 GitHub 关键备份清单

这页只回答一个问题：

- 如果以后电脑全删了，哪些东西`不在 GitHub`，但想重建出同一套正式发布件就必须提前备份？

## 1. 树莓派固件

### 想重建当前 clean 正式固件

只靠 GitHub 基本就够了。

你至少需要：

- GitHub 仓库源码
- 对应正式源码冻结 tag
- 正式镜像的 `.sha256`
- 正式镜像的 `.build-info.txt`

现在这套都已经在仓库里：

- `release-manifest.json`
- `scripts/rebuild_official_release.sh`
- `scripts/check_named_release.sh`
- `dist/system-update-latest.img.xz.sha256`
- `dist/system-update-latest.build-info.txt`

所以固件这条线，通常`不需要额外备份私有文件`。

## 2. 安卓观察钱包 `wallet/`

### 想重建出和当前正式 APK `一模一样`

光靠 GitHub 不够，必须保住下面这些：

- `wallet/keystore.properties`
- `wallet/keystore.properties` 里 `storeFile` 指向的正式 keystore 文件
- `storePassword`
- `keyAlias`
- `keyPassword`

原因：

- 正式 APK 是`签名产物`
- 源码一样，不等于签名一样
- keystore 一变，最终 APK 的 `sha256` 就会变
- keystore 一变，旧包通常也不能直接覆盖安装

最稳的做法：

1. 备份 `wallet/keystore.properties`
2. 再备份它引用的 keystore 文件
3. 再把密码单独离线保存

## 3. 安卓“智能卡”App `app/`

### 现在能用不代表以后能重建出同一签名

`app/` 当前逻辑是：

- 有 `app/keystore.properties` 就用正式 keystore
- 没有就会回退到 `debug` 签名

所以如果你以后想：

- 继续发同一个包名的正式版
- 保证平滑覆盖升级
- 保持和以前同一个签名

那也应该备份：

- `app/keystore.properties`
- 它引用的正式 keystore 文件
- `storePassword`
- `keyAlias`
- `keyPassword`

如果你只是临时自己安装测试，`app/` 这条线没有钱包那么严格。

## 4. 不一定要备份，但必须知道怎么恢复

这些一般可以重装，不一定非要离线备份原文件：

- `JDK 17`
- `Android SDK 34`
- `Android Build Tools 35.0.0`
- `platform-tools`
- `local.properties`

但它们的版本要固定，不然结果更容易漂。

## 5. 最短结论

### 只想重建当前正式树莓派固件

- GitHub 基本就够

### 想重建当前正式钱包 APK 且 `sha256` 完全一样

- GitHub `不够`
- 必须同时保住钱包正式 keystore 和密码

### 想重建当前正式智能卡 App 且保持同一签名

- 也应该保住 `app/` 的 keystore 和密码

## 6. 删机前最该做的事

至少单独离线备份这几样：

- `wallet/keystore.properties`
- 钱包正式 keystore 文件
- `app/keystore.properties`
- 智能卡 App 正式 keystore 文件
- 所有 keystore 对应密码

然后再保留 GitHub 仓库本身。

## 7. 以后新的 AI 该看哪里

- [固定正式发布重建入口](固定正式发布重建入口.zh-CN.md)
- [固件与源码对应关系](固件与源码对应关系.zh-CN.md)
- [版本时间线与发布入口](版本时间线与发布入口.zh-CN.md)
- [wallet/docs/固定构建与验包流程](../wallet/docs/固定构建与验包流程.zh-CN.md)
