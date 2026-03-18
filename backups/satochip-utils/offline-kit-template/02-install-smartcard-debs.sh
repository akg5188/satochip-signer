#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

sudo dpkg -i \
  ./libpcsclite1_2.3.3-1_amd64.deb \
  ./libccid_1.6.2-1_amd64.deb \
  ./pcscd_2.3.3-1_amd64.deb

sudo systemctl restart pcscd
echo "安装完成。"
