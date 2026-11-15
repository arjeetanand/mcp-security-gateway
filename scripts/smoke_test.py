from __future__ import annotations

import json
import sys
from typing import Any
from uuid import uuid4

import httpx

from generate_test_jwt import mint


BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4038"


def rpc(client: httpx.Client, headers: dict[str, str], method: str, params: dict[str, Any] | None = None, rpc_id: int = 1) -> dict[str, Any]:
    """Helper function that sends a JSON-RPC request to the gateway at a specified URL."""
    response = client.post(
        f"{BASE_URL}/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}},
    )
    response.raise_for_status()
    return response.json()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"Smoke check failed: {message}")


def main() -> None:
    """Entry point for the smoke test script that executes a sequence of MCP operations."""
    with httpx.Client(timeout=10.0) as client:
        reader_headers = {"Authorization": f"Bearer {mint('alice', ['reader'])}"}
        writer_headers = {"Authorization": f"Bearer {mint(f'smoke-writer-{uuid4().hex}', ['writer'])}"}
        admin_headers = {"Authorization": f"Bearer {mint('carol', ['admin'])}"}

        print("1) initialize")
        initialized = rpc(client, reader_headers, "initialize")
        print(json.dumps(initialized, indent=2))
        require(bool(initialized.get("result", {}).get("protocolVersion")), "initialization")

        print("\n2) list tools for reader")
        reader_tools = rpc(client, reader_headers, "tools/list", rpc_id=2)
        print(json.dumps(reader_tools, indent=2))
        names = {tool["name"] for tool in reader_tools["result"]["tools"]}
        require("finance.get_customer_balance" in names and not {"finance.update_credit_limit", "finance.purge_order"} & names,
                "reader tool visibility")

        print("\n3) read-only tool succeeds")
        read = rpc(
            client, reader_headers, "tools/call",
            {"name": "finance.get_customer_balance", "arguments": {"customer_id": "CUST-001"}}, rpc_id=3,
        )
        print(json.dumps(read, indent=2))
        require(read["result"].get("isError") is False, "reader tool call")

        print("\n4) writer tool as reader is denied")
        denied = rpc(
            client, reader_headers, "tools/call",
            {"name": "finance.update_credit_limit", "arguments": {"customer_id": "CUST-001", "new_limit": 30000}}, rpc_id=4,
        )
        print(json.dumps(denied, indent=2))
        require(denied["result"].get("isError") is True, "reader write denial")

        print("\n5) writer tool as writer requests approval")
        pending = rpc(
            client,
            writer_headers,
            "tools/call",
            {
                "name": "finance.update_credit_limit",
                "arguments": {"customer_id": "CUST-001", "new_limit": 30000},
            },
            rpc_id=5,
        )
        print(json.dumps(pending, indent=2))
        require(pending["result"].get("_meta", {}).get("status") == "pending", "approval request")
        approval_id = pending["result"]["_meta"]["approval_id"]

        print("\n6) admin approves")
        approval_response = client.post(
            f"{BASE_URL}/admin/approvals/{approval_id}/approve",
            headers=admin_headers,
            json={"note": "approved from smoke test"},
        )
        approval_response.raise_for_status()
        print(json.dumps(approval_response.json(), indent=2))
        require(approval_response.json().get("status") == "approved", "admin approval")

        print("\n7) writer tool after approval succeeds")
        approved = rpc(
            client, writer_headers, "tools/call",
            {"name": "finance.update_credit_limit", "arguments": {"customer_id": "CUST-001", "new_limit": 30000}}, rpc_id=7,
        )
        print(json.dumps(approved, indent=2))
        require(approved["result"].get("isError") is False, "approved writer tool call")

        print("\n8) admin can discover the restricted tool")
        admin_tools = rpc(client, admin_headers, "tools/list", rpc_id=8)
        print(json.dumps(admin_tools, indent=2))
        require("finance.purge_order" in {tool["name"] for tool in admin_tools["result"]["tools"]}, "admin tool visibility")


if __name__ == "__main__":
    main()
