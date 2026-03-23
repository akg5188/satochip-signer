# pi-signer-py

纯 Python 版本的离线签名 CLI，接口尽量兼容原 `pi-signer`：

- `unlock --pin ...`
- `sign --pin ... --payload-file ... --out ... --qr ...`

## 依赖

- `python3`
- `pyscard`（PC/SC 读卡）
- `pycryptodome` 或 `pysha3`（keccak256）
- `qrcode` + `Pillow`（二维码图片输出）
- 可选：`eth-account`（用于 `signTypedData`）

## 功能范围

- 支持 `signTransaction`（Legacy + EIP-1559）
- 支持 `personalSign` / `signPersonalMessage`
- 支持 `signTypedData` / `signTypeDataV4`（需 `eth-account`）
- 支持 `tp:multiFragment` 文本输入自动拼接

## 例子

```bash
./bin/pi-signer unlock --pin 123456

./bin/pi-signer sign \
  --pin 123456 \
  --payload-file request.txt \
  --out response.txt \
  --qr response.png
```
