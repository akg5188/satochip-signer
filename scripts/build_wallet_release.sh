#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/dist}"
BUILD_ROOT="${BUILD_ROOT:-/tmp/satochip-wallet-ascii-build}"
ARTIFACT_MODE="${WALLET_ARTIFACT_MODE:-worktree-latest}"

case "$ARTIFACT_MODE" in
  release-baseline)
    OUT_APK="${OUT_APK:-$OUT_DIR/satochip-wallet-release.apk}"
    OUT_INFO="${OUT_INFO:-$OUT_DIR/satochip-wallet-release.build-info.txt}"
    ;;
  worktree-latest)
    OUT_APK="${OUT_APK:-$OUT_DIR/satochip-wallet-worktree-latest.apk}"
    OUT_INFO="${OUT_INFO:-$OUT_DIR/satochip-wallet-worktree-latest.build-info.txt}"
    ;;
  *)
    echo "Unknown WALLET_ARTIFACT_MODE: $ARTIFACT_MODE (supported: release-baseline, worktree-latest)" >&2
    exit 1
    ;;
esac

OUT_SUM="${OUT_SUM:-$OUT_APK.sha256}"

mkdir -p "$OUT_DIR"

repo_head="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
repo_dirty="$(
  if [[ -n "$(git -C "$ROOT_DIR" status --porcelain --untracked-files=normal 2>/dev/null)" ]]; then
    echo 1
  else
    echo 0
  fi
)"
if [[ "$ARTIFACT_MODE" == "release-baseline" && "$repo_dirty" == "1" ]]; then
  echo "Refusing to write release-baseline wallet artifact from a dirty repository." >&2
  echo "Use bash scripts/build_current_wallet_apk.sh for current worktree builds." >&2
  exit 1
fi

(
  cd "$ROOT_DIR/wallet"
  OUT_DIR="$OUT_DIR" BUILD_ROOT="$BUILD_ROOT" ./scripts/build_local_ascii.sh release
)
apk_sha="$(awk 'NR==1 {print $1}' "$OUT_SUM")"
version_name="$(awk -F'"' '/versionName = / {print $2; exit}' "$ROOT_DIR/wallet/app/build.gradle.kts")"
build_epoch="$(git -C "$ROOT_DIR" show -s --format=%ct "$repo_head" 2>/dev/null || echo "")"
if [[ -n "$build_epoch" ]]; then
  build_time_utc="$(date -u -d "@$build_epoch" '+%Y-%m-%dT%H:%M:%SZ')"
else
  build_time_utc=""
fi

cat > "$OUT_INFO" <<EOF
module=wallet
artifact_path=dist/$(basename "$OUT_APK")
artifact_sha256=$apk_sha
version_name=$version_name
repo_head=$repo_head
repo_dirty=$repo_dirty
build_script=scripts/build_wallet_release.sh
artifact_mode=$ARTIFACT_MODE
build_time_utc=$build_time_utc
EOF

echo "APK written to: $OUT_APK"
echo "SHA256 file:    $OUT_SUM"
echo "Build info:     $OUT_INFO"
