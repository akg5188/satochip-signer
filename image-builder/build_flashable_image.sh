#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORK_DIR="${WORK_DIR:-/tmp/satochip_pi_image_build}"
DOWNLOAD_DIR="$WORK_DIR/download"
MOUNT_DIR="$WORK_DIR/mnt"
OUTPUT_DIR="$ROOT_DIR/dist"

BASE_URL_DEFAULT="https://downloads.raspberrypi.com/raspios_lite_armhf_latest"
BASE_URL="${BASE_URL:-$BASE_URL_DEFAULT}"

BUNDLE_DIR="${BUNDLE_DIR:-}"
BASE_IMAGE_INPUT="${BASE_IMAGE_INPUT:-}"

usage() {
  cat <<USAGE
Usage:
  sudo bash image-builder/build_flashable_image.sh [options]

Options:
  --bundle <path>      Release bundle directory containing offline-signer/ and pi-appliance/
                       default: latest dist/offline-signer-*/ directory
  --base-image <path>  Existing .img/.img.xz/.zip base image file
  --base-url <url>     Download URL when --base-image not provided
                       default: $BASE_URL_DEFAULT
  --output <path>      Output image path (.img). xz is generated automatically.
  --signer-runtime <auto|java|python>
                       Runtime dependency profile for offline-signer
                       default: auto (detect from bundle content)
  --skip-apt           Skip apt install in chroot (not recommended)

Environment overrides:
  WORK_DIR=/tmp/satochip_pi_image_build
USAGE
}

SKIP_APT=0
OUTPUT_IMAGE=""
SIGNER_RUNTIME="${SIGNER_RUNTIME:-auto}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle)
      BUNDLE_DIR="$2"; shift 2 ;;
    --base-image)
      BASE_IMAGE_INPUT="$2"; shift 2 ;;
    --base-url)
      BASE_URL="$2"; shift 2 ;;
    --output)
      OUTPUT_IMAGE="$2"; shift 2 ;;
    --skip-apt)
      SKIP_APT=1; shift ;;
    --signer-runtime)
      SIGNER_RUNTIME="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1 ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root: sudo bash image-builder/build_flashable_image.sh" >&2
  exit 1
fi

find_latest_bundle_dir() {
  local latest
  latest="$(find "$OUTPUT_DIR" -maxdepth 1 -type d -name 'offline-signer-*' | sort | tail -n1)"
  if [[ -n "$latest" ]]; then
    echo "$latest"
    return
  fi
  find "$OUTPUT_DIR" -maxdepth 1 -type d \( -name '*pi-signer-*' -o -name 'offline-signer-*' \) | sort | tail -n1
}

if [[ -z "$BUNDLE_DIR" ]]; then
  BUNDLE_DIR="$(find_latest_bundle_dir || true)"
fi

if [[ -z "$BUNDLE_DIR" || ! -d "$BUNDLE_DIR" ]]; then
  echo "Bundle directory not found. Build release first:" >&2
  echo "  bash scripts/build_pi_release.sh" >&2
  exit 1
fi

resolve_bundle_signer_dir() {
  local bundle="$1"
  if [[ -x "$bundle/offline-signer/bin/offline-signer" || -x "$bundle/offline-signer/bin/pi-signer" ]]; then
    echo "$bundle/offline-signer"
    return 0
  fi
  if [[ -x "$bundle/pi-signer/bin/pi-signer" || -x "$bundle/pi-signer/bin/offline-signer" ]]; then
    echo "$bundle/pi-signer"
    return 0
  fi
  return 1
}

SIGNER_DIR="$(resolve_bundle_signer_dir "$BUNDLE_DIR" || true)"
if [[ -z "$SIGNER_DIR" ]]; then
  echo "Invalid bundle: missing offline-signer binary in $BUNDLE_DIR" >&2
  exit 1
fi

detect_signer_runtime() {
  local signer_dir="$1"
  if compgen -G "$signer_dir/lib/*.jar" >/dev/null; then
    echo "java"
    return
  fi
  echo "python"
}

