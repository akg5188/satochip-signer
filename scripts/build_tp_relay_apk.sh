#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_ROOT="${BUILD_ROOT:-/tmp/satochip-relay-ascii-build}"
BUILD_DIR="${BUILD_DIR:-$BUILD_ROOT/satochip-signer-android}"
GRADLE_USER_HOME="${GRADLE_USER_HOME:-$BUILD_ROOT/.gradle}"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/dist}"
OUT_APK="$OUT_DIR/tp-qr-relay-android-latest.apk"
OUT_SUM="$OUT_APK.sha256"
OUT_INFO="$OUT_DIR/tp-qr-relay-android-latest.build-info.txt"
REQUIRED_JAVA_MAJOR="17"

java_major_version() {
  local java_bin="$1"
  "$java_bin" -version 2>&1 | awk -F '"' '/version/ {split($2, parts, "."); print parts[1]; exit}'
}

is_required_jdk() {
  local candidate="${1:-}"
  local java_bin="$candidate/bin/java"
  local javac_bin="$candidate/bin/javac"
  local major=""
  [[ -x "$java_bin" && -x "$javac_bin" ]] || return 1
  major="$(java_major_version "$java_bin")"
  [[ "$major" == "$REQUIRED_JAVA_MAJOR" ]]
}

detect_java_home() {
  local candidate=""

  find_local_jdk17() {
    local dir
    shopt -s nullglob
    for dir in "$HOME"/.local-jdk/jdk-17*; do
      if [[ -x "$dir/bin/java" && -x "$dir/bin/javac" ]]; then
        printf '%s\n' "$dir"
        return 0
      fi
    done
    return 1
  }

  for candidate in \
    "${JAVA_HOME:-}" \
    "$(find_local_jdk17 || true)"
  do
    if [[ -n "$candidate" ]] && is_required_jdk "$candidate"; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  if command -v javac >/dev/null 2>&1; then
    candidate="$(dirname "$(dirname "$(readlink -f "$(command -v javac)")")")"
    if is_required_jdk "$candidate"; then
      printf '%s\n' "$candidate"
      return
    fi
  fi

  if command -v java >/dev/null 2>&1; then
    candidate="$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")"
    if is_required_jdk "$candidate"; then
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
    "$(read_sdk_dir_from_properties "$ROOT_DIR/local.properties")" \
    "${ANDROID_SDK_ROOT:-}" \
    "${ANDROID_HOME:-}" \
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

mkdir -p "$BUILD_ROOT" "$GRADLE_USER_HOME" "$OUT_DIR"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

rsync -a \
  --exclude '.git' \
  --exclude '.gradle' \
  --exclude 'build' \
  --exclude 'dist' \
  --exclude 'local.properties' \
  "$ROOT_DIR/gradle" \
  "$ROOT_DIR/gradlew" \
  "$ROOT_DIR/build.gradle.kts" \
  "$ROOT_DIR/settings.gradle.kts" \
  "$ROOT_DIR/gradle.properties" \
  "$ROOT_DIR/local.properties.example" \
  "$ROOT_DIR/app" \
  "$ROOT_DIR/satochip-lib" \
  "$ROOT_DIR/pi-signer" \
  "$BUILD_DIR/"

printf 'sdk.dir=%s\n' "$SDK_DIR" > "$BUILD_DIR/local.properties"

cd "$BUILD_DIR"
export JAVA_HOME="$(detect_java_home)"
if [[ -z "$JAVA_HOME" ]]; then
  echo "Unable to locate a usable JDK $REQUIRED_JAVA_MAJOR with both java and javac" >&2
  exit 1
fi
export GRADLE_USER_HOME
export ORG_GRADLE_JAVA_INSTALLATIONS_PATHS="$JAVA_HOME"
export PATH="$JAVA_HOME/bin:$PATH"
./gradlew --no-daemon :app:assembleRelease --console=plain

cp -f "$BUILD_DIR/app/build/outputs/apk/release/app-release.apk" "$OUT_APK"
apk_sha="$(sha256sum "$OUT_APK" | awk '{print $1}')"
printf '%s  %s\n' "$apk_sha" "$(basename "$OUT_APK")" > "$OUT_SUM"

repo_head="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
version_name="$(awk -F'"' '/versionName = / {print $2; exit}' "$ROOT_DIR/app/build.gradle.kts")"
build_epoch="$(git -C "$ROOT_DIR" show -s --format=%ct "$repo_head" 2>/dev/null || echo "")"
if [[ -n "$build_epoch" ]]; then
  build_time_utc="$(date -u -d "@$build_epoch" '+%Y-%m-%dT%H:%M:%SZ')"
else
  build_time_utc=""
fi

cat > "$OUT_INFO" <<EOF
module=app
artifact_path=dist/$(basename "$OUT_APK")
artifact_sha256=$apk_sha
version_name=$version_name
repo_head=$repo_head
build_script=scripts/build_tp_relay_apk.sh
build_time_utc=$build_time_utc
EOF

echo "APK written to: $OUT_APK"
echo "SHA256 file:    $OUT_SUM"
echo "Build info:     $OUT_INFO"
