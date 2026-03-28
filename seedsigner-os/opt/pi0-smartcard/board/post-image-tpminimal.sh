#!/bin/bash

set -e

sectors_to_blocks() {
  echo $((("$1" * 512) / 1024))
}

sectors_to_bytes() {
  echo $(( "$1" * 512 ))
}

export disk_timestamp="2023/01/01T12:15:05"

round_up() {
  local value="$1"
  local quantum="$2"
  echo $((((value + quantum - 1) / quantum) * quantum))
}

echo "*****Generating Main System Image*****"

rm -rf "${BUILD_DIR}/custom_image"
mkdir -p "${BUILD_DIR}/custom_image"
cd "${BUILD_DIR}/custom_image"

mkdir -p boot overlays
cp "${BASE_DIR}/images/rpi-firmware/cmdline.txt" boot/cmdline.txt
cp "${BASE_DIR}/images/rpi-firmware/config.txt" boot/config.txt
cp "${BASE_DIR}/images/rpi-firmware/bootcode.bin" boot/bootcode.bin
cp "${BASE_DIR}/images/rpi-firmware/fixup_x.dat" boot/fixup_x.dat
cp "${BASE_DIR}/images/rpi-firmware/start_x.elf" boot/start_x.elf
cp "${BASE_DIR}/images/bcm2708-rpi-zero.dtb" boot/
cp "${BASE_DIR}/images/zImage" boot/zImage

sed -i \
  -e '/^dtoverlay=mmc$/d' \
  boot/config.txt

grep -qxF 'dtoverlay=disable-wifi' boot/config.txt || echo 'dtoverlay=disable-wifi' >> boot/config.txt
grep -qxF 'dtoverlay=disable-bt' boot/config.txt || echo 'dtoverlay=disable-bt' >> boot/config.txt

while IFS= read -r overlay_name; do
  [ -n "${overlay_name}" ] || continue
  src="${BASE_DIR}/images/rpi-firmware/overlays/${overlay_name}.dtbo"
  if [ -f "${src}" ]; then
    cp "${src}" overlays/
  fi
done < <(awk -F= '/^dtoverlay=/{split($2, parts, ","); print parts[1]}' boot/config.txt)

chmod 0755 boot overlays
touch -d "${disk_timestamp}" boot/*
if find overlays -mindepth 1 -type f | grep -q .; then
  touch -d "${disk_timestamp}" overlays/*
fi

payload_bytes=$(find boot overlays -type f -printf '%s\n' | awk '{s += $1} END {print s + 0}')
min_bytes=$((96 * 1024 * 1024))
reserve_bytes=$((16 * 1024 * 1024))
image_bytes=$(round_up $((payload_bytes + reserve_bytes)) $((16 * 1024 * 1024)))
if [ "${image_bytes}" -lt "${min_bytes}" ]; then
  image_bytes="${min_bytes}"
fi

truncate -s "${image_bytes}" disk.img

/sbin/sfdisk disk.img <<EOF
  label: dos
  label-id: 0xba5eba11

  disk.img1 : type=c, bootable
EOF

START=$(/sbin/fdisk -l -o Start disk.img | awk 'END{gsub(/^ +| +$/, "", $1); print $1}')
SECTORS=$(/sbin/fdisk -l -o Sectors disk.img | awk 'END{gsub(/^ +| +$/, "", $1); print $1}')
/sbin/mkfs.vfat --invariant -i ba5eba11 -n BOOT disk.img --offset "$START" "$(sectors_to_blocks "$SECTORS")"
OFFSET=$(sectors_to_bytes "$START")

mcopy -bpm -i "disk.img@@$OFFSET" boot/* ::
if find overlays -mindepth 1 -type f | grep -q .; then
  mmd -i "disk.img@@$OFFSET" ::overlays
  mcopy -bpm -i "disk.img@@$OFFSET" overlays/* ::overlays/
fi

mv disk.img "${BASE_DIR}/images/seedsigner_os.img"
