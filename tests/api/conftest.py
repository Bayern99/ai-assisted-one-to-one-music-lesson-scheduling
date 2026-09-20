from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from modules.api.app import create_app
from modules.api.config import AppConfig


@pytest.fixture
def bootstrap_token() -> str:
    return "test-token"


@pytest.fixture
def client(tmp_path: Path, bootstrap_token: str) -> Iterator[TestClient]:
    config = AppConfig(
        base_dir=tmp_path,
        bootstrap_token=bootstrap_token,
        frontend_dir=None,
        allow_test_host=True,
    )
    with TestClient(create_app(config)) as active_client:
        yield active_client
