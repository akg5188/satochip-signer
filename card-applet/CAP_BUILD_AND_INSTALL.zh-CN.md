# Satochip CAP 编译与写卡（J3R180 白卡）

本文档对应本仓库目录：`card-applet/SatochipApplet/`。

如果不修改源码，可直接使用预编译 CAP：

- `card-applet/prebuilt/SatoChip-3.0.4.cap`
- `card-applet/prebuilt/SHA256SUMS.txt`

下载 `gp.jar`、上游官方 CAP、以及固定 `SHA256` 的验真流程，先看：

- [../docs/官方程序下载验真与校验.zh-CN.md](../docs/官方程序下载验真与校验.zh-CN.md)

## 1. 前提条件

- 系统：Linux/Tails（建议离线环境进行助记词导入和关键操作）
- 读卡器：`ACS ACR39U ICC Reader`
- 卡片：`J3R180`（已验证可安装 Satochip applet）
- 工具：
  - `openjdk-11-jdk`
  - `ant`
  - `pcsc-tools`
  - `opensc`
  - `wget`

安装命令：

```bash
sudo apt install -y openjdk-11-jdk ant pcsc-tools opensc wget
```

## 2. 检查读卡器与卡片

```bash
pcsc_scan
```

看到 `ACS ACR39U...` 且 `Card inserted` 即正常。

## 3. 准备 CAP 编译环境

进入 applet 源码目录：

```bash
cd card-applet/SatochipApplet
```

下载 JavaCard SDK 集合到 `sdks/`（`build.xml` 依赖 `sdks/jc304_kit`）：

```bash
git clone --depth=1 https://github.com/martinpaljak/oracle_javacard_sdks sdks
```

说明：

- 上面这条命令是快速拿工具链，不是严格冻结版本
- 如果你以后第一次成功编过，最好把当时的 `oracle_javacard_sdks` 提交号记到你自己的维护记录里
- 不要每次维护都无脑追 `latest`

设置 Java 11：

```bash
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
```

## 4. 编译 CAP

```bash
cd card-applet/SatochipApplet
ant
```

编译成功后会生成：

```text
card-applet/SatochipApplet/SatoChip-3.0.4.cap
```

## 5. 安装 CAP 到卡（GlobalPlatformPro）

下载固定版本 `gp.jar`：

```bash
mkdir -p ~/card-work && cd ~/card-work
wget -O gp.jar \
  https://github.com/martinpaljak/GlobalPlatformPro/releases/download/v25.10.20/gp.jar
```

说明：

- 当前固定版本是 `v25.10.20`
- 对应 `SHA256` 是：
  `c88e0c5093032ec4571571f5397b6174e56bf632667950fa5bb716338534b122`
- 长期维护时，最好把第一次验证通过的 `GlobalPlatformPro` 版本号单独记下来
- 如果你手里已经有一份能稳定装卡的 `gp.jar`，不要随便替换

安装 CAP：

```bash
CAP=/absolute/path/to/SatoChip-3.0.4.cap
java -jar gp.jar -install "$CAP"
java -jar gp.jar -l
```

`-l` 输出中出现：

- `APP: 5361746F4368697000 (SELECTABLE)`
- `PKG: 5361746F43686970 (LOADED)`

表示 applet 已装入并可选择。

## 6. 验证 SELECT AID

```bash
opensc-tool -s 00A40400085361746F43686970
```

返回 `SW1=0x90, SW2=0x00` 代表选择成功。

## 7. 后续流程（简版）

1. 用官方工具离线导入助记词、设置 PIN（你已完成）。
2. 安卓端用本项目 APK 做：
   - 扫 TP 观察钱包请求二维码
   - 贴卡签名
   - 回传签名二维码给 TP

## 8. 安全提醒（必须做）

- 当前很多白卡默认仍是 GP 默认管理密钥（`404142...4F`），这不是安全状态。
- 至少应执行一次卡管理密钥更换（GP key diversification / key update）。
- 若不改管理密钥，攻击者在拿到卡+读卡器后可能执行管理级操作。

## 9. 源码来源说明

- 上游项目：`https://github.com/Toporin/SatochipApplet`
- 本仓库内源码为该项目的可构建快照（已去掉 `.git`、`sdks` 和 `gp` 二进制）。
- 当前快照信息见：
  `card-applet/SatochipApplet/UPSTREAM_SNAPSHOT.txt`
