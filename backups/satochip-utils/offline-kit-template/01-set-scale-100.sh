#!/usr/bin/env bash
set -euo pipefail

echo "把显示缩放设置为 100%..."
gsettings set org.gnome.desktop.interface scaling-factor 1
echo
echo "如果软件已经打开，请关闭后重新打开。"
