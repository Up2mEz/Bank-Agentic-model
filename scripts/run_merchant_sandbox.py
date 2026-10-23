"""Legacy launcher; prefer .venv/Scripts/python.exe agent_app/run.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent_app/src"))

from merchant_sandbox.server import main  # noqa: E402

if __name__ == "__main__":
    main()
