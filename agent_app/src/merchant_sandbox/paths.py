"""Locations of application code and shared, versioned workspace resources."""

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent


def workspace_root() -> Path:
    """Find the checkout independently of cwd, including an editable/wheel install.

    An installation outside the checkout requires AGENT_APP_WORKSPACE. Shared
    policy, fixtures and outputs deliberately remain in the repository.
    """
    configured = os.environ.get("AGENT_APP_WORKSPACE")
    candidates = [Path(configured).expanduser().resolve()] if configured else PACKAGE_ROOT.parents
    for candidate in candidates:
        if (candidate / "agent_app/pyproject.toml").is_file() and (
            candidate / "docs/merchant_lending/demo_parameters.json"
        ).is_file():
            return candidate
    raise RuntimeError(
        "Agent workspace not found; set AGENT_APP_WORKSPACE to the NTT-Bank-Agentic checkout"
    )


ROOT = workspace_root()
