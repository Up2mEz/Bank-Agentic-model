"""Checkout import compatibility; implementation lives in agent_app/src/.

Install `./agent_app` for packaged use. This shim is excluded from the research
distribution, so it never installs a second merchant_sandbox implementation.
"""

from pathlib import Path as _Path

_canonical = _Path(__file__).resolve().parents[2] / "agent_app/src/merchant_sandbox"
if not _canonical.is_dir():
    raise ImportError("Missing agent_app/src/merchant_sandbox; use the complete checkout")
__path__ = [str(_canonical)]
