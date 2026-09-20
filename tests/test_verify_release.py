from __future__ import annotations

from contextlib import contextmanager
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_release.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("verify_release", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gate_runs_lint_and_build_once_before_buildless_e2e():
    verifier = load_verifier()

    commands = [command for _cwd, command in verifier.COMMANDS]

    assert ["npm", "run", "lint"] in commands
    assert commands.count(["npm", "run", "build"]) == 1
    assert ["npm", "run", "e2e:run"] in commands
    assert ["npm", "run", "e2e"] not in commands
    assert [
        verifier.sys.executable,
        "-m",
        "pytest",
        "-q",
    ] in commands


def test_disposable_data_root_is_copied_and_removed(tmp_path):
    verifier = load_verifier()
    source = tmp_path / "source-data"
    source.mkdir()
    (source / "sentinel.json").write_text('{"live": true}\n', encoding="utf8")
    (source / ".music-lesson-scheduler.lock").write_text("live runtime lock\n", encoding="utf8")

    with verifier.disposable_data_root(source) as isolated:
        assert isolated != source
        assert (isolated / "sentinel.json").read_text(encoding="utf8") == '{"live": true}\n'
        assert not (isolated / ".music-lesson-scheduler.lock").exists()
        (isolated / "sentinel.json").write_text('{"live": false}\n', encoding="utf8")
        isolated_parent = isolated.parent

    assert source.joinpath("sentinel.json").read_text(encoding="utf8") == '{"live": true}\n'
    assert source.joinpath(".music-lesson-scheduler.lock").read_text(encoding="utf8") == "live runtime lock\n"
    assert not isolated_parent.exists()


def test_every_gate_command_receives_the_disposable_data_root(monkeypatch, tmp_path):
    verifier = load_verifier()
    isolated = tmp_path / "copied-data"
    isolated.mkdir()
    calls = []

    @contextmanager
    def fake_disposable_data_root(_source):
        yield isolated

    def fake_run(command, *, cwd, check, env):
        calls.append((command, cwd, check, env))

        class Completed:
            returncode = 0

        return Completed()

    monkeypatch.setattr(verifier, "disposable_data_root", fake_disposable_data_root)
    monkeypatch.setattr(verifier.subprocess, "run", fake_run)

    assert verifier.main() == 0
    assert len(calls) == len(verifier.COMMANDS)
    assert all(call[3]["PI_DATA_DIR"] == str(isolated) for call in calls)
    assert all(call[3]["PYTHON"] == verifier.sys.executable for call in calls)
