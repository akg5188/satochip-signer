#!/usr/bin/env bash
set -euo pipefail

export PATH="/tmp/tp-mtools/usr/bin:$PATH"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RAW_IMG="${RAW_IMG:-$ROOT_DIR/seedsigner-os/images/seedsigner_os.dev_.pi0-smartcard.img}"
NEW_ZIMAGE="${NEW_ZIMAGE:-$ROOT_DIR/seedsigner-os/output/images/zImage}"
DIST_IMG="${DIST_IMG:-$ROOT_DIR/dist/system-update-latest.img.xz}"
DIST_SUM="${DIST_SUM:-$DIST_IMG.sha256}"
DIST_INFO="${DIST_INFO:-$ROOT_DIR/dist/system-update-latest.build-info.txt}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/opt}"
SNAPSHOT_TIME_FILE="${SNAPSHOT_TIME_FILE:-$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/opt/src/.build_commit_time}"
NFC_BINDINGS_FILE="${NFC_BINDINGS_FILE:-$ROOT_DIR/seedsigner-os/opt/external-packages/nfc-bindings/nfc-bindings.mk}"
BOOT_OFFSET="${BOOT_OFFSET:-$((2048 * 512))}"

for tool in mcopy mdel xz sha256sum; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Missing required tool: $tool" >&2
    exit 1
  }
done

[[ -f "$RAW_IMG" ]] || { echo "Missing raw image: $RAW_IMG" >&2; exit 1; }
[[ -f "$NEW_ZIMAGE" ]] || { echo "Missing zImage: $NEW_ZIMAGE" >&2; exit 1; }
[[ -d "$SNAPSHOT_DIR" ]] || { echo "Missing snapshot dir: $SNAPSHOT_DIR" >&2; exit 1; }
[[ -f "$SNAPSHOT_TIME_FILE" ]] || { echo "Missing snapshot timestamp: $SNAPSHOT_TIME_FILE" >&2; exit 1; }
[[ -f "$NFC_BINDINGS_FILE" ]] || { echo "Missing nfc-bindings file: $NFC_BINDINGS_FILE" >&2; exit 1; }

TMP_DIR="$(mktemp -d)"
cleanup() {
  set +e
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mdel -i "${RAW_IMG}@@${BOOT_OFFSET}" ::zImage || true
mcopy -bpm -i "${RAW_IMG}@@${BOOT_OFFSET}" "$NEW_ZIMAGE" ::zImage
mcopy -i "${RAW_IMG}@@${BOOT_OFFSET}" ::zImage "$TMP_DIR/zImage"

raw_sha="$(sha256sum "$RAW_IMG" | awk '{print $1}')"
zimage_sha="$(sha256sum "$NEW_ZIMAGE" | awk '{print $1}')"
embedded_zimage_sha="$(sha256sum "$TMP_DIR/zImage" | awk '{print $1}')"
snapshot_time="$(cat "$SNAPSHOT_TIME_FILE")"
build_time_utc="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
repo_head="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
repo_dirty=0
if [[ -n "$(git -C "$ROOT_DIR" status --porcelain --untracked-files=no 2>/dev/null || true)" ]]; then
  repo_dirty=1
fi
snapshot_tree_sha="$(
  cd "$SNAPSHOT_DIR"
  while IFS= read -r -d '' file; do
    sha256sum "$file"
  done < <(find . -type f -print0 | LC_ALL=C sort -z) | sha256sum | awk '{print $1}'
)"
nfc_bindings_sha="$(sha256sum "$NFC_BINDINGS_FILE" | awk '{print $1}')"

mkdir -p "$(dirname "$DIST_IMG")"
tmp_img="$(mktemp "$(dirname "$DIST_IMG")/.repack-current-pi.XXXXXX")"
ionice -c3 nice -n 19 xz -T1 -9 -c "$RAW_IMG" > "$tmp_img"
mv "$tmp_img" "$DIST_IMG"

dist_sha="$(sha256sum "$DIST_IMG" | awk '{print $1}')"
printf '%s  %s\n' "$dist_sha" "$(basename "$DIST_IMG")" > "$DIST_SUM"

cat > "$DIST_INFO" <<EOF
source_snapshot_build_commit_time=$snapshot_time
raw_image_path=seedsigner-os/images/$(basename "$RAW_IMG")
raw_image_sha256=$raw_sha
raw_image_zImage_sha256=$zimage_sha
raw_image_embedded_zImage_sha256=$embedded_zimage_sha
compressed_image_path=dist/$(basename "$DIST_IMG")
compressed_image_sha256=$dist_sha
repo_head=$repo_head
repo_dirty=$repo_dirty
runtime_snapshot_tree_sha256=$snapshot_tree_sha
nfc_bindings_mk_sha256=$nfc_bindings_sha
build_script=scripts/repack_current_pi_image.sh
package_script=scripts/repack_current_pi_image.sh
build_time_utc=$build_time_utc
EOF

echo "Raw image:              $RAW_IMG"
echo "Raw image sha256:       $raw_sha"
echo "New zImage sha256:      $zimage_sha"
echo "Embedded zImage sha256: $embedded_zimage_sha"
echo "Dist image:             $DIST_IMG"
echo "Dist image sha256:      $dist_sha"
echo "Build info:             $DIST_INFO"
