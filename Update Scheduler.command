#!/bin/bash
set -Eeuo pipefail

pause_on_error() {
    local status=$?
    echo ""
    echo "❌ 更新失败（第 $1 行）。请保留上面的错误信息。"
    echo "   若提示缺少依赖，请改用 Install Scheduler.command。"
    read -r -p "按 Enter 退出..." _unused || true
    exit "$status"
}
trap 'pause_on_error "$LINENO"' ERR

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"
unset PYTHONHOME PYTHONPATH PYTHONNOUSERSITE
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:${PATH:-}"
PRODUCT_VERSION="$(grep -E '^version = ' "$ROOT_DIR/pyproject.toml" | sed -E 's/^version = "([^"]+)".*/\1/')"
if [[ -z "$PRODUCT_VERSION" ]]; then
    echo "❌ 无法从 pyproject.toml 读取产品版本。"
    exit 1
fi

echo "========================================"
echo "  Music Lesson Scheduler ${PRODUCT_VERSION} — 快速更新"
echo "========================================"
echo ""
echo "跳过依赖安装；只清理旧副本并重新编译安装。"
echo "第一次安装，或改过依赖时，请用 Install Scheduler.command。"
echo ""

for command in python3 node npm swift xcrun codesign; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "❌ 缺少必需工具: $command"
        echo "   请先运行 Install Scheduler.command。"
        exit 1
    fi
done

if [[ ! -x "$ROOT_DIR/.venv/bin/python3" ]]; then
    echo "❌ 尚未创建项目虚拟环境。"
    echo "   请先双击 Install Scheduler.command。"
    exit 1
fi
if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
    echo "❌ 尚未安装 React 依赖。"
    echo "   请先双击 Install Scheduler.command。"
    exit 1
fi

PYTHON_EXEC="$ROOT_DIR/.venv/bin/python3"
if ! "$PYTHON_EXEC" -c 'import fastapi, multipart, uvicorn' 2>/dev/null; then
    echo "❌ Python runtime 依赖不完整。"
    echo "   请先双击 Install Scheduler.command。"
    exit 1
fi

echo "✅ Python: $PYTHON_EXEC"
echo "✅ Node.js: $(node --version)"
echo "✅ Swift: $(swift --version | head -1)"
echo "✅ 依赖已就绪，跳过 pip / npm 安装"

echo "🧹 清理遗留应用副本..."
./script/cleanup_legacy_apps.sh

echo "🔨 构建并签名 Swift + React 原生应用..."
rm -rf native-shell/.build
PI_PYTHON_EXECUTABLE="$PYTHON_EXEC" ./script/build_and_run.sh --install

APP_PATH="$HOME/Applications/Music Lesson Scheduler.app"
codesign --verify --deep --strict "$APP_PATH"
if [[ ! -x "$APP_PATH/Contents/MacOS/MusicLessonSchedulerSwift" ]]; then
    echo "❌ Swift 应用主程序缺失。"
    exit 1
fi

echo ""
echo "========================================"
echo "  ✅ Music Lesson Scheduler ${PRODUCT_VERSION} 已更新"
echo "========================================"
echo ""
echo "应用位置: $APP_PATH"
echo "日常使用: 双击 Start Scheduler.command，或打开 Applications 里的 App"
echo "完整重装: 双击 Install Scheduler.command（首次 / 依赖变更）"
echo ""
read -r -p "按 Enter 关闭..." _unused || true
