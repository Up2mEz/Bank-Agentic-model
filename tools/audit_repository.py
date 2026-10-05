"""Audit staged publication files for secrets, excluded artifacts and broken local links."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = (
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{40,}"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}\b"),
    re.compile(rb"AKIA[A-Z0-9]{16}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def git(*arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def main():
    paths = [
        name.decode("utf-8")
        for name in git("diff", "--cached", "--name-only", "-z").split(b"\0")
        if name
    ]
    if not paths:
        raise ValueError("No staged files to audit.")
    local_secrets = []
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                value = value.strip().strip("\"'")
                if (
                    any(word in key.upper() for word in ("TOKEN", "KEY", "SECRET"))
                    and len(value) >= 16
                ):
                    local_secrets.append(value.encode("utf-8"))
    problems = []
    blobs = {}
    for name in paths:
        blob = git("show", f":{name}")
        blobs[name] = blob
        if (
            name.startswith(("outputs/", "data/raw/", ".venv/"))
            or name.endswith((".joblib", ".cbm", ".pt", ".pth"))
            or (Path(name).name.startswith(".env") and name != ".env.example")
        ):
            problems.append({"path": name, "problem": "Excluded local/raw/model artifact staged"})
        if any(secret in blob for secret in local_secrets) or any(
            pattern.search(blob) for pattern in SECRET_PATTERNS
        ):
            # Never print any matched value or surrounding line.
            problems.append({"path": name, "problem": "Potential credential material detected"})
        if name.startswith(("scripts/", "reports/")) and blob != (ROOT / name).read_bytes():
            problems.append(
                {"path": name, "problem": "Staging changed bytes of historical evidence"}
            )
    broken_links = []
    staged = set(paths)
    for name, blob in blobs.items():
        if not name.endswith(".md"):
            continue
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", blob.decode("utf-8")):
            target = target.strip("<>").split("#", 1)[0]
            if not target or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target):
                continue
            resolved = (ROOT / name).parent.joinpath(target).resolve()
            if not resolved.is_relative_to(ROOT):
                continue
            relative = resolved.relative_to(ROOT).as_posix()
            if relative not in staged and not resolved.is_dir():
                broken_links.append({"path": name, "target": target})
    record = {
        "staged_files": len(paths),
        "staged_bytes": sum(map(len, blobs.values())),
        "secret_or_artifact_problems": problems,
        "broken_local_links": broken_links,
        "scope": "Staged snapshot, common credential patterns plus actual local .env secrets; no guarantee for unknown secret types.",
    }
    print(json.dumps(record, ensure_ascii=False, indent=2))
    raise SystemExit(1 if problems or broken_links else 0)


if __name__ == "__main__":
    main()
