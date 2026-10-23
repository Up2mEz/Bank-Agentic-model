"""Explicit source snapshots are new provenance, never historical V4 acceptance."""

import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Keep temporary manifest paths short: the runner also preserves their relative
# paths inside source-snapshot, which would otherwise exceed Windows path limits.
WORK = ROOT / "outputs/app-tests"
TOOLS = (
    "run_lending_openai_failed.py",
    "run_statement_review_experiment.py",
    "run_lending_scenario_audit.py",
    "run_lending_agentic_experiment.py",
    "run_lending_agentic_heldout.py",
    "evaluate_lending_agentic_experiment.py",
    "statement_report_fixtures.py",
    "evaluate_statement_review.py",
)


def workspace_tmp(prefix):
    WORK.mkdir(parents=True, exist_ok=True)
    return TemporaryDirectory(dir=WORK, prefix=prefix)


def require_historical(*paths):
    """Skip an absent run bundle, but fail for missing files within a present run."""
    missing = [path for path in paths if not path.exists()]
    partial = [
        path
        for path in missing
        if (ROOT / "outputs" / path.relative_to(ROOT / "outputs").parts[0]).exists()
    ]
    if partial:
        pytest.fail(
            "Historical replay bundle is incomplete: "
            + ", ".join(str(path.relative_to(ROOT)) for path in partial)
        )
    if missing:
        pytest.skip(
            "Historical replay bundle absent (Git ignored): "
            + ", ".join(str(path.relative_to(ROOT)) for path in missing)
        )


def forbid_credentials(monkeypatch):
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path.resolve() == (ROOT / ".env").resolve():
            pytest.fail("Preparation attempted to read real credentials")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)


def write_current_manifest(folder):
    # Independent inventory: do not ask the verifier what it requires.
    paths = [
        *sorted((ROOT / "agent_app/src/merchant_sandbox").rglob("*.py")),
        *(ROOT / "agent_app/tools" / name for name in TOOLS),
        ROOT / "docs/merchant_lending/demo_parameters.json",
        ROOT / "examples/merchant_sandbox/lending_scenarios_v1.json",
        ROOT / "examples/merchant_sandbox/statement_review_additional_v1.json",
    ]
    manifest = folder / "current-source.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": p.relative_to(ROOT).as_posix(),
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    }
                    for p in paths
                ]
            }
        ),
        encoding="utf-8",
    )
    return manifest


