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

check_pi_firmware_artifact() {
  local artifact="$1"
  local sha_file="$2"
  local info_file="$3"
  local require_clean="${4:-0}"
  local allow_missing_build_clean_mode="${5:-0}"

  require_file "$artifact"
  require_file "$sha_file"
  require_file "$info_file"

  local expected_sha
  local actual_sha
  expected_sha="$(awk 'NR==1 {print $1}' "$sha_file")"
  actual_sha="$(sha256sum "$artifact" | awk '{print $1}')"
  [[ "$expected_sha" == "$actual_sha" ]] || fail "sha256 mismatch for $artifact"

  local info_sha
  info_sha="$(awk -F= '/^compressed_image_sha256=/{print $2}' "$info_file")"
  [[ "$info_sha" == "$actual_sha" ]] || fail "build-info mismatch for $artifact"

  local info_raw_sha
  local raw_sha
  info_raw_sha="$(awk -F= '/^raw_image_sha256=/{print $2}' "$info_file")"
  raw_sha="$(xz -dc "$artifact" | sha256sum | awk '{print $1}')"
  [[ "$info_raw_sha" == "$raw_sha" ]] || fail "raw image sha mismatch for $artifact"

  grep -q '^repo_head=' "$info_file" || fail "Missing repo_head in $info_file"
  grep -q '^repo_dirty=' "$info_file" || fail "Missing repo_dirty in $info_file"
  grep -q '^runtime_snapshot_tree_sha256=' "$info_file" || fail "Missing runtime_snapshot_tree_sha256 in $info_file"
  grep -q '^nfc_bindings_mk_sha256=' "$info_file" || fail "Missing nfc_bindings_mk_sha256 in $info_file"
  grep -q '^build_script=' "$info_file" || fail "Missing build_script in $info_file"
  grep -q '^package_script=' "$info_file" || fail "Missing package_script in $info_file"
  local repo_dirty
  repo_dirty="$(awk -F= '/^repo_dirty=/{print $2}' "$info_file")"
  local build_clean_mode
  if grep -q '^build_clean_mode=' "$info_file"; then
    build_clean_mode="$(awk -F= '/^build_clean_mode=/{print $2}' "$info_file")"
  elif [[ "$allow_missing_build_clean_mode" == "1" ]]; then
    warn "Missing build_clean_mode in $info_file; treating as legacy clean-baseline metadata"
    build_clean_mode=""
  else
    fail "Missing build_clean_mode in $info_file"
  fi

  if [[ "$require_clean" == "1" ]]; then
    [[ "$repo_dirty" == "0" ]] || fail "Pi firmware build-info repo_dirty must be 0"
    if [[ -n "$build_clean_mode" ]]; then
      [[ "$build_clean_mode" == "clean" ]] || fail "Pi firmware build-info build_clean_mode must be clean"
    fi
  fi

  local repo_head
  repo_head="$(awk -F= '/^repo_head=/{print $2}' "$info_file")"
  git -C "$ROOT_DIR" cat-file -e "${repo_head}^{commit}" 2>/dev/null || fail "repo_head ${repo_head} from $info_file is not a valid commit"
  git -C "$ROOT_DIR" merge-base --is-ancestor "$repo_head" HEAD 2>/dev/null || fail "repo_head ${repo_head} from $info_file is not reachable from current HEAD"

  local package_script
  package_script="$(awk -F= '/^package_script=/{print $2}' "$info_file")"
  [[ "$package_script" != "manual-low-impact-xz" ]] || fail "Pi firmware build-info still uses obsolete manual-low-impact-xz package_script"
}

check_pi_firmware_backup_artifact() {
  check_pi_firmware_artifact "$1" "$2" "$3" 0 0
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

warn_if_optional_artifact_stale() {
  local label="$1"
  local info_file="$2"
  local expected_build_script="${3:-}"
  local repo_head
  local current_head
  local build_script

  repo_head="$(awk -F= '/^repo_head=/{print $2}' "$info_file")"
  current_head="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  if [[ -n "$repo_head" && "$repo_head" != "$current_head" ]]; then
    warn "$label is not rebuilt from current HEAD: repo_head=$repo_head current_head=$current_head"
  fi

  if [[ -n "$expected_build_script" ]]; then
    build_script="$(awk -F= '/^build_script=/{print $2}' "$info_file")"
    if [[ -n "$build_script" && "$build_script" != "$expected_build_script" ]]; then
      warn "$label uses non-canonical build_script=$build_script expected=$expected_build_script"
    fi
  fi
}

check_optional_artifact() {
  local label="$1"
  local artifact="$2"
  local sha_file="$3"
  local info_file="$4"
  local expected_build_script="${5:-}"
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
  warn_if_optional_artifact_stale "$label" "$info_file" "$expected_build_script"
}

require_file "$ROOT_DIR/card-applet/prebuilt/SatoChip-3.0.4.cap"
require_file "$ROOT_DIR/card-applet/prebuilt/SHA256SUMS.txt"
( cd "$ROOT_DIR/card-applet/prebuilt" && sha256sum -c SHA256SUMS.txt >/dev/null )

check_pi_firmware_artifact \
  "$ROOT_DIR/dist/system-update-latest.img.xz" \
  "$ROOT_DIR/dist/system-update-latest.img.xz.sha256" \
  "$ROOT_DIR/dist/system-update-latest.build-info.txt" \
  1 \
  1

if [[ -f "$ROOT_DIR/dist/system-update-offline-signer-repair7.img.xz" || \
      -f "$ROOT_DIR/dist/system-update-offline-signer-repair7.img.xz.sha256" || \
      -f "$ROOT_DIR/dist/system-update-offline-signer-repair7.build-info.txt" ]]; then
  check_pi_firmware_backup_artifact \
    "$ROOT_DIR/dist/system-update-offline-signer-repair7.img.xz" \
    "$ROOT_DIR/dist/system-update-offline-signer-repair7.img.xz.sha256" \
    "$ROOT_DIR/dist/system-update-offline-signer-repair7.build-info.txt"
fi

check_optional_artifact \
  "TP relay APK" \
  "$ROOT_DIR/dist/tp-qr-relay-android-latest.apk" \
  "$ROOT_DIR/dist/tp-qr-relay-android-latest.apk.sha256" \
  "$ROOT_DIR/dist/tp-qr-relay-android-latest.build-info.txt" \
  "scripts/build_tp_relay_apk.sh"

check_optional_artifact \
  "wallet release APK" \
  "$ROOT_DIR/dist/satochip-wallet-release.apk" \
  "$ROOT_DIR/dist/satochip-wallet-release.apk.sha256" \
  "$ROOT_DIR/dist/satochip-wallet-release.build-info.txt" \
  "scripts/build_wallet_release.sh"

echo "Release artifact checks passed."
