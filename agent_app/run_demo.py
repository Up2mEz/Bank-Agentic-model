"""Start separate Case API and Agent service processes with workspace-local state."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staff-port", type=int, default=8770)
    parser.add_argument("--agent-port", type=int, default=8781)
    parser.add_argument("--state-dir", type=Path, default=ROOT / "outputs/agent-demo")
    parser.add_argument("--bank-url", default="")
    parser.add_argument("--bank-agent-key-file", type=Path)
    parser.add_argument("--bank-reviewer-key-file", type=Path)
    parser.add_argument("--bridge-token-file", type=Path)
    parser.add_argument("--agent-review-mode", choices=("offline", "typhoon"), default="typhoon")
    parser.add_argument(
        "--env-file", type=Path, help="Provider configuration passed only to Agent service"
    )
    parser.add_argument(
        "--check", action="store_true", help="Start, check health, then stop only these processes"
    )
    args = parser.parse_args(argv)
    state = args.state_dir.resolve()
    if not state.is_relative_to(ROOT) or args.staff_port == args.agent_port:
        parser.error("Use separate ports and a state directory inside this repository")
    for port in (args.staff_port, args.agent_port):
        if not 1 <= port <= 65535:
            parser.error("Ports must be between 1 and 65535")
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
        except OSError:
            parser.error(f"Port {port} is in use; select another port")
    state.mkdir(parents=True, exist_ok=True)
    token_file = state / "agent-service.token"
    if not token_file.exists():
        token_file.write_text(secrets.token_urlsafe(40), encoding="utf-8")
        token_file.chmod(0o600)
    token = token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        parser.error("Existing service token is invalid; review its file before starting")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "agent_app/src"), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("AGENT_SERVICE_TOKEN", None)
    env.pop("AGENT_SERVICE_URL", None)
    agent = [
        sys.executable,
        str(ROOT / "agent_app/run_service.py"),
        "--port",
        str(args.agent_port),
        "--db",
        str(state / "reviews.sqlite3"),
        "--token-file",
        str(token_file),
    ]
    if args.env_file:
        agent += ["--env-file", str(args.env_file.resolve())]
    staff = [
        sys.executable,
        str(ROOT / "agent_app/run.py"),
        "--port",
        str(args.staff_port),
        "--db",
        str(state / "cases.sqlite3"),
        "--agent-service-url",
        f"http://127.0.0.1:{args.agent_port}",
        "--agent-service-token-file",
        str(token_file),
    ]
    if args.bank_url:
        staff += ["--bank-url", args.bank_url, "--agent-review-mode", args.agent_review_mode]
    for name in ("bank_agent_key_file", "bank_reviewer_key_file", "bridge_token_file"):
        value = getattr(args, name)
        if value:
            staff += ["--" + name.replace("_", "-"), str(value.resolve())]
    children, logs = [], []
    try:
        for label, command, port in (
            ("agent", agent, args.agent_port),
            ("staff", staff, args.staff_port),
        ):
            log = (state / f"{label}.log").open("ab")
            logs.append(log)
            child = subprocess.Popen(
                command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
            )
            children.append(child)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError(
                        f"{label} exited; inspect {label}.log in the state directory"
                    )
                try:
                    with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError, OSError):
                    time.sleep(0.1)
            else:
                raise RuntimeError(f"{label} health check timed out; inspect its local log")
        print(
            json.dumps(
                {
                    "staff": f"http://127.0.0.1:{args.staff_port}/",
                    "manual_test": f"http://127.0.0.1:{args.staff_port}/test-application",
                    "agent_health": f"http://127.0.0.1:{args.agent_port}/healthz",
                    "state_dir": str(state),
                    "status": "HEALTHY",
                }
            ),
            flush=True,
        )
        if args.check:
            return 0
        print("Press Ctrl+C to stop this demo's two processes.", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.3)
        raise RuntimeError("A demo process exited; inspect the state directory logs")
    except KeyboardInterrupt:
        return 0
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        for log in logs:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
