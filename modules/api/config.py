from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    base_dir: Path
    bootstrap_token: str
    frontend_dir: Path | None = None
    allow_test_host: bool = False
    dev_origin: str | None = None

    def safe_export_dir(self) -> Path:
        path = (self.base_dir / "exports").resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
