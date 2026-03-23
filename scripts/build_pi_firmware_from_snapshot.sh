#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RAW_IMG="$ROOT_DIR/seedsigner-os/images/seedsigner_os.dev_.pi0-smartcard.img"
DIST_DIR="$ROOT_DIR/dist"
DIST_IMG="${DIST_IMG:-$DIST_DIR/system-update-latest.img.xz}"
DIST_SUM="${DIST_SUM:-$DIST_IMG.sha256}"
DIST_INFO="${DIST_INFO:-$DIST_DIR/system-update-latest.build-info.txt}"
SNAPSHOT_DIR="$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/opt"
SNAPSHOT_TIME_FILE="$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/opt/src/.build_commit_time"
NFC_BINDINGS_FILE="$ROOT_DIR/seedsigner-os/opt/external-packages/nfc-bindings/nfc-bindings.mk"

mkdir -p "$DIST_DIR"

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  "$ROOT_DIR/scripts/run_seedsigner_build.sh"
fi

if [[ ! -f "$RAW_IMG" ]]; then
  echo "Raw image not found: $RAW_IMG" >&2
  exit 1
fi

if [[ ! -f "$SNAPSHOT_TIME_FILE" ]]; then
  echo "Snapshot timestamp file not found: $SNAPSHOT_TIME_FILE" >&2
  exit 1
fi

if [[ ! -d "$SNAPSHOT_DIR" ]]; then
  echo "Snapshot directory not found: $SNAPSHOT_DIR" >&2
  exit 1
fi

if [[ ! -f "$NFC_BINDINGS_FILE" ]]; then
  echo "nfc-bindings file not found: $NFC_BINDINGS_FILE" >&2
  exit 1
fi

raw_sha="$(sha256sum "$RAW_IMG" | awk '{print $1}')"
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

tmp_img="$(mktemp "$DIST_DIR/.system-update-latest.img.xz.XXXXXX")"
xz -T0 -9 -c "$RAW_IMG" > "$tmp_img"
mv "$tmp_img" "$DIST_IMG"

dist_sha="$(sha256sum "$DIST_IMG" | awk '{print $1}')"
printf '%s  %s\n' "$dist_sha" "$(basename "$DIST_IMG")" > "$DIST_SUM"

cat > "$DIST_INFO" <<EOF
source_snapshot_build_commit_time=$snapshot_time
raw_image_path=seedsigner-os/images/$(basename "$RAW_IMG")
raw_image_sha256=$raw_sha
compressed_image_path=dist/$(basename "$DIST_IMG")
compressed_image_sha256=$dist_sha
repo_head=$repo_head
repo_dirty=$repo_dirty
runtime_snapshot_tree_sha256=$snapshot_tree_sha
nfc_bindings_mk_sha256=$nfc_bindings_sha
build_script=scripts/run_seedsigner_build.sh
package_script=scripts/build_pi_firmware_from_snapshot.sh
build_time_utc=$build_time_utc
EOF

echo "Raw image:        $RAW_IMG"
echo "Raw image sha256: $raw_sha"
echo "Dist image:       $DIST_IMG"
echo "Dist image sha256:$dist_sha"
echo "Build info:       $DIST_INFO"