if [[ "$SIGNER_RUNTIME" == "auto" ]]; then
  SIGNER_RUNTIME="$(detect_signer_runtime "$SIGNER_DIR")"
fi

if [[ "$SIGNER_RUNTIME" != "java" && "$SIGNER_RUNTIME" != "python" ]]; then
  echo "Invalid signer runtime: $SIGNER_RUNTIME (allowed: auto|java|python)" >&2
  exit 1
fi

echo "Signer runtime: $SIGNER_RUNTIME"

if [[ ! -f "$BUNDLE_DIR/pi-appliance/setup/install_standalone.sh" ]]; then
  echo "Invalid bundle: missing pi-appliance setup scripts in $BUNDLE_DIR" >&2
  exit 1
fi

mkdir -p "$DOWNLOAD_DIR" "$MOUNT_DIR" "$OUTPUT_DIR"

cleanup() {
  set +e
  local root_mnt="${ROOT_MNT:-}"
  local boot_mnt="${BOOT_MNT:-}"

  if [[ -z "$root_mnt" || -z "$boot_mnt" ]]; then
    return 0
  fi

  for p in dev/pts dev proc sys run; do
    if mountpoint -q "$root_mnt/$p"; then
      umount "$root_mnt/$p"
    fi
  done

  if mountpoint -q "$boot_mnt"; then
    umount "$boot_mnt"
  fi
  if mountpoint -q "$root_mnt"; then
    umount "$root_mnt"
  fi

  if [[ -n "${LOOP_DEV:-}" ]]; then
    losetup -d "$LOOP_DEV"
  fi
}
trap cleanup EXIT

extract_base_image() {
  local src="$1"
  local out_img="$2"

  local mime
  mime="$(file -b --mime-type "$src")"

  if [[ "$src" == *.img ]]; then
    cp -f "$src" "$out_img"
    return
  fi

  if [[ "$src" == *.xz ]] || [[ "$mime" == "application/x-xz" ]]; then
    xz -dc "$src" > "$out_img"
    return
  fi

  if [[ "$src" == *.zip ]] || [[ "$mime" == "application/zip" ]]; then
    local tmpdir
    tmpdir="$(mktemp -d "$WORK_DIR/unzip.XXXX")"
    unzip -oq "$src" -d "$tmpdir"
    local img
    img="$(find "$tmpdir" -type f -name '*.img' | head -n1 || true)"
    if [[ -z "$img" ]]; then
      echo "Zip does not contain .img: $src" >&2
      exit 1
    fi
    cp -f "$img" "$out_img"
    rm -rf "$tmpdir"
    return
  fi

  echo "Unsupported base image format: $src" >&2
  exit 1
}

if [[ -z "$BASE_IMAGE_INPUT" ]]; then
  ARCHIVE_PATH="$DOWNLOAD_DIR/base_image"
  echo "Downloading base image: $BASE_URL"
  curl -fL "$BASE_URL" -o "$ARCHIVE_PATH"
  BASE_IMAGE_INPUT="$ARCHIVE_PATH"
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
if [[ -z "$OUTPUT_IMAGE" ]]; then
  OUTPUT_IMAGE="$OUTPUT_DIR/offline-signer-appliance-$STAMP.img"
fi

ROOT_MNT="$MOUNT_DIR/root"
BOOT_MNT="$MOUNT_DIR/boot"
mkdir -p "$ROOT_MNT" "$BOOT_MNT"

echo "Extracting base image..."
extract_base_image "$BASE_IMAGE_INPUT" "$OUTPUT_IMAGE"

echo "Attaching loop device..."
LOOP_DEV="$(losetup --show -Pf "$OUTPUT_IMAGE")"
BOOT_DEV="${LOOP_DEV}p1"
ROOT_DEV="${LOOP_DEV}p2"

if [[ ! -b "$BOOT_DEV" || ! -b "$ROOT_DEV" ]]; then
  echo "Failed to detect partitions on $LOOP_DEV" >&2
  exit 1
fi

echo "Mounting partitions..."
mount "$ROOT_DEV" "$ROOT_MNT"
mount "$BOOT_DEV" "$BOOT_MNT"

