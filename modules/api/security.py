from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Cookie, HTTPException, Request


def require_session(
    request: Request,
    pi_session: Optional[str] = Cookie(default=None),
) -> None:
    expected = request.app.state.config.bootstrap_token
    if not pi_session or not secrets.compare_digest(pi_session, expected):
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
