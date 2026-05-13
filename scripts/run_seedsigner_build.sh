#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="${TP_BUILD_LOG_FILE:-$LOG_DIR/seedsigner-build-live.log}"
APP_DIR="$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/opt"
APP_SETTINGS_TEMPLATE="$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/default-settings.json"
APP_SETTINGS_TARGET="$APP_DIR/src/settings.json"
SNAPSHOT_DIR="$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/opt"
SNAPSHOT_DIR_REL="seedsigner-os/opt/rootfs-overlay/opt"
GENERATED_MANIFEST_REL="seedsigner-os/opt/rootfs-overlay/opt/src/seedsigner/resources/offline-signer-firmware-integrity.json"
SNAPSHOT_TIME_FILE="$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/opt/src/.build_commit_time"
NFC_BINDINGS_FILE="$ROOT_DIR/seedsigner-os/opt/external-packages/nfc-bindings/nfc-bindings.mk"
L10N_SRC="$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/app-assets/seedsigner-translations/l10n"
L10N_DST="$APP_DIR/src/seedsigner/resources/seedsigner-translations/l10n"
ZH_PO_REL="seedsigner-os/opt/rootfs-overlay/opt/src/seedsigner/resources/seedsigner-translations/l10n/zh_Hans_CN/LC_MESSAGES/messages.po"
ZH_MO_REL="seedsigner-os/opt/rootfs-overlay/opt/src/seedsigner/resources/seedsigner-translations/l10n/zh_Hans_CN/LC_MESSAGES/messages.mo"
ASCII_BASE="${TP_ASCII_BASE:-$HOME/satochip-signer-ascii}"
ASCII_ROOT="${TP_ASCII_ROOT:-$ASCII_BASE/root}"
ASCII_BUILD_DIR="${TP_BUILD_DIR:-$ASCII_BASE/output}"
ASCII_IMAGE_DIR="${TP_IMAGE_DIR:-$ASCII_BASE/images}"
ASCII_CCACHE_DIR="${TP_CCACHE_DIR:-$ASCII_BASE/ccache}"
ASCII_CCACHE_TEMPDIR="${TP_CCACHE_TEMPDIR:-$ASCII_BASE/ccache-tmp}"
RAW_IMG_PATH="${TP_RAW_IMG_PATH:-$ASCII_IMAGE_DIR/seedsigner_os.dev_.pi0-smartcard.img}"
RAW_BUILD_INFO="${TP_RAW_BUILD_INFO:-$RAW_IMG_PATH.build-info.txt}"
BR2_JLEVEL="${BR2_JLEVEL:-4}"
TP_BUILD_CPUSET="${TP_BUILD_CPUSET:-0,1,2,3}"
TP_BUILD_NICE="${TP_BUILD_NICE:-19}"
TP_BUILD_IONICE_CLASS="${TP_BUILD_IONICE_CLASS:-3}"
TP_BUILD_CLEAN_MODE="${TP_BUILD_CLEAN_MODE:-clean}"
TP_SKIP_HOST_FIX_RPATH="${TP_SKIP_HOST_FIX_RPATH:-1}"

case "$TP_BUILD_CLEAN_MODE" in
  clean|no-clean)
    ;;
  *)
    echo "Unsupported TP_BUILD_CLEAN_MODE: $TP_BUILD_CLEAN_MODE" >&2
    echo "Expected one of: clean, no-clean" >&2
    exit 1
    ;;
esac

