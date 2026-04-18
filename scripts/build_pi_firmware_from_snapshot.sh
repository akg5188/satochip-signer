#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ASCII_BASE="${TP_ASCII_BASE:-$HOME/satochip-signer-ascii}"
ASCII_IMAGE_DIR="${TP_IMAGE_DIR:-$ASCII_BASE/images}"
ASCII_BUILD_DIR="${TP_BUILD_DIR:-$ASCII_BASE/output}"
DEFAULT_RAW_IMG="$ASCII_IMAGE_DIR/seedsigner_os.dev_.pi0-smartcard.img"
LEGACY_RAW_IMG="$ROOT_DIR/seedsigner-os/images/seedsigner_os.dev_.pi0-smartcard.img"
RAW_IMG="${RAW_IMG:-$DEFAULT_RAW_IMG}"
DIST_DIR="$ROOT_DIR/dist"
DIST_IMG="${DIST_IMG:-$DIST_DIR/system-update-latest.img.xz}"
DIST_SUM="${DIST_SUM:-$DIST_IMG.sha256}"
DIST_INFO="${DIST_INFO:-$DIST_DIR/system-update-latest.build-info.txt}"
DIST_BASENAME="$(basename "$DIST_IMG")"
SNAPSHOT_DIR="$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/opt"
SNAPSHOT_DIR_REL="seedsigner-os/opt/rootfs-overlay/opt"
GENERATED_MANIFEST_REL="seedsigner-os/opt/rootfs-overlay/opt/src/seedsigner/resources/offline-signer-firmware-integrity.json"
SNAPSHOT_TIME_FILE="$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/opt/src/.build_commit_time"
NFC_BINDINGS_FILE="$ROOT_DIR/seedsigner-os/opt/external-packages/nfc-bindings/nfc-bindings.mk"
XZ_THREADS="${XZ_THREADS:-1}"
BUILD_CLEAN_MODE="${TP_BUILD_CLEAN_MODE:-clean}"

case "$BUILD_CLEAN_MODE" in
  clean|no-clean)
    ;;
  *)
    echo "Unsupported TP_BUILD_CLEAN_MODE: $BUILD_CLEAN_MODE" >&2
    echo "Expected one of: clean, no-clean" >&2
    exit 1
    ;;
esac

mkdir -p "$DIST_DIR"

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  export TP_BUILD_CLEAN_MODE="$BUILD_CLEAN_MODE"
  "$ROOT_DIR/scripts/run_seedsigner_build.sh"
fi

if [[ ! -f "$RAW_IMG" ]]; then
  if [[ -f "$LEGACY_RAW_IMG" ]]; then
    RAW_IMG="$LEGACY_RAW_IMG"
  else
    echo "Raw image not found: $RAW_IMG" >&2
    exit 1
  fi
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
repo_head="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
build_epoch="$(git -C "$ROOT_DIR" show -s --format=%ct "$repo_head" 2>/dev/null || echo "")"
if [[ -n "$build_epoch" ]]; then
  build_time_utc="$(date -u -d "@$build_epoch" '+%Y-%m-%dT%H:%M:%SZ')"
else
  build_time_utc=""
fi
repo_status="$(git -C "$ROOT_DIR" status --porcelain 2>/dev/null || true)"
repo_dirty=0
if [[ -n "$repo_status" ]]; then
  repo_dirty=1
fi
if [[ "$repo_dirty" == "1" && "$DIST_BASENAME" == "system-update-latest.img.xz" && "${ALLOW_DIRTY_REPO:-0}" != "1" ]]; then
  echo "Refusing to write dist/system-update-latest.img.xz from a dirty repository." >&2
  echo "Commit source/doc changes first, or set DIST_IMG/DIST_SUM/DIST_INFO to a scratch filename for test builds." >&2
  echo "Override only if you truly want an unreproducible stable artifact: ALLOW_DIRTY_REPO=1" >&2
  exit 1
