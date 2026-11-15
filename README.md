# MCP Security Gateway

A reference implementation of an **MCP security gateway** designed for secure, role-based control of enterprise agents.

The gateway places an explicit security control plane between an LLM host and upstream MCP servers, enforcing:

- **Tool allowlists**: Only specifically declared tools are visible to the agent.
- **Read/write/admin separation**: Clear risk classification for every tool.
- **Per-tool authorization**: Granular access control based on user identity.
- **Human approval**: Mandatory admin sign-off for high-risk operations.
- **Structured audit logging**: Selected tool, discovery, and approval events are recorded for review.

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
├── run.sh               # Local development launcher (run_dev.sh is an alias)
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
./run.sh
```

This starts a loopback-only sample server and gateway using generated local test
credentials and a disposable database under `.run/`. The stable ports are:

| Instance | Gateway | Sample server |
| --- | --- | --- |
| Main: `./run.sh` | 4038 | 4039 |
| Test: `./run.sh 5038` | 5038 | 5039 |
| Test: `./run.sh 6038` | 6038 | 6039 |

Running the same command again restarts only processes whose recorded marker,
working directory, and listener prove they belong to this checkout; an unknown
listener causes a conflict instead of being stopped. `./run.sh stop` stops the
owned main instance, and `./run.sh stop 5038` stops the first test instance.
The local SQLite file remains in `.run/` across restarts. Set `MCP_DEMO_PYTHON`
to an existing compatible interpreter if the project has no `.venv`. The
launcher uses `lsof` to verify ownership and must be able to inspect both ports.

The launcher deliberately ignores `.env` and creates a fresh development JWT
signing key on every start. The owner-readable key is stored in `.run/4038.secret`
for the main instance; never use it or the sample dataset in production.

### 3. Run Smoke Test

In a separate terminal, run the validation script to verify everything is working:

```bash
JWT_SECRET="$(cat .run/4038.secret)" JWT_ALGORITHM=HS256 JWT_AUDIENCE='' \
  JWT_ROLES_CLAIM='https://mcp-gateway/roles' \
  "${MCP_DEMO_PYTHON:-.venv/bin/python}" scripts/smoke_test.py http://127.0.0.1:4038
```

The smoke test validates:
1. Protocol initialization
2. Tool discovery filtered by role
3. Successful execution of read-only tools
4. Denial of unauthorized tool access
5. Generation of manual approval requests
6. Administrative approval of pending requests
7. Post-approval success of previously blocked tools

Use the matching secret file and gateway port for either test instance. Each
smoke run uses a new synthetic writer identity so it can request a fresh
approval without deleting earlier records. The script is for the local HS256
demo; it requires the same signing secret as the gateway.

## Security Model

### 1. Allowlist
Only tools declared in `config/tool_policies.json` are exposed. Everything else is hidden from the agent.

### 2. Risk Classification
Tools are classified as `read`, `write`, or `admin` to ensure appropriate guardrails.

### 3. Identity and Roles
The gateway verifies a signed bearer JWT. Its `sub` claim identifies the user,
and the configured `JWT_ROLES_CLAIM` supplies roles such as `reader`, `writer`,
and `admin`. Signature, expiry, issued-at, and optional audience are validated.

### 4. Human-in-the-loop Approval
High-risk tools (e.g., `destructive` actions) can be configured to require explicit human approval via the admin API before the gateway will proxy the call.

### 5. Persistent Audit Trail
Selected tool-list, policy decision, upstream error, and approval events are
logged and stored in SQLite. Authentication failures and some malformed or
unlisted tool requests return before an audit event is recorded.

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
