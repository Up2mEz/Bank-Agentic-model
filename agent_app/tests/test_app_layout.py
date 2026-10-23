"""Check the application boundary and checkout compatibility after relocation."""

import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "agent_app"


def python_probe(code, cwd, source):
    env = {**os.environ, "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("source", [ROOT / "src", APP / "src"])
def test_checkout_import_resolves_canonical_source_and_shared_inputs(tmp_path, source):
    result = python_probe(
        "import json; from pathlib import Path; from merchant_sandbox import core, server; "
        "print(json.dumps({'source':str(Path(core.__file__).resolve()), 'root':str(core.ROOT), "
        "'fixture':core.FIXTURE.is_file(), 'policy':core.PARAMS.is_file(), "
        "'static':(Path(server.__file__).parent/'static/index.html').is_file()}))",
        tmp_path,
        source,
    )
    assert Path(result["source"]) == APP / "src/merchant_sandbox/core.py"
    assert Path(result["root"]) == ROOT
    assert result["fixture"] and result["policy"] and result["static"]


@pytest.mark.parametrize("launcher", ["agent_app/run.py", "scripts/run_merchant_sandbox.py"])
def test_server_launchers_support_help_from_another_directory(tmp_path, launcher):
    result = subprocess.run(
        [sys.executable, str(ROOT / launcher), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "--port" in result.stdout and "--bridge-token-file" in result.stdout


def test_legacy_tool_import_uses_canonical_file_and_same_module_globals():
    spec = importlib.util.spec_from_file_location(
        "layout_legacy_runner", ROOT / "tools/run_lending_agentic_experiment.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert Path(module.__file__) == APP / "tools/run_lending_agentic_experiment.py"
    assert module.save.__globals__ is module.__dict__
    assert module.ROOT == ROOT
    assert module.audit_module().__file__ == str(APP / "tools/run_lending_scenario_audit.py")


def test_agent_package_is_separate_from_research_dependencies():
    app = tomllib.loads((APP / "pyproject.toml").read_text(encoding="utf-8"))
    research = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert app["project"]["scripts"]["merchant-agent"] == "merchant_sandbox.server:main"
    assert not any(
        name in dependency.lower()
        for dependency in app["project"]["dependencies"]
        for name in ("catboost", "lightgbm", "scikit-learn", "pandas", "numpy")
    )
    assert "merchant_sandbox*" in research["tool"]["setuptools"]["packages"]["find"]["exclude"]
