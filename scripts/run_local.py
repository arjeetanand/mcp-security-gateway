"""Start or safely restart the two loopback-only development services."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".run"
START = (
    "import sys,types,uvicorn; "
    "sys.modules['dotenv']=types.SimpleNamespace(load_dotenv=lambda **kwargs: None); "
    "uvicorn.run(sys.argv[1],host='127.0.0.1',port=int(sys.argv[2]),log_level='warning')"
)


def listeners(port: int) -> set[int]:
    result = subprocess.run(
        ["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        text=True, capture_output=True,
    )
    if result.returncode not in (0, 1) or (result.returncode == 1 and result.stderr.strip()):
        raise RuntimeError(f"Cannot inspect port {port}; no process was stopped.")
    return {int(line) for line in result.stdout.splitlines() if line.isdigit()}


def active(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def owns(entry: dict, role: str, port: int) -> bool:
    try:
        pid, fd = int(entry["pid"]), int(entry["fd"])
        marker = Path(entry["marker"]).resolve(strict=True)
        expected_cwd = ROOT / ("gateway" if role == "gateway" else "sample_server")
        if (pid <= 1 or fd < 3 or marker.parent != RUNTIME.resolve()
                or not marker.name.startswith(f"{port}.{role}.") or entry["port"] != port):
            return False
        for descriptor, expected in ((str(fd), marker), ("cwd", expected_cwd)):
            result = subprocess.run(
                ["lsof", "-a", "-p", str(pid), "-d", descriptor, "-Fn"],
                text=True, capture_output=True,
            )
            if result.returncode != 0 or f"n{expected}" not in result.stdout.splitlines():
                return False
        return True
    except (KeyError, TypeError, ValueError, OSError):
        return False


def stop_existing(state: dict | None, main_port: int) -> None:
    services = (("gateway", main_port), ("sample", main_port + 1))
    to_stop = []
    for role, port in services:
        occupied = listeners(port)
        entry = (state or {}).get(role)
        if entry is None:
            if occupied:
                raise RuntimeError(f"Port {port} is occupied by an unowned process; nothing was stopped.")
            continue
        try:
            pid = int(entry["pid"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Invalid ownership record; nothing was stopped.") from exc
        running = active(pid)
        if occupied and occupied != {pid}:
            raise RuntimeError(f"Port {port} has an unexpected listener; nothing was stopped.")
        if running and not owns(entry, role, port):
            raise RuntimeError(f"Process ownership for port {port} is unclear; nothing was stopped.")
        if running:
            to_stop.append((pid, entry, role, port))
        elif occupied:
            raise RuntimeError(f"Port {port} has an unexpected listener; nothing was stopped.")

    for pid, _, _, _ in to_stop:
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while to_stop and time.monotonic() < deadline:
        to_stop = [item for item in to_stop if active(item[0]) and owns(item[1], item[2], item[3])]
        if to_stop:
            time.sleep(0.1)
    if to_stop:
        raise RuntimeError("An owned process did not stop gracefully; refusing to start another instance.")


def start_service(role: str, port: int, environment: dict[str, str]) -> tuple[subprocess.Popen, dict]:
    cwd = ROOT / ("gateway" if role == "gateway" else "sample_server")
    app = "app.main:app" if role == "gateway" else "app:app"
    fd, marker = tempfile.mkstemp(prefix=f"{port}.{role}.", dir=RUNTIME)
    try:
        log_path = RUNTIME / f"{port}.{role}.log"
        if log_path.is_symlink():
            raise RuntimeError(f"Refusing to write through symlink {log_path}.")
        with log_path.open("ab", buffering=0) as log:
            process = subprocess.Popen(
                [sys.executable, "-c", START, app, str(port)], cwd=cwd, env=environment,
                stdout=log, stderr=subprocess.STDOUT, pass_fds=(fd,), start_new_session=True,
            )
    except Exception:
        os.close(fd)
        raise
    entry = {"pid": process.pid, "fd": fd, "marker": marker, "port": port}
    os.close(fd)
    return process, entry


def wait_ready(process: subprocess.Popen, entry: dict, role: str, port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{role} exited; inspect .run/{port}.{role}.log.")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                if listeners(port) == {process.pid} and owns(entry, role, port):
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"{role} did not become ready on 127.0.0.1:{port}.")


def main() -> None:
    arguments = sys.argv[1:]
    stop_only = bool(arguments and arguments[0] == "stop")
    if stop_only:
        arguments = arguments[1:]
    if len(arguments) > 1 or (arguments and arguments[0] not in {"4038", "5038", "6038"}):
        raise SystemExit("Usage: ./run.sh [stop] [4038|5038|6038]")
    main_port = int(arguments[0]) if arguments else 4038
    if RUNTIME.is_symlink():
        raise RuntimeError(".run must not be a symlink.")
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    lock = RUNTIME / f"{main_port}.lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise RuntimeError(f"Another start may be running; inspect {lock}.") from exc
    try:
        state_path = RUNTIME / f"{main_port}.state.json"
        if state_path.is_symlink():
            raise RuntimeError("Ownership record must not be a symlink; nothing was stopped.")
        state = json.loads(state_path.read_text()) if state_path.exists() else None
        if state is not None and (not isinstance(state, dict) or state.get("project") != str(ROOT)):
            raise RuntimeError("Ownership record belongs to another project; nothing was stopped.")
        if stop_only:
            stop_existing(state, main_port)
            print(f"Stopped the owned demo on ports {main_port} and {main_port + 1} if it was running.")
            return
        secret_path = RUNTIME / f"{main_port}.secret"
        upstream_file = RUNTIME / f"{main_port}.upstream.json"
        database_path = RUNTIME / f"{main_port}.sqlite3"
        generated_paths = (secret_path, upstream_file, database_path,
                           RUNTIME / f"{main_port}.gateway.log", RUNTIME / f"{main_port + 1}.sample.log")
        if any(path.is_symlink() for path in generated_paths):
            raise RuntimeError("Local runtime files must not be symlinks; nothing was stopped.")
        if state is None and any(path.exists() for path in (secret_path, upstream_file, database_path)):
            raise RuntimeError("Existing runtime files have no ownership record; refusing to overwrite or use them.")
        stop_existing(state, main_port)
        if state is None:
            state_path.write_text(json.dumps({"project": str(ROOT)}))

        secret = secrets.token_urlsafe(32)
        temp_fd, temp_name = tempfile.mkstemp(prefix=f"{main_port}.secret.", dir=RUNTIME)
        with os.fdopen(temp_fd, "w") as handle:
            handle.write(secret)
        os.replace(temp_name, secret_path)
        upstream_file.write_text(json.dumps({"servers": [{"alias": "finance", "url": f"http://127.0.0.1:{main_port + 1}/mcp", "timeout_seconds": 10}]}))
        environment = {name: os.environ[name] for name in ("PATH", "LANG", "LC_ALL", "TZ") if name in os.environ}
        environment.update({
            "JWT_SECRET": secret, "JWT_ALGORITHM": "HS256", "JWT_AUDIENCE": "",
            "JWT_ROLES_CLAIM": "https://mcp-gateway/roles", "PYTHON_DOTENV_DISABLED": "1",
            "UPSTREAM_SERVERS_FILE": str(upstream_file),
            "TOOL_POLICY_FILE": str(ROOT / "config/tool_policies.json"),
            "DATABASE_PATH": str(database_path),
        })
        started = []
        try:
            sample, sample_entry = start_service("sample", main_port + 1, environment)
            started.append(sample)
            wait_ready(sample, sample_entry, "sample", main_port + 1)
            gateway, gateway_entry = start_service("gateway", main_port, environment)
            started.append(gateway)
            wait_ready(gateway, gateway_entry, "gateway", main_port)
            state_path.write_text(json.dumps({"project": str(ROOT), "gateway": gateway_entry, "sample": sample_entry}, indent=2))
        except Exception:
            for process in reversed(started):
                if process.poll() is None:
                    process.terminate()
            for process in started:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            raise
        print(f"Gateway: http://127.0.0.1:{main_port}")
        print(f"Sample server: http://127.0.0.1:{main_port + 1}")
        print(f"Development JWT secret file: {secret_path}")
        print(f"Disposable demo database: {database_path}")
    finally:
        lock.rmdir()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Cannot start local gateway: {error}", file=sys.stderr)
        raise SystemExit(1) from error
