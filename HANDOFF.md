# Local demo handoff

The former smoke script sent obsolete identity headers and failed with HTTP 401.
It now mints the existing local JWT roles, verifies each step, and uses a fresh
synthetic writer identity for repeat runs. `run.sh` starts the gateway and sample
server on loopback, maintains separate ownership markers, generates a new local
test key, and keeps the disposable SQLite file under `.run/`. `run_dev.sh` is a
compatibility alias. README describes the authentication and audit scope.

Verification on November 15, 2026:

- Seven in-process unittest checks passed, including the full smoke workflow
  twice, missing-secret/error behavior, and owned-process checks.
- The earlier in-process gateway evaluation passed 50/50 synthetic scenarios.
  Its copied harness and results are in ignored `tmp/` in this checkout.
- Local-only startup and ownership-checked restart passed on ports 4038/4039;
  the smoke workflow passed before and after restart, including consecutive
  runs against the same database. Stop and restart also passed.
- A separately owned loopback listener on test port 5038 was left running when
  the launcher correctly refused the port conflict.
- Python compilation and shell syntax checks passed. Tests used the existing
  `/Users/arjeetanand/projects/briefly-voice/.venv/bin/python`; its dependency
  versions may differ from this repository's pins.

Checkout: `codex/mcp-demo-jwt-fix`, based on `5e99d84`. Task commit message:
`fix: restore authenticated local smoke workflow`; inspect the current commit
with `git log -1`. No changes were pushed or merged.

Run with `./run.sh` after preparing `.venv`, or set `MCP_DEMO_PYTHON` to an
existing compatible interpreter. See README for smoke, stop, and test ports.
The verified main gateway is `http://127.0.0.1:4038`. Local keys, databases,
logs, and ownership markers are development-only and remain ignored by Git.

Remaining limits: tests do not certify production security or every possible
audit path. The sample server and demo credentials are not production systems.
