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
- 如果同一张卡已经同时装好了 `SeedKeeper / SatochipApplet`，就不要为了“更纯粹”再重刷
- 真资金卡不建议把重刷当成日常流程

如果你还没看过两张卡方案，先看：

- [../docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md](../docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md)
- [../docs/官方程序下载验真与校验.zh-CN.md](../docs/官方程序下载验真与校验.zh-CN.md)

## 1. 什么时候用这份教程

### 先检查卡里已经装了什么

先跑：

```bash
java -jar gp.jar --list
```

如果你已经能看到这两行：

```text
APP: 5361746F4368697000 (SELECTABLE)
APP: 536565644B656570657200 (SELECTABLE)
```

那就说明同一张卡上已经同时装好了：

- `SatochipApplet`
- `SeedKeeper`

这时候最稳的做法是：

- 不再重刷
- 直接去用树莓派固件里的对应功能

只有当某个 applet 根本不存在，或者你是在准备白卡时，才继续往下安装。

### 你要刷 `SatochipApplet`

适合：

- 你手里是白卡
- 你想把它变成当前树莓派固件和安卓智能卡 App 可以直接使用的签名卡

### 你要刷 `SeedKeeper`

适合：

- 你想把这张卡变成秘密管理卡
- 或你正在准备单独的秘密管理卡

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
└── SHA256SUMS.expected
```

## 4. 联网时只做一次的准备

如果你现在还有网络，就先把刷卡材料准备好；以后断网后直接刷。

### 4.1 建目录

```bash
mkdir -p ~/下载/j3r180刷卡
cd ~/下载/j3r180刷卡
```

### 4.2 下载固定版本 `gp.jar`

```bash
wget -O gp.jar \
  https://github.com/martinpaljak/GlobalPlatformPro/releases/download/v25.10.20/gp.jar
```

### 4.3 准备 `SatochipApplet` 的 CAP

本项目默认使用仓库里已经固定归档并校验过的预编译 CAP：

```bash
cp /home/ak/tp-satochip-signer/card-applet/prebuilt/SatoChip-3.0.4.cap .
```

注意：

- 这张 `SatoChip-3.0.4.cap` 是本项目固定配套文件
- 不要和上游官方 `Toporin/SatochipApplet` 的 `SatoChip-0.12-05.cap` 混用

### 4.4 准备 `SeedKeeper` 的 CAP

从上游官方固定 release 下载标准版 CAP：

```bash
wget -O SeedKeeper-v0.2-0.1.cap \
  https://github.com/Toporin/Seedkeeper-Applet/releases/download/v0.2-0.1/SeedKeeper-v0.2-0.1.cap
```

如果你明确要 NDEF 版，再额外下载：

```bash
wget -O SeedKeeper-Ndef-v0.2-0.1.cap \
  https://github.com/Toporin/Seedkeeper-Applet/releases/download/v0.2-0.1/SeedKeeper-Ndef-v0.2-0.1.cap
```

### 4.5 写入固定校验清单并验证

```bash
cat > SHA256SUMS.expected <<'EOF'
c88e0c5093032ec4571571f5397b6174e56bf632667950fa5bb716338534b122  gp.jar
ded5a2efbb8a417109a629dd0e0e09711e1ea2c90da4bab79e719cef9f933ec7  SatoChip-3.0.4.cap
28dbae3c7c130a6f7d0e6d05f41386ffd93976fd290eaa5d8db708b9903dabcd  SeedKeeper-v0.2-0.1.cap
EOF
```

如果你下载了 NDEF 版，就在清单里额外加这一行：

```text
ef776360415ee0c64881b1e36339ffba815231aab2406014559d18fdaa632c9b  SeedKeeper-Ndef-v0.2-0.1.cap
```

开始校验：

```bash
sha256sum -c SHA256SUMS.expected
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

## 7. 安装 `SatochipApplet`

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

### 7.4 如果同一张卡还想继续装 `SeedKeeper`

可以直接继续看第 `8` 节。
同一张卡可以同时装两种 applet，不需要先把 `SatochipApplet` 卸掉。

