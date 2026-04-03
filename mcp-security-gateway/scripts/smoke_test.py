from __future__ import annotations

import json
import sys
from typing import Any

import httpx


BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"


def rpc(client: httpx.Client, headers: dict[str, str], method: str, params: dict[str, Any] | None = None, rpc_id: int = 1) -> dict[str, Any]:
    response = client.post(
        f"{BASE_URL}/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}},
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    with httpx.Client(timeout=10.0) as client:
        reader_headers = {"X-User-ID": "alice", "X-Roles": "reader"}
        writer_headers = {"X-User-ID": "bob", "X-Roles": "writer"}
        admin_headers = {"X-User-ID": "carol", "X-Roles": "admin"}

        print("1) initialize")
        print(json.dumps(rpc(client, reader_headers, "initialize"), indent=2))

        print("\n2) list tools for reader")
        print(json.dumps(rpc(client, reader_headers, "tools/list", rpc_id=2), indent=2))

        print("\n3) read-only tool succeeds")
        print(
            json.dumps(
                rpc(
                    client,
                    reader_headers,
                    "tools/call",
                    {"name": "finance.get_customer_balance", "arguments": {"customer_id": "CUST-001"}},
                    rpc_id=3,
                ),
                indent=2,
            )
        )

        print("\n4) writer tool as reader is denied")
        print(
            json.dumps(
                rpc(
                    client,
                    reader_headers,
                    "tools/call",
                    {
                        "name": "finance.update_credit_limit",
                        "arguments": {"customer_id": "CUST-001", "new_limit": 30000},
                    },
                    rpc_id=4,
                ),
                indent=2,
            )
        )

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
        approval_id = pending["result"]["_meta"]["approval_id"]

        print("\n6) admin approves")
        approval_response = client.post(
            f"{BASE_URL}/admin/approvals/{approval_id}/approve",
            headers=admin_headers,
            json={"note": "approved from smoke test"},
        )
        approval_response.raise_for_status()
        print(json.dumps(approval_response.json(), indent=2))

        print("\n7) writer tool after approval succeeds")
        print(
            json.dumps(
                rpc(
                    client,
                    writer_headers,
                    "tools/call",
                    {
                        "name": "finance.update_credit_limit",
                        "arguments": {"customer_id": "CUST-001", "new_limit": 30000},
                    },
                    rpc_id=7,
                ),
                indent=2,
            )
        )

        print("\n8) admin-only destructive tool is hidden from writer and only callable by admin with approval")
        print(json.dumps(rpc(client, admin_headers, "tools/list", rpc_id=8), indent=2))


if __name__ == "__main__":
    main()
