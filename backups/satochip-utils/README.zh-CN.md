# Satochip-Utils 备份说明

这个目录对应的是 `Satochip-Utils` 的离线备份。

它的用途很明确：

- 给 `J3R180` 卡设置 `PIN`
- 给卡导入或生成 `BIP39` 助记词
- 适合在 `Tails OS` 这种离线环境中使用

它不是：

- `J3R180` 卡固件
- 树莓派固件
- 安卓 APK

## 目录内容

- `Satochip-Utils-backup-20260303.bundle`
  上游仓库的离线 git bundle 备份
- `README-BUNDLE.md`
  bundle 恢复命令
- [Tails-离线使用教程.zh-CN.md](Tails-离线使用教程.zh-CN.md)
  在 `Tails OS` 里安装依赖、设置 100% 显示缩放、运行工具、设置 `PIN` 和助记词的完整教程

## 上游与备份来源

- 上游项目：`Toporin/Satochip-Utils`
- 上游地址：`https://github.com/Toporin/Satochip-Utils`
- 备份仓库：`akg5188/satochip-utils-backup`
- 备份地址：`https://github.com/akg5188/satochip-utils-backup`

## 什么时候看这里

如果你当前要做的是：

- 用读卡器连接 `J3R180`
- 初始化卡
- 设置 `PIN`
- 导入 12/24 词助记词

那就看这里。

如果你要做的是：

- 给卡写入 applet 固件

那去看：

- [../../card-applet/README.zh-CN.md](../../card-applet/README.zh-CN.md)

## 离线恢复

如果以后上游仓库没了，仍然可以用本目录里的 bundle 恢复源码。

最简单的恢复命令：

```bash
git clone Satochip-Utils-backup-20260303.bundle Satochip-Utils-restore
```

更完整的说明见：

- [README-BUNDLE.md](README-BUNDLE.md)
