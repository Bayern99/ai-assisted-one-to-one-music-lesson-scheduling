#!/bin/bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$HOME/Applications/Music Lesson Scheduler.app"

if [[ ! -x "$APP_PATH/Contents/MacOS/MusicLessonSchedulerSwift" ]]; then
    echo "错误: 尚未安装 Swift 版 Music Lesson Scheduler 4.6.5。"
    echo "请先双击 Install Scheduler.command。"
    read -r -p "按 Enter 退出..." _unused || true
    exit 1
fi

/usr/bin/open "$APP_PATH"
