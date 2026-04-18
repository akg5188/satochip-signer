# Web3 UR 二维码生成说明

这份说明只管一件事: 让 Web3 连接二维码在不同钱包里保持兼容，并固定成已经实测通过的组合。

## 结论

最终固定成两条连接规则:

1. `MetaMask / Rabby / TokenPocket`:

```text
UR:CRYPTO-HDKEY/...
```

单张静态二维码，导出 `account.standard`

2. `Bitget`:

```text
UR:CRYPTO-MULTI-ACCOUNTS/...
```

单张静态二维码，多账户一起导出

3. `OKX`:

```text
UR:CRYPTO-MULTI-ACCOUNTS/...
```

动态连续二维码，导出 `1 个标准 EVM + 10 个 OKX EVM + BTC 49' + 84'`

结果码仍然只对树莓派回传给钱包的 `eth-signature` 做大写渲染:

```text
ur:eth-signature/...
```

显示时改成:

```text
UR:ETH-SIGNATURE/...
```

这不会改掉协议内容。UR 是大小写不敏感的，钱包解码后拿到的还是同一份 payload。

连接码不要再一刀切:

- `MetaMask / Rabby / TokenPocket` 保持单张静态码
- `Bitget` 保持单张静态码
- `OKX` 恢复成动态分片码

## 为什么

对 `eth-signature` 来说，小写 UR 更容易让二维码编码器走 byte mode，码会更密。

大写 UR 更容易让编码器走 alphanumeric mode，码会更稀、更好扫。

这次排查里，同一条 227 字符的 `eth-signature`:

- 小写 + `ERROR_CORRECT_L` -> QR Version 9
- 大写 + `ERROR_CORRECT_L` -> QR Version 8

版本降一档，模块数更少，OKX 的扫码成功率明显更高。

## 固定规则

以后按下面的规则区分:

1. `eth-signature` 回传码: 显示前转大写
2. `MetaMask / Rabby / TokenPocket` 连接码: 单张静态 `crypto-hdkey`
3. `Bitget` 连接码: 单张静态 `crypto-multi-accounts`，包含 `ETH + BTC Native SegWit`
4. `OKX` 连接码: 动态 `crypto-multi-accounts`，包含 `ETH + 10 个 OKX EVM + BTC 49' + 84'`
5. 优先使用 `ERROR_CORRECT_L`
6. 白底黑码
7. 保留足够静区
8. 不要截图后再压缩转发

其中最关键的是不要一刀切。前面踩坑最久的根因，就是把对 OKX 有利的渲染方式直接套到了 Bitget 连接码上。

## 固件实现约定

正式固件里保留这几个约定:

- 只有 `eth-signature` 渲染成二维码时转成大写
- `Bitget` 连接码使用大写静态 `crypto-multi-accounts`
- `OKX` 连接码使用大写动态 `crypto-multi-accounts`
- `MetaMask / Rabby / TokenPocket` 连接码使用大写静态 `crypto-hdkey`
- Web3 返回码默认使用低密度、白底、高静区的显示参数
- 正式版不向 TF 卡写任何 Web3 请求或签名调试文件

这样协议层和显示层分开，既兼容钱包，又不污染用户卡里的数据。

## 当前源码入口

以后如果需要排查或重编，不要满仓库乱改，先看这几个入口:

- 树莓派连接码与结果码主逻辑:
  `seedsigner-os/opt/rootfs-overlay/opt/src/seedsigner/views/tp_views.py`
- Web3 二维码显示渲染:
  `seedsigner-os/opt/rootfs-overlay/opt/src/seedsigner/helpers/qr.py`
- 树莓派扫码链路:
  `seedsigner-os/opt/rootfs-overlay/opt/src/seedsigner/gui/screens/scan_screens.py`
  `seedsigner-os/opt/rootfs-overlay/opt/src/seedsigner/hardware/camera.py`
  `seedsigner-os/opt/rootfs-overlay/opt/src/seedsigner/hardware/pivideostream.py`
  `seedsigner-os/opt/rootfs-overlay/opt/src/seedsigner/models/decode_qr.py`

## 当前固定规则

以后重编前，先按这张表核对:

| 场景 | 协议 | 当前固定规则 | 不要做什么 |
| --- | --- | --- | --- |
| `MetaMask / Rabby / TokenPocket` 连接硬件钱包 | `crypto-hdkey` | 单张静态码 | 不要再退回 multi-accounts |
| `Bitget` 连接硬件钱包 | `crypto-multi-accounts` | 单张静态码，带 `ETH + BTC Native SegWit` | 不要再把 `44' / 49'` 混进去 |
| `OKX` 连接硬件钱包 | `crypto-multi-accounts` | 动态连续码，带 `ETH + 10 个 OKX EVM + BTC 49' + 84'` | 不要再退回单张静态精简码；实测 OKX 不认 `84' only` 的 BTC |
| `OKX / Bitget` 扫回签名结果 | `eth-signature` | 显示前转大写、低纠错、白底黑码 | 不要把连接码也套用这套渲染 |

一句话记住:

- EVM 钱包连接码走 `crypto-hdkey`
- OKX / Bitget 连接码走 `crypto-multi-accounts`
- 结果码走 `eth-signature`
- 只有结果码为了 OKX 扫码成功率才转大写
- Web3 连接码不要再统一成单张静态码

## 重编前自检清单

以后任何 AI 或人工准备重编前，先确认:

1. `tp_views.py` 里 `WEB3_BITKEEP_BTC_ACCOUNT_PATHS` 只保留 `m/84'/0'/0'`
2. `tp_views.py` 里 `WEB3_OKX_BTC_ACCOUNT_PATHS` 固定为 `m/49'/0'/0'` + `m/84'/0'/0'`
3. `tp_views.py` 里 `WEB3_OKX_LEDGER_LIVE_ACCOUNT_COUNT` 固定为 `10`
4. `tp_views.py` 里 `OKX` 连接码输出动态 `crypto-multi-accounts`
5. `tp_views.py` 里 `MetaMask / Rabby / TokenPocket` 连接码输出单张静态 `crypto-hdkey`
6. `eth-signature` 的二维码渲染仍然只在显示层做大写优化
7. 先看这份文档，再执行 `bash scripts/build_pi_firmware_from_snapshot.sh`
8. 编完至少核对一次 `dist/*.build-info.txt` 和 `sha256`

## 手工生成 PNG

如果以后需要离线手工出一张测试二维码，可以直接套这个模板:

```python
import qrcode

data = "ur:eth-signature/..."
data = data.upper()

qr = qrcode.QRCode(
    version=None,
    error_correction=qrcode.constants.ERROR_CORRECT_L,
    box_size=20,
    border=10,
)
qr.add_data(data)
qr.make(fit=True)

img = qr.make_image(fill_color="black", back_color="white")
img.save("web3-ur.png")
```

如果 `L` 纠错在某些场景下仍然不稳，再试 `M`。不要先上 `Q/H`，那通常只会把码做得更密。
