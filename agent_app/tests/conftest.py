"""Application tests use workspace-local output folders, never live stores."""

from pathlib import Path


def pytest_sessionstart(session):
    (Path(__file__).resolve().parents[2] / "outputs").mkdir(exist_ok=True)
