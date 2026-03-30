#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/dist}"
BUILD_ROOT="${BUILD_ROOT:-/tmp/satochip-wallet-ascii-build}"
OUT_APK="$OUT_DIR/satochip-wallet-release.apk"
OUT_SUM="$OUT_APK.sha256"
OUT_INFO="$OUT_DIR/satochip-wallet-release.build-info.txt"

mkdir -p "$OUT_DIR"

(
  cd "$ROOT_DIR/wallet"
  OUT_DIR="$OUT_DIR" BUILD_ROOT="$BUILD_ROOT" ./scripts/build_local_ascii.sh release
)

repo_head="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
apk_sha="$(awk 'NR==1 {print $1}' "$OUT_SUM")"
version_name="$(awk -F'"' '/versionName = / {print $2; exit}' "$ROOT_DIR/wallet/app/build.gradle.kts")"
build_time_utc="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

cat > "$OUT_INFO" <<EOF
module=wallet
artifact_path=dist/$(basename "$OUT_APK")
artifact_sha256=$apk_sha
version_name=$version_name
repo_head=$repo_head
build_script=scripts/build_wallet_release.sh
build_time_utc=$build_time_utc
EOF

echo "APK written to: $OUT_APK"
echo "SHA256 file:    $OUT_SUM"
echo "Build info:     $OUT_INFO"
