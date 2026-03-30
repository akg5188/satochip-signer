#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

export PATH="/tmp/satochip-mtools/usr/bin:/tmp/tp-mtools/usr/bin:$PATH"

BASE_PART_00="${BASE_PART_00:-$ROOT_DIR/dist/system-update-latest.img.xz.part-00}"
BASE_PART_01="${BASE_PART_01:-$ROOT_DIR/dist/system-update-latest.img.xz.part-01}"
BASE_PART_02="${BASE_PART_02:-$ROOT_DIR/dist/system-update-latest.img.xz.part-02}"
OVERLAY_DIR="${OVERLAY_DIR:-$ROOT_DIR/seedsigner-os/opt/rootfs-overlay}"
STAMP="${STAMP:-$(date +%Y%m%d-%H%M%S)}"

for tool in mcopy mdel mmd sfdisk mkfs.vfat xz gzip cpio sha256sum; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Missing required tool: $tool" >&2
    exit 1
  }
done

for part in "$BASE_PART_00" "$BASE_PART_01" "$BASE_PART_02"; do
  [[ -f "$part" ]] || {
    echo "Missing firmware part: $part" >&2
    exit 1
  }
done

WORK_DIR="$(mktemp -d /tmp/satochip-minfw.XXXXXX)"
cleanup() {
  set +e
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

BASE_XZ="$WORK_DIR/base.img.xz"
BASE_IMG="$WORK_DIR/base.img"
STAGE_BOOT="$WORK_DIR/boot"
STAGE_ROOT="$WORK_DIR/root"
NEW_IMG="$ROOT_DIR/dist/system-update-${STAMP}.img"
NEW_XZ="$NEW_IMG.xz"
NEW_SUM="$NEW_IMG.SHA256SUMS"
NEW_XZ_SUM="$NEW_XZ.sha256"
BOOT_OFFSET=$((2048 * 512))

mkdir -p "$STAGE_BOOT" "$STAGE_ROOT"

cat "$BASE_PART_00" "$BASE_PART_01" "$BASE_PART_02" > "$BASE_XZ"
xz -dk "$BASE_XZ"

# Extract current boot payload and runtime overlay.
mcopy -s -i "$BASE_IMG@@$BOOT_OFFSET" ::* "$STAGE_BOOT/" >/dev/null 2>&1 || true
gzip -dc "$STAGE_BOOT/syscfg.dat" | (cd "$STAGE_ROOT" && cpio -idmu --quiet)

# Keep the current runtime tree in sync with the source overlay.
mkdir -p "$STAGE_ROOT/opt/pi-signer-py"
rsync -a --delete "$OVERLAY_DIR/opt/pi-signer-py/" "$STAGE_ROOT/opt/pi-signer-py/"
rsync -a --exclude '/opt/pi-signer-py/' "$OVERLAY_DIR/" "$STAGE_ROOT/"

# Drop files that are not needed at runtime.
rm -rf \
  "$STAGE_ROOT/opt/electronics" \
  "$STAGE_ROOT/opt/gpg_keys" \
  "$STAGE_ROOT/opt/AGENTS.md" \
  "$STAGE_ROOT/opt/CHANGELOG.md" \
  "$STAGE_ROOT/opt/CLAUDE.md" \
  "$STAGE_ROOT/opt/requirements-desktop.txt" \
  "$STAGE_ROOT/opt/setup.cfg" \
  "$STAGE_ROOT/opt/setup.py"
find "$STAGE_ROOT" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$STAGE_ROOT" -type f -name '*.pyc' -delete

# Rebuild the initramfs payload.
rm -f "$STAGE_BOOT/syscfg.dat"
( cd "$STAGE_ROOT" && find . -print0 | LC_ALL=C sort -z | cpio --null -o -H newc --quiet | gzip -9 ) > "$STAGE_BOOT/syscfg.dat"

# Trim boot files to the Pi Zero appliance only.
find "$STAGE_BOOT" -maxdepth 1 -type f \
  ! -name 'bootcode.bin' \
  ! -name 'cmdline.txt' \
  ! -name 'config.txt' \
  ! -name 'fixup_x.dat' \
  ! -name 'start_x.elf' \
  ! -name 'zImage' \
  ! -name 'bcm2708-rpi-zero.dtb' \
  ! -name 'bcm2708-rpi-zero-w.dtb' \
  ! -name 'syscfg.dat' \
  -delete

if [[ -d "$STAGE_BOOT/overlays" ]]; then
  find "$STAGE_BOOT/overlays" -type f \
    ! -name 'disable-bt.dtbo' \
    ! -name 'disable-wifi.dtbo' \
    ! -name 'mmc.dtbo' \
    ! -name 'ov5647.dtbo' \
    ! -name 'overlay_map.dtb' \
    -delete
fi

payload_bytes="$(du -sb "$STAGE_BOOT" | awk '{print $1}')"
min_image_bytes=$((128 * 1024 * 1024))
target_bytes=$((payload_bytes + 16 * 1024 * 1024))
if (( target_bytes < min_image_bytes )); then
  target_bytes="$min_image_bytes"
fi
align=$((4 * 1024 * 1024))
target_bytes=$(( (target_bytes + align - 1) / align * align ))

truncate -s "$target_bytes" "$NEW_IMG"
/sbin/sfdisk "$NEW_IMG" <<EOF
label: dos
label-id: 0xba5eba11

start=2048, type=c, bootable
EOF

start_sector="$(/sbin/fdisk -l -o Start "$NEW_IMG" | tail -n 1 | tr -d '[:space:]')"
sector_count="$(/sbin/fdisk -l -o Sectors "$NEW_IMG" | tail -n 1 | tr -d '[:space:]')"
/sbin/mkfs.vfat --invariant -i ba5eba11 -n BOOT --offset="$start_sector" "$NEW_IMG" $(( (sector_count * 512) / 1024 ))
new_offset=$((start_sector * 512))

mcopy -s -bpm -i "$NEW_IMG@@$new_offset" "$STAGE_BOOT"/* ::

xz -T0 -6 -kf "$NEW_IMG"
( cd "$ROOT_DIR/dist" && sha256sum "$(basename "$NEW_IMG")" > "$(basename "$NEW_SUM")" )
sha256sum "$NEW_XZ" | awk -v name="$(basename "$NEW_XZ")" '{print $1 "  " name}' > "$NEW_XZ_SUM"

echo "payload_bytes=$payload_bytes"
echo "$NEW_IMG"
echo "$NEW_XZ"
