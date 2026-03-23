#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

warn() {
  echo "WARN: $*" >&2
}

require_file() {
  local path="$1"
  [[ -f "$path" ]] || fail "Missing required file: $path"
}

check_artifact() {
  local artifact="$1"
  local sha_file="$2"
  local info_file="$3"

  require_file "$artifact"
  require_file "$sha_file"
  require_file "$info_file"

  local expected_sha
  local actual_sha
  expected_sha="$(awk 'NR==1 {print $1}' "$sha_file")"
  actual_sha="$(sha256sum "$artifact" | awk '{print $1}')"
  [[ "$expected_sha" == "$actual_sha" ]] || fail "sha256 mismatch for $artifact"

  local info_sha
  info_sha="$(awk -F= '/^artifact_sha256=/{print $2}' "$info_file")"
  [[ "$info_sha" == "$actual_sha" ]] || fail "build-info mismatch for $artifact"

  grep -q '^repo_head=' "$info_file" || fail "Missing repo_head in $info_file"
  grep -q '^build_script=' "$info_file" || fail "Missing build_script in $info_file"
}

check_optional_artifact() {
  local label="$1"
  local artifact="$2"
  local sha_file="$3"
  local info_file="$4"
  local present_count=0

  [[ -f "$artifact" ]] && present_count=$((present_count + 1))
  [[ -f "$sha_file" ]] && present_count=$((present_count + 1))
  [[ -f "$info_file" ]] && present_count=$((present_count + 1))

  if [[ "$present_count" -eq 0 ]]; then
    if [[ "${STRICT_MISSING_RELEASE_ARTIFACTS:-0}" == "1" ]]; then
      fail "Missing optional release artifact set: $label"
    fi
    warn "Optional release artifact not present yet: $label"
    return 0
  fi

  check_artifact "$artifact" "$sha_file" "$info_file"
}

require_file "$ROOT_DIR/card-applet/prebuilt/SatoChip-3.0.4.cap"
require_file "$ROOT_DIR/card-applet/prebuilt/SHA256SUMS.txt"
( cd "$ROOT_DIR/card-applet/prebuilt" && sha256sum -c SHA256SUMS.txt >/dev/null )

check_artifact \
  "$ROOT_DIR/dist/tp-qr-relay-android-latest.apk" \
  "$ROOT_DIR/dist/tp-qr-relay-android-latest.apk.sha256" \
  "$ROOT_DIR/dist/tp-qr-relay-android-latest.build-info.txt"

check_optional_artifact \
  "wallet release APK" \
  "$ROOT_DIR/dist/satochip-wallet-release.apk" \
  "$ROOT_DIR/dist/satochip-wallet-release.apk.sha256" \
  "$ROOT_DIR/dist/satochip-wallet-release.build-info.txt"

echo "Release artifact checks passed."