echo "Deploying signer bundle..."
rm -rf "$ROOT_MNT/opt/offline-signer" "$ROOT_MNT/opt/offline-signer-kiosk"
mkdir -p "$ROOT_MNT/opt/offline-signer" "$ROOT_MNT/opt/offline-signer-kiosk"
cp -a "$SIGNER_DIR"/. "$ROOT_MNT/opt/offline-signer/"
cp -a "$BUNDLE_DIR/pi-appliance/app"/. "$ROOT_MNT/opt/offline-signer-kiosk/"
chmod +x "$ROOT_MNT/opt/offline-signer-kiosk"/*.py "$ROOT_MNT/opt/offline-signer-kiosk/launch_kiosk.sh"

cp "$BUNDLE_DIR/pi-appliance/systemd/offline-signer-kiosk.service" \
  "$ROOT_MNT/etc/systemd/system/offline-signer-kiosk.service"

# boot config
BOOT_CFG="$BOOT_MNT/config.txt"
if [[ ! -f "$BOOT_CFG" ]]; then
  BOOT_CFG="$ROOT_MNT/boot/firmware/config.txt"
fi
if [[ ! -f "$BOOT_CFG" ]]; then
  echo "Cannot locate config.txt in mounted image" >&2
  exit 1
fi

ensure_cfg_line() {
  local line="$1"
  if ! grep -qxF "$line" "$BOOT_CFG"; then
    echo "$line" >> "$BOOT_CFG"
  fi
}

ensure_cfg_line "# offline-signer"
ensure_cfg_line "dtparam=spi=on"
ensure_cfg_line "camera_auto_detect=1"
ensure_cfg_line "dtoverlay=ov5647"
ensure_cfg_line "dtoverlay=disable-wifi"
ensure_cfg_line "dtoverlay=disable-bt"

if [[ "$SKIP_APT" -eq 0 ]]; then
  echo "Installing runtime packages in chroot (this may take a while)..."
  mount --bind /dev "$ROOT_MNT/dev"
  mount --bind /dev/pts "$ROOT_MNT/dev/pts"
  mount --bind /proc "$ROOT_MNT/proc"
  mount --bind /sys "$ROOT_MNT/sys"
  mount --bind /run "$ROOT_MNT/run"

  chroot "$ROOT_MNT" /bin/bash -lc '
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y \
      pcscd pcsc-tools libpcsclite1 \
      python3 python3-pil python3-numpy python3-gpiozero python3-spidev \
      python3-picamera2 python3-pyzbar libzbar0
  '

  if [[ "$SIGNER_RUNTIME" == "java" ]]; then
    chroot "$ROOT_MNT" /bin/bash -lc '
      set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive
      apt-get install -y openjdk-17-jre-headless
    '
  else
    chroot "$ROOT_MNT" /bin/bash -lc '
      set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive
      apt-get install -y \
        python3-pyscard \
        python3-pycryptodome \
        python3-qrcode
    '
  fi
fi

echo "Enabling services..."
systemctl --root "$ROOT_MNT" enable pcscd.service >/dev/null || true
systemctl --root "$ROOT_MNT" enable offline-signer-kiosk.service >/dev/null

# Optional hard-disable network services on first boot.
systemctl --root "$ROOT_MNT" disable wpa_supplicant.service >/dev/null 2>&1 || true
systemctl --root "$ROOT_MNT" disable bluetooth.service >/dev/null 2>&1 || true
systemctl --root "$ROOT_MNT" disable hciuart.service >/dev/null 2>&1 || true

sync

echo "Detaching image..."
cleanup
trap - EXIT

echo "Compressing image..."
XZ_OUTPUT="$OUTPUT_IMAGE.xz"
rm -f "$XZ_OUTPUT"
xz -T0 -6 -k "$OUTPUT_IMAGE"

cat <<DONE
Build completed:
  Raw image: $OUTPUT_IMAGE
  Compressed: $XZ_OUTPUT

Flash to SD card with Raspberry Pi Imager or balenaEtcher.
DONE
