from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Settings:
    upstream_servers_file: str = os.getenv("UPSTREAM_SERVERS_FILE", "/app/config/upstreams.json")
    tool_policy_file: str = os.getenv("TOOL_POLICY_FILE", "/app/config/tool_policies.json")
    database_path: str = os.getenv("DATABASE_PATH", "/app/data/gateway.db")
    opa_url: str = os.getenv("OPA_URL", "")
    enable_fallback_policy_engine: bool = os.getenv(
        "ENABLE_FALLBACK_POLICY_ENGINE", "true"
    ).lower() in {"1", "true", "yes"}
    server_name: str = os.getenv("SERVER_NAME", "mcp-security-gateway")
    protocol_version: str = os.getenv("MCP_PROTOCOL_VERSION", "2025-06-18")


settings = Settings()


def load_json_file(path: str) -> dict[str, Any]:
    payload = Path(path).read_text(encoding="utf-8")
    return json.loads(payload)


def load_upstreams() -> list[dict[str, Any]]:
    return load_json_file(settings.upstream_servers_file).get("servers", [])


def load_tool_policies() -> dict[str, Any]:
    return load_json_file(settings.tool_policy_file).get("tools", {})
