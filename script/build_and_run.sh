#!/bin/bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="Music Lesson Scheduler"
EXECUTABLE_NAME="MusicLessonSchedulerSwift"
BUNDLE_ID="com.research.music-lesson-scheduler"
MIN_SYSTEM_VERSION="14.0"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_DIR="$ROOT_DIR/native-shell"
DIST_DIR="$ROOT_DIR/dist"
PRODUCT_VERSION="$(grep -E '^version = ' "$ROOT_DIR/pyproject.toml" | sed -E 's/^version = "([^"]+)".*/\1/')"
if [[ "$MODE" == "--install" || "$MODE" == "install" ]]; then
  INSTALL_DIR="${PI_APP_INSTALL_DIR:-$HOME/Applications}"
  APP_BUNDLE="$INSTALL_DIR/$APP_NAME.app"
  APP_DATA_DIR="${PI_APP_DATA_DIR:-$HOME/Library/Application Support/Music Lesson Scheduler/Data}"
  RUNTIME_FILE="$APP_DATA_DIR/logs/swift-shell-runtime.json"
else
  APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
  APP_DATA_DIR="${PI_APP_DATA_DIR:-$HOME/Library/Application Support/Music Lesson Scheduler/Data}"
  RUNTIME_FILE="$APP_DATA_DIR/logs/swift-shell-runtime.json"
fi
APP_BINARY="$APP_BUNDLE/Contents/MacOS/$EXECUTABLE_NAME"
PYTHON_EXECUTABLE="${PI_PYTHON_EXECUTABLE:-$(command -v python3)}"
PI_EXECUTABLE="${PI_EXECUTABLE:-$(command -v pi || true)}"
if [[ -n "${PI_NODE_EXECUTABLE:-}" ]]; then
  NODE_EXECUTABLE="$PI_NODE_EXECUTABLE"
elif [[ -x /opt/homebrew/bin/node ]]; then
  NODE_EXECUTABLE=/opt/homebrew/bin/node
else
  NODE_EXECUTABLE="$(command -v node)"
fi

terminate_pid() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  kill -0 "$pid" >/dev/null 2>&1 || return 0
  kill "$pid" >/dev/null 2>&1 || true
  for _ in {1..20}; do
    kill -0 "$pid" >/dev/null 2>&1 || return 0
    sleep 0.05
  done
  kill -9 "$pid" >/dev/null 2>&1 || true
}

stop_runtime_file() {
  local runtime_file="$1"
  if [[ -f "$runtime_file" ]]; then
    local backend_pid shell_pid
    backend_pid="$(/usr/bin/plutil -extract backend_pid raw -o - "$runtime_file" 2>/dev/null || true)"
    shell_pid="$(/usr/bin/plutil -extract shell_pid raw -o - "$runtime_file" 2>/dev/null || true)"
    terminate_pid "$backend_pid"
    terminate_pid "$shell_pid"
    rm -f "$runtime_file"
  fi
}

stop_running_copy() {
  /usr/bin/osascript -e 'tell application id "com.research.music-lesson-scheduler" to quit' >/dev/null 2>&1 || true
  stop_runtime_file "$RUNTIME_FILE"
  # Clean up the pre-App-Support runtime once during migration.
  stop_runtime_file "$ROOT_DIR/data/logs/swift-shell-runtime.json"
  local pid
  while IFS= read -r pid; do
    terminate_pid "$pid"
  done < <(/usr/bin/pgrep -f "$APP_BUNDLE/Contents/Resources/runtime" 2>/dev/null || true)
  while IFS= read -r pid; do
    terminate_pid "$pid"
  done < <(/usr/bin/pgrep -f "$APP_BINARY" 2>/dev/null || true)
  for _ in {1..40}; do
    if ! /usr/bin/pgrep -f "$APP_BINARY" >/dev/null 2>&1; then
      break
    fi
    sleep 0.05
  done
}

prepare_app_data() {
  mkdir -p "$APP_DATA_DIR"
  if [[ -z "$(find "$APP_DATA_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    /usr/bin/ditto "$ROOT_DIR/data" "$APP_DATA_DIR"
  fi
  rm -f "$APP_DATA_DIR/.music-lesson-scheduler.lock" "$APP_DATA_DIR/logs/swift-shell-runtime.json"
}

build_app() {
  if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
    npm --prefix "$ROOT_DIR/frontend" ci
  fi
  (
    cd "$ROOT_DIR/frontend"
    "$NODE_EXECUTABLE" node_modules/typescript/bin/tsc -b
    "$NODE_EXECUTABLE" node_modules/vite/bin/vite.js build
  )
  swift test --package-path "$PACKAGE_DIR"
  swift build --package-path "$PACKAGE_DIR"

  local build_binary
  build_binary="$(swift build --package-path "$PACKAGE_DIR" --show-bin-path)/$EXECUTABLE_NAME"

  local stage_root stage_bundle stage_contents stage_macos stage_resources stage_runtime stage_binary info_plist
  stage_root="$(mktemp -d /tmp/music-lesson-scheduler-swift-app.XXXXXX)"
  stage_bundle="$stage_root/$APP_NAME.app"
  stage_contents="$stage_bundle/Contents"
  stage_macos="$stage_contents/MacOS"
  stage_resources="$stage_contents/Resources"
  stage_runtime="$stage_resources/runtime"
  stage_binary="$stage_macos/$EXECUTABLE_NAME"
  info_plist="$stage_contents/Info.plist"

  mkdir -p "$stage_macos" "$stage_resources"
  cp "$build_binary" "$stage_binary"
  chmod +x "$stage_binary"
  mkdir -p "$stage_runtime/frontend"
  /usr/bin/ditto "$ROOT_DIR/modules" "$stage_runtime/modules"
  /usr/bin/ditto "$ROOT_DIR/frontend/dist" "$stage_runtime/frontend/dist"
  find "$stage_runtime" -type f -name '*.pyc' -delete
  printf '%s\n' "$ROOT_DIR" > "$stage_resources/project-root"
  printf '%s\n' "$PYTHON_EXECUTABLE" > "$stage_resources/python-executable"
  if [[ -n "$PI_EXECUTABLE" && -x "$PI_EXECUTABLE" ]]; then
    printf '%s\n' "$PI_EXECUTABLE" > "$stage_resources/pi-executable"
  fi
  if [[ "$MODE" == "--install" || "$MODE" == "install" ]]; then
    prepare_app_data
    printf '%s\n' "$APP_DATA_DIR" > "$stage_resources/data-directory"
  fi

  local icon_source iconset icon_file
  icon_source="$ROOT_DIR/app_icon_v2.png"
  iconset="$stage_root/AppIcon.iconset"
  icon_file="$stage_resources/app_icon.icns"
  if [[ -f "$icon_source" ]]; then
    mkdir -p "$iconset"
    /usr/bin/sips -s format png -z 16 16 "$icon_source" --out "$iconset/icon_16x16.png" >/dev/null
    /usr/bin/sips -s format png -z 32 32 "$icon_source" --out "$iconset/icon_16x16@2x.png" >/dev/null
    /usr/bin/sips -s format png -z 32 32 "$icon_source" --out "$iconset/icon_32x32.png" >/dev/null
    /usr/bin/sips -s format png -z 64 64 "$icon_source" --out "$iconset/icon_32x32@2x.png" >/dev/null
    /usr/bin/sips -s format png -z 128 128 "$icon_source" --out "$iconset/icon_128x128.png" >/dev/null
    /usr/bin/sips -s format png -z 256 256 "$icon_source" --out "$iconset/icon_128x128@2x.png" >/dev/null
    /usr/bin/sips -s format png -z 256 256 "$icon_source" --out "$iconset/icon_256x256.png" >/dev/null
    /usr/bin/sips -s format png -z 512 512 "$icon_source" --out "$iconset/icon_256x256@2x.png" >/dev/null
    /usr/bin/sips -s format png -z 512 512 "$icon_source" --out "$iconset/icon_512x512.png" >/dev/null
    /usr/bin/sips -s format png -z 1024 1024 "$icon_source" --out "$iconset/icon_512x512@2x.png" >/dev/null
    /usr/bin/iconutil -c icns "$iconset" -o "$icon_file"
  fi

  /usr/bin/plutil -create xml1 "$info_plist"
  /usr/bin/plutil -insert CFBundleExecutable -string "$EXECUTABLE_NAME" "$info_plist"
  /usr/bin/plutil -insert CFBundleIdentifier -string "$BUNDLE_ID" "$info_plist"
  /usr/bin/plutil -insert CFBundleDisplayName -string "Music Lesson Scheduler" "$info_plist"
  /usr/bin/plutil -insert CFBundleName -string "$APP_NAME" "$info_plist"
  /usr/bin/plutil -insert CFBundlePackageType -string APPL "$info_plist"
  /usr/bin/plutil -insert CFBundleShortVersionString -string "$PRODUCT_VERSION" "$info_plist"
  /usr/bin/plutil -insert CFBundleVersion -string "$PRODUCT_VERSION" "$info_plist"
  if [[ -f "$icon_file" ]]; then
    /usr/bin/plutil -insert CFBundleIconFile -string app_icon "$info_plist"
  fi
  /usr/bin/plutil -insert LSMinimumSystemVersion -string "$MIN_SYSTEM_VERSION" "$info_plist"
  /usr/bin/plutil -insert NSPrincipalClass -string NSApplication "$info_plist"
  /usr/bin/plutil -insert NSHighResolutionCapable -bool true "$info_plist"
  /usr/bin/plutil -insert NSDocumentsFolderUsageDescription -string "Music Lesson Scheduler reads and updates the local scheduling workspace selected during installation." "$info_plist"

  /usr/bin/xattr -cr "$stage_bundle"
  /usr/bin/codesign --force --deep --sign - "$stage_bundle"
  /usr/bin/codesign --verify --deep --strict "$stage_bundle"
  mkdir -p "$(dirname "$APP_BUNDLE")"
  rm -rf "$APP_BUNDLE"
  mv "$stage_bundle" "$APP_BUNDLE"
  # Finder can attach FinderInfo after a bundle move. That metadata is outside
  # the code-signature envelope, so remove it before the final strict check.
  /usr/bin/xattr -d com.apple.FinderInfo "$APP_BUNDLE" >/dev/null 2>&1 || true
  /usr/bin/codesign --verify --deep --strict "$APP_BUNDLE"
  rm -rf "$stage_root"
}

open_app() {
  /usr/bin/open "$APP_BUNDLE"
}

verify_app() {
  local shell_pid=""
  local backend_pid=""
  local port=""
  for _ in {1..120}; do
    if [[ -f "$RUNTIME_FILE" ]]; then
      shell_pid="$(/usr/bin/plutil -extract shell_pid raw -o - "$RUNTIME_FILE" 2>/dev/null || true)"
      backend_pid="$(/usr/bin/plutil -extract backend_pid raw -o - "$RUNTIME_FILE" 2>/dev/null || true)"
      port="$(/usr/bin/plutil -extract port raw -o - "$RUNTIME_FILE" 2>/dev/null || true)"
      if [[ "$shell_pid" =~ ^[0-9]+$ && "$backend_pid" =~ ^[0-9]+$ && "$port" =~ ^[0-9]+$ ]]; then
        break
      fi
    fi
    sleep 0.25
  done

  [[ "$shell_pid" =~ ^[0-9]+$ ]] && kill -0 "$shell_pid"
  [[ "$backend_pid" =~ ^[0-9]+$ ]] && kill -0 "$backend_pid"
  [[ "$port" =~ ^[0-9]+$ ]]
  local healthy=false
  for _ in {1..120}; do
    if /usr/bin/curl --fail --silent "http://127.0.0.1:$port/api/health" >/dev/null 2>&1; then
      healthy=true
      break
    fi
    sleep 0.25
  done
  [[ "$healthy" == true ]]
  echo "Swift shell verified: shell PID $shell_pid, Python PID $backend_pid, loopback port $port"
}

stop_running_copy
if [[ "$MODE" == "--install" || "$MODE" == "install" ]]; then
  "$ROOT_DIR/script/cleanup_legacy_apps.sh"
fi
build_app

case "$MODE" in
  run)
    open_app
    ;;
  --debug|debug)
    lldb -- "$APP_BINARY"
    ;;
  --logs|logs)
    open_app
    /usr/bin/log stream --info --style compact --predicate "process == \"$EXECUTABLE_NAME\""
    ;;
  --telemetry|telemetry)
    open_app
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    open_app
    verify_app
    ;;
  --install|install)
    echo "Installed and verified: $APP_BUNDLE"
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify|--install]" >&2
    exit 2
    ;;
esac
