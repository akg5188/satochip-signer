# Tails OS 离线使用教程

这份教程对应的是：

- 系统：`Tails OS`
- 卡：`J3R180`（卡里已经安装好 Satochip applet）
- 读卡器：例如 `ACR39U`
- 工具：`Satochip-Utils`
- 目标：在尽量离线的环境里设置卡的 `PIN`，并导入或生成助记词

## 1. 先看清楚这个工具是做什么的

`Satochip-Utils` 是桌面端卡管理工具，不是固件。

它主要负责：

- 设置卡的 `PIN`
- 设置卡标签
- 导入已有的 `12/24` 词 `BIP39` 助记词
- 或者生成新的助记词写入卡

如果你的卡还是白卡、还没写入 Satochip applet，请先看：

- [../../card-applet/CAP_BUILD_AND_INSTALL.zh-CN.md](../../card-applet/CAP_BUILD_AND_INSTALL.zh-CN.md)

## 2. 离线使用前的重要提醒

`Tails OS` 默认是易失环境。

这意味着：

- 你重启以后，临时安装的软件通常不会自动保留
- 如果完全不联网，`apt` 和 `pip` 都不能临时下载依赖

所以更稳妥的做法是二选一：

### 方案 A：推荐

先在一台联网环境里准备好：

- 本仓库里的 `Satochip-Utils-backup-20260303.bundle`
- 需要的 Debian 包
- 需要的 Python wheel 或源码依赖

然后再带到 `Tails OS` 离线机器上用。

### 方案 B：更省事

先在一次临时联网的 `Tails` 会话里安装依赖，确认工具能跑起来后，再断网完成 `PIN` 和助记词操作。

## 3. 先把显示缩放改成 100%

这个步骤很重要。

如果不是 `100%`，窗口有可能显示不完整，按钮被裁掉，看起来像软件坏了。

操作方法：

1. 打开 `Settings`
2. 进入 `Displays`
3. 找到 `Scale`
4. 选择 `100%`
5. 应用后，重新打开 `Satochip-Utils`

如果改成 `100%` 后仍然觉得界面挤，可以再把分辨率调高一点，但优先保证缩放是 `100%`。

## 4. Tails OS 需要的系统依赖

下面这些依赖来自上游项目的 `requirements.txt`、`setup.py` 和 Linux 构建脚本。

先安装系统层依赖：

```bash
sudo apt update
sudo apt install -y \
  pcscd \
  pcsc-tools \
  libpcsclite1 \
  libpcsclite-dev \
  libnotify4 \
  libgtk-3-0 \
  libsdl2-2.0-0 \
  libsdl2-dev \
  python3-venv \
  python3-pip \
  python3-tk \
  python3-pyscard
```

装好以后启动读卡器服务：

```bash
sudo systemctl enable --now pcscd
```

检查读卡器和卡是否正常：

```bash
pcsc_scan
```

看到读卡器型号和 `Card inserted` 一类信息，说明基础环境正常。

## 5. 从 bundle 恢复源码

假设你当前就在 `backups/satochip-utils/` 目录：

```bash
git clone Satochip-Utils-backup-20260303.bundle Satochip-Utils-restore
cd Satochip-Utils-restore
```

如果你的 `Tails` 里没有 `git`，那就需要提前在别的 Linux 机器上恢复好源码，再把整个目录拷过来。

## 6. 安装 Python 依赖

上游 `requirements.txt` 里当前列出的核心依赖是：

- `customtkinter==5.2.2`
- `mnemonic==0.20`
- `pillow==10.3.0`
- `pysatochip==0.15.1`
- `pyscard==2.0.9`
- `pyqrcode`

推荐在虚拟环境里安装：

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

如果你完全离线，那上面这一步不能直接联网下载。

这时你要提前准备好：

- Python wheel 缓存
- 或者在另一台 Linux 机器上先把整个 `.venv` / 可运行环境准备好，再拷到 `Tails`

## 7. 启动工具

在源码目录里运行：

```bash
source .venv/bin/activate
python satochip_utils.py
```

如果你手上不是源码，而是别人已经打好的 Linux 可执行包，那么优先保证：

- `Scale` 已设成 `100%`
- `pcscd` 已启动
- 读卡器已被系统识别

## 8. 设置 PIN

插入读卡器和卡之后：

1. 打开 `Satochip-Utils`
2. 进入 `Setup my card`
3. 输入新的 `PIN`
4. 再确认一次 `PIN`
5. 点击保存

建议：

- `PIN` 长度保持在工具允许范围内
- 设置一个你能稳定记住、但不容易被猜到的值

## 9. 导入或生成助记词

设置完 `PIN` 后，再进入种子相关页面。

你可以选择两种方式：

### 导入已有助记词

适合你已经有一套 `12/24` 词助记词。

操作：

1. 进入 `Setup Seed` 或导入种子页面
2. 选择导入已有助记词
3. 输入 `12` 或 `24` 词 `BIP39` 助记词
4. 如果你用了 `passphrase`，按页面提示一并填写
5. 确认并写入卡

### 生成新助记词

适合你要新建一张卡的钱包身份。

操作：

1. 进入生成助记词页面
2. 选择 `12` 词或 `24` 词
3. 记录好生成结果
4. 再写入卡

注意：

- 助记词和可选 `passphrase` 一定要单独、安全地备份
- 不要把助记词拍照、截图、联网传输

## 10. 完成后检查

完成以后建议检查三件事：

1. 工具里已经不再提示卡未初始化
2. 重新插卡后能正常识别
3. 你的安卓端或后续流程能正常读出地址并完成签名

## 11. 常见问题

### 11.1 窗口显示不完整

先检查：

- `Settings -> Displays -> Scale` 是否已经是 `100%`

这是最常见原因。

### 11.2 软件打不开

优先检查：

- `python3-tk` 是否已安装
- `python3-pyscard` 是否已安装
- `pcscd` 是否已启动
- `pip` 依赖是否已装全

### 11.3 读卡器有反应但软件识别不到卡

检查：

- 读卡器是否被 `pcsc_scan` 识别
- 卡是否已正确插入
- `pcscd` 是否运行中

### 11.4 完全离线时装不上依赖

这是正常现象。

因为完全离线时：

- `apt` 不能下载 Debian 包
- `pip` 不能下载 Python 包

解决办法是提前准备好离线依赖，或者先在一次临时联网的会话里装好。

## 12. 相关入口

- [README.zh-CN.md](README.zh-CN.md)
- [README-BUNDLE.md](README-BUNDLE.md)
- [../../card-applet/README.zh-CN.md](../../card-applet/README.zh-CN.md)

## 13. 本教程依据

这份教程整理时主要参考了上游项目这些文件：

- `Toporin/Satochip-Utils` 的 `README.md`
- `Toporin/Satochip-Utils` 的 `requirements.txt`
- `Toporin/Satochip-Utils` 的 `setup.py`
- `Toporin/Satochip-Utils` 的 `.github/workflows/build.yml`

对应仓库：

- `https://github.com/Toporin/Satochip-Utils`
