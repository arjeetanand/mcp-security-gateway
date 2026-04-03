from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Settings:
    """Application settings, loaded from environment variables where applicable."""
    upstream_servers_file: str = os.getenv("UPSTREAM_SERVERS_FILE", "/app/config/upstreams.json")
    tool_policy_file: str = os.getenv("TOOL_POLICY_FILE", "/app/config/tool_policies.json")
    database_path: str = os.getenv("DATABASE_PATH", "/app/data/gateway.db")
    server_name: str = os.getenv("SERVER_NAME", "mcp-security-gateway")
    protocol_version: str = os.getenv("MCP_PROTOCOL_VERSION", "2025-06-18")


settings = Settings()


def load_json_file(path: str) -> dict[str, Any]:
    """Loads and parses a JSON file from the filesystem with UTF-8 encoding."""
    payload = Path(path).read_text(encoding="utf-8")
    return json.loads(payload)


def load_upstreams() -> list[dict[str, Any]]:
    """Retrieves the list of configured upstream MCP servers from the settings file."""
    return load_json_file(settings.upstream_servers_file).get("servers", [])


def load_tool_policies() -> dict[str, Any]:
    """Retrieves the tool-specific security policies from the settings file."""
    return load_json_file(settings.tool_policy_file).get("tools", {})
