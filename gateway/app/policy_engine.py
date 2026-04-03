from __future__ import annotations

from typing import Any

class PolicyEngine:
    """Evaluates relative risk and role-based access for tool invocation requests."""
    def __init__(self) -> None:
        """Initializes the PolicyEngine for local role and approval validation."""
        pass

    async def evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Evaluates whether a tool call is permitted based on user roles and active approvals."""
        required_roles = payload.get("required_roles", [])
        user_roles = payload.get("user", {}).get("roles", [])
        
        # Check if the user has any of the roles required by the tool policy
        has_role = not required_roles or any(role in user_roles for role in required_roles)
        if not has_role:
            return {"allow": False, "reason": "missing_required_role"}
            
        # Check if administrative approval is required and whether it has been granted
        if payload.get("requires_approval") and not payload.get("is_approved"):
            return {"allow": False, "reason": "approval_required"}
            
        return {"allow": True, "reason": "allowed"}
