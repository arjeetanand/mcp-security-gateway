from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Sample Finance MCP Server", version="0.1.0")


CUSTOMERS = {
    "CUST-001": {"name": "Acme Manufacturing", "balance": 12450.25, "credit_limit": 20000.0},
    "CUST-002": {"name": "Nova Retail", "balance": 8430.50, "credit_limit": 15000.0},
    "CUST-003": {"name": "BlueSky Logistics", "balance": 2250.00, "credit_limit": 10000.0},
}

ORDERS = [
    {"order_id": "ORD-1001", "customer_id": "CUST-001", "amount": 810.0, "status": "OPEN"},
    {"order_id": "ORD-1002", "customer_id": "CUST-002", "amount": 240.5, "status": "OPEN"},
    {"order_id": "ORD-1003", "customer_id": "CUST-001", "amount": 90.0, "status": "CLOSED"},
    {"order_id": "ORD-1004", "customer_id": "CUST-003", "amount": 1200.0, "status": "OPEN"},
]


def rpc_success(rpc_id: Any, result: Any) -> dict[str, Any]:
    """Constructs a standard JSON-RPC 2.0 success response object."""
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def rpc_error(rpc_id: Any, code: int, message: str) -> dict[str, Any]:
    """Constructs a standard JSON-RPC 2.0 error response object."""
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


TOOLS = [
    {
        "name": "get_orders",
        "description": "Return recent orders, optionally filtered by customer id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Optional customer identifier."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    },
    {
        "name": "get_customer_balance",
        "description": "Look up a customer balance and current credit limit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
            },
            "required": ["customer_id"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    },
    {
        "name": "update_credit_limit",
        "description": "Update the approved credit limit for a customer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "new_limit": {"type": "number", "minimum": 0},
            },
            "required": ["customer_id", "new_limit"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    },
    {
        "name": "purge_order",
        "description": "Delete an order from the operational dataset.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": False,
        },
    },
]


def text_result(text: str) -> dict[str, Any]:
    """Wraps a string into the standard MCP text content format."""
    return {"content": [{"type": "text", "text": text}], "isError": False}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Provides a simple health check endpoint to verify service availability."""
    return {"status": "ok"}


@app.post("/mcp")
async def mcp(request: Request) -> JSONResponse:
    """Main POST entry point for the sample server's MCP protocol communications."""
    payload = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse(rpc_error(None, -32600, "invalid request"), status_code=400)

    rpc_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params", {})

    if method == "initialize":
        result = {
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "sample-finance-server", "version": "0.1.0"},
            "capabilities": {"tools": {"listChanged": False}},
        }
        return JSONResponse(rpc_success(rpc_id, result))

    if method == "tools/list":
        return JSONResponse(rpc_success(rpc_id, {"tools": deepcopy(TOOLS)}))

    if method != "tools/call":
        return JSONResponse(rpc_error(rpc_id, -32601, f"unsupported method: {method}"))

    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if tool_name == "get_orders":
        customer_id = arguments.get("customer_id")
        limit = int(arguments.get("limit", 5))
        rows = [row for row in ORDERS if not customer_id or row["customer_id"] == customer_id][:limit]
        return JSONResponse(rpc_success(rpc_id, text_result(str(rows))))

    if tool_name == "get_customer_balance":
        customer_id = arguments.get("customer_id")
        customer = CUSTOMERS.get(customer_id)
        if not customer:
            return JSONResponse(rpc_success(rpc_id, {"content": [{"type": "text", "text": f"Unknown customer: {customer_id}"}], "isError": True}))
        result = {"customer_id": customer_id, **customer}
        return JSONResponse(rpc_success(rpc_id, text_result(str(result))))

    if tool_name == "update_credit_limit":
        customer_id = arguments.get("customer_id")
        customer = CUSTOMERS.get(customer_id)
        if not customer:
            return JSONResponse(rpc_success(rpc_id, {"content": [{"type": "text", "text": f"Unknown customer: {customer_id}"}], "isError": True}))
        before = customer["credit_limit"]
        customer["credit_limit"] = float(arguments.get("new_limit"))
        result = {
            "customer_id": customer_id,
            "previous_credit_limit": before,
            "new_credit_limit": customer["credit_limit"],
        }
        return JSONResponse(rpc_success(rpc_id, text_result(str(result))))

    if tool_name == "purge_order":
        order_id = arguments.get("order_id")
        index = next((i for i, item in enumerate(ORDERS) if item["order_id"] == order_id), None)
        if index is None:
            return JSONResponse(rpc_success(rpc_id, {"content": [{"type": "text", "text": f"Unknown order: {order_id}"}], "isError": True}))
        deleted = ORDERS.pop(index)
        return JSONResponse(rpc_success(rpc_id, text_result(str({"deleted": deleted}))))

    return JSONResponse(rpc_error(rpc_id, -32601, f"unknown tool: {tool_name}"))
