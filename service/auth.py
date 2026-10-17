"""Fail-closed JWT authentication for the SaaS API.

Configure a trusted identity provider's JWKS URL, issuer, and audience. Never
accept user IDs or tenant membership from request headers or request bodies.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from pydantic import BaseModel

_bearer = HTTPBearer(auto_error=False)


class Principal(BaseModel):
    user_id: str
    issuer: str
    claims: dict[str, Any]


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True, timeout=5)


def verified_claims(token: str) -> dict[str, Any]:
    jwks_url = os.getenv("JWT_JWKS_URL", "").strip()
    issuer = os.getenv("JWT_ISSUER", "").strip()
    audience = os.getenv("JWT_AUDIENCE", "").strip()
    if not all((jwks_url, issuer, audience)):
        raise HTTPException(status_code=503, detail="Authentication provider is not configured")
    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            issuer=issuer,
            audience=audience,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            leeway=30,
        )
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise jwt.InvalidTokenError("Missing subject")
        return claims
    except HTTPException:
        raise
    except Exception as exc:
        # Avoid returning parser/provider internals to an untrusted caller.
        raise HTTPException(status_code=401, detail="Invalid or expired bearer token") from exc


def require_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = verified_claims(credentials.credentials)
    try:
        import uuid
        user_id = str(uuid.UUID(claims["sub"]))
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=401, detail="Token subject must be a user UUID") from exc
    return Principal(user_id=user_id, issuer=claims["iss"], claims=claims)
