# MCP Security Gateway on OCI

A production-style reference implementation of an **MCP security gateway** for enterprise agents.

It places an explicit security control plane between an LLM host and upstream MCP servers.
The gateway enforces:

- **Tool allowlists**
- **Read/write/admin separation**
- **Per-tool authorization**
- **Human approval for risky actions**
- **Structured audit logging**
- **OCI-ready deployment manifests**
- **Open source policy-as-code with OPA**

## Architecture

```text
LLM Host / Agent Client
        |
        |  JSON-RPC over HTTP (MCP)
        v
+------------------------------+
| MCP Security Gateway         |
| - tool exposure allowlist    |
| - role checks                |
| - approval workflow          |
| - audit events               |
+------------------------------+
        |                |
        |                +--> OPA (policy decision API)
        |
        +--> Upstream MCP servers
             - read-only tools
             - write tools
             - destructive tools
```

## What is included

- `gateway/` FastAPI-based MCP-compatible gateway
- `sample_server/` a finance-flavored upstream MCP server for demos
- `policy/` OPA Rego policy
- `config/` allowlist and risk policy files
- `scripts/smoke_test.py` end-to-end validation script
- `oci/kubernetes/` OKE manifests, CSI-based Vault mount, NetworkPolicy, and services
- `compose.yaml` local multi-container stack for Docker users

## Repo layout

```text
mcp-security-gateway/
├── README.md
├── compose.yaml
├── config/
│   ├── tool_policies.json
│   ├── upstreams.json
│   └── upstreams.local.json
├── gateway/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
├── oci/
│   └── kubernetes/
├── policy/
│   └── gateway.rego
├── sample_server/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
└── scripts/
    └── smoke_test.py
```

## Security model

### 1. Allowlist
Only tools declared in `config/tool_policies.json` are exposed to the client.
Everything else is invisible.

### 2. Read/write/admin risk separation
Each exposed tool is classified as `read`, `write`, or `admin`.

### 3. Role checks
The gateway expects identity attributes from upstream auth infrastructure.
For the demo, those arrive in request headers:

- `X-User-ID`
- `X-Roles`

In production on OCI, put the gateway behind your identity-aware edge and forward trusted claims.

### 4. Approval workflow
Risky tools can require human approval even when the caller already has the correct role.
The approval record is stored in SQLite for the demo and can be swapped for PostgreSQL.

### 5. Audit trail
All list/call/approval decisions emit structured audit events to stdout and to the local database.
On OKE, container logs can be collected by OCI logging pipelines.

### 6. Secret handling
The OKE manifests mount OCI Vault-backed secrets using the Secrets Store CSI driver provider.
That lets you inject upstream MCP bearer tokens without baking them into images.

## Local run without Docker (Recommended)

This is the quickest path for development. We provide a helper script that manages the environment and starts both the sample server and the gateway.

### 1. Setup

First, ensure you have Python 3.10+ installed. Then create a virtual environment and install dependencies:

```bash
# From the mcp-security-gateway directory
python3 -m venv .venv
source .venv/bin/activate
pip install -r gateway/requirements.txt
```

### 2. Start Services

Run the unified development script:

```bash
./run_dev.sh
```

This starts:
- **Sample MCP Server** on `http://127.0.0.1:18090`
- **Security Gateway** on `http://127.0.0.1:18080` (using fallback policy engine)

### 3. Run Smoke Test

In a separate terminal, run the validation script:

```bash
.venv/bin/python scripts/smoke_test.py http://127.0.0.1:18080
```

The smoke test validates:
- initialize
- tool discovery
- read-only call success
- role-based denial
- approval-required response
- admin approval
- successful retry after approval

### Troubleshooting

If the smoke test fails due to existing approvals in the database, you can reset the local state:

```bash
rm data/gateway.local.db
```

## Local run with Docker Compose

```bash
docker compose up --build
python scripts/smoke_test.py http://127.0.0.1:8080
```

This path uses the bundled OPA policy service instead of the fallback evaluator.

## How the gateway works

### Tool discovery
When the client calls `tools/list`, the gateway:

1. Fetches upstream tools from configured MCP servers
2. Filters them through the local allowlist
3. Overwrites any risky metadata with gateway-owned annotations
4. Hides tools the caller is not allowed to see

