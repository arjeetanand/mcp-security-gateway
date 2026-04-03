from __future__ import annotations

import json
import logging
from dataclasses import asdict
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .auth import UserContext, get_user_context, require_admin
from .config import settings
from .mcp_proxy import build_upstream_headers, call_upstream, canonical_arguments, list_exposed_tools, resolve_tool
from .policy_engine import PolicyEngine
from .storage import Storage


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("mcp-security-gateway")

storage = Storage(settings.database_path)
policy_engine = PolicyEngine()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Manages the application lifecycle, including initial startup logging and database initialization."""
    storage.log_event("startup", None, {"server": settings.server_name})
    yield


app = FastAPI(title="MCP Security Gateway", version="0.1.0", lifespan=lifespan)


def audit(event_type: str, user: UserContext | None, payload: dict[str, Any]) -> None:
    """Logs security-relevant events to both standard output (JSON) and the persistent database."""
    envelope = {
        "event_type": event_type,
        "user_id": user.user_id if user else None,
        "payload": payload,
    }
    logger.info(json.dumps(envelope, sort_keys=True))
    storage.log_event(event_type, user.user_id if user else None, payload)


def rpc_success(rpc_id: Any, result: Any) -> dict[str, Any]:
    """Constructs a standard JSON-RPC 2.0 success response object."""
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def rpc_error(rpc_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
    """Constructs a standard JSON-RPC 2.0 error response object with optional detailed data."""
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    }
    if data is not None:
        payload["error"]["data"] = data
    return payload


def tool_error_result(message: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Formats tool execution errors according to the Model Context Protocol specification."""
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }
    if meta:
        result["_meta"] = meta
    return result


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Provides a simple health check endpoint to verify service availability."""
    return {"status": "ok"}


@app.get("/admin/approvals")
async def list_approvals(_: UserContext = Depends(require_admin)) -> list[dict[str, Any]]:
    """Admin endpoint to retrieve all pending and historical tool approval requests."""
    return [asdict(record) for record in storage.list_approvals()]


@app.post("/admin/approvals/{approval_id}/approve")
async def approve_request(
    approval_id: str,
    request: Request,
    admin: UserContext = Depends(require_admin),
) -> dict[str, Any]:
    """Admin endpoint to approve a specific tool invocation request by ID."""
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    record = storage.update_approval_status(
        approval_id,
        status="approved",
        approver=admin.user_id,
        note=body.get("note"),
    )
    if not record:
        raise HTTPException(status_code=404, detail="approval not found")
    audit("approval_approved", admin, {"approval_id": approval_id, "tool_name": record.tool_name})
    return asdict(record)


@app.post("/admin/approvals/{approval_id}/reject")
async def reject_request(
    approval_id: str,
    request: Request,
    admin: UserContext = Depends(require_admin),
) -> dict[str, Any]:
    """Admin endpoint to reject a specific tool invocation request by ID."""
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    record = storage.update_approval_status(
        approval_id,
        status="rejected",
        approver=admin.user_id,
        note=body.get("note"),
    )
    if not record:
        raise HTTPException(status_code=404, detail="approval not found")
    audit("approval_rejected", admin, {"approval_id": approval_id, "tool_name": record.tool_name})
    return asdict(record)


async def handle_initialize(rpc_id: Any) -> dict[str, Any]:
    """Processes MCP 'initialize' requests to negotiate protocol version and capabilities."""
    result = {
        "protocolVersion": settings.protocol_version,
        "serverInfo": {"name": settings.server_name, "version": "0.1.0"},
        "capabilities": {"tools": {"listChanged": False}},
    }
    return rpc_success(rpc_id, result)


async def handle_tools_list(rpc_id: Any, user: UserContext) -> dict[str, Any]:
    """Aggregates and returns the list of tools permitted for the current user's roles."""
    tools = await list_exposed_tools(user.roles)
    audit("tools_list", user, {"tool_count": len(tools)})
    return rpc_success(rpc_id, {"tools": tools})


