from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request, status


@dataclass(slots=True)
class UserContext:
    user_id: str
    roles: list[str]
    display_name: str


async def get_user_context(request: Request) -> UserContext:
    """Extracts user identity, roles, and display name from incoming request headers."""
    user_id = request.headers.get("x-user-id", "anonymous").strip() or "anonymous"
    display_name = request.headers.get("x-user-name", user_id).strip() or user_id
    roles_header = request.headers.get("x-roles", "")
    roles = sorted({role.strip() for role in roles_header.split(",") if role.strip()})
    return UserContext(user_id=user_id, roles=roles, display_name=display_name)


async def require_admin(request: Request) -> UserContext:
    """Dependency that ensures the authenticated user has administrative privileges."""
    user = await get_user_context(request)
    if "admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin role required",
        )
    return user