def runner():
    spec = importlib.util.spec_from_file_location(
        "manifest_runner", ROOT / "agent_app/tools/run_lending_openai_failed.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matching_current_snapshot_is_explicitly_not_v4():
    m = runner()
    with workspace_tmp("manifest-match-") as temp:
        manifest = write_current_manifest(Path(temp))
        result = m.verify_frozen(manifest)
        assert result["snapshot_kind"] == "EXPLICIT_SOURCE_SNAPSHOT"
        assert result["v4_acceptance"] is False
        assert result["files"] == len(json.loads(manifest.read_text())["files"])
        assert result["drift"] == []
        assert result["manifest"]["sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()


@pytest.mark.historical_replay
def test_original_v4_remains_refused_without_changing_frozen_output():
    m = runner()
    manifest = m.PREVIOUS / "source-v4-manifest.json"
    require_historical(manifest)
    before = manifest.read_bytes()
    with pytest.raises(RuntimeError, match="^frozen_source_drift:"):
        m.verify_frozen()
    assert manifest.read_bytes() == before


@pytest.mark.parametrize("problem", ["content", "missing", "duplicate", "case_alias", "hash"])
def test_snapshot_rejects_drift_missing_duplicates_and_invalid_hash(problem):
    m = runner()
    with workspace_tmp("manifest-invalid-") as temp:
        manifest = write_current_manifest(Path(temp))
        data = json.loads(manifest.read_text())
        first = data["files"][0]
        if problem == "content":
            first["sha256"] = "0" * 64
        elif problem == "missing":
            data["files"].append({"path": "agent_app/nonexistent.py", "sha256": "0" * 64})
        elif problem == "duplicate":
            data["files"].append(dict(first))
        elif problem == "case_alias":
            data["files"].append({**first, "path": first["path"].upper()})
        else:
            first["sha256"] = "not-a-sha256"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(RuntimeError, match="^frozen_source_drift:"):
            m.verify_frozen(manifest)


@pytest.mark.parametrize(
    "path",
    [
        "../README.md",
        "/README.md",
        "C:/README.md",
        "agent_app/../README.md",
        "./README.md",
        "agent_app\\tools\\runner.py",
        "README.md:stream",
    ],
)
def test_snapshot_rejects_non_repository_relative_canonical_paths(path):
    m = runner()
    with workspace_tmp("manifest-path-") as temp:
        manifest = write_current_manifest(Path(temp))
        data = json.loads(manifest.read_text())
        data["files"].append({"path": path, "sha256": "0" * 64})
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(RuntimeError, match="^frozen_source_drift:"):
            m.verify_frozen(manifest)


@pytest.mark.parametrize(
    "omitted",
    [
        "agent_app/src/merchant_sandbox/agentic_review.py",
        "agent_app/src/merchant_sandbox/agentic_openai.py",
        "agent_app/tools/run_lending_scenario_audit.py",
        "agent_app/tools/evaluate_statement_review.py",
        "docs/merchant_lending/demo_parameters.json",
        "examples/merchant_sandbox/lending_scenarios_v1.json",
        "examples/merchant_sandbox/statement_review_additional_v1.json",
    ],
)
def test_snapshot_requires_runtime_dependencies_policy_and_fixtures(omitted):
    m = runner()
    with workspace_tmp("manifest-incomplete-") as temp:
        manifest = write_current_manifest(Path(temp))
        data = json.loads(manifest.read_text())
        data["files"] = [entry for entry in data["files"] if entry["path"] != omitted]
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(RuntimeError, match="^frozen_source_drift:.*incomplete"):
            m.verify_frozen(manifest)


def test_one_irrelevant_file_cannot_bypass_provenance():
    m = runner()
    with workspace_tmp("manifest-irrelevant-") as temp:
        manifest = Path(temp) / "one.json"
        manifest.write_text(json.dumps({"files": [m.receipt(ROOT / "README.md")]}))
        with pytest.raises(RuntimeError, match="^frozen_source_drift:.*incomplete"):
            m.verify_frozen(manifest)


@pytest.mark.parametrize("content", [None, "{", "[]", "{}", '{"files": [{}]}'])
def test_missing_or_malformed_manifest_fails_closed(content):
    m = runner()
    with workspace_tmp("manifest-malformed-") as temp:
        manifest = Path(temp) / "bad.json"
        if content is not None:
            manifest.write_text(content, encoding="utf-8")
        with pytest.raises(RuntimeError, match="^frozen_source_drift:"):
            m.verify_frozen(manifest)


def test_missing_default_manifest_fails_closed(monkeypatch):
    m = runner()
    with workspace_tmp("manifest-absent-v4-") as temp:
        monkeypatch.setattr(m, "PREVIOUS", Path(temp))
        with pytest.raises(RuntimeError, match="^frozen_source_drift:"):
            m.verify_frozen()


def test_historical_helper_skips_absent_bundle_but_fails_partial_bundle(monkeypatch):
    with workspace_tmp("historical-guard-") as temp:
        root = Path(temp)
        monkeypatch.setitem(require_historical.__globals__, "ROOT", root)
        required = root / "outputs/frozen-run/case.json"
        with pytest.raises(pytest.skip.Exception, match="bundle absent"):
            require_historical(required)
        required.parent.mkdir(parents=True)
        with pytest.raises(pytest.fail.Exception, match="bundle is incomplete"):
            require_historical(required)
        required.write_text("corrupt JSON", encoding="utf-8")
        require_historical(required)
        with pytest.raises(json.JSONDecodeError):
            json.loads(required.read_text())
