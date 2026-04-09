# real-ui-screenshot-guide

这组图片不是手绘示意图，而是直接用当前树莓派固件的真实 UI 代码在电脑里渲染出来的截图。

当前生成脚本：

- [scripts/generate_real_ui_screenshots.py](../../../scripts/generate_real_ui_screenshots.py)

推荐重生成方式：

```bash
bash scripts/setup_desktop_smoke_env.sh /tmp/satochip-desktop-smoke-venv
python3 scripts/generate_real_ui_screenshots.py /tmp/satochip-desktop-smoke-venv
```

当前输出文件：

- `01-login-password.png`
- `02-home-menu.png`
- `03-seed-tools.png`
- `04-xpub-details.png`
- `05-scan-psbt.png`
- `06-review-psbt.png`
- `07-sign-psbt.png`
- `08-signed-qr.png`
