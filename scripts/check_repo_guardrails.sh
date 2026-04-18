#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST_PATH="$ROOT_DIR/release-manifest.json"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_file() {
  local path="$1"
  [[ -f "$path" ]] || fail "Missing required file: $path"
}

require_file "$MANIFEST_PATH"
python3 -m json.tool "$MANIFEST_PATH" >/dev/null

python3 - "$MANIFEST_PATH" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

profiles = data["profiles"]

firmware_clean = profiles["firmware-clean"]
assert firmware_clean["source_tag"] == "HEAD", firmware_clean
assert firmware_clean["artifact_path"] == "dist/system-update-latest.img.xz", firmware_clean
assert firmware_clean["sha_path"] == "dist/system-update-latest.img.xz.sha256", firmware_clean
assert firmware_clean["build_info_path"] == "dist/system-update-latest.build-info.txt", firmware_clean
assert firmware_clean["expected"]["repo_dirty"] == "0", firmware_clean
assert firmware_clean["expected"]["build_clean_mode"] == "clean", firmware_clean

historical = profiles["firmware-public-20260410b-clean"]
assert historical["source_tag"] == "offline-signer-clean-source-20260410b", historical

wallet_release = profiles["wallet-release"]
assert wallet_release["source_tag"] == "HEAD", wallet_release
assert wallet_release["artifact_path"] == "dist/satochip-wallet-release.apk", wallet_release
assert wallet_release["defaults"]["WALLET_ARTIFACT_MODE"] == "release-baseline", wallet_release
PY

bash -n "$ROOT_DIR/scripts/build_current_firmware.sh"
bash -n "$ROOT_DIR/scripts/build_current_wallet_apk.sh"
bash -n "$ROOT_DIR/scripts/build_pi_firmware_from_snapshot.sh"
bash -n "$ROOT_DIR/scripts/check_named_release.sh"
bash -n "$ROOT_DIR/scripts/rebuild_official_release.sh"

grep -q 'system-update-worktree-latest.img.xz' "$ROOT_DIR/scripts/build_current_firmware.sh" || \
  fail "build_current_firmware.sh must write to system-update-worktree-latest.img.xz by default"

if rg -n 'DIST_IMG:-\$DIST_DIR/system-update-latest\.img\.xz' "$ROOT_DIR/scripts/build_current_firmware.sh" >/dev/null; then
  fail "build_current_firmware.sh still points at system-update-latest.img.xz"
fi

grep -q 'system-update-worktree-latest.img.xz' "$ROOT_DIR/README.md" || \
  fail "README.md must document the worktree firmware artifact name"
grep -q 'system-update-worktree-latest.img.xz' "$ROOT_DIR/docs/快速开始.zh-CN.md" || \
  fail "快速开始 must document the worktree firmware artifact name"
grep -q 'system-update-worktree-latest.img.xz' "$ROOT_DIR/docs/固件与源码对应关系.zh-CN.md" || \
  fail "固件与源码对应关系 must document the worktree firmware artifact name"
grep -q 'system-update-worktree-latest.img.xz' "$ROOT_DIR/docs/长期维护总入口.zh-CN.md" || \
  fail "长期维护总入口 must document the worktree firmware artifact name"

grep -q 'satochip-wallet-worktree-latest.apk' "$ROOT_DIR/scripts/build_wallet_release.sh" || \
  fail "build_wallet_release.sh must write to satochip-wallet-worktree-latest.apk by default"
grep -q 'satochip-wallet-worktree-latest.apk' "$ROOT_DIR/scripts/build_current_wallet_apk.sh" || \
  fail "build_current_wallet_apk.sh must target satochip-wallet-worktree-latest.apk"
grep -q 'satochip-wallet-worktree-latest.apk' "$ROOT_DIR/README.md" || \
  fail "README.md must document the worktree wallet artifact name"
grep -q 'satochip-wallet-worktree-latest.apk' "$ROOT_DIR/docs/两个安卓APK说明.zh-CN.md" || \
  fail "两个安卓APK说明 must document the worktree wallet artifact name"
grep -q 'satochip-wallet-worktree-latest.apk' "$ROOT_DIR/wallet/README.md" || \
  fail "wallet README must document the worktree wallet artifact name"

echo "Repository guardrails checks passed."
