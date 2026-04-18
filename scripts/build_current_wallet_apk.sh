#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/dist}"
KEYSTORE_PROPS="${KEYSTORE_PROPS:-$ROOT_DIR/wallet/keystore.properties}"

export WALLET_ARTIFACT_MODE="${WALLET_ARTIFACT_MODE:-worktree-latest}"
export OUT_APK="${OUT_APK:-$OUT_DIR/satochip-wallet-worktree-latest.apk}"
export OUT_SUM="${OUT_SUM:-$OUT_APK.sha256}"
export OUT_INFO="${OUT_INFO:-$OUT_DIR/satochip-wallet-worktree-latest.build-info.txt}"

if [[ ! -f "$KEYSTORE_PROPS" ]]; then
  echo "Missing wallet/keystore.properties; cannot build the current wallet release APK." >&2
  echo "The existing dist/satochip-wallet-release.apk may still be an older formal release artifact." >&2
  echo "Restore the wallet release keystore first, then rerun this script." >&2
  exit 1
fi

echo "Building latest worktree wallet APK"
echo "  out_apk=$OUT_APK"

rm -f \
  "$OUT_DIR"/satochip-wallet-worktree-latest.apk \
  "$OUT_DIR"/satochip-wallet-worktree-latest.apk.sha256 \
  "$OUT_DIR"/satochip-wallet-worktree-latest.build-info.txt

bash "$ROOT_DIR/scripts/build_wallet_release.sh"
