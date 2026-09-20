#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CANONICAL_APP="$HOME/Applications/Music Lesson Scheduler.app"
ICLOUD_ROOT="${PI_LEGACY_ICLOUD_ROOT:-}"  # optional local legacy path; unset in public checkout
LEGACY_REACT_ROOT="$(dirname "$ROOT_DIR")/music-lesson-scheduler-react"

cleanup_dir() {
  local dir="$1"
  local removed=0

  [[ -d "$dir" ]] || return 0

  shopt -s nullglob
  for app in "$dir"/Music\ Lesson\ Scheduler*.app; do
    echo "🧹 移除旧应用副本: $app"
    rm -rf "$app"
    removed=$((removed + 1))
  done
  shopt -u nullglob

  if [[ "$removed" -gt 0 ]]; then
    echo "   已清理 ${removed} 个副本, 目录: ${dir}"
  fi
}

echo "========================================"
echo "  清理遗留 Music Lesson Scheduler 应用副本"
echo "========================================"
echo ""

cleanup_dir "$ROOT_DIR/dist"
cleanup_dir "$ROOT_DIR"
if [[ -n "$ICLOUD_ROOT" ]]; then
  cleanup_dir "$ICLOUD_ROOT/dist"
  cleanup_dir "$ICLOUD_ROOT"
fi
cleanup_dir "$LEGACY_REACT_ROOT"

echo ""
echo "正式安装位置（保留）: $CANONICAL_APP"
echo "✅ 遗留副本清理完成。"