async def handle_tools_call(rpc_id: Any, params: dict[str, Any], user: UserContext) -> dict[str, Any]:
    """Enforces security policies and manages the end-to-end execution flow of tool calls."""
    tool_name = params.get("name")
    if not isinstance(tool_name, str):
        return rpc_success(rpc_id, tool_error_result("tool name must be a string"))
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return rpc_success(rpc_id, tool_error_result("tool arguments must be an object"))

    resolved = resolve_tool(tool_name)
    if not resolved:
        return rpc_success(rpc_id, tool_error_result(f"tool not exposed by gateway: {tool_name}"))

    server, policy, upstream_tool_name = resolved
    arguments_json, arguments_hash = canonical_arguments(arguments)
    is_approved = storage.has_active_approval(user.user_id, tool_name, arguments_hash)
    decision_input = {
        "user": {"id": user.user_id, "roles": user.roles},
        "tool_name": tool_name,
        "risk": policy.get("risk", "unknown"),
        "required_roles": policy.get("required_roles", []),
        "requires_approval": policy.get("approval_required", False),
        "is_approved": is_approved,
    }
    decision = await policy_engine.evaluate(decision_input)

    if not decision.get("allow", False):
        reason = decision.get("reason", "policy_denied")
        audit(
            "tool_call_denied",
            user,
            {
                "tool_name": tool_name,
                "reason": reason,
                "arguments": arguments,
            },
        )
        if reason == "approval_required":
            record = storage.ensure_pending_approval(
                user_id=user.user_id,
                tool_name=tool_name,
                arguments_json=arguments_json,
                arguments_hash=arguments_hash,
            )
            return rpc_success(
                rpc_id,
                tool_error_result(
                    f"Approval required for {tool_name}. Use /admin/approvals/{record.approval_id}/approve and retry.",
                    {
                        "approval_id": record.approval_id,
                        "status": record.status,
                        "expires_at": record.expires_at,
                    },
                ),
            )
        return rpc_success(rpc_id, tool_error_result(f"Access denied for {tool_name}: {reason}"))

    upstream_response = await call_upstream(
        server["url"],
        "tools/call",
        {"name": upstream_tool_name, "arguments": arguments},
        rpc_id=rpc_id,
        timeout_seconds=server.get("timeout_seconds", 10),
        headers=build_upstream_headers(server),
    )
    if "error" in upstream_response:
        audit(
            "tool_call_upstream_error",
            user,
            {"tool_name": tool_name, "error": upstream_response["error"]},
        )
        return rpc_error(rpc_id, -32002, "upstream tool call failed", upstream_response["error"])

    audit(
        "tool_call_allowed",
        user,
        {"tool_name": tool_name, "approval_used": is_approved, "arguments": arguments},
    )
    return rpc_success(rpc_id, upstream_response.get("result", {}))


async def dispatch_rpc(message: dict[str, Any], user: UserContext) -> dict[str, Any]:
    """Routes incoming JSON-RPC messages to their appropriate internal sub-handlers."""
    rpc_id = message.get("id")
    method = message.get("method")
    params = message.get("params", {})

    if method == "initialize":
        return await handle_initialize(rpc_id)
    if method == "notifications/initialized":
        return rpc_success(rpc_id, {})
    if method == "tools/list":
        return await handle_tools_list(rpc_id, user)
    if method == "tools/call":
        return await handle_tools_call(rpc_id, params, user)
    return rpc_error(rpc_id, -32601, f"method not supported: {method}")


@app.post("/mcp")
async def mcp_endpoint(request: Request, user: UserContext = Depends(get_user_context)) -> JSONResponse:
    """Main POST entry point for all incoming MCP-compliant protocol communications."""
    body = await request.json()
    if isinstance(body, list):
        responses = [await dispatch_rpc(message, user) for message in body]
        return JSONResponse(responses)
    if not isinstance(body, dict):
        return JSONResponse(rpc_error(None, -32600, "invalid request"), status_code=400)
    response = await dispatch_rpc(body, user)
    return JSONResponse(response)
