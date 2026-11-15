"""Exercise the smoke workflow against real in-process gateway and sample apps."""
import asyncio
import contextlib
import io
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
os.environ.update({
    "JWT_SECRET": "synthetic-test-key-for-in-process-gateway-tests-only",
    "JWT_ALGORITHM": "HS256",
    "JWT_ROLES_CLAIM": "roles",
    "JWT_AUDIENCE": "",
    "UPSTREAM_SERVERS_FILE": str(ROOT / "config/upstreams.local.json"),
    "TOOL_POLICY_FILE": str(ROOT / "config/tool_policies.json"),
    "DATABASE_PATH": ":memory:",
})
sys.path.insert(0, str(ROOT / "scripts"))

with patch.dict(sys.modules, {"dotenv": types.SimpleNamespace(load_dotenv=lambda **kwargs: None)}):
    from gateway.app import main as gateway, mcp_proxy
    from sample_server import app as sample
    import smoke_test
    import generate_test_jwt

smoke_test.BASE_URL = "http://gateway"


async def sample_upstream(url, method, params, rpc_id=1, timeout_seconds=10, headers=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=sample.app), base_url="http://sample") as client:
        response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params})
        response.raise_for_status()
        return response.json()


class InProcessClient:
    def __init__(self, *args, **kwargs):
        self.responses = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, **kwargs):
        async def request():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app)) as client:
                return await client.post(url, **kwargs)
        response = asyncio.run(request())
        self.responses.append(response)
        return response


class SmokeWorkflowTests(unittest.TestCase):
    def test_unexpected_initialize_response_fails_the_smoke_test(self):
        with patch.object(smoke_test.httpx, "Client", return_value=InProcessClient()), \
             patch.object(smoke_test, "rpc", return_value={"result": {}}), \
             contextlib.redirect_stdout(io.StringIO()), \
             self.assertRaisesRegex(RuntimeError, "initialization"):
            smoke_test.main()

    def test_smoke_requires_a_signing_secret(self):
        with patch.object(generate_test_jwt, "SECRET", ""), \
             patch.object(smoke_test.httpx, "Client", return_value=InProcessClient()), \
             self.assertRaisesRegex(SystemExit, "JWT_SECRET is not set"):
            smoke_test.main()

    def test_role_based_workflow_can_run_twice(self):
        with patch.object(gateway, "call_upstream", sample_upstream), patch.object(mcp_proxy, "call_upstream", sample_upstream):
            for _ in range(2):
                client = InProcessClient()
                with patch.object(smoke_test.httpx, "Client", return_value=client), contextlib.redirect_stdout(io.StringIO()):
                    smoke_test.main()
                self.assertEqual(len(client.responses), 8)
                self.assertTrue(all(response.status_code == 200 for response in client.responses))
                responses = [response.json() for response in client.responses]
                visible = {tool["name"] for tool in responses[1]["result"]["tools"]}
                self.assertEqual(visible, {"finance.get_orders", "finance.get_customer_balance"})
                self.assertFalse(responses[2]["result"]["isError"])
                self.assertTrue(responses[3]["result"]["isError"])
                self.assertEqual(responses[4]["result"]["_meta"]["status"], "pending")
                self.assertEqual(responses[5]["status"], "approved")
                self.assertFalse(responses[6]["result"]["isError"])
                self.assertIn("finance.purge_order", {tool["name"] for tool in responses[7]["result"]["tools"]})


if __name__ == "__main__":
    unittest.main()
