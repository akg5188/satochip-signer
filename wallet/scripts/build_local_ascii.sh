#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_ROOT="${BUILD_ROOT:-/tmp/satochip-wallet-ascii-build}"
BUILD_DIR="$BUILD_ROOT/satochip-wallet-android"
GRADLE_USER_HOME="${GRADLE_USER_HOME:-$BUILD_ROOT/.gradle}"
OUT_DIR="${OUT_DIR:-$SRC_DIR/dist}"
VARIANT="${1:-release}"

detect_java_home() {
  local candidate=""

  for candidate in \
    "${JAVA_HOME:-}" \
    "/home/ak/.local-jdk/jdk-17.0.18+8"
  do
    if [[ -n "$candidate" && -x "$candidate/bin/java" && -x "$candidate/bin/javac" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  if command -v javac >/dev/null 2>&1; then
    dirname "$(dirname "$(readlink -f "$(command -v javac)")")"
    return
  fi

  if command -v java >/dev/null 2>&1; then
    candidate="$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")"
    if [[ -x "$candidate/bin/javac" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  fi

  echo ""
}

read_sdk_dir_from_properties() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  awk -F= '/^sdk\.dir=/{sub(/^[^=]*=/, ""); print; exit}' "$file"
}

is_valid_sdk_dir() {
  local dir="${1:-}"
  [[ -n "$dir" && -d "$dir" ]]
}

detect_android_sdk() {
  local candidate

  for candidate in \
    "$(read_sdk_dir_from_properties "$SRC_DIR/local.properties")" \
    "${ANDROID_SDK_ROOT:-}" \
    "${ANDROID_HOME:-}" \
    "/home/ak/Android/Sdk" \
    "$HOME/Android/Sdk" \
    "$HOME/Android/sdk" \
    "/usr/lib/android-sdk" \
    "/opt/android-sdk" \
    "/opt/android-sdk-linux"
  do
    if is_valid_sdk_dir "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  echo ""
}

require_sdk_component() {
  local path="$1"
  local description="$2"
  if [[ ! -e "$path" ]]; then
    cat >&2 <<EOF
Missing required Android SDK component: $description
Checked path: $path

Install at least:
  platforms;android-34
  build-tools;35.0.0
  platform-tools
EOF
    exit 1
  fi
}

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

SDK_DIR="$(detect_android_sdk)"
if [[ -z "$SDK_DIR" ]]; then
  cat >&2 <<'EOF'
Unable to locate a usable Android SDK.

Checked:
  1. ./local.properties -> sdk.dir
  2. ANDROID_SDK_ROOT
  3. ANDROID_HOME
  4. Common paths like ~/Android/Sdk

Fix it with either:
  cp local.properties.example local.properties
  # then edit sdk.dir=/your/Android/Sdk

Or export:
  export ANDROID_SDK_ROOT=/your/Android/Sdk

Required packages:
  platforms;android-34
  build-tools;35.0.0
  platform-tools
EOF
  exit 1
fi

require_sdk_component "$SDK_DIR/platforms/android-34" "Android SDK Platform 34"
require_sdk_component "$SDK_DIR/build-tools/35.0.0" "Android Build Tools 35.0.0"
require_sdk_component "$SDK_DIR/platform-tools" "Android platform-tools"

mkdir -p "$BUILD_ROOT" "$GRADLE_USER_HOME"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

rsync -a \
  --exclude '.gradle' \
  --exclude 'app/build' \
  --exclude 'dist' \
  --exclude 'local.properties' \
  "$SRC_DIR/" "$BUILD_DIR/"

printf 'sdk.dir=%s\n' "$SDK_DIR" > "$BUILD_DIR/local.properties"

cd "$BUILD_DIR"
export JAVA_HOME="$(detect_java_home)"
if [[ -z "$JAVA_HOME" ]]; then
  echo "Unable to locate a usable JDK 17 with both java and javac" >&2
  exit 1
fi
export GRADLE_USER_HOME
export ORG_GRADLE_JAVA_INSTALLATIONS_PATHS="$JAVA_HOME"
export PATH="$JAVA_HOME/bin:$PATH"
./gradlew --no-daemon "$GRADLE_TASK" --console=plain

mkdir -p "$OUT_DIR"
cp -f "$SRC_APK" "$OUT_APK"
sha256sum "$OUT_APK" > "$OUT_APK.sha256"

echo "APK written to: $OUT_APK"
