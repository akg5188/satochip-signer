# J3R180 刷 SatochipApplet 与 SeedKeeper 教程

这份教程只讲一件事：

- 怎么在普通 Linux 或 `Tails` 这类离线系统里，给 `J3R180` 卡刷：
  - `SatochipApplet`
  - `SeedKeeper`

目标是以后你只要照着复制粘贴，不用再临时猜命令。

## 0. 先看清楚边界

- 当前官方 `SeedSigner` 固件不能直接给卡刷 applet
- 当前本仓库树莓派固件也不能直接给卡刷 applet
- 刷卡这件事还是要在普通 Linux / `Tails` 终端里做
- 最稳的是两张卡分工，不建议真资金卡来回切换 `SeedKeeper / SatochipApplet`

如果你还没看过两张卡方案，先看：

- [../docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md](../docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md)

## 1. 什么时候用这份教程

### 你要刷 `SatochipApplet`

适合：

- 你手里是白卡
- 你想把它变成当前树莓派固件和安卓智能卡 App 可以直接使用的签名卡

### 你要刷 `SeedKeeper`

适合：

- 你想把这张卡变成秘密管理卡
- 以后和 `Satochip` 卡做两张卡分工

## 2. 你需要准备什么

- 一台 Linux 电脑，或 `Tails OS`
- 一只支持 `PC/SC` 的读卡器，例如 `ACR39U`
- `J3R180` 卡
- `Java`
- `GlobalPlatformPro` 的 `gp.jar`

## 3. 最推荐的目录结构

以后你离线刷卡，建议固定准备这样一个目录：

```text
~/下载/j3r180刷卡/
├── gp.jar
├── SatoChip-3.0.4.cap
├── SeedKeeper-v0.2-0.1.cap
└── SHA256SUMS.local.txt
```

## 4. 联网时只做一次的准备

如果你现在还有网络，就先把刷卡材料准备好；以后断网后直接刷。

### 4.1 建目录

```bash
mkdir -p ~/下载/j3r180刷卡
cd ~/下载/j3r180刷卡
```

### 4.2 下载 `gp.jar`

```bash
wget -O gp.jar https://github.com/martinpaljak/GlobalPlatformPro/releases/latest/download/gp.jar
```

### 4.3 准备 `SatochipApplet` 的 CAP

如果你现在就在本仓库机器上，直接复制：

```bash
cp /home/ak/tp-satochip-signer/card-applet/prebuilt/SatoChip-3.0.4.cap .
```

### 4.4 准备 `SeedKeeper` 的 CAP

从官方仓库取当前提供的预编译 CAP：

```bash
git clone --depth 1 https://github.com/Toporin/Seedkeeper-Applet.git
cp Seedkeeper-Applet/SeedKeeper-*.cap .
```

### 4.5 记一份本地校验

```bash
sha256sum gp.jar SatoChip-3.0.4.cap SeedKeeper-*.cap > SHA256SUMS.local.txt
cat SHA256SUMS.local.txt
```

做完以后，你可以：

- 物理断网
- 或把整个目录拷到一台离线电脑 / `Tails`

## 5. 离线环境里的系统依赖

如果是普通 Debian / Ubuntu / `Tails`，先装这些：

```bash
sudo apt update
sudo apt install -y pcsc-tools opensc default-jre
```

如果你已经完全离线，就要提前把这些 `.deb` 包准备好，再离线安装。

## 6. 每次刷卡前先检查读卡器

```bash
pcsc_scan
```

看到读卡器和插卡状态后，再继续。

## 7. 刷 `SatochipApplet`

下面这段就是以后可以直接复制粘贴的最短流程。

### 7.1 进入目录

```bash
cd ~/下载/j3r180刷卡
```

### 7.2 安装 `SatochipApplet`

```bash
java -jar gp.jar -install ./SatoChip-3.0.4.cap
java -jar gp.jar -l
```

### 7.3 额外确认 applet 可选中

```bash
opensc-tool -s 00A40400085361746F43686970
```

如果返回：

```text
SW1=0x90, SW2=0x00
```

说明这张 `SatochipApplet` 卡已经能被选中。

### 7.4 接下来做什么

刷完以后，再去初始化卡、设置 `PIN`、导入助记词：

- [../backups/satochip-utils/Tails-离线使用教程.zh-CN.md](../backups/satochip-utils/Tails-离线使用教程.zh-CN.md)

## 8. 刷 `SeedKeeper`

这部分同样按“以后直接复制粘贴”来写。

### 8.1 进入目录

```bash
cd ~/下载/j3r180刷卡
```

### 8.2 找到 CAP 文件

```bash
CAP="$(find . -maxdepth 1 -name 'SeedKeeper-*.cap' | head -n 1)"
echo "$CAP"
```

如果输出为空，说明当前目录没有准备好 `SeedKeeper` 的 CAP。

### 8.3 安装 `SeedKeeper`

```bash
CAP="$(find . -maxdepth 1 -name 'SeedKeeper-*.cap' | head -n 1)"
[ -n "$CAP" ] || { echo '没找到 SeedKeeper CAP'; exit 1; }
java -jar gp.jar -install "$CAP"
java -jar gp.jar -l
```

### 8.4 接下来做什么

刷完 `SeedKeeper` 后，后续通常不是去树莓派固件里初始化，而是要用支持 `SeedKeeper` 的桌面或手机工具继续做：

- 设置 `PIN`
- 导入/生成 secret
- 导出给对应目标设备

本仓库当前没有把完整的 `SeedKeeper` 初始化工具链打包进来，所以这一步不要误以为还能继续走 `Satochip-Utils` 教程。

## 9. 如果你一定要同一张卡来回刷

我不推荐把这条路写成“日常流程”。

如果你只是测试：

1. 先确认这张卡不是装资金的正式卡
2. 先离线备份你当前需要保留的信息
3. 再刷新的 applet
4. 刷完后把它当一张全新卡重新初始化

不要假设：

- 原 `PIN` 一定还在
- 原标签一定还在
- 原卡内秘密还能无损保留

## 10. 最容易踩坑的点

- `SeedKeeper` 和 `SatochipApplet` 不是同一个东西
- 这两种 applet 不要在真资金卡上来回切
- 官方 `SeedSigner` 固件不能直接刷 applet
- 本仓库树莓派固件也不能直接刷 applet
- `Satochip-Utils` 主要讲的是 `Satochip` 卡初始化，不是 `SeedKeeper` 刷卡

## 11. 如果以后忘了先看哪里

- [README.zh-CN.md](README.zh-CN.md)
- [CAP_BUILD_AND_INSTALL.zh-CN.md](CAP_BUILD_AND_INSTALL.zh-CN.md)
- [../docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md](../docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md)
- [../backups/satochip-utils/Tails-离线使用教程.zh-CN.md](../backups/satochip-utils/Tails-离线使用教程.zh-CN.md)
