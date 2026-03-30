# 可直接烧录镜像构建

此目录用于生成“开箱即用”的树莓派离线签名器镜像。

生成结果：

- `dist/offline-signer-appliance-*.img`
- `dist/offline-signer-appliance-*.img.xz`

## 一键构建

```bash
sudo bash image-builder/build_flashable_image.sh
```

默认行为：

1. 下载 `Raspberry Pi OS Lite (armhf) latest`
2. 注入 `pi-signer` 和 `pi-appliance` 到镜像
3. 在镜像内预装运行依赖（自动识别 Java/Python signer，安装对应依赖）
4. 配置 `ST7789 + OV5647` 和禁用 WiFi/BT
5. 启用开机自启动 `offline-signer-kiosk.service`
6. 输出可直接烧录镜像

## 可选参数

```bash
sudo bash image-builder/build_flashable_image.sh \
  --bundle dist/offline-signer-20260308-142005 \
  --base-image /path/to/raspios.img.xz \
  --output dist/my-offline-signer.img \
  --signer-runtime auto
```

- `--skip-apt`：跳过 chroot 安装依赖（不建议）
- `--signer-runtime`：`auto|java|python`（默认 `auto`）

## 烧录

用 Raspberry Pi Imager / balenaEtcher 把 `.img.xz` 烧录到 SD 卡。
