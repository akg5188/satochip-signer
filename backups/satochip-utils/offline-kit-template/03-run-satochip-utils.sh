#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

chmod +x ./Satochip-Utils-linux-x86_64-0.3.0-beta
sudo systemctl restart pcscd
exec ./Satochip-Utils-linux-x86_64-0.3.0-beta
