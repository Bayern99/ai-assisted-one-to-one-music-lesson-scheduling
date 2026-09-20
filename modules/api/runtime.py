from __future__ import annotations

import os
from pathlib import Path

from modules.api.app import create_app
from modules.api.config import AppConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]

try:
    bootstrap_token = os.environ["PI_BOOTSTRAP_TOKEN"]
except KeyError as exc:
    raise RuntimeError(
        "PI_BOOTSTRAP_TOKEN is required; start through the native app or development runbook"
    ) from exc

if not bootstrap_token:
    raise RuntimeError("PI_BOOTSTRAP_TOKEN must not be empty")

data_dir = Path(os.environ.get("PI_DATA_DIR", PROJECT_ROOT / "data")).resolve()
frontend_dir = (PROJECT_ROOT / "frontend" / "dist").resolve()

app = create_app(
    AppConfig(
        base_dir=data_dir,
        bootstrap_token=bootstrap_token,
        frontend_dir=frontend_dir,
    )
)
