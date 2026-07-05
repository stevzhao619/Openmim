from __future__ import annotations

from fastapi import Header, HTTPException, Request


def token_from_request(request: Request, authorization: str | None = Header(default=None)) -> str:
    """Extract token from Authorization: Bearer <token> or ?token=<token>."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    token = request.query_params.get("token")
    return (token or "").strip()


def require_token(expected: str):
    """FastAPI dependency: empty expected → 503; mismatch → 401."""

    async def dep(request: Request, authorization: str | None = Header(default=None)) -> bool:
        if not expected:
            raise HTTPException(status_code=503, detail="WEB_PANEL_ACCESS_TOKEN is required")
        if token_from_request(request, authorization) != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return True

    return dep
