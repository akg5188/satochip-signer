#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_ROOT="${BUILD_ROOT:-$HOME/ascii-build-clean}"
BUILD_DIR="$BUILD_ROOT/satochip-wallet-android"
OUT_DIR="$SRC_DIR/dist"
VARIANT="${1:-release}"

case "$VARIANT" in
  release)
    GRADLE_TASK=":app:assembleRelease"
    SRC_APK="$BUILD_DIR/app/build/outputs/apk/release/app-release.apk"
    OUT_APK="$OUT_DIR/satochip-wallet-release.apk"
    ;;
  debug)
    GRADLE_TASK=":app:assembleDebug"
    SRC_APK="$BUILD_DIR/app/build/outputs/apk/debug/app-debug.apk"
    OUT_APK="$OUT_DIR/satochip-wallet-debug.apk"
    ;;
  *)
    echo "用法: ./scripts/build_local_ascii.sh [release|debug]" >&2
    exit 1
    ;;
esac

mkdir -p "$BUILD_ROOT"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

rsync -a \
  --exclude '.gradle' \
  --exclude 'app/build' \
  --exclude 'dist' \
  --exclude 'local.properties' \
  "$SRC_DIR/" "$BUILD_DIR/"

if [[ -f "$SRC_DIR/local.properties" ]]; then
  cp "$SRC_DIR/local.properties" "$BUILD_DIR/local.properties"
else
  printf 'sdk.dir=/home/ak/Android/Sdk\n' > "$BUILD_DIR/local.properties"
fi

cd "$BUILD_DIR"
export JAVA_HOME="${JAVA_HOME:-/home/ak/zero/.local-jdk/jdk-17.0.18+8}"
export PATH="$JAVA_HOME/bin:$PATH"
./gradlew --no-daemon "$GRADLE_TASK" --console=plain

mkdir -p "$OUT_DIR"
cp -f "$SRC_APK" "$OUT_APK"
sha256sum "$OUT_APK" > "$OUT_APK.sha256"

echo "APK written to: $OUT_APK"
