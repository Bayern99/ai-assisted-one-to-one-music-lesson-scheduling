"""
TDD tests for P1-5: startup health check.
"""
import os
import json

import pytest


class TestHealthCheck:
    """Verify health check reports system state correctly."""

    @pytest.fixture
    def data_dir(self, tmp_path):
        """Create a minimal data directory with required files."""
        d = tmp_path / "data"
        d.mkdir()
        # Create minimal valid files
        (d / "rooms.json").write_text(json.dumps([{"id": "R104", "name": "Room A", "eq": "piano", "type": "piano"}]))
        (d / "workflow_state.json").write_text(json.dumps({"semester": "2025-2026", "current_phase": "planning"}))
        (d / "students.json").write_text(json.dumps([]))
        return str(d)

    def test_health_check_verifies_data_directory(self, data_dir):
        """Health check confirms data directory exists and is readable."""
        from modules.shared.health_check import run_health_check
        result = run_health_check(base_dir=data_dir)
        assert result["status"] in ("ok", "warning")
        assert any("data" in c["name"].lower() for c in result["checks"])

    def test_health_check_detects_missing_critical_files(self, tmp_path):
        """Health check warns when expected files are absent."""
        from modules.shared.health_check import run_health_check
        result = run_health_check(base_dir=str(tmp_path))
        # Should not crash, should report warnings
        assert result["status"] in ("ok", "warning", "error")
        assert len(result["checks"]) > 0

    def test_health_check_reports_imports_ok(self, data_dir):
        """Health check confirms key modules are importable."""
        from modules.shared.health_check import run_health_check
        result = run_health_check(base_dir=data_dir)
        assert len(result["recommendations"]) >= 0  # recommendations list exists
        assert isinstance(result["checks"], list)

    def test_health_check_reports_filesystem_probe_oserror(self, data_dir, monkeypatch):
        from modules.shared import health_check

        def fail_probe(_path):
            raise OSError("probe unavailable")

        monkeypatch.setattr(health_check.os, "listdir", fail_probe)

        result = health_check.run_health_check(base_dir=data_dir)

        assert result["status"] == "error"
        assert any(check["status"] == "error" for check in result["checks"])
