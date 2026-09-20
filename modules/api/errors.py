from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from modules.api.schemas.common import ApiEnvelope, ApiErrorPayload


class ApiProblem(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    envelope = ApiEnvelope(
        error=ApiErrorPayload(code=code, message=message, details=details)
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json"),
        headers=headers,
    )


class ApiTrustedHostMiddleware(TrustedHostMiddleware):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.allow_any or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        host = Headers(scope=scope).get("host", "").split(":")[0]
        is_valid_host = any(
            host == pattern
            or (pattern.startswith("*") and host.endswith(pattern[1:]))
            for pattern in self.allowed_hosts
        )
        if is_valid_host:
            await self.app(scope, receive, send)
            return

        response = error_response(
            status_code=400,
            code="INVALID_HOST",
            message="Invalid host header",
        )
        await response(scope, receive, send)


class ApiCORSMiddleware(CORSMiddleware):
    def preflight_response(self, request_headers: Headers) -> Response:
        response = super().preflight_response(request_headers)
        if response.status_code < 400:
            return response

        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-length", "content-type"}
        }
        return error_response(
            status_code=response.status_code,
            code="CORS_REJECTED",
            message=response.body.decode("utf-8"),
            headers=headers,
        )


def _http_error_code(status_code: int, detail: Any) -> str:
    if isinstance(detail, str):
        normalized = detail.replace("_", "")
        if normalized.isalnum() and detail == detail.upper():
            return detail
    return "HTTP_{0}".format(status_code)


def _http_error_message(status_code: int, detail: Any) -> str:
    if isinstance(detail, str) and detail != "AUTH_REQUIRED":
        return detail
    if detail == "AUTH_REQUIRED":
        return "Authentication required"
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed"


async def _api_problem_handler(request: Request, exc: ApiProblem) -> JSONResponse:
    del request
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    del request
    return error_response(
        status_code=exc.status_code,
        code=_http_error_code(exc.status_code, exc.detail),
        message=_http_error_message(exc.status_code, exc.detail),
        headers=exc.headers,
    )


async def _validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    del request
    return error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details={"errors": exc.errors()},
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request, exc
    return error_response(
        status_code=500,
        code="INTERNAL_ERROR",
        message="Internal server error",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiProblem, _api_problem_handler)
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