mkdir -p "$LOG_DIR"
mkdir -p "$ASCII_BUILD_DIR" "$ASCII_IMAGE_DIR" "$ASCII_CCACHE_DIR" "$ASCII_CCACHE_TEMPDIR"
case "$ASCII_ROOT" in
  ""|"/")
    echo "Refusing unsafe TP_ASCII_ROOT: $ASCII_ROOT" >&2
    exit 1
    ;;
  "$ROOT_DIR"|"$ROOT_DIR"/*)
    echo "Refusing TP_ASCII_ROOT inside repository: $ASCII_ROOT" >&2
    exit 1
    ;;
  "$ASCII_BASE"/*)
    ;;
  *)
    echo "Refusing TP_ASCII_ROOT outside TP_ASCII_BASE: $ASCII_ROOT" >&2
    exit 1
    ;;
esac
if [[ -e "$ASCII_ROOT" && ! -L "$ASCII_ROOT" ]]; then
  echo "Refusing to remove non-symlink TP_ASCII_ROOT: $ASCII_ROOT" >&2
  exit 1
fi
rm -rf "$ASCII_ROOT"
ln -s "$ROOT_DIR" "$ASCII_ROOT"

mkdir -p "$(dirname "$L10N_DST")"
rm -rf "$L10N_DST"
cp -a "$L10N_SRC" "$L10N_DST"
cp "$APP_SETTINGS_TEMPLATE" "$APP_SETTINGS_TARGET"
# Purge host-generated Python caches from the overlay so target runtime never
# prefers stale .pyc files over the source we are trying to ship.
find "$APP_DIR/src" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$APP_DIR/src" -type f -name '*.pyc' -delete
if [[ -f "$APP_DIR/setup.py" ]]; then
(
cd "$APP_DIR"
  python3 setup.py compile_catalog
)
else
  echo "Skipping compile_catalog: $APP_DIR/setup.py not found"
  ZH_PO_PATH="$ROOT_DIR/$ZH_PO_REL"
  ZH_MO_PATH="$ROOT_DIR/$ZH_MO_REL"
  if command -v pybabel >/dev/null 2>&1 && [[ -f "$ZH_PO_PATH" ]]; then
    pybabel compile --statistics --use-fuzzy -D messages -l zh_Hans_CN -i "$ZH_PO_PATH" -o "$ZH_MO_PATH"
  else
    # Fall back to the tracked compiled catalog when pybabel is unavailable;
    # otherwise the target may silently lose translated UI strings.
    if git -C "$ROOT_DIR" ls-files --error-unmatch "$ZH_MO_REL" >/dev/null 2>&1; then
      git -C "$ROOT_DIR" show "HEAD:$ZH_MO_REL" > "$ZH_MO_PATH"
    fi
  fi
fi

cd "$ASCII_ROOT/seedsigner-os/opt"
if [ -d /tmp/mtools-local/root/usr/bin ]; then
  export PATH=/tmp/mtools-local/root/usr/bin:$PATH
elif [ -d /tmp/mtools-local/usr/bin ]; then
  export PATH=/tmp/mtools-local/usr/bin:$PATH
fi
export CCACHE_DIR="$ASCII_CCACHE_DIR"
export CCACHE_TEMPDIR="$ASCII_CCACHE_TEMPDIR"
export LC_ALL=C.UTF-8
export LANG=C.UTF-8
export TP_BUILD_DIR="$ASCII_BUILD_DIR"
export TP_IMAGE_DIR="$ASCII_IMAGE_DIR"
BUILD_PREFIX=(env "BR2_JLEVEL=$BR2_JLEVEL")
BUILD_PREFIX+=("TP_SKIP_HOST_FIX_RPATH=$TP_SKIP_HOST_FIX_RPATH")
BUILD_PATH=""
IFS=':' read -r -a PATH_PARTS <<< "${PATH:-}"
for path_part in "${PATH_PARTS[@]}"; do
  if [[ "$path_part" == "$HOME/.local/bin" ]]; then
    continue
  fi
  if [[ -z "$BUILD_PATH" ]]; then
    BUILD_PATH="$path_part"
  else
    BUILD_PATH="$BUILD_PATH:$path_part"
  fi
done
BUILD_PREFIX+=("PATH=$BUILD_PATH")
if command -v taskset >/dev/null 2>&1; then
  BUILD_PREFIX=(taskset -c "$TP_BUILD_CPUSET" "${BUILD_PREFIX[@]}")
fi
BUILD_ARGS=(./build.sh --pi0 --smartcard --skip-repo)
if [[ "$TP_BUILD_CLEAN_MODE" == "no-clean" ]]; then
  BUILD_ARGS+=(--no-clean)
fi

echo "Starting SeedSigner OS build"
echo "  BR2_JLEVEL=$BR2_JLEVEL"
echo "  TP_BUILD_CPUSET=$TP_BUILD_CPUSET"
echo "  TP_BUILD_CLEAN_MODE=$TP_BUILD_CLEAN_MODE"
echo "  TP_SKIP_HOST_FIX_RPATH=$TP_SKIP_HOST_FIX_RPATH"
echo "  log=$LOG_FILE"

nice -n "$TP_BUILD_NICE" ionice -c "$TP_BUILD_IONICE_CLASS" \
  "${BUILD_PREFIX[@]}" "${BUILD_ARGS[@]}" 2>&1 | tee "$LOG_FILE"

if [[ ! -f "$RAW_IMG_PATH" ]]; then
  echo "Expected raw image not found after build: $RAW_IMG_PATH" >&2
  exit 1
fi

raw_sha="$(sha256sum "$RAW_IMG_PATH" | awk '{print $1}')"
zimage_path="$ASCII_BUILD_DIR/images/zImage"
rootfs_cpio_path="$ASCII_BUILD_DIR/images/rootfs.cpio"
zimage_sha=""
rootfs_cpio_sha=""
if [[ -f "$zimage_path" ]]; then
  zimage_sha="$(sha256sum "$zimage_path" | awk '{print $1}')"
fi
if [[ -f "$rootfs_cpio_path" ]]; then
  rootfs_cpio_sha="$(sha256sum "$rootfs_cpio_path" | awk '{print $1}')"
fi

snapshot_time=""
if [[ -f "$SNAPSHOT_TIME_FILE" ]]; then
  snapshot_time="$(cat "$SNAPSHOT_TIME_FILE")"
fi

snapshot_tree_sha=""
if [[ -d "$SNAPSHOT_DIR" ]]; then
  snapshot_tree_sha="$(
    (
      cd "$SNAPSHOT_DIR"
      while IFS= read -r -d '' file; do
        rel_path="${file#$SNAPSHOT_DIR_REL/}"
        if [[ "$rel_path" == "${GENERATED_MANIFEST_REL#$SNAPSHOT_DIR_REL/}" ]]; then
          continue
        fi
        sha256sum "./$rel_path"
      done < <(git -C "$ROOT_DIR" ls-files -z -- "$SNAPSHOT_DIR_REL")
    ) | sha256sum | awk '{print $1}'
  )"
fi

nfc_bindings_sha=""
if [[ -f "$NFC_BINDINGS_FILE" ]]; then
  nfc_bindings_sha="$(sha256sum "$NFC_BINDINGS_FILE" | awk '{print $1}')"
fi

repo_head="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
repo_dirty=0
if [[ -n "$(git -C "$ROOT_DIR" status --porcelain 2>/dev/null || true)" ]]; then
  repo_dirty=1
fi
build_time_utc="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

mkdir -p "$(dirname "$RAW_BUILD_INFO")"
{
  printf 'raw_image_path=%q\n' "$RAW_IMG_PATH"
  printf 'raw_image_sha256=%q\n' "$raw_sha"
  printf 'build_output_zimage_path=%q\n' "$zimage_path"
  printf 'build_output_zimage_sha256=%q\n' "$zimage_sha"
  printf 'build_output_rootfs_cpio_path=%q\n' "$rootfs_cpio_path"
  printf 'build_output_rootfs_cpio_sha256=%q\n' "$rootfs_cpio_sha"
  printf 'source_snapshot_build_commit_time=%q\n' "$snapshot_time"
  printf 'runtime_snapshot_tree_sha256=%q\n' "$snapshot_tree_sha"
  printf 'nfc_bindings_mk_sha256=%q\n' "$nfc_bindings_sha"
  printf 'repo_head=%q\n' "$repo_head"
  printf 'repo_dirty=%q\n' "$repo_dirty"
  printf 'build_clean_mode=%q\n' "$TP_BUILD_CLEAN_MODE"
  printf 'build_time_utc=%q\n' "$build_time_utc"
  printf 'build_script=%q\n' "scripts/run_seedsigner_build.sh"
} > "$RAW_BUILD_INFO"

echo "Raw build info:  $RAW_BUILD_INFO"
