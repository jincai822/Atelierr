#!/bin/bash
# Atelierr launchd 安装脚本（macOS）
# 用法: REPO=<代码库绝对路径> VAULT=<vault 绝对路径> bash install.sh
# 例:   REPO=/Users/you/Atelierr VAULT=/Users/you/atelierr-data bash install.sh
set -euo pipefail

REPO="${REPO:?请先设置 REPO=<代码库绝对路径>}"
VAULT="${VAULT:?请先设置 VAULT=<vault 绝对路径>}"
HOME_DIR="$HOME"
DEST="$HOME_DIR/Library/LaunchAgents"
SRC="$(cd "$(dirname "$0")" && pwd)/launchd"

mkdir -p "$DEST" "$VAULT/state/logs"

for plist in "$SRC"/com.atelierr.*.plist; do
    name="$(basename "$plist")"
    sed -e "s|__REPO__|$REPO|g" -e "s|__VAULT__|$VAULT|g" -e "s|__HOME__|$HOME_DIR|g" "$plist" > "$DEST/$name"
    launchctl unload "$DEST/$name" 2>/dev/null || true
    launchctl load "$DEST/$name"
    echo "loaded: $name"
done

echo
echo "完成。常驻服务状态检查："
echo "  launchctl list | grep atelierr"
echo "日志在 ~/atelierr-data/state/logs/launchd-*.log"
echo "卸载单个: launchctl unload ~/Library/LaunchAgents/<name>.plist"
