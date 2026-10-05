"""Run a bounded native agy review of supplied material; never expose environment keys."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from creditrisk.artifacts import sha256, utc_now, write_json


def review(prompt_path: Path, destination: Path) -> dict:
    executable = shutil.which("agy")
    if not executable:
        raise RuntimeError("Native agy is unavailable on PATH.")
    prompt = prompt_path.read_text(encoding="utf-8")
    if len(prompt) > 24000:
        raise ValueError("Review prompt exceeds the conservative Windows argument budget.")
    status_path = destination.with_suffix(".status.json")
    if status_path.exists():
        raise FileExistsError("This review already has a status; do not dispatch it twice.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stdout_path, stderr_path = (
        destination.with_suffix(".txt"),
        destination.with_suffix(".stderr.txt"),
    )
    started = utc_now()
    with (
        stdout_path.open("x", encoding="utf-8") as stdout,
        stderr_path.open("x", encoding="utf-8") as stderr,
    ):
        try:
            completed = subprocess.run(
                [executable, "--print", prompt, "--mode", "plan"],
                stdout=stdout,
                stderr=stderr,
                encoding="utf-8",
                timeout=300,
                check=False,
            )
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            exit_code = "timeout"
    content = stdout_path.read_text(encoding="utf-8")
    error = stderr_path.read_text(encoding="utf-8")
    denied = any(
        marker in (content + error).lower()
        for marker in ("auto-denied", "permission request denied", "permission was denied")
    )
    record = {
        "started_utc": started,
        "completed_utc": utc_now(),
        "exit_code": exit_code,
        "nonempty_stdout": bool(content.strip()),
        "stdout_chars": len(content),
        "denied_tool_detected": denied,
        "review_completed": exit_code == 0 and bool(content.strip()) and not denied,
        "prompt_sha256": sha256(prompt_path),
        "scope": "Supplied material only; no independent file inspection or measurements claimed",
    }
    write_json(status_path, record, exclusive=True)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = review(args.prompt, args.destination)
    print(result)
    raise SystemExit(0 if result["review_completed"] else 1)
