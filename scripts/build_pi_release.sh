#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

SIGNER_IMPL="${SIGNER_IMPL:-python}"

source_dir=""
if [[ "$SIGNER_IMPL" == "java" ]]; then
  source_dir="$ROOT_DIR/pi-signer/build/release/offline-signer"
  if [[ ! -d "$source_dir" || "${FORCE_BUILD:-0}" == "1" ]]; then
    ./gradlew :pi-signer:assembleReleaseBundle
  fi
elif [[ "$SIGNER_IMPL" == "python" ]]; then
  source_dir="$ROOT_DIR/pi-signer-py"
  if [[ ! -x "$source_dir/bin/pi-signer" && ! -x "$source_dir/bin/offline-signer" ]]; then
    echo "Python signer not found in: $source_dir/bin/" >&2
    exit 1
  fi
else
  echo "Unknown SIGNER_IMPL: $SIGNER_IMPL (supported: python, java)" >&2
  exit 1
fi

stamp="$(date +%Y%m%d-%H%M%S)"
release_name="offline-signer-${stamp}"
release_dir="$ROOT_DIR/dist/${release_name}"

rm -rf "$release_dir"
mkdir -p "$ROOT_DIR/dist"
mkdir -p "$release_dir/offline-signer"
cp -a "$source_dir"/. "$release_dir/offline-signer/"
if [[ ! -x "$release_dir/offline-signer/bin/offline-signer" && -x "$release_dir/offline-signer/bin/pi-signer" ]]; then
  cat > "$release_dir/offline-signer/bin/offline-signer" <<'EOF'
#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$SCRIPT_DIR/pi-signer" "$@"
EOF
  chmod +x "$release_dir/offline-signer/bin/offline-signer"
fi

mkdir -p "$release_dir/pi-appliance"
cp -a "$ROOT_DIR/pi-appliance/app" "$release_dir/pi-appliance/"
cp -a "$ROOT_DIR/pi-appliance/setup" "$release_dir/pi-appliance/"
cp -a "$ROOT_DIR/pi-appliance/systemd" "$release_dir/pi-appliance/"
cp "$ROOT_DIR/pi-appliance/README.zh-CN.md" "$release_dir/pi-appliance/"
find "$release_dir" -type d -name "__pycache__" -prune -exec rm -rf {} +

mkdir -p "$release_dir/image-builder"
cp "$ROOT_DIR/image-builder/build_flashable_image.sh" "$release_dir/image-builder/"
cp "$ROOT_DIR/image-builder/README.zh-CN.md" "$release_dir/image-builder/"

tarball="$ROOT_DIR/dist/${release_name}.tar.gz"
rm -f "$tarball"
tar -C "$ROOT_DIR/dist" -czf "$tarball" "$release_name"

echo "Release directory: $release_dir"
echo "Release tarball:   $tarball"