fi
if [[ "$BUILD_CLEAN_MODE" != "clean" && "$DIST_BASENAME" == "system-update-latest.img.xz" && "${ALLOW_NO_CLEAN_RELEASE_BUILD:-0}" != "1" ]]; then
  echo "Refusing to write dist/system-update-latest.img.xz from a no-clean build." >&2
  echo "Stable artifacts must come from TP_BUILD_CLEAN_MODE=clean so later rebuilds have a chance to match." >&2
  echo "Use a scratch DIST_IMG filename for incremental test builds, or override only if you truly want a non-reproducible stable artifact: ALLOW_NO_CLEAN_RELEASE_BUILD=1" >&2
  exit 1
fi
snapshot_tree_sha="$(
  (
    cd "$SNAPSHOT_DIR"
    while IFS= read -r -d '' file; do
      rel_path="${file#$SNAPSHOT_DIR_REL/}"
      if [[ "$rel_path" == "${GENERATED_MANIFEST_REL#$SNAPSHOT_DIR_REL/}" ]]; then
        continue
      fi
      sha256sum "./$rel_path"
    done < <(git -C "$ROOT_DIR" ls-files -z -- "$SNAPSHOT_DIR_REL")
  ) | sha256sum | awk '{print $1}'
)"
nfc_bindings_sha="$(sha256sum "$NFC_BINDINGS_FILE" | awk '{print $1}')"
RAW_BUILD_INFO="${RAW_BUILD_INFO:-$RAW_IMG.build-info.txt}"
CURRENT_ZIMAGE="${CURRENT_ZIMAGE:-$ASCII_BUILD_DIR/images/zImage}"
CURRENT_ROOTFS_CPIO="${CURRENT_ROOTFS_CPIO:-$ASCII_BUILD_DIR/images/rootfs.cpio}"

if [[ -f "$RAW_BUILD_INFO" ]]; then
  # The raw image should carry a build fingerprint so packaging can reject stale
  # outputs that no longer match the current runtime tree.
  # shellcheck disable=SC1090
  source "$RAW_BUILD_INFO"

  if [[ -n "${raw_image_sha256:-}" && "$raw_image_sha256" != "$raw_sha" ]]; then
    echo "Raw image sha256 does not match its recorded build info: $RAW_BUILD_INFO" >&2
    echo "Expected $raw_image_sha256 but found $raw_sha" >&2
    echo "Run bash scripts/build_current_firmware.sh or bash scripts/run_seedsigner_build.sh first." >&2
    exit 1
  fi

  if [[ -n "${runtime_snapshot_tree_sha256:-}" && "$runtime_snapshot_tree_sha256" != "$snapshot_tree_sha" && "${ALLOW_STALE_RAW_IMAGE:-0}" != "1" ]]; then
    echo "Raw image was built from an older runtime tree than the current worktree." >&2
    echo "Raw image tree sha: $runtime_snapshot_tree_sha256" >&2
    echo "Current tree sha:   $snapshot_tree_sha" >&2
    echo "Rebuild the raw image before packaging: bash scripts/build_current_firmware.sh" >&2
    echo "Override only if you intentionally want to package a stale raw image: ALLOW_STALE_RAW_IMAGE=1" >&2
    exit 1
  fi

  if [[ -n "${nfc_bindings_mk_sha256:-}" && "$nfc_bindings_mk_sha256" != "$nfc_bindings_sha" && "${ALLOW_STALE_RAW_IMAGE:-0}" != "1" ]]; then
    echo "Raw image was built against different NFC bindings metadata." >&2
    echo "Raw image nfc sha:  $nfc_bindings_mk_sha256" >&2
    echo "Current nfc sha:    $nfc_bindings_sha" >&2
    echo "Rebuild the raw image before packaging: bash scripts/build_current_firmware.sh" >&2
    echo "Override only if you intentionally want to package a stale raw image: ALLOW_STALE_RAW_IMAGE=1" >&2
    exit 1
  fi

  if [[ -f "$CURRENT_ZIMAGE" && -n "${build_output_zimage_sha256:-}" ]]; then
    current_zimage_sha="$(sha256sum "$CURRENT_ZIMAGE" | awk '{print $1}')"
    if [[ "$current_zimage_sha" != "$build_output_zimage_sha256" && "${ALLOW_STALE_RAW_IMAGE:-0}" != "1" ]]; then
      echo "Current zImage differs from the zImage that produced the raw image." >&2
      echo "Raw image zImage sha: $build_output_zimage_sha256" >&2
      echo "Current zImage sha:   $current_zimage_sha" >&2
      echo "Rebuild the raw image before packaging: bash scripts/build_current_firmware.sh" >&2
      echo "Override only if you intentionally want to package a stale raw image: ALLOW_STALE_RAW_IMAGE=1" >&2
      exit 1
    fi
  fi

  if [[ -f "$CURRENT_ROOTFS_CPIO" && -n "${build_output_rootfs_cpio_sha256:-}" ]]; then
    current_rootfs_cpio_sha="$(sha256sum "$CURRENT_ROOTFS_CPIO" | awk '{print $1}')"
    if [[ "$current_rootfs_cpio_sha" != "$build_output_rootfs_cpio_sha256" && "${ALLOW_STALE_RAW_IMAGE:-0}" != "1" ]]; then
      echo "Current rootfs.cpio differs from the rootfs packed into the raw image." >&2
      echo "Raw image rootfs sha: $build_output_rootfs_cpio_sha256" >&2
      echo "Current rootfs sha:   $current_rootfs_cpio_sha" >&2
      echo "Rebuild the raw image before packaging: bash scripts/build_current_firmware.sh" >&2
      echo "Override only if you intentionally want to package a stale raw image: ALLOW_STALE_RAW_IMAGE=1" >&2
      exit 1
    fi
  fi
