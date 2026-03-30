#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="/opt/offline-signer-kiosk"
SIGNER_ROOT="/opt/offline-signer"
DEFAULT_PATH="m/44'/60'/0'/0/0"

DEFAULT_SIGNER_BIN="$SIGNER_ROOT/bin/offline-signer"
if [[ ! -x "$DEFAULT_SIGNER_BIN" ]]; then
  DEFAULT_SIGNER_BIN="$SIGNER_ROOT/bin/pi-signer"
fi

export PYTHONUNBUFFERED=1
export OFFLINE_SIGNER_BIN="${OFFLINE_SIGNER_BIN:-$DEFAULT_SIGNER_BIN}"
export TP_PI_SIGNER_BIN="${TP_PI_SIGNER_BIN:-$OFFLINE_SIGNER_BIN}"
export TP_READER_HINT="${TP_READER_HINT:-ACR39}"
export TP_DERIVATION_PATH="${TP_DERIVATION_PATH:-$DEFAULT_PATH}"

cd "$APP_ROOT"
exec /usr/bin/python3 "$APP_ROOT/kiosk.py"
