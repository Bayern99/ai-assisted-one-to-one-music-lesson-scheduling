#!/bin/bash
set -Eeuo pipefail

STAGE_ROOT=""
pause_on_error() {
    local status=$?
    [[ -n "$STAGE_ROOT" && -d "$STAGE_ROOT" ]] && rm -rf "$STAGE_ROOT"
    echo ""
    echo "❌ 安装失败（第 $1 行）。请保留上面的错误信息。"
    read -r -p "按 Enter 退出..." _unused || true
    exit "$status"
}
trap 'pause_on_error "$LINENO"' ERR

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"
unset PYTHONHOME PYTHONPATH PYTHONNOUSERSITE
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:${PATH:-}"

echo "========================================"
echo "  Music Lesson Scheduler 4.6.5 — 原生安装"
echo "========================================"
echo ""

for command in python3 node npm swift xcrun codesign; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "❌ 缺少必需工具: $command"
        echo "   请安装 Python 3、Node.js 和 Xcode Command Line Tools。"
        exit 1
    fi
done

PYTHON_EXEC=""
if [[ -x "$ROOT_DIR/.venv/bin/python3" ]]; then
    PYTHON_EXEC="$ROOT_DIR/.venv/bin/python3"
else
    SYSTEM_PYTHON="$(command -v python3)"
    if [[ "$SYSTEM_PYTHON" != /* || ! -x "$SYSTEM_PYTHON" ]]; then
        echo "❌ Python 3 不是可执行的绝对路径: $SYSTEM_PYTHON"
        exit 1
    fi
    echo "📦 创建项目虚拟环境..."
    "$SYSTEM_PYTHON" -m venv "$ROOT_DIR/.venv"
    PYTHON_EXEC="$ROOT_DIR/.venv/bin/python3"
fi
if ! "$PYTHON_EXEC" -m pip --version >/dev/null 2>&1; then
    echo "❌ 当前 Python 3 没有可用的 pip。"
    exit 1
fi
if ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22 ? 0 : 1)'; then
    echo "❌ Node.js 版本不受支持: $(node --version)"
    echo "   需要 ^20.19.0、^22.12.0 或更新的受支持版本。"
    exit 1
fi

echo "✅ Python: $PYTHON_EXEC"
echo "✅ Node.js: $(node --version)"
echo "✅ Swift: $(swift --version | head -1)"

echo "📦 安装 Python 依赖..."
"$PYTHON_EXEC" -m pip install -r requirements.txt
if ! "$PYTHON_EXEC" -c 'import fastapi, multipart, uvicorn' 2>/dev/null; then
    echo "❌ Python runtime 依赖验证失败。"
    exit 1
fi

echo "📦 安装 React 依赖..."
npm --prefix frontend ci

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
echo "  ✅ Music Lesson Scheduler 4.6.5 安装完成"
echo "========================================"
echo ""
echo "应用位置: $APP_PATH"
echo "工作数据: $HOME/Library/Application Support/Music Lesson Scheduler/Data"
echo "日常使用: 在个人 Applications 文件夹双击 Music Lesson Scheduler.app"
echo "备用启动: 双击 Start Scheduler.command"
echo "改完代码后更新: 双击 Update Scheduler.command（跳过依赖，更快）"
echo ""
read -r -p "按 Enter 关闭..." _unused || true
