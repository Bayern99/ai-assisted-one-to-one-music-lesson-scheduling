from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from modules.api.app import create_app
from modules.api.config import AppConfig


@pytest.fixture
def built_frontend(tmp_path: Path) -> Path:
    frontend_dir = tmp_path / "dist"
    assets_dir = frontend_dir / "assets"
    assets_dir.mkdir(parents=True)
    (frontend_dir / "index.html").write_text(
        '<!doctype html><div id="root"></div>', encoding="utf-8"
    )
    (assets_dir / "index-deadbeef.js").write_text(
        "console.log('pi')", encoding="utf-8"
    )
    return frontend_dir


@pytest.fixture
def static_client(tmp_path: Path, built_frontend: Path) -> TestClient:
    app = create_app(
        AppConfig(
            base_dir=tmp_path / "data",
            bootstrap_token="test-token",
            frontend_dir=built_frontend,
            allow_test_host=True,
        )
    )
    return TestClient(app)


def test_root_returns_react_index(static_client: TestClient):
    response = static_client.get("/")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_unknown_client_route_returns_react_index(static_client: TestClient):
    response = static_client.get("/schedule/resolve")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text


def test_unknown_api_route_remains_json_404(static_client: TestClient):
    response = static_client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "HTTP_404"


def test_hashed_assets_are_cacheable_and_missing_assets_do_not_fall_back(
    static_client: TestClient,
):
    asset = static_client.get("/assets/index-deadbeef.js")
    missing = static_client.get("/assets/missing.js")

    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/json")


def test_asset_mount_root_does_not_fall_back_to_spa(static_client: TestClient):
    response = static_client.get("/assets")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize(
    "path",
    [
        "/assets/..%2Findex.html",
        "/assets/%2e%2e/%2e%2e/etc/passwd",
    ],
)
def test_asset_traversal_is_rejected(static_client: TestClient, path: str):
    response = static_client.get(path)

    assert response.status_code == 404
    assert '<div id="root"></div>' not in response.text


def test_api_only_app_still_uses_json_404(tmp_path: Path):
    app = create_app(
        AppConfig(
            base_dir=tmp_path / "data",
            bootstrap_token="test-token",
            frontend_dir=None,
            allow_test_host=True,
        )
    )

    with TestClient(app) as client:
        response = client.get("/schedule/resolve")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"


def test_configured_frontend_requires_complete_build(tmp_path: Path):
    missing_dist = tmp_path / "frontend" / "dist"

    with pytest.raises(RuntimeError, match="React frontend build is missing"):
        create_app(
            AppConfig(
                base_dir=tmp_path / "data",
                bootstrap_token="test-token",
                frontend_dir=missing_dist,
                allow_test_host=True,
            )
        )


def test_configured_frontend_rejects_index_symlink_outside_build(tmp_path: Path):
    frontend_dir = tmp_path / "frontend" / "dist"
    (frontend_dir / "assets").mkdir(parents=True)
    secret = tmp_path / "secret.html"
    secret.write_text("outside build", encoding="utf-8")
    (frontend_dir / "index.html").symlink_to(secret)

    with pytest.raises(RuntimeError, match="React frontend build is missing"):
        create_app(
            AppConfig(
                base_dir=tmp_path / "data",
                bootstrap_token="test-token",
                frontend_dir=frontend_dir,
                allow_test_host=True,
            )
        )


def test_configured_frontend_rejects_assets_symlink_outside_build(tmp_path: Path):
    frontend_dir = tmp_path / "frontend" / "dist"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "index.html").write_text("<div id='root'></div>", encoding="utf-8")
    outside_assets = tmp_path / "outside-assets"
    outside_assets.mkdir()
    (outside_assets / "secret.js").write_text("secret", encoding="utf-8")
    (frontend_dir / "assets").symlink_to(outside_assets, target_is_directory=True)

    with pytest.raises(RuntimeError, match="React frontend build is missing"):
        create_app(
            AppConfig(
                base_dir=tmp_path / "data",
                bootstrap_token="test-token",
                frontend_dir=frontend_dir,
                allow_test_host=True,
            )
        )
