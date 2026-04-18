#!/usr/bin/env bash
set -euo pipefail

SCRIPT_ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ROOT_DIR="${TP_RELEASE_ROOT_DIR:-$SCRIPT_ROOT_DIR}"
MANIFEST_PATH="${TP_RELEASE_MANIFEST_PATH:-$ROOT_DIR/release-manifest.json}"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_file() {
  local path="$1"
  [[ -f "$path" ]] || fail "Missing required file: $path"
}

usage() {
  cat <<'EOF'
用法:
  bash scripts/check_named_release.sh --list
  bash scripts/check_named_release.sh firmware-clean
  bash scripts/check_named_release.sh firmware-public-20260410b-clean
  bash scripts/check_named_release.sh wallet-release
EOF
}

manifest_print_profile() {
  local profile="$1"
  python3 - "$MANIFEST_PATH" "$profile" <<'PY'
import json
import shlex
import sys

manifest_path, profile = sys.argv[1:]
with open(manifest_path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

entry = data["profiles"].get(profile)
if entry is None:
    sys.exit(2)

for key in [
    "title",
    "release_tag",
    "source_tag",
    "artifact_type",
    "artifact_path",
    "sha_path",
    "build_info_path",
]:
    print(f"{key.upper()}={shlex.quote(str(entry[key]))}")

for key, value in entry.get("expected", {}).items():
    shell_key = f"EXPECTED_{key.upper()}"
    print(f"{shell_key}={shlex.quote(str(value))}")
PY
}

if [[ "${1:-}" == "--list" || "${1:-}" == "list" ]]; then
  python3 - "$MANIFEST_PATH" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

for name, entry in data["profiles"].items():
    print(f"{name}\t{entry['title']}\t{entry['release_tag']}\t{entry['source_tag']}")
PY
  exit 0
fi

PROFILE="${1:-}"
[[ -n "$PROFILE" ]] || {
  usage
  exit 1
}

if ! profile_vars="$(manifest_print_profile "$PROFILE")"; then
  usage
  fail "Unknown release profile: $PROFILE"
fi
eval "$profile_vars"

ARTIFACT="$ROOT_DIR/$ARTIFACT_PATH"
SHA_FILE="$ROOT_DIR/$SHA_PATH"
BUILD_INFO="$ROOT_DIR/$BUILD_INFO_PATH"
SOURCE_TAG_COMMIT="$(git -C "$ROOT_DIR" rev-parse "${SOURCE_TAG}^{commit}")"

require_file "$ARTIFACT"
require_file "$SHA_FILE"
require_file "$BUILD_INFO"

expected_sha_from_file="$(awk 'NR==1 {print $1}' "$SHA_FILE")"
actual_sha="$(sha256sum "$ARTIFACT" | awk '{print $1}')"
[[ "$actual_sha" == "$expected_sha_from_file" ]] || fail "sha256 mismatch for $ARTIFACT_PATH"

case "$ARTIFACT_TYPE" in
  firmware_xz)
    info_sha="$(awk -F= '/^compressed_image_sha256=/{print $2}' "$BUILD_INFO")"
    info_raw_sha="$(awk -F= '/^raw_image_sha256=/{print $2}' "$BUILD_INFO")"
    info_repo_head="$(awk -F= '/^repo_head=/{print $2}' "$BUILD_INFO")"
    info_repo_dirty="$(awk -F= '/^repo_dirty=/{print $2}' "$BUILD_INFO")"
    info_build_clean_mode="$(awk -F= '/^build_clean_mode=/{print $2}' "$BUILD_INFO")"
    raw_sha="$(xz -dc "$ARTIFACT" | sha256sum | awk '{print $1}')"

    [[ "$info_sha" == "$actual_sha" ]] || fail "build-info compressed_image_sha256 mismatch for $PROFILE"
    [[ "$info_raw_sha" == "$raw_sha" ]] || fail "build-info raw_image_sha256 mismatch for $PROFILE"
    [[ "$info_repo_head" == "$SOURCE_TAG_COMMIT" ]] || fail "build-info repo_head does not match source_tag for $PROFILE"
    if [[ -n "${EXPECTED_REPO_HEAD:-}" ]]; then
      [[ "$info_repo_head" == "$EXPECTED_REPO_HEAD" ]] || fail "build-info repo_head does not match manifest expected repo_head for $PROFILE"
    fi
    if [[ -n "${EXPECTED_COMPRESSED_IMAGE_SHA256:-}" ]]; then
      [[ "$actual_sha" == "$EXPECTED_COMPRESSED_IMAGE_SHA256" ]] || fail "artifact sha256 does not match manifest expected compressed image sha for $PROFILE"
    fi
    if [[ -n "${EXPECTED_REPO_DIRTY:-}" ]]; then
      [[ "$info_repo_dirty" == "$EXPECTED_REPO_DIRTY" ]] || fail "repo_dirty does not match manifest for $PROFILE"
    fi
    if [[ -n "${EXPECTED_BUILD_CLEAN_MODE:-}" ]]; then
      [[ "$info_build_clean_mode" == "$EXPECTED_BUILD_CLEAN_MODE" ]] || fail "build_clean_mode does not match manifest for $PROFILE"
    fi
    ;;
  apk)
    info_sha="$(awk -F= '/^artifact_sha256=/{print $2}' "$BUILD_INFO")"
    info_repo_head="$(awk -F= '/^repo_head=/{print $2}' "$BUILD_INFO")"
    info_version_name="$(awk -F= '/^version_name=/{print $2}' "$BUILD_INFO")"

    [[ "$info_sha" == "$actual_sha" ]] || fail "build-info artifact_sha256 mismatch for $PROFILE"
    [[ "$info_repo_head" == "$SOURCE_TAG_COMMIT" ]] || fail "build-info repo_head does not match source_tag for $PROFILE"
    if [[ -n "${EXPECTED_REPO_HEAD:-}" ]]; then
      [[ "$info_repo_head" == "$EXPECTED_REPO_HEAD" ]] || fail "build-info repo_head does not match manifest expected repo_head for $PROFILE"
    fi
    if [[ -n "${EXPECTED_ARTIFACT_SHA256:-}" ]]; then
      [[ "$actual_sha" == "$EXPECTED_ARTIFACT_SHA256" ]] || fail "artifact sha256 does not match manifest for $PROFILE"
    fi
    if [[ -n "${EXPECTED_VERSION_NAME:-}" ]]; then
      [[ "$info_version_name" == "$EXPECTED_VERSION_NAME" ]] || fail "version_name does not match manifest for $PROFILE"
    fi
    ;;
  *)
    fail "Unsupported artifact_type in manifest: $ARTIFACT_TYPE"
    ;;
esac

echo "Named release checks passed: $PROFILE"
