#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WALLET_DIR="$ROOT_DIR/wallet"
SDK_DIR="${ANDROID_SDK_ROOT:-/tmp/satochip-android-sdk}"
TOOLS_URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
TOOLS_DIR="$SDK_DIR/cmdline-tools"
LATEST_DIR="$TOOLS_DIR/latest"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$SDK_DIR" "$TOOLS_DIR"

if [[ ! -x "$LATEST_DIR/bin/sdkmanager" ]]; then
  curl -fsSL "$TOOLS_URL" -o "$TMP_DIR/cmdline-tools.zip"
  unzip -q "$TMP_DIR/cmdline-tools.zip" -d "$TMP_DIR/unpack"
  rm -rf "$LATEST_DIR"
  mkdir -p "$LATEST_DIR"
  rsync -a "$TMP_DIR/unpack/cmdline-tools/" "$LATEST_DIR/"
fi

export ANDROID_SDK_ROOT="$SDK_DIR"
export ANDROID_HOME="$SDK_DIR"

yes | "$LATEST_DIR/bin/sdkmanager" --sdk_root="$SDK_DIR" --licenses >/dev/null || true
"$LATEST_DIR/bin/sdkmanager" --sdk_root="$SDK_DIR" \
  "platform-tools" \
  "platforms;android-34" \
  "build-tools;34.0.0"

cat > "$ROOT_DIR/local.properties" <<EOF
sdk.dir=$SDK_DIR
EOF

if [[ -d "$WALLET_DIR" ]]; then
cat > "$WALLET_DIR/local.properties" <<EOF
sdk.dir=$SDK_DIR
EOF
fi

printf 'SDK ready at %s\n' "$SDK_DIR"