### Tool execution
When the client calls `tools/call`, the gateway:

1. Resolves the composite tool name, such as `finance.update_credit_limit`
2. Computes a deterministic hash of the arguments
3. Checks whether an active approval already exists
4. Calls OPA with user roles and tool policy
5. Either denies, creates an approval request, or proxies the call upstream
6. Logs the outcome to the audit trail

## Demo identities

For local testing, emulate users with headers:

- Reader: `X-User-ID: alice`, `X-Roles: reader`
- Writer: `X-User-ID: bob`, `X-Roles: writer`
- Admin: `X-User-ID: carol`, `X-Roles: admin`

## OCI deployment plan

## 1. Build and push images to OCIR

Replace the placeholders first.

```bash
export REGION_KEY=iad
export TENANCY_NAMESPACE=<your-tenancy-namespace>
export TAG=$(date +%Y%m%d%H%M%S)

docker build -t ${REGION_KEY}.ocir.io/${TENANCY_NAMESPACE}/mcp-security-gateway:${TAG} gateway
docker build -t ${REGION_KEY}.ocir.io/${TENANCY_NAMESPACE}/sample-mcp-server:${TAG} sample_server

docker push ${REGION_KEY}.ocir.io/${TENANCY_NAMESPACE}/mcp-security-gateway:${TAG}
docker push ${REGION_KEY}.ocir.io/${TENANCY_NAMESPACE}/sample-mcp-server:${TAG}
```

Update the image references in:

- `oci/kubernetes/gateway-deployment.yaml`
- `oci/kubernetes/sample-server-deployment.yaml`

## 2. Create the OKE cluster

Create an OKE cluster and make sure `kubectl` points to it.

## 3. Install the OCI Secrets Store CSI driver provider

```bash
helm repo add oci-provider https://oracle.github.io/oci-secrets-store-csi-driver-provider/charts
helm install oci-provider oci-provider/oci-secrets-store-csi-driver-provider --namespace kube-system
```

If you use instance principals, keep `authType: instance` in `secret-provider-class.yaml`.
If you use workload identity, switch the SecretProviderClass and IAM policy accordingly.

## 4. Create the OCI Vault secrets

Create secrets such as:

- `gateway-upstream-token`
- `gateway-admin-token`

Then replace the `vaultId` placeholders in `oci/kubernetes/secret-provider-class.yaml`.

## 5. Deploy to OKE

```bash
kubectl apply -k oci/kubernetes
```

## 6. Validate the deployment

```bash
kubectl get pods -n mcp-security-gateway
kubectl get svc -n mcp-security-gateway
kubectl logs deploy/mcp-security-gateway -n mcp-security-gateway
```

## 7. Call the public service

Find the load balancer IP and send MCP requests to the gateway service.

## OCI hardening ideas

For a production blog/demo, add these next:

- Put the gateway behind **OCI API Gateway** for JWT validation
- Send audit events to **OCI Logging / Log Analytics**
- Store approvals in **Autonomous Database** or **PostgreSQL**
- Replace the demo header auth with **trusted identity claims**
- Use **OCI DevOps** to build and deploy to OKE
- Sign images and enforce signed image policies on OKE
- Use separate namespaces or node pools for high-risk tool adapters

## Suggested blog angles

### Why this gateway exists
MCP tool annotations are useful hints for UX, but they are not enforcement.
A real enterprise deployment needs deterministic policy and approval checks outside the model.

### What the demo proves
You can keep the flexibility of MCP while adding a real control plane:

- expose only approved tools
- separate read paths from write paths
- require human approval for sensitive mutations
- keep logs for every decision
- deploy the whole pattern on OCI with open source components

## Limitations of the demo

- The sample identity model uses headers for developer convenience
- SQLite is fine for demos but not for multi-replica shared state
- The sample upstream server is intentionally simple
- The current manifests use a public load balancer for simplicity

## Next extensions

- Multi-server tool federation
- per-tenant policy bundles
- semantic risk scoring
- data classification tags
- JIT approvals with expiration windows
- approval UI and chat notifications
- Langfuse or OpenTelemetry trace correlation

