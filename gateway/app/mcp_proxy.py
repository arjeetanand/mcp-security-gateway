from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from .config import load_tool_policies, load_upstreams


def build_upstream_headers(server: dict[str, Any]) -> dict[str, str]:
    headers = {str(k): str(v) for k, v in server.get("headers", {}).items()}
    bearer_token_file = server.get("bearer_token_file")
    if bearer_token_file:
        token = Path(bearer_token_file).read_text(encoding="utf-8").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


async def call_upstream(url: str, method: str, params: dict[str, Any], rpc_id: int | str | None = 1, timeout_seconds: int = 10, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request_body = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": method,
        "params": params,
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(url, json=request_body, headers=headers or {})
        response.raise_for_status()
        return response.json()


async def list_exposed_tools(user_roles: list[str]) -> list[dict[str, Any]]:
    tool_policies = load_tool_policies()
    exposed_tools: list[dict[str, Any]] = []
    for server in load_upstreams():
        upstream_payload = await call_upstream(
            server["url"],
            "tools/list",
            {},
            timeout_seconds=server.get("timeout_seconds", 10),
            headers=build_upstream_headers(server),
        )
        for tool in upstream_payload.get("result", {}).get("tools", []):
            composite_name = f"{server['alias']}.{tool['name']}"
            policy = tool_policies.get(composite_name)
            if not policy or not policy.get("exposed", False):
                continue
            required_roles = policy.get("required_roles", [])
            if required_roles and not any(role in user_roles for role in required_roles):
                continue
            exposed = dict(tool)
            exposed["name"] = composite_name
            exposed["description"] = f"{tool.get('description', '').rstrip()}{policy.get('description_suffix', '')}".strip()
            annotations = dict(tool.get("annotations", {}))
            annotations.update(policy.get("annotations", {}))
            exposed["annotations"] = annotations
            metadata = dict(tool.get("_meta", {}))
            metadata["gateway"] = {
                "source_server": server["alias"],
                "risk": policy.get("risk", "unknown"),
                "approval_required": policy.get("approval_required", False),
                "required_roles": required_roles,
            }
            exposed["_meta"] = metadata
            exposed_tools.append(exposed)
    return exposed_tools


def resolve_tool(tool_name: str) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    if not isinstance(tool_name, str) or "." not in tool_name:
        return None
    tool_policies = load_tool_policies()
    policy = tool_policies.get(tool_name)
    if not policy or not policy.get("exposed", False):
        return None
    alias, upstream_tool_name = tool_name.split(".", 1)
    for server in load_upstreams():
        if server["alias"] == alias:
            return server, policy, upstream_tool_name
    return None


def canonical_arguments(arguments: dict[str, Any]) -> tuple[str, str]:
    import hashlib

    payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return payload, digest
