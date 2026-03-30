#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root: sudo bash pi-appliance/setup/install_standalone.sh" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
KIOSK_SRC="$ROOT_DIR/pi-appliance/app"
SERVICE_SRC="$ROOT_DIR/pi-appliance/systemd/offline-signer-kiosk.service"

if [[ -x "$ROOT_DIR/offline-signer/bin/offline-signer" || -x "$ROOT_DIR/offline-signer/bin/pi-signer" ]]; then
  SIGNER_SRC="$ROOT_DIR/offline-signer"
elif [[ -x "$ROOT_DIR/pi-signer/bin/pi-signer" ]]; then
  SIGNER_SRC="$ROOT_DIR/pi-signer"
elif [[ -x "$ROOT_DIR/bin/offline-signer" || -x "$ROOT_DIR/bin/pi-signer" ]]; then
  SIGNER_SRC="$ROOT_DIR"
else
  echo "Missing signer binary in release bundle." >&2
  echo "Please run from the release bundle root." >&2
  exit 1
fi

echo "[1/6] Installing runtime packages..."
apt-get update
apt-get install -y \
  openjdk-17-jre-headless \
  pcscd pcsc-tools libpcsclite1 \
  python3 python3-pil python3-numpy python3-gpiozero python3-spidev \
  python3-picamera2 python3-pyzbar libzbar0

systemctl enable --now pcscd

echo "[2/6] Configuring boot options..."
BOOT_CFG="/boot/firmware/config.txt"
if [[ ! -f "$BOOT_CFG" ]]; then
  BOOT_CFG="/boot/config.txt"
fi

ensure_line() {
  local line="$1"
  if ! grep -qxF "$line" "$BOOT_CFG"; then
    echo "$line" >>"$BOOT_CFG"
  fi
}

ensure_line "# offline-signer"
ensure_line "dtparam=spi=on"
ensure_line "camera_auto_detect=1"
ensure_line "dtoverlay=ov5647"
ensure_line "dtoverlay=disable-wifi"
ensure_line "dtoverlay=disable-bt"

echo "[3/6] Deploying signer binaries..."
rm -rf /opt/offline-signer
mkdir -p /opt/offline-signer
cp -a "$SIGNER_SRC"/* /opt/offline-signer/

echo "[4/6] Deploying kiosk app..."
rm -rf /opt/offline-signer-kiosk
mkdir -p /opt/offline-signer-kiosk
cp -a "$KIOSK_SRC"/* /opt/offline-signer-kiosk/
chmod +x /opt/offline-signer-kiosk/*.py /opt/offline-signer-kiosk/launch_kiosk.sh

echo "[5/6] Installing systemd service..."
cp "$SERVICE_SRC" /etc/systemd/system/offline-signer-kiosk.service
systemctl daemon-reload
systemctl enable offline-signer-kiosk.service

echo "[6/6] Done"
echo
cat <<MSG
Installation complete.

Next step:
  reboot

After reboot, kiosk should auto-start on the ST7789 display.
If you need logs:
  journalctl -u offline-signer-kiosk -f
MSG
