# Local demo handoff

The former smoke script sent obsolete identity headers and failed with HTTP 401.
It now mints the existing local JWT roles, verifies each step, and uses a fresh
synthetic writer identity for repeat runs. `run.sh` starts the gateway and sample
server on loopback, maintains separate ownership markers, generates a new local
test key, and keeps the disposable SQLite file under `.run/`. `run_dev.sh` is a
compatibility alias. README describes the authentication and audit scope.

Verification on November 15, 2026:

- Twelve in-process unittest checks passed, including the full smoke workflow
  twice, missing-secret/error behavior, interruption, cleanup timeout, and
  owned-process and failed-state-write checks.
- The earlier in-process gateway evaluation passed 50/50 synthetic scenarios.
  Its copied harness and results are in ignored `tmp/` in this checkout.
- Local-only startup and ownership-checked restart passed on ports 4038/4039;
  the smoke workflow passed before and after restart, including consecutive
  runs against the same database. Stop and restart also passed.
- A separately owned loopback listener on test port 5038 was left running when
  the launcher correctly refused the port conflict.
- A SIGTERM during sample-server startup on the isolated 6038/6039 test pair
  left a recorded child, stopped it, cleared its confirmed-stopped entry, and
  allowed a subsequent restart and smoke check. The test instance was stopped.
- One early mocked test overwrote the demo ownership state. It was restored only
  after independently verifying both listeners, working directories, and unique
  marker descriptors; no process was signaled during recovery. Launcher tests
  now use temporary state, and the final suite left the live state unchanged.
- Python compilation and shell syntax checks passed. Tests used the existing
  `/Users/arjeetanand/projects/briefly-voice/.venv/bin/python`; its dependency
  versions may differ from this repository's pins.

Checkout: `codex/mcp-demo-jwt-fix`, based on `5e99d84`. The first task commit is
`3239ec8`; the follow-up commit is `fix: preserve ownership during interrupted
startup`. Inspect the current commit with `git log -1`. No changes were pushed
or merged.

Run with `./run.sh` after preparing `.venv`, or set `MCP_DEMO_PYTHON` to an
existing compatible interpreter. See README for smoke, stop, and test ports.
The verified main gateway is `http://127.0.0.1:4038`. Local keys, databases,
logs, and ownership markers are development-only and remain ignored by Git.

Remaining limits: tests do not certify production security or every possible
audit path. The sample server and demo credentials are not production systems.
An uncatchable crash during the short interval between process creation and
recording its state may require manual inspection; the launcher fails closed.
If state cannot be written and a child cannot be stopped, the launcher reports
its PID, port, marker, and descriptor for manual ownership verification; it
does not claim that a durable record exists or stop an unverified listener.
The existing tracked `gateway/data/gateway.db` contains historical audit data;
review it before sharing the repository or packaging its contents. It was not
modified by this task.
