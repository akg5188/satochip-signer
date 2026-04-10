#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PATH="${1:-/tmp/satochip-desktop-smoke-venv}"
REQ_FILE="$ROOT_DIR/scripts/requirements-desktop-smoke.txt"
URTYPES_TARBALL="$ROOT_DIR/seedsigner-os/buildroot_dl/python-urtypes/python-urtypes-0.1.0.tar.gz"
SHAMIR_TARBALL="$ROOT_DIR/seedsigner-os/buildroot_dl/python-shamir-mnemonic/python-shamir-mnemonic-0.3-setuptools.tar.gz"
MNEMONIC_TARBALL="$ROOT_DIR/seedsigner-os/buildroot_dl/python-mnemonic/python-mnemonic-0.20.tar.gz"
PYCRYPTODOMEX_TARBALL="$ROOT_DIR/seedsigner-os/buildroot_dl/python-pycryptodomex/pycryptodomex-3.21.0.tar.gz"
PYASN1_TARBALL="$ROOT_DIR/seedsigner-os/buildroot_dl/python-pyasn1/pyasn1-0.4.8.tar.gz"
PERIPHERY_TARBALL="$ROOT_DIR/seedsigner-os/buildroot_dl/python-periphery/python-periphery-2.4.1.tar.gz"
PGPY_TARBALL="$ROOT_DIR/seedsigner-os/buildroot_dl/python-pgpy/PGPy-0.6.0.tar.gz"
PYSATOCHIP_TARBALL="$ROOT_DIR/seedsigner-os/buildroot_dl/python-pysatochip/python-pysatochip-0.5-alpha.tar.gz"

python3 -m venv "$VENV_PATH"
"$VENV_PATH/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_PATH/bin/pip" install -r "$REQ_FILE"
# Match the same package families the firmware buildroot image uses.
"$VENV_PATH/bin/pip" install \
  "$URTYPES_TARBALL" \
  "$SHAMIR_TARBALL" \
  "$MNEMONIC_TARBALL" \
  "$PYCRYPTODOMEX_TARBALL" \
  "$PYASN1_TARBALL" \
  "$PERIPHERY_TARBALL" \
  "$PGPY_TARBALL"
# `pyscard` needs host PC/SC headers, so keep smartcard access stubbed in smoke and
# install pysatochip itself without pulling that hard system dependency.
"$VENV_PATH/bin/pip" install --no-deps "$PYSATOCHIP_TARBALL"

echo "Desktop smoke environment ready: $VENV_PATH"
echo "Run with:"
echo "  python3 \"$ROOT_DIR/scripts/smoke_desktop_runtime.py\" \"$VENV_PATH\""
echo "  python3 \"$ROOT_DIR/scripts/smoke_firmware_imports.py\" \"$VENV_PATH\""