elif [[ "$RAW_IMG" == "$ASCII_IMAGE_DIR/"* && "${ALLOW_MISSING_RAW_BUILD_INFO:-0}" != "1" ]]; then
  echo "Raw image build info not found: $RAW_BUILD_INFO" >&2
  echo "Run bash scripts/build_current_firmware.sh first so the raw image is stamped with the current source fingerprint." >&2
  echo "Override only if you intentionally want to package an unmanaged raw image: ALLOW_MISSING_RAW_BUILD_INFO=1" >&2
  exit 1
fi

raw_image_path="$RAW_IMG"
if [[ "$RAW_IMG" == "$ROOT_DIR/"* ]]; then
  raw_image_path="${RAW_IMG#$ROOT_DIR/}"
elif [[ "$RAW_IMG" == "$ASCII_BASE/"* ]]; then
  raw_image_path="TP_ASCII_BASE/${RAW_IMG#$ASCII_BASE/}"
elif [[ "$RAW_IMG" == "$HOME/"* ]]; then
  raw_image_path="HOME/${RAW_IMG#$HOME/}"
fi

tmp_img="$(mktemp "$DIST_DIR/.${DIST_BASENAME}.XXXXXX")"
ionice -c3 nice -n 19 xz -T"$XZ_THREADS" -9 -c "$RAW_IMG" > "$tmp_img"
mv "$tmp_img" "$DIST_IMG"

dist_sha="$(sha256sum "$DIST_IMG" | awk '{print $1}')"
printf '%s  %s\n' "$dist_sha" "$(basename "$DIST_IMG")" > "$DIST_SUM"

cat > "$DIST_INFO" <<EOF
source_snapshot_build_commit_time=$snapshot_time
raw_image_path=$raw_image_path
raw_image_sha256=$raw_sha
raw_image_build_info_path=$RAW_BUILD_INFO
compressed_image_path=dist/$(basename "$DIST_IMG")
compressed_image_sha256=$dist_sha
repo_head=$repo_head
repo_dirty=$repo_dirty
runtime_snapshot_tree_sha256=$snapshot_tree_sha
nfc_bindings_mk_sha256=$nfc_bindings_sha
build_script=scripts/run_seedsigner_build.sh
package_script=scripts/build_pi_firmware_from_snapshot.sh
build_clean_mode=$BUILD_CLEAN_MODE
build_time_utc=$build_time_utc
EOF

echo "Raw image:        $RAW_IMG"
echo "Raw image sha256: $raw_sha"
echo "Dist image:       $DIST_IMG"
echo "Dist image sha256:$dist_sha"
echo "Build info:       $DIST_INFO"
