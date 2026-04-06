# SeedKeeper 与 SatochipApplet 分工指南

这份文档只回答 4 件事：

- `SeedKeeper` 和 `SatochipApplet` 到底是不是同一个东西
- 同一张 `J3R180` 卡能不能同时装两种 applet
- 当前这套树莓派固件、官方 `SeedSigner` 固件、以及本仓库分别能做什么
- 以后最稳该怎么分工，时间久了也不容易搞混

## 1. 先记住最短结论

- `SeedKeeper` 和 `SatochipApplet` 不是同一个 applet
- 它们都可以装在 `J3R180` 这类卡上，但用途不同
- 技术上同一张卡也可以同时装两种 applet，但当前长期建议已经改成：`一张卡只装一个程序`
- 当前官方 `SeedSigner` 固件不能直接给卡刷 applet
- 当前本仓库的树莓派固件也不能直接给卡切换 `SeedKeeper / SatochipApplet`
- 最稳的长期方案就是：`两张卡分工，一张卡只装一个程序`

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

## 3. 为什么不建议把同一张卡拿来回重刷

技术上“同一张卡安装两个 applet”完全可能。
但你现在的实机结果已经说明：长期正式使用时，不应该再把“双 applet 共卡”当成标准方案。

原因：

- 来回刷 applet 本身就是高风险操作
- 原来的 `PIN`、标签、卡内状态不能指望完整保留
- 很容易把“这张卡现在到底是哪一种 applet”搞混
- 以后恢复或验卡时，最容易因为记错流程而出错

如果你只是偶尔实验，可以单独拿一张测试卡折腾。
但长期正式使用时，现在更稳的建议已经改成：

- `SeedKeeper` 一张专用卡
- `SatochipApplet` 一张专用卡
- 不再把双 applet 共卡当成长期标准方案

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
- 用 `SeedKeeper` 真随机创建标准 `BIP39` 助记词
- 从 `SeedKeeper` 导入助记词
- 在 `查看和管理卡内助记词` 里直接看可明文导出的助记词
- 在 `查看和管理卡内助记词` 里直接删除这些助记词
- 查看 `BIP39` 序号
- 查看标准 `BIP39` 原始熵 `HEX`
- 把原始熵 `HEX` 显示成二维码，便于手机扫去 `BIP39` 网站复核
- `BIP85` 子助记词
- 二次加密 / 二次还原
- 钢板数字流程
- 把当前助记词或 `BIP85` 子助记词写入已安装 `SatochipApplet` 的卡
- 把当前助记词或 `BIP85` 子助记词写入 `SeedKeeper`
- 把二次加密后的假助记词保存到 `SeedKeeper`
- 从 `SeedKeeper` 把二次加密后的假助记词加载回树莓派继续二次还原
- 进入 `SeedKeeper` 功能菜单
- 分别更改 `Satochip PIN / SeedKeeper PIN`
- 分别重置 `Satochip / SeedKeeper`
- 进入 `Satochip` 功能菜单
- 用 `Satochip` 派生地址、导出 `xpub/zpub`、参与签名

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
- 写卡前先按固定 `tag + 文件名 + SHA256` 做验真：
  [官方程序下载验真与校验](官方程序下载验真与校验.zh-CN.md)

本仓库现在不再维护 `SatochipApplet` 的本地 `CAP` 归档。
如果以后真的要刷 applet，统一改走上游官方 release，并先做固定 tag / 文件名 / `SHA256` 验真：

- [官方程序下载验真与校验](官方程序下载验真与校验.zh-CN.md)

## 7. 最稳的实际方案

### 方案 A：最稳的长期分工

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

### 方案 B：一张卡来回刷

不推荐，只适合单独测试卡。

## 8. 你现在这张卡属于哪种情况

先用这个命令核对：

```bash
java -jar gp.jar --list
```

如果输出里同时有：

- `APP: 5361746F4368697000 (SELECTABLE)`
- `APP: 536565644B656570657200 (SELECTABLE)`

那就说明你这张卡已经同时装好了：

- `SatochipApplet`
- `SeedKeeper`

这时最准确的说法不是“它到底是哪一种卡”，而是：

- 这是一张同时装有 `SatochipApplet` 和 `SeedKeeper` 的卡
- 可以继续拿来做测试或临时使用
- 但不再建议把它当成长期正式方案

## 9. 以后最不容易出错的操作顺序

### 你现在就想稳定使用

1. 准备两张专用卡
   - `SeedKeeper` 一张
   - `SatochipApplet` 一张
2. 用本仓库当前树莓派固件
3. 需要时在“助记词工具”里导入或创建助记词
   - 如果想优先用卡内真随机，就先点 `智能卡真随机创建助记词`
4. 在“已加载助记词”里查看：
   - `查看 BIP39 序号`
   - `查看原始熵(HEX)`
   - `显示二维码`
5. 需要存到卡里时：
   - 存到 `SatochipApplet` 就点 `写入当前助记词到智能卡`
   - 存到 `SeedKeeper` 就点 `写入当前助记词到 SeedKeeper`
6. 需要进一步管卡时，再去“智能卡工具”里：
   - `SeedKeeper 功能`
   - `Satochip 功能`
   - `完整智能卡菜单`
   - `保存二次加密助记词到 SeedKeeper`
   - `从 SeedKeeper 加载二次加密助记词`
   - `更改 Satochip PIN / 更改 SeedKeeper PIN`
   - `重置 Satochip / 重置 SeedKeeper`

如果你当前手里还是双 applet 共卡：

- 日常查看/导入/签名还可以继续用
- 但不要在固件里做恢复出厂

`Javacard / GlobalPlatform` 刷卡维护功能现在不再放在树莓派固件主菜单里。

原因是：

- 风险高
- 容易把已经装好的双 applet 卡弄乱
- 日常使用几乎不需要

如果你以后真的要刷 applet，请改走电脑端离线教程，不要在树莓派日常菜单里碰。

## 10. 如果以后忘了，先看哪里

- [官方程序下载验真与校验](官方程序下载验真与校验.zh-CN.md)
- [离线签名器使用教程](离线签名器使用教程.zh-CN.md)
- [固件下载与写入指南](固件下载与写入指南.zh-CN.md)
- [../backups/satochip-utils/Tails-离线使用教程.zh-CN.md](../backups/satochip-utils/Tails-离线使用教程.zh-CN.md)
