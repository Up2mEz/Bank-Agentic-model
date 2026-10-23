"""Compatibility entry point; maintain the implementation in agent_app/tools/."""

from pathlib import Path as _Path

_target = _Path(__file__).resolve().parents[1] / "agent_app/tools" / _Path(__file__).name
__file__ = str(_target)
exec(compile(_target.read_bytes(), __file__, "exec"))
