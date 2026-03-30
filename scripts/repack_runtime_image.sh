#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

BASE_IMG="${1:-$ROOT_DIR/dist/system-update-20260311-194633.img}"
if [[ ! -f "$BASE_IMG" ]]; then
  echo "Base image not found: $BASE_IMG" >&2
  exit 1
fi

STAMP="${STAMP:-$(date +%Y%m%d-%H%M%S)}"
OUT_IMG="$ROOT_DIR/dist/system-update-${STAMP}.img"
OUT_SUM="$OUT_IMG.SHA256SUMS"
BOOT_OFFSET=$((2048 * 512))
export PATH="/tmp/satochip-mtools/usr/bin:/tmp/tp-mtools/usr/bin:$PATH"
if ! command -v mcopy >/dev/null 2>&1 || ! command -v mdel >/dev/null 2>&1; then
  echo "mtools not found in /tmp/satochip-mtools/usr/bin or /tmp/tp-mtools/usr/bin" >&2
  exit 1
fi

WORK_DIR="$(mktemp -d /tmp/satochip-image-repack.XXXXXX)"
ROOTFS_DIR="$WORK_DIR/root"
OVERLAY_DIR="$ROOT_DIR/seedsigner-os/opt/rootfs-overlay"
IMG_SPEC="$BASE_IMG@@$BOOT_OFFSET"

cleanup() {
  set +e
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

mkdir -p "$ROOTFS_DIR"

mcopy -i "$IMG_SPEC" ::syscfg.dat "$WORK_DIR/syscfg.dat"

gzip -dc "$WORK_DIR/syscfg.dat" | (cd "$ROOTFS_DIR" && cpio -idmu --quiet)
mkdir -p "$ROOTFS_DIR/opt/pi-signer-py"
rsync -a --delete "$OVERLAY_DIR/opt/pi-signer-py/" "$ROOTFS_DIR/opt/pi-signer-py/"
rsync -a --exclude '/opt/pi-signer-py/' "$OVERLAY_DIR"/ "$ROOTFS_DIR"/

( cd "$ROOTFS_DIR" && find . -print0 | LC_ALL=C sort -z | cpio --null -o -H newc --quiet | gzip -9 ) > "$WORK_DIR/syscfg.new"

cp "$BASE_IMG" "$OUT_IMG"
mdel -i "$OUT_IMG@@$BOOT_OFFSET" ::syscfg.dat
mcopy -i "$OUT_IMG@@$BOOT_OFFSET" "$WORK_DIR/syscfg.new" ::syscfg.dat

( cd "$ROOT_DIR/dist" && sha256sum "$(basename "$OUT_IMG")" > "$(basename "$OUT_SUM")" )

echo "$OUT_IMG"
echo "$OUT_SUM"