### 7.5 接下来做什么

刷完以后，再去初始化卡、设置 `PIN`、导入助记词：

- [../backups/satochip-utils/Tails-离线使用教程.zh-CN.md](../backups/satochip-utils/Tails-离线使用教程.zh-CN.md)

## 8. 安装 `SeedKeeper`

这部分同样按“以后直接复制粘贴”来写。

### 8.1 进入目录

```bash
cd ~/下载/j3r180刷卡
```

### 8.2 找到 CAP 文件

```bash
CAP="$(find . -maxdepth 1 -name 'SeedKeeper-v0.2-0.1.cap' | head -n 1)"
echo "$CAP"
```

如果输出为空，说明当前目录没有准备好 `SeedKeeper` 的 CAP。

### 8.3 安装 `SeedKeeper`

```bash
CAP="$(find . -maxdepth 1 -name 'SeedKeeper-v0.2-0.1.cap' | head -n 1)"
[ -n "$CAP" ] || { echo '没找到 SeedKeeper CAP'; exit 1; }
java -jar gp.jar -install "$CAP"
java -jar gp.jar -l
```

### 8.4 安装后确认它已经和 `SatochipApplet` 共存

```bash
java -jar gp.jar --list
```

如果同一张卡上要同时保留两种 applet，最后至少应能看到：

```text
APP: 5361746F4368697000 (SELECTABLE)
APP: 536565644B656570657200 (SELECTABLE)
```

### 8.5 接下来做什么

刷完 `SeedKeeper` 后，后续不要再把“刷卡”和“树莓派里的日常使用”混在一起。

当前树莓派固件里已经能直接做的，是：

- `助记词工具 -> 智能卡真随机创建助记词`
- `智能卡工具 -> SeedKeeper 功能`
- `更改 SeedKeeper PIN`
- `重置 SeedKeeper`
- 把当前助记词或 `BIP85` 子助记词写入 `SeedKeeper`

当前树莓派固件里仍然不能做的，是：

- 给白卡安装 `SeedKeeper` applet
- 卸载/切换 applet
- 把刷 applet 当成固件菜单里的一个步骤

所以顺序应该是：

1. 先在普通系统里用 `gp.jar` 把 applet 安装好
2. 再回到树莓派固件里做日常的 `SeedKeeper / Satochip` 使用

## 9. 如果你一定要改动卡上的 applet 组合

我不推荐把“重刷”写成日常流程。

如果你只是测试：

1. 先确认这张卡不是装资金的正式卡
2. 先跑一次 `java -jar gp.jar --list`
3. 记录当前已经安装的 `APP` 和 `PKG`
4. 先离线备份你当前需要保留的信息
5. 再安装缺少的 applet
6. 安装后重新跑 `java -jar gp.jar --list`

不要假设：

- 原 `PIN` 一定还在
- 原标签一定还在
- 原卡内秘密还能无损保留

## 10. 最容易踩坑的点

- `SeedKeeper` 和 `SatochipApplet` 不是同一个东西
- 如果卡里已经同时有两种 applet，就没必要再来回折腾
- 官方 `SeedSigner` 固件不能直接刷 applet
- 本仓库树莓派固件也不能直接刷 applet
- `Satochip-Utils` 主要讲的是 `Satochip` 卡初始化，不是 `SeedKeeper` 刷卡

## 11. 如果以后忘了先看哪里

- [README.zh-CN.md](README.zh-CN.md)
- [../docs/官方程序下载验真与校验.zh-CN.md](../docs/官方程序下载验真与校验.zh-CN.md)
- [CAP_BUILD_AND_INSTALL.zh-CN.md](CAP_BUILD_AND_INSTALL.zh-CN.md)
- [../docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md](../docs/SeedKeeper与SatochipApplet分工指南.zh-CN.md)
- [../backups/satochip-utils/Tails-离线使用教程.zh-CN.md](../backups/satochip-utils/Tails-离线使用教程.zh-CN.md)
