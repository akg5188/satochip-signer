#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"

export BR2_JLEVEL="${BR2_JLEVEL:-1}"
export TP_BUILD_CPUSET="${TP_BUILD_CPUSET:-0}"
export TP_BUILD_NICE="${TP_BUILD_NICE:-19}"
export TP_BUILD_IONICE_CLASS="${TP_BUILD_IONICE_CLASS:-3}"
export TP_BUILD_CLEAN_MODE="${TP_BUILD_CLEAN_MODE:-no-clean}"
export XZ_THREADS="${XZ_THREADS:-1}"
export DIST_IMG="${DIST_IMG:-$DIST_DIR/system-update-worktree-latest.img.xz}"
export DIST_SUM="${DIST_SUM:-$DIST_IMG.sha256}"
export DIST_INFO="${DIST_INFO:-$DIST_DIR/system-update-worktree-latest.build-info.txt}"

echo "Building latest worktree firmware"
echo "  dist_img=$DIST_IMG"
echo "  build_clean_mode=$TP_BUILD_CLEAN_MODE"
echo "  br2_jlevel=$BR2_JLEVEL"
echo "  cpuset=$TP_BUILD_CPUSET"
echo "  note=system-update-latest is reserved for clean HEAD builds"

rm -f \
  "$DIST_DIR"/system-update-worktree-latest.img.xz \
  "$DIST_DIR"/system-update-worktree-latest.img.xz.sha256 \
  "$DIST_DIR"/system-update-worktree-latest.build-info.txt \
  "$DIST_DIR"/system-update-current-latest.img.xz \
  "$DIST_DIR"/system-update-current-latest.img.xz.sha256 \
  "$DIST_DIR"/system-update-current-latest.build-info.txt \
  "$DIST_DIR"/system-update-current-test-*.img.xz \
  "$DIST_DIR"/system-update-current-test-*.img.xz.sha256 \
  "$DIST_DIR"/system-update-current-test-*.build-info.txt

bash "$ROOT_DIR/scripts/build_pi_firmware_from_snapshot.sh"
