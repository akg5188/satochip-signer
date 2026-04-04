# SeedKeeper 与 SatochipApplet 分工指南

这份文档只回答 4 件事：

- `SeedKeeper` 和 `SatochipApplet` 到底是不是同一个东西
- 为什么不建议一张 `J3R180` 卡来回刷两种 applet
- 当前这套树莓派固件、官方 `SeedSigner` 固件、以及本仓库分别能做什么
- 以后最稳该怎么分工，时间久了也不容易搞混

## 1. 先记住最短结论

- `SeedKeeper` 和 `SatochipApplet` 不是同一个 applet
- 它们都可以装在 `J3R180` 这类卡上，但用途不同
- 当前官方 `SeedSigner` 固件不能直接给卡刷 applet
- 当前本仓库的树莓派固件也不能直接给卡切换 `SeedKeeper / SatochipApplet`
- 最稳的方案是：
  - 一张 `SeedKeeper` 卡负责秘密管理/备份导入导出
  - 一张 `Satochip` 卡负责签名

## 2. 它们分别是干什么的

### `SatochipApplet`

更像硬件钱包 applet，主要负责：

- 卡内保存主种子
- 派生地址、公钥、`xpub/zpub`
- 交易签名
- 当前仓库树莓派固件和安卓智能卡 App 的主力签名对象

### `SeedKeeper`

更像秘密管理 applet，主要负责：

- 保存或导入秘密材料
- 适合做种子管理、备份、迁移
- 可以作为和 `Satochip` 搭配的上游秘密容器

## 3. 为什么不建议一张卡来回刷

技术上“同一张卡重新安装别的 applet”不是完全不可能，但不适合当日常流程。

原因：

- 来回刷 applet 本身就是高风险操作
- 原来的 `PIN`、标签、卡内状态不能指望完整保留
- 很容易把“这张卡现在到底是哪一种 applet”搞混
- 以后恢复或验卡时，最容易因为记错流程而出错

如果你只是偶尔实验，可以单独拿一张测试卡折腾。
但真资金、长期使用、以后还要靠教程回忆时，不建议把同一张卡一会儿刷成 `SeedKeeper`，一会儿又刷回 `SatochipApplet`。

## 4. 当前官方 SeedSigner 固件能不能刷卡

不能。

官方 `SeedSigner` 固件的定位是：

- 树莓派离线种子工具
- 比特币二维码离线签名器

它不是 `JavaCard / GlobalPlatform` 卡管理工具。

所以它不能直接完成：

- 安装 `SeedKeeper` applet
- 安装 `SatochipApplet`
- 卸载/切换 applet

## 5. 当前本仓库树莓派固件能不能刷卡

也不能。

当前这套“离线签名器”固件可以做的是：

- 使用已加载助记词
- 查看 `BIP39` 序号
- 查看标准 `BIP39` 原始熵 `HEX`
- `BIP85` 子助记词
- 二次加密 / 二次还原
- 钢板数字流程
- 把当前助记词或 `BIP85` 子助记词写入已安装 `SatochipApplet` 的卡
- 用智能卡派生地址、导出 `xpub/zpub`、参与签名

它不能直接做的是：

- 给白卡安装 `SatochipApplet`
- 给白卡安装 `SeedKeeper`
- 在同一张卡上来回切换两种 applet

## 6. 那 applet 应该在哪里刷

要刷 applet，仍然应该用一套普通系统里的卡管理工具，例如：

- `GlobalPlatformPro`
- `gp.jar`

推荐方式：

- 一台离线电脑
- 或 `Tails / Live Linux`
- 断网后再写卡

本仓库当前已经整理好的，是 `SatochipApplet` 这条线：

- `card-applet/prebuilt/SatoChip-3.0.4.cap`
- [../card-applet/CAP_BUILD_AND_INSTALL.zh-CN.md](../card-applet/CAP_BUILD_AND_INSTALL.zh-CN.md)
- [../card-applet/J3R180刷SatochipApplet与SeedKeeper.zh-CN.md](../card-applet/J3R180刷SatochipApplet与SeedKeeper.zh-CN.md)

## 7. 最稳的实际方案

### 方案 A：最推荐

两张卡分工：

- `SeedKeeper` 卡：
  - 管理秘密材料
  - 做导入/迁移/长期备份
- `Satochip` 卡：
  - 平时签名
  - 配合树莓派或安卓智能卡 App 使用

优点：

- 职责清楚
- 不需要来回刷 applet
- 教程最容易写清楚
- 以后恢复时也最不容易搞混

### 方案 B：当前最省事

只有一张 `Satochip` 卡，先不碰 `SeedKeeper`。

适合：

- 你现在就想稳定使用树莓派签名、BlueWallet、自己的安卓观察钱包
- 先把“签名工作流”跑稳

### 方案 C：一张卡来回刷

不推荐，只适合单独测试卡。

## 8. 你现在这张卡属于哪种情况

如果你卡里安装的是：

- `SatochipApplet v0.15-0.1: MuSig2 support (beta)`

那它当前就是一张 `Satochip` 签名卡，不是 `SeedKeeper` 卡。

这意味着：

- 能签名
- 能派生地址
- 能导出 `xpub/zpub`
- 能配合当前树莓派固件使用

但不要把它当成“已经变成 SeedKeeper”。

## 9. 以后最不容易出错的操作顺序

### 你只想稳定签名

1. 保持当前 `Satochip` 卡不动
2. 用本仓库当前树莓派固件
3. 需要时导入助记词、查看 `BIP39` 序号、做 `BIP85`
4. 再把要用的助记词写入 `Satochip` 卡

### 你以后真要引入 SeedKeeper

1. 另外准备一张卡
2. 单独刷成 `SeedKeeper`
3. 让 `SeedKeeper` 负责种子管理
4. 让 `Satochip` 继续负责签名
5. 不要拿同一张卡在两种 applet 之间来回刷

## 10. 如果以后忘了，先看哪里

- [离线签名器使用教程](离线签名器使用教程.zh-CN.md)
- [固件下载与写入指南](固件下载与写入指南.zh-CN.md)
- [../card-applet/README.zh-CN.md](../card-applet/README.zh-CN.md)
- [../backups/satochip-utils/Tails-离线使用教程.zh-CN.md](../backups/satochip-utils/Tails-离线使用教程.zh-CN.md)
