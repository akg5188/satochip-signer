#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/seedsigner-build-live.log"
APP_DIR="$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/opt"
APP_SETTINGS_TEMPLATE="$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/default-settings.json"
APP_SETTINGS_TARGET="$APP_DIR/src/settings.json"
L10N_SRC="$ROOT_DIR/seedsigner-os/opt/rootfs-overlay/app-assets/seedsigner-translations/l10n"
L10N_DST="$APP_DIR/src/seedsigner/resources/seedsigner-translations/l10n"
ASCII_BASE="${TP_ASCII_BASE:-$HOME/tp-signer-ascii}"
ASCII_ROOT="${TP_ASCII_ROOT:-$ASCII_BASE/root}"
ASCII_BUILD_DIR="${TP_BUILD_DIR:-$ASCII_BASE/output}"
ASCII_IMAGE_DIR="${TP_IMAGE_DIR:-$ASCII_BASE/images}"
ASCII_CCACHE_DIR="${TP_CCACHE_DIR:-$ASCII_BASE/ccache}"
ASCII_CCACHE_TEMPDIR="${TP_CCACHE_TEMPDIR:-$ASCII_BASE/ccache-tmp}"
BR2_JLEVEL="${BR2_JLEVEL:-4}"
TP_BUILD_CPUSET="${TP_BUILD_CPUSET:-0,1,2,3}"
TP_BUILD_NICE="${TP_BUILD_NICE:-19}"
TP_BUILD_IONICE_CLASS="${TP_BUILD_IONICE_CLASS:-3}"

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
(
cd "$APP_DIR"
  python3 setup.py compile_catalog
)

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
if command -v taskset >/dev/null 2>&1; then
  BUILD_PREFIX=(taskset -c "$TP_BUILD_CPUSET" "${BUILD_PREFIX[@]}")
fi

echo "Starting SeedSigner OS build"
echo "  BR2_JLEVEL=$BR2_JLEVEL"
echo "  TP_BUILD_CPUSET=$TP_BUILD_CPUSET"
echo "  log=$LOG_FILE"

nice -n "$TP_BUILD_NICE" ionice -c "$TP_BUILD_IONICE_CLASS" \
  "${BUILD_PREFIX[@]}" ./build.sh --pi0 --smartcard --skip-repo --no-clean 2>&1 | tee "$LOG_FILE"
