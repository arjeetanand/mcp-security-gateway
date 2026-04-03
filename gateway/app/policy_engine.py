from __future__ import annotations

from typing import Any

import httpx

from .config import settings


class PolicyEngine:
    def __init__(self, opa_url: str) -> None:
        self.opa_url = opa_url

    async def evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Submits tool call context to OPA for authorization or uses fallback logic if OPA is unavailable."""
        if self.opa_url:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.post(self.opa_url, json={"input": payload})
                    response.raise_for_status()
                    result = response.json().get("result")
                    if isinstance(result, dict):
                        return result
            except Exception as exc:  # pragma: no cover - fallback path used in local tests
                if not settings.enable_fallback_policy_engine:
                    return {"allow": False, "reason": f"policy_engine_unavailable:{exc.__class__.__name__}"}

        return self._fallback(payload)

    @staticmethod
    def _fallback(payload: dict[str, Any]) -> dict[str, Any]:
        """Implements role-based access control and approval checks when the external policy engine is bypassed."""
        required_roles = payload.get("required_roles", [])
        user_roles = payload.get("user", {}).get("roles", [])
        has_role = not required_roles or any(role in user_roles for role in required_roles)
        if not has_role:
            return {"allow": False, "reason": "missing_required_role"}
        if payload.get("requires_approval") and not payload.get("is_approved"):
            return {"allow": False, "reason": "approval_required"}
        return {"allow": True, "reason": "allowed"}
