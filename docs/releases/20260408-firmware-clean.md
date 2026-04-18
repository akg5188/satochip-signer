# offline-signer-firmware-20260408-clean

本次正式固件重点更新：

- 修复 `BlueWallet` 扫回已签名 `BTC PSBT` 的二维码兼容性
- 已签名 `PSBT` 按输入格式回传，不再强行统一成单一路径
- `PSBT / 已签名交易` 二维码恢复优先自动动画输出
- 二维码显示尺寸改成跟随真实画布，不再写死 `240x240`
- 同步补齐固件 smoke、桌面模拟、二维码 round-trip 和模块导入测试

建议下载后先看：

- `README.md`
- `docs/快速开始.zh-CN.md`
- `docs/版本时间线与发布入口.zh-CN.md`
- `docs/真机全套回归清单.zh-CN.md`

已知事项：

- 官方 `BlueWallet` 现在已经可以扫回树莓派签名结果
- 但对输入数较多的交易，`BlueWallet` 自己的广播页可能会被长 `tx hex` 挤掉底部按钮
- 这种情况可以先复制 `tx hex` 再去别的广播器发送，或者直接配合自家安卓观察钱包使用
