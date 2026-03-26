#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:-/home/ak/zero/tp-satochip-signer/dist/system-update-latest.img.xz}"
DEVICE="${2:-/dev/sdc}"

if [[ $EUID -ne 0 ]]; then
  echo "请用 sudo 运行此脚本。"
  exit 1
fi

if [[ ! -f "$IMAGE" ]]; then
  echo "镜像不存在: $IMAGE"
  exit 1
fi

if [[ ! -b "$DEVICE" ]]; then
  echo "目标设备不存在或不是块设备: $DEVICE"
  exit 1
fi

root_disk="$(findmnt -n -o SOURCE / | sed 's/[0-9]*$//')"
if [[ -n "$root_disk" && "$DEVICE" == "$root_disk" ]]; then
  echo "拒绝写入系统盘: $DEVICE"
  exit 1
fi

echo "即将写入:"
echo "  镜像: $IMAGE"
echo "  设备: $DEVICE"
echo
lsblk "$DEVICE" -o NAME,SIZE,TYPE,RM,RO,MODEL,VENDOR,FSTYPE,MOUNTPOINTS
echo

for part in $(lsblk -ln -o PATH "$DEVICE" | tail -n +2); do
  umount "$part" 2>/dev/null || true
done

sync
echo "开始写入镜像..."
xz -dc "$IMAGE" | dd of="$DEVICE" bs=4M status=progress conv=fsync
sync
partprobe "$DEVICE" || true
sleep 2
echo
echo "写入完成，当前分区如下:"
lsblk "$DEVICE" -o NAME,SIZE,TYPE,RM,RO,FSTYPE,MOUNTPOINTS
