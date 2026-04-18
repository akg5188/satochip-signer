#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST_PATH="$ROOT_DIR/release-manifest.json"
WORKTREE_BASE="${REBUILD_WORKTREE_BASE:-$HOME/.cache/satochip-signer-rebuilds}"
STATE_BASE="${REBUILD_STATE_BASE:-$WORKTREE_BASE/_state}"
ARTIFACT_BASE="${REBUILD_ARTIFACT_BASE:-$ROOT_DIR/dist/rebuilds}"
KEEP_WORKTREE="${KEEP_WORKTREE:-0}"
LOW_IMPACT="${LOW_IMPACT:-1}"

usage() {
  cat <<'EOF'
用法:
  bash scripts/rebuild_official_release.sh --list
  bash scripts/rebuild_official_release.sh firmware-clean
  bash scripts/rebuild_official_release.sh firmware-public-20260410b-clean
  bash scripts/rebuild_official_release.sh wallet-release

说明:
  - firmware-clean 现在默认跟随当前 HEAD 的 clean 固件，不再回到旧固件 tag
  - 历史冻结固件请显式选择对应 profile，例如 firmware-public-20260410b-clean
  - 其它 profile 仍按 release-manifest.json 里的源码冻结 tag
  - 如果要当前工作区未提交改动也一起进固件，用 bash scripts/build_current_firmware.sh
  - 默认启用低负载参数，尽量避免把机器顶满
  - 每次都在临时 git worktree 里重建，不污染当前工作区
  - 校验通过后会把产物复制到 dist/rebuilds/<profile>/，避免 worktree 清理时一并删除
EOF
}

collect_build_sensitive_changes() {
  {
    git -C "$ROOT_DIR" diff --name-only HEAD -- . ':(exclude)docs/**' ':(exclude)dist/**' ':(exclude)README.md'
    git -C "$ROOT_DIR" diff --cached --name-only -- . ':(exclude)docs/**' ':(exclude)dist/**' ':(exclude)README.md'
    git -C "$ROOT_DIR" ls-files --others --exclude-standard -- . ':(exclude)docs/**' ':(exclude)dist/**'
  } | sed '/^$/d' | sort -u
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

if [[ "$SOURCE_TAG" == "HEAD" ]]; then
  BUILD_SENSITIVE_CHANGES="$(collect_build_sensitive_changes)"
  if [[ -n "$BUILD_SENSITIVE_CHANGES" ]]; then
    echo "ERROR: 当前工作区还有未提交的构建相关改动，firmware-clean 只会按当前 HEAD 重建 clean 固件，不会带入这些改动。" >&2
    echo "ERROR: 请先提交这些改动，或者直接改用 bash scripts/build_current_firmware.sh" >&2
    echo "ERROR: 未提交改动列表：" >&2
    printf '%s\n' "$BUILD_SENSITIVE_CHANGES" | sed 's/^/  - /' >&2
    exit 1
  fi
fi

mkdir -p "$WORKTREE_BASE"
WORKTREE="$(mktemp -d "$WORKTREE_BASE/${PROFILE}.XXXXXX")"
PROFILE_STATE_DIR="$STATE_BASE/$PROFILE"
PROFILE_ARTIFACT_DIR="$ARTIFACT_BASE/$PROFILE"
PROFILE_LOG_DIR="$PROFILE_STATE_DIR/logs"

cleanup() {
  if [[ "$KEEP_WORKTREE" == "1" ]]; then
    return 0
  fi
  git -C "$ROOT_DIR" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  rm -rf "$WORKTREE"
}
trap cleanup EXIT

git -C "$ROOT_DIR" worktree add --detach "$WORKTREE" "$SOURCE_TAG" >/dev/null
mkdir -p "$PROFILE_STATE_DIR" "$PROFILE_ARTIFACT_DIR" "$PROFILE_LOG_DIR"

REBUILD_LOG="$PROFILE_LOG_DIR/rebuild-$(date -u +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$REBUILD_LOG") 2>&1

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

export TP_ASCII_BASE="${TP_ASCII_BASE:-$PROFILE_STATE_DIR/ascii}"
export BUILD_ROOT="${BUILD_ROOT:-$PROFILE_STATE_DIR/build-root}"
export GRADLE_USER_HOME="${GRADLE_USER_HOME:-$PROFILE_STATE_DIR/gradle-home}"
export OUT_DIR="${OUT_DIR:-$WORKTREE/dist}"

VERIFY_COMMAND_RESOLVED="$VERIFY_COMMAND"
printf -v VERIFY_SCRIPT_ABS '%q' "$ROOT_DIR/scripts/check_named_release.sh"
VERIFY_COMMAND_RESOLVED="${VERIFY_COMMAND_RESOLVED//scripts\/check_named_release.sh/$VERIFY_SCRIPT_ABS}"

echo "Profile:      $PROFILE"
echo "Title:        $TITLE"
echo "Release tag:  $RELEASE_TAG"
echo "Source tag:   $SOURCE_TAG"
echo "Worktree:     $WORKTREE"
echo "Rebuild log:  $REBUILD_LOG"
echo "Build cmd:    $BUILD_COMMAND"
echo "Verify cmd:   $VERIFY_COMMAND"
echo "Verify exec:  $VERIFY_COMMAND_RESOLVED"

(
  cd "$WORKTREE"
  bash -lc "$BUILD_COMMAND"
)

(
  cd "$WORKTREE"
  TP_RELEASE_ROOT_DIR="$WORKTREE" \
  TP_RELEASE_MANIFEST_PATH="$MANIFEST_PATH" \
  bash -lc "$VERIFY_COMMAND_RESOLVED"
)

ARTIFACT_COPY="$PROFILE_ARTIFACT_DIR/$(basename "$ARTIFACT_PATH")"
SHA_COPY="$PROFILE_ARTIFACT_DIR/$(basename "$SHA_PATH")"
BUILD_INFO_COPY="$PROFILE_ARTIFACT_DIR/$(basename "$BUILD_INFO_PATH")"
cp -f "$WORKTREE/$ARTIFACT_PATH" "$ARTIFACT_COPY"
cp -f "$WORKTREE/$SHA_PATH" "$SHA_COPY"
cp -f "$WORKTREE/$BUILD_INFO_PATH" "$BUILD_INFO_COPY"

echo "Artifacts:"
echo "  $ARTIFACT_COPY"
echo "  $SHA_COPY"
echo "  $BUILD_INFO_COPY"
