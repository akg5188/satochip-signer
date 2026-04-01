#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_IMG="$ROOT_DIR/dist/system-update-latest.img.xz"
DIST_SUM="$ROOT_DIR/dist/system-update-latest.img.xz.sha256"
DIST_INFO="$ROOT_DIR/dist/system-update-latest.build-info.txt"
MANIFEST_PATH="$ROOT_DIR/release-manifest.json"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_file() {
  local path="$1"
  [[ -f "$path" ]] || fail "Missing required file: $path"
}

require_file "$DIST_IMG"
require_file "$DIST_SUM"
require_file "$DIST_INFO"
require_file "$MANIFEST_PATH"

python3 -m json.tool "$MANIFEST_PATH" >/dev/null
while IFS= read -r tag; do
  [[ -n "$tag" ]] || continue
  git -C "$ROOT_DIR" rev-parse "${tag}^{commit}" >/dev/null 2>&1 || fail "Missing manifest source tag: $tag"
done < <(
  python3 - "$MANIFEST_PATH" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

for entry in data["profiles"].values():
    print(entry["source_tag"])
PY
)

while IFS= read -r script_path; do
  bash -n "$ROOT_DIR/$script_path"
done < <(git -C "$ROOT_DIR" ls-files '*.sh')

expected_dist_sha="$(awk 'NR==1 {print $1}' "$DIST_SUM")"
actual_dist_sha="$(sha256sum "$DIST_IMG" | awk '{print $1}')"
[[ "$expected_dist_sha" == "$actual_dist_sha" ]] || fail "dist sha256 mismatch"

info_dist_sha="$(awk -F= '/^compressed_image_sha256=/{print $2}' "$DIST_INFO")"
[[ "$info_dist_sha" == "$actual_dist_sha" ]] || fail "build-info compressed_image_sha256 mismatch"

raw_from_dist_sha="$(xz -dc "$DIST_IMG" | sha256sum | awk '{print $1}')"
info_raw_sha="$(awk -F= '/^raw_image_sha256=/{print $2}' "$DIST_INFO")"
[[ "$info_raw_sha" == "$raw_from_dist_sha" ]] || fail "build-info raw_image_sha256 mismatch"

info_repo_dirty="$(awk -F= '/^repo_dirty=/{print $2}' "$DIST_INFO")"
[[ "$info_repo_dirty" == "0" ]] || fail "Pi firmware build-info repo_dirty must be 0"

info_package_script="$(awk -F= '/^package_script=/{print $2}' "$DIST_INFO")"
[[ "$info_package_script" != "manual-low-impact-xz" ]] || \
  fail "Pi firmware build-info still uses obsolete manual-low-impact-xz package_script"

for key in \
  source_snapshot_build_commit_time \
  repo_head \
  repo_dirty \
  runtime_snapshot_tree_sha256 \
  nfc_bindings_mk_sha256 \
  build_script \
  package_script
do
  grep -q "^${key}=" "$DIST_INFO" || fail "Missing build-info key: ${key}"
done

mapfile -t docs_to_scan < <(
  find "$ROOT_DIR/docs" -maxdepth 1 -type f -name '*.md' \
    ! -name '版本时间线与发布入口.zh-CN.md' \
    -print
)

if rg -n 'repack_runtime_image\.sh|releases/tag/(pi-signer-firmware-|offline-signer-firmware-)' \
  "$ROOT_DIR/README.md" \
  "${docs_to_scan[@]}" \
  "$ROOT_DIR/seedsigner-os/README.zh-CN.md"
then
  fail "Found obsolete Pi firmware docs references"
fi

grep -q 'build_pi_firmware_from_snapshot.sh' "$ROOT_DIR/docs/一页式总导航.zh-CN.md" || \
  fail "Missing canonical Pi firmware build command in one-page guide"
grep -q 'rebuild_official_release.sh' "$ROOT_DIR/README.md" || \
  fail "Missing canonical rebuild_official_release.sh entry in README"
grep -q 'rebuild_official_release.sh' "$ROOT_DIR/docs/长期维护总入口.zh-CN.md" || \
  fail "Missing canonical rebuild_official_release.sh entry in maintenance guide"

echo "Repository consistency checks passed."
