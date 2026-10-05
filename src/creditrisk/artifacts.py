"""Small artifact helpers with explicit immutable-write semantics."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def verify_hashes(root: Path, hashes: dict[str, str]) -> None:
    for name, expected in hashes.items():
        if sha256(root / name) != expected:
            raise ValueError(f"Frozen artifact changed: {name}")
