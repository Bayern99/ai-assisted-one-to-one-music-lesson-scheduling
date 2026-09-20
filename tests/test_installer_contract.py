from pathlib import Path


INSTALLER = Path(__file__).parents[1] / "Install Scheduler.command"
STARTER = Path(__file__).parents[1] / "Start Scheduler.command"
BUILD_SCRIPT = Path(__file__).parents[1] / "script" / "build_and_run.sh"
APPLICATION_PATHS = (
    Path(__file__).parents[1]
    / "native-shell"
    / "Sources"
    / "MusicLessonSchedulerSwift"
    / "Support"
    / "ApplicationPaths.swift"
)
BACKEND_LAUNCH_SPEC = (
    Path(__file__).parents[1]
    / "native-shell"
    / "Sources"
    / "DashboardShellCore"
    / "BackendLaunchSpec.swift"
)


def _installer_source() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_installer_pins_one_python_for_install_and_runtime_checks():
    source = _installer_source()

    assert 'PYTHON_EXEC="$ROOT_DIR/.venv/bin/python3"' in source
    assert '"$SYSTEM_PYTHON" -m venv "$ROOT_DIR/.venv"' in source
    assert '"$PYTHON_EXEC" -m pip install -r requirements.txt' in source
    assert "--user" not in source
    assert '"$PYTHON_EXEC" -c \'import fastapi, multipart, uvicorn\'' in source
    assert 'PI_PYTHON_EXECUTABLE="$PYTHON_EXEC" ./script/build_and_run.sh --install' in source
    assert "webview" not in source
    assert "pip3 install" not in source


def test_swift_bundle_persists_and_reads_the_pinned_python():
    build_script = BUILD_SCRIPT.read_text(encoding="utf-8")
    application_paths = APPLICATION_PATHS.read_text(encoding="utf-8")

    assert 'printf \'%s\\n\' "$PYTHON_EXECUTABLE" > "$stage_resources/python-executable"' in build_script
    assert 'resourceName: "python-executable"' in application_paths
    assert "command -v python3" not in application_paths


def test_swift_bundle_passes_an_available_pi_executable_to_python():
    build_script = BUILD_SCRIPT.read_text(encoding="utf-8")
    application_paths = APPLICATION_PATHS.read_text(encoding="utf-8")
    launch_spec = BACKEND_LAUNCH_SPEC.read_text(encoding="utf-8")

    assert 'printf \'%s\\n\' "$PI_EXECUTABLE" > "$stage_resources/pi-executable"' in build_script
    assert 'resourceName: "pi-executable"' in application_paths
    assert 'environment["PI_EXECUTABLE"] = piExecutable.path' in launch_spec


def test_installed_app_uses_application_support_and_preserves_existing_workspace():
    build_script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert (
        'APP_DATA_DIR="${PI_APP_DATA_DIR:-$HOME/Library/Application Support/'
        'Music Lesson Scheduler/Data}"' in build_script
    )
    assert '/usr/bin/ditto "$ROOT_DIR/data" "$APP_DATA_DIR"' in build_script
    assert 'printf \'%s\\n\' "$APP_DATA_DIR" > "$stage_resources/data-directory"' in build_script
    assert 'rm -rf "$APP_DATA_DIR"' not in build_script


def test_swift_backend_uses_clean_python_environment_and_absolute_data_dir():
    launch_spec = BACKEND_LAUNCH_SPEC.read_text(encoding="utf-8")

    assert 'environment.removeValue(forKey: "PYTHONHOME")' in launch_spec
    assert 'environment.removeValue(forKey: "PYTHONPATH")' in launch_spec
    assert 'environment.removeValue(forKey: "PYTHONNOUSERSITE")' in launch_spec
    assert 'environment["PI_DATA_DIR"] = dataDirectory.path' in launch_spec
    assert 'currentDirectoryURL: workingDirectory' in launch_spec


def test_installer_builds_and_verifies_a_signed_swift_app_before_replacement():
    installer = _installer_source()
    build_script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "swift test --package-path \"$PACKAGE_DIR\"" in build_script
    assert "swift build --package-path \"$PACKAGE_DIR\"" in build_script
    assert 'codesign --force --deep --sign - "$stage_bundle"' in build_script
    assert 'codesign --verify --deep --strict "$stage_bundle"' in build_script
    assert "NSDocumentsFolderUsageDescription" in build_script
    assert build_script.index('codesign --verify --deep --strict "$stage_bundle"') < build_script.index(
        'rm -rf "$APP_BUNDLE"'
    )
    assert 'codesign --verify --deep --strict "$APP_PATH"' in installer
    assert 'MusicLessonSchedulerSwift' in installer


def test_start_command_opens_only_the_installed_swift_app():
    source = STARTER.read_text(encoding="utf-8")

    assert 'APP_PATH="$HOME/Applications/Music Lesson Scheduler.app"' in source
    assert '"$APP_PATH/Contents/MacOS/MusicLessonSchedulerSwift"' in source
    assert '/usr/bin/open "$APP_PATH"' in source
    assert "launcher.py" not in source
    assert "python" not in source.lower()


def test_update_command_rebuilds_without_reinstalling_dependencies():
    source = (Path(__file__).parents[1] / "Update Scheduler.command").read_text(
        encoding="utf-8"
    )

    assert 'PYTHON_EXEC="$ROOT_DIR/.venv/bin/python3"' in source
    assert "pip install" not in source
    assert "npm --prefix frontend ci" not in source
    assert 'PI_PYTHON_EXECUTABLE="$PYTHON_EXEC" ./script/build_and_run.sh --install' in source
    assert "cleanup_legacy_apps.sh" in source
