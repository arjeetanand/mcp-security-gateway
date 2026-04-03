# MCP Security Gateway

A reference implementation of an **MCP security gateway** designed for secure, role-based control of enterprise agents.

The gateway places an explicit security control plane between an LLM host and upstream MCP servers, enforcing:

- **Tool allowlists**: Only specifically declared tools are visible to the agent.
- **Read/write/admin separation**: Clear risk classification for every tool.
- **Per-tool authorization**: Granular access control based on user identity.
- **Human approval**: Mandatory admin sign-off for high-risk operations.
- **Structured audit logging**: All security decisions are recorded for compliance.

## Architecture

```text
LLM Host / Agent Client
        |
        |  JSON-RPC over HTTP (MCP)
        v
+------------------------------+
| MCP Security Gateway         |
| - tool exposure allowlist    |
| - role-based access control  |
| - approval workflow          |
| - audit events               |
+------------------------------+
        |
        +--> Upstream MCP servers
             - read-only tools
             - write tools
             - destructive tools
```

## Repo Layout

```text
mcp-security-gateway/
├── README.md
├── run_dev.sh           # Unified local development script
├── config/              # Allowlist and risk policy files
├── gateway/             # Security Gateway (FastAPI)
├── sample_server/       # Sample Finance MCP Server (Upstream)
├── scripts/             # Validation and testing scripts
└── data/                # Local SQLite storage
```

## Local Development (Recommended)

This project is optimized for local execution. Use the provided helper script to manage the environment and start all services.

### 1. Setup

Ensure you have Python 3.10+ installed. Create a virtual environment and install dependencies:

```bash
# From the project root
python3 -m venv .venv
source .venv/bin/activate
pip install -r gateway/requirements.txt
```

### 2. Start Services

```bash
./run_dev.sh
```

This starts:
- **Sample MCP Server** on `http://127.0.0.1:18090`
- **Security Gateway** on `http://127.0.0.1:18080`

### 3. Run Smoke Test

In a separate terminal, run the validation script to verify everything is working:

```bash
.venv/bin/python scripts/smoke_test.py http://127.0.0.1:18080
```

The smoke test validates:
1. Protocol initialization
2. Tool discovery filtered by role
3. Successful execution of read-only tools
4. Denial of unauthorized tool access
5. Generation of manual approval requests
6. Administrative approval of pending requests
7. Post-approval success of previously blocked tools

## Security Model

### 1. Allowlist
Only tools declared in `config/tool_policies.json` are exposed. Everything else is hidden from the agent.

### 2. Risk Classification
Tools are classified as `read`, `write`, or `admin` to ensure appropriate guardrails.

### 3. Identity and Roles
The gateway expects user identity and roles via request headers (emulating an identity-aware gateway):
- `X-User-ID`: Unique identifier for the caller.
- `X-Roles`: Comma-separated list of roles (e.g., `reader, writer, admin`).

### 4. Human-in-the-loop Approval
High-risk tools (e.g., `destructive` actions) can be configured to require explicit human approval via the admin API before the gateway will proxy the call.

### 5. Persistent Audit Trail
All decisions are logged to stdout and stored in a local SQLite database for auditing and forensics.

---

## Tool Discovery Process
When `tools/list` is called, the gateway:
1. Fetches tools from all configured upstream servers.
2. Filters tools through the local allowlist.
3. Annotates tools with risk-level metadata.
4. Hides any tool for which the caller lacks the required role.

## Tool Execution Process
When `tools/call` is called, the gateway:
1. Resolves the composite tool name (e.g., `finance.purge_order`).
2. Checks for an active, unexpired approval record.
3. Evaluates the tool policy (Roles + Risk + Approvals).
4. Either denies the call, requests approval, or proxies it to the source server.

## Next Extensions

- Multi-server tool federation
- Per-tenant policy bundles
- Semantic risk scoring
- Data classification tags
- JIT approvals with expiration windows
- Approval UI and chat notifications
- Langfuse or OpenTelemetry trace correlation
