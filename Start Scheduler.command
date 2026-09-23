#!/bin/bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$HOME/Applications/Music Lesson Scheduler.app"
PRODUCT_VERSION="$(grep -E '^version = ' "$ROOT_DIR/pyproject.toml" | sed -E 's/^version = "([^"]+)".*/\1/')"
if [[ -z "$PRODUCT_VERSION" ]]; then
    PRODUCT_VERSION="current"
fi

if [[ ! -x "$APP_PATH/Contents/MacOS/MusicLessonSchedulerSwift" ]]; then
    echo "错误: 尚未安装 Swift 版 Music Lesson Scheduler ${PRODUCT_VERSION}。"
    echo "请先双击 Install Scheduler.command。"
    read -r -p "按 Enter 退出..." _unused || true
    exit 1
fi

/usr/bin/open "$APP_PATH"
