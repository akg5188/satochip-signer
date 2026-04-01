#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST_PATH="$ROOT_DIR/release-manifest.json"
WORKTREE_BASE="${REBUILD_WORKTREE_BASE:-$HOME/.cache/satochip-signer-rebuilds}"
KEEP_WORKTREE="${KEEP_WORKTREE:-0}"
LOW_IMPACT="${LOW_IMPACT:-1}"

usage() {
  cat <<'EOF'
用法:
  bash scripts/rebuild_official_release.sh --list
  bash scripts/rebuild_official_release.sh firmware-clean
  bash scripts/rebuild_official_release.sh wallet-release

说明:
  - 默认使用官方 release-manifest.json 里的源码冻结 tag
  - 默认启用低负载参数，尽量避免把机器顶满
  - 每次都在临时 git worktree 里重建，不污染当前工作区
EOF
}

manifest_eval_profile() {
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
    "artifact_path",
    "sha_path",
    "build_info_path",
    "build_command",
    "verify_command",
]:
    print(f"{key.upper()}={shlex.quote(str(entry[key]))}")

for key, value in entry.get("defaults", {}).items():
    print(f"DEFAULT_{key}={shlex.quote(str(value))}")
PY
}

if [[ "${1:-}" == "--list" || "${1:-}" == "list" || "${1:-}" == "" ]]; then
  usage
  echo
  bash "$ROOT_DIR/scripts/check_named_release.sh" --list
  exit 0
fi

PROFILE="$1"
if ! profile_vars="$(manifest_eval_profile "$PROFILE")"; then
  usage
  exit 1
fi
eval "$profile_vars"

mkdir -p "$WORKTREE_BASE"
WORKTREE="$(mktemp -d "$WORKTREE_BASE/${PROFILE}.XXXXXX")"

cleanup() {
  if [[ "$KEEP_WORKTREE" == "1" ]]; then
    return 0
  fi
  git -C "$ROOT_DIR" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  rm -rf "$WORKTREE"
}
trap cleanup EXIT

git -C "$ROOT_DIR" worktree add --detach "$WORKTREE" "$SOURCE_TAG" >/dev/null

if [[ "$LOW_IMPACT" == "1" ]]; then
  export BR2_JLEVEL="${BR2_JLEVEL:-${DEFAULT_BR2_JLEVEL:-1}}"
  export TP_BUILD_CPUSET="${TP_BUILD_CPUSET:-${DEFAULT_TP_BUILD_CPUSET:-0}}"
  export TP_BUILD_NICE="${TP_BUILD_NICE:-${DEFAULT_TP_BUILD_NICE:-19}}"
  export TP_BUILD_IONICE_CLASS="${TP_BUILD_IONICE_CLASS:-${DEFAULT_TP_BUILD_IONICE_CLASS:-3}}"
  export TP_BUILD_CLEAN_MODE="${TP_BUILD_CLEAN_MODE:-${DEFAULT_TP_BUILD_CLEAN_MODE:-clean}}"
  export XZ_THREADS="${XZ_THREADS:-${DEFAULT_XZ_THREADS:-1}}"
  export WALLET_GRADLE_JVMARGS="${WALLET_GRADLE_JVMARGS:-${DEFAULT_WALLET_GRADLE_JVMARGS:-}}"
  export WALLET_GRADLE_WORKERS_MAX="${WALLET_GRADLE_WORKERS_MAX:-${DEFAULT_WALLET_GRADLE_WORKERS_MAX:-}}"
fi

export TP_ASCII_BASE="${TP_ASCII_BASE:-$WORKTREE/.tp-ascii}"
export BUILD_ROOT="${BUILD_ROOT:-$WORKTREE/.build-root}"
export GRADLE_USER_HOME="${GRADLE_USER_HOME:-$WORKTREE/.gradle-home}"
export OUT_DIR="${OUT_DIR:-$WORKTREE/dist}"

echo "Profile:      $PROFILE"
echo "Title:        $TITLE"
echo "Release tag:  $RELEASE_TAG"
echo "Source tag:   $SOURCE_TAG"
echo "Worktree:     $WORKTREE"
echo "Build cmd:    $BUILD_COMMAND"
echo "Verify cmd:   $VERIFY_COMMAND"

(
  cd "$WORKTREE"
  bash -lc "$BUILD_COMMAND"
)

(
  cd "$WORKTREE"
  bash -lc "$VERIFY_COMMAND"
)

echo "Artifacts:"
echo "  $WORKTREE/$ARTIFACT_PATH"
echo "  $WORKTREE/$SHA_PATH"
echo "  $WORKTREE/$BUILD_INFO_PATH"
