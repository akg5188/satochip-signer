#!/usr/bin/env bash
set -euo pipefail

SRC_DIR='/home/ak/树莓派/arbitrum-wallet-android'
BUILD_ROOT='/home/ak/ascii-build-clean'
BUILD_DIR="$BUILD_ROOT/arbitrum-wallet-android"
OUT_DIR="$SRC_DIR/dist"

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
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
./gradlew --no-daemon :app:assembleDebug --console=plain

mkdir -p "$OUT_DIR"
cp -f "$BUILD_DIR/app/build/outputs/apk/debug/app-debug.apk" "$OUT_DIR/arbitrum-wallet-debug.apk"
sha256sum "$OUT_DIR/arbitrum-wallet-debug.apk" > "$OUT_DIR/arbitrum-wallet-debug.apk.sha256"

echo "APK written to: $OUT_DIR/arbitrum-wallet-debug.apk"
