from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import jwt  # PyJWT
from fastapi import HTTPException, Request, status

from .config import settings


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class UserContext:
    """Verified identity extracted from a JWT bearer token."""
    user_id: str          # maps to the JWT `sub` claim
    roles: list[str]      # maps to settings.jwt_roles_claim
    display_name: str     # maps to `name` claim, falls back to user_id
    email: str            # maps to `email` claim when present
    raw_claims: dict[str, Any] = field(default_factory=dict)  # full decoded payload


# ── Internal helpers ──────────────────────────────────────────────────────────

def _decode_key() -> str | bytes:
    """Returns the secret / public-key material used for signature verification.

    For HMAC algorithms (HS256/HS384/HS512) this is the raw secret string.
    For asymmetric algorithms (RS256, ES256 …) set JWT_SECRET to the path of a
    PEM-encoded public-key file; this function will read and return the bytes.
    """
    secret = settings.jwt_secret
    if not secret:
        raise RuntimeError(
            "JWT_SECRET is not configured. "
            "Set the JWT_SECRET environment variable before starting the gateway."
        )
    from pathlib import Path
    candidate = Path(secret)
    if candidate.is_file():
        return candidate.read_bytes()
    return secret


def _build_decode_options() -> dict[str, Any]:
    """Constructs PyJWT decode options based on current settings."""
    options: dict[str, Any] = {
        "verify_signature": True,
        "require": ["sub", "exp", "iat"],
    }
    return options


# ── Public API ────────────────────────────────────────────────────────────────

_INVALID_TOKEN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or missing bearer token.",
    headers={"WWW-Authenticate": "Bearer"},
)

_EXPIRED_TOKEN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Token has expired.",
    headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Token expired"'},
)

_MISSING_TOKEN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Authorization header missing or not a Bearer token.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_user_context(request: Request) -> UserContext:
    """Verifies the JWT in the ``Authorization: Bearer <token>`` header and
    returns a :class:`UserContext` populated from the token's claims.

    Raises:
        401 – if the header is absent, the token is malformed, the signature
              is invalid, or the token has expired.
    """
    # 1. Extract raw token from header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise _MISSING_TOKEN

    raw_token = auth_header[len("bearer "):].strip()
    if not raw_token:
        raise _MISSING_TOKEN

    # 2. Verify signature, expiry, and (optionally) audience
    try:
        key = _decode_key()
    except RuntimeError as exc:
        # Mis-configuration is a server error, not a client error – but we
        # still surface it as 401 so callers are not confused.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    decode_kwargs: dict[str, Any] = {
        "algorithms": [settings.jwt_algorithm],
        "options": _build_decode_options(),
    }
    if settings.jwt_audience:
        decode_kwargs["audience"] = settings.jwt_audience

    try:
        claims: dict[str, Any] = jwt.decode(raw_token, key, **decode_kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise _EXPIRED_TOKEN from exc
    except jwt.PyJWTError as exc:
        # Covers DecodeError, InvalidSignatureError, InvalidAlgorithmError, etc.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # 3. Extract standard + custom claims
    user_id: str = claims.get("sub", "").strip() or "anonymous"
    display_name: str = claims.get("name", user_id).strip() or user_id
    email: str = claims.get("email", "").strip()

    raw_roles = claims.get(settings.jwt_roles_claim, [])
    if isinstance(raw_roles, str):
        # Support a single role encoded as a plain string
        raw_roles = [raw_roles]
    roles: list[str] = sorted({r.strip() for r in raw_roles if isinstance(r, str) and r.strip()})

    return UserContext(
        user_id=user_id,
        roles=roles,
        display_name=display_name,
        email=email,
        raw_claims=claims,
    )


async def require_admin(request: Request) -> UserContext:
    """FastAPI dependency that ensures the caller holds the ``admin`` role.

    Raises:
        401 – propagated from :func:`get_user_context` for auth failures.
        403 – if the verified token does not contain the ``admin`` role.
    """
    user = await get_user_context(request)
    if "admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint requires the 'admin' role.",
        )
    return user
