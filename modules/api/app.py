from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from modules.api.config import AppConfig
from modules.api.errors import (
    ApiCORSMiddleware,
    ApiTrustedHostMiddleware,
    register_exception_handlers,
)
from modules.api.operations import OperationRegistry
from modules.api.routers import (
    auth,
    health,
    info_hub,
    operations,
    scheduler_configuration,
    scheduler_draft,
    scheduler_exports,
    scheduler_finalize,
    scheduler_imports,
    scheduler_optimizer,
    scheduler_pi_intervention,
    scheduler_resolution,
    scheduler_session,
    scheduler_stage,
    workspace,
)
from modules.api.services.exports import ArtifactRegistry
from modules.api.services.pi_reconciliation import PiReconciliationCapabilityStore
from modules.api.services.imports import ImportPreviewStore
from modules.scheduler.context import build_scheduler_context
from modules.shared.data_loader import DataLoader


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    base_dir = str(app.state.config.base_dir)
    app.state.scheduler_context = build_scheduler_context(
        base_dir=base_dir,
        loader=DataLoader(
            base_dir=base_dir,
            backup_corrupt_reads=False,
        ),
    )
    app.state.operation_registry = OperationRegistry()
    app.state.import_preview_store = ImportPreviewStore()
    app.state.artifact_registry = ArtifactRegistry()
    app.state.pi_reconciliation_capabilities = PiReconciliationCapabilityStore()
    app.state.operation_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="pi-operation",
    )
    try:
        yield
    finally:
        app.state.operation_executor.shutdown(wait=True, cancel_futures=True)


def create_app(config: AppConfig) -> FastAPI:
    frontend_dir: Path | None = None
    index_path: Path | None = None
    assets_dir: Path | None = None
    if config.frontend_dir is not None:
        frontend_dir = config.frontend_dir.resolve()
        index_path = (frontend_dir / "index.html").resolve()
        assets_dir = (frontend_dir / "assets").resolve()
        try:
            index_path.relative_to(frontend_dir)
            assets_dir.relative_to(frontend_dir)
        except ValueError as exc:
            raise RuntimeError(
                "React frontend build is missing or incomplete at "
                f"{frontend_dir}. Run `cd frontend && npm run build`."
            ) from exc
        if not index_path.is_file() or not assets_dir.is_dir():
            raise RuntimeError(
                "React frontend build is missing or incomplete at "
                f"{frontend_dir}. Run `cd frontend && npm run build`."
            )

    app = FastAPI(
        title="AI-Assisted One-to-One Music Lesson Scheduling Local API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.config = config

    if config.dev_origin:
        app.add_middleware(
            ApiCORSMiddleware,
            allow_origins=[config.dev_origin],
            allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-PI-Bootstrap-Token"],
        )

    hosts = ["127.0.0.1", "localhost"]
    if config.allow_test_host:
        hosts.append("testserver")
    # Starlette makes the most recently added user middleware outermost.
    app.add_middleware(ApiTrustedHostMiddleware, allowed_hosts=hosts)

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(workspace.router, prefix="/api")
    app.include_router(info_hub.router, prefix="/api")
    app.include_router(operations.router, prefix="/api")
    app.include_router(scheduler_session.router, prefix="/api")
    app.include_router(scheduler_imports.router, prefix="/api")
    app.include_router(scheduler_configuration.router, prefix="/api")
    app.include_router(scheduler_draft.router, prefix="/api")
    app.include_router(scheduler_finalize.router, prefix="/api")
    app.include_router(scheduler_stage.router, prefix="/api")
    app.include_router(scheduler_exports.router, prefix="/api")
    app.include_router(scheduler_optimizer.router, prefix="/api")
    app.include_router(scheduler_resolution.router, prefix="/api")
    app.include_router(scheduler_pi_intervention.router, prefix="/api")
    app.include_router(scheduler_pi_intervention.internal_router, prefix="/api")
    register_exception_handlers(app)

    if frontend_dir is not None:
        assert assets_dir is not None
        assert index_path is not None

        @app.get("/assets/{asset_path:path}", include_in_schema=False)
        @app.head("/assets/{asset_path:path}", include_in_schema=False)
        def serve_frontend_asset(asset_path: str) -> FileResponse:
            candidate = (assets_dir / asset_path).resolve()
            try:
                candidate.relative_to(assets_dir)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail="Not Found") from exc
            if not candidate.is_file():
                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(
                candidate,
                headers={
                    "Cache-Control": "public, max-age=31536000, immutable",
                    "X-Content-Type-Options": "nosniff",
                },
            )

        @app.get("/", include_in_schema=False)
        @app.head("/", include_in_schema=False)
        def serve_frontend_root() -> FileResponse:
            return FileResponse(index_path, headers={"Cache-Control": "no-cache"})

        @app.get("/{client_path:path}", include_in_schema=False)
        @app.head("/{client_path:path}", include_in_schema=False)
        def serve_frontend_route(client_path: str) -> FileResponse:
            if client_path in {"api", "assets"} or client_path.startswith(
                ("api/", "assets/")
            ):
                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(index_path, headers={"Cache-Control": "no-cache"})

    return app
