"""Runner provenance, evaluation and accounting checks; no network."""

import importlib.util
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_source_manifest import (
    forbid_credentials,
    require_historical,
    workspace_tmp,
    write_current_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "luna_failed_runner", ROOT / "agent_app/tools/run_lending_openai_failed.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_cached_input_and_reasoning_are_subsets_not_extra_tokens():
    record = {
        "attempt": 1,
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 100,
            "total_tokens": 1100,
            "input_tokens_details": {"cached_tokens": 400},
            "output_tokens_details": {"reasoning_tokens": 60},
        },
    }
    row = runner.usage_row("C01", record)
    assert row["total_tokens"] == 1100
    assert row["cached_input_tokens"] == 400
    assert row["reasoning_tokens"] == 60
    assert Decimal(row["estimated_standard_cost_usd_excluding_cache_writes"]) == Decimal("0.000114")


def test_missing_usage_stays_unknown_in_request_and_case_totals(tmp_path):
    totals = runner.write_usage(tmp_path, {"C01": [{"attempt": 1, "usage": None}]})
    assert totals[0]["usage_missing_requests"] == 1
    assert totals[0]["input_tokens"] is None
    assert totals[0]["total_tokens"] is None
    rows = json.loads((tmp_path / "per-request-usage.json").read_text(encoding="utf-8"))
    assert rows[0]["estimated_standard_cost_usd_excluding_cache_writes"] is None


@pytest.mark.historical_replay
def test_h01_input_reuses_frozen_documents_without_regeneration():
    source = runner.PREVIOUS / "heldout-v4-final/H01/replayed-documents.json"
    require_historical(source, source.with_name("input-case.json"))
    before = source.read_bytes()
    case, docs, initial, oracle, receipts = runner.load_input("H01")
    assert docs == json.loads(before)
    assert oracle is None
    assert initial["issues"] == []
    assert "old equipment disposal proceeds" in str(initial["source_groups"])
    assert case["decision"] is None
    assert len(receipts) == 2
    assert source.read_bytes() == before


@pytest.mark.historical_replay
def test_prior_h01_bad_recommendation_still_fails_financial_oracle():
    folder = runner.PREVIOUS / "heldout-v4-final/H01"
    require_historical(
        *(folder / name for name in ("input-case.json", "replayed-documents.json", "case.json"))
    )
    _, _, initial, oracle, _ = runner.load_input("H01")
    source = runner.PREVIOUS / "heldout-v4-final/H01/case.json"
    case = deepcopy(runner.read(source))
    result = runner.evaluate("H01", case, initial, oracle, [{"usage": {"total_tokens": 1}}])
    assert result["status"] == "FAIL"
    assert result["original_oracle_status"] == "FAIL"
    checks = result["oracle"]["checks"]
    assert any(
        "not included in recurring revenue" in c["requirement"] and not c["passed"] for c in checks
    )


def test_preexisting_output_is_refused_before_source_or_api_work(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner, "verify_frozen", lambda: pytest.fail("must stop before reading source")
    )
    with pytest.raises(SystemExit, match="NEW directory"):
        runner.main(["--output", str(tmp_path)])


def test_case_selection_cannot_silently_expand_to_passing_case(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner, "verify_frozen", lambda: pytest.fail("must stop before source access")
    )
    with pytest.raises(SystemExit, match="previously non-passing"):
        runner.main(["--output", str(tmp_path / "new"), "--cases", "C02"])


@pytest.mark.historical_replay
def test_prepare_only_never_reads_credentials(monkeypatch):
    from merchant_sandbox.agentic_openai import OpenAIConfig

    require_historical(
        runner.BASELINE / "cases.sqlite3",
        runner.BASELINE / "C01/case.json",
        runner.BASELINE / "C01/oracle.json",
        runner.PREVIOUS / "agentic-v4-final/report.json",
    )
    forbid_credentials(monkeypatch)
    monkeypatch.setattr(OpenAIConfig, "load", lambda *a, **kw: pytest.fail("credential load"))
    with workspace_tmp("luna-prepare-") as temp:
        manifest = write_current_manifest(Path(temp))
        output = Path(temp) / "run"
        assert (
            runner.main(
                [
                    "--output",
                    str(output),
                    "--cases",
                    "C01",
                    "--prepare-only",
                    "--source-manifest",
                    str(manifest),
                ]
            )
            == 0
        )
        report = runner.read(output / "report.json")
        assert report["frozen_after"] == report["frozen_preflight"]
        assert report["human_final_decision_required"] is True
        assert runner.read(output / "C01/input-case.json")["decision"] is None


@pytest.mark.parametrize("quota_error", [False, True])
@pytest.mark.historical_replay
def test_offline_end_to_end_receipts_and_quota_stop(monkeypatch, quota_error):
    from merchant_sandbox import agentic_openai

    selected = ["C01", "C03"] if quota_error else ["C01"]
    require_historical(
        runner.BASELINE / "cases.sqlite3",
        runner.PREVIOUS / "agentic-v4-final/report.json",
        *(
            runner.BASELINE / sid / name
            for sid in selected
            for name in ("case.json", "oracle.json")
        ),
    )
    monkeypatch.setattr(
        agentic_openai.OpenAIConfig,
        "load",
        classmethod(lambda cls, *a, **kw: cls(api_key="offline-test-only")),
    )
    dispatched = []

    def fake_post(url, **kwargs):
        payload = kwargs["json"]
        context = json.loads(payload["input"][0]["content"])
        available = {tool["name"] for tool in payload["tools"]}
        dispatched.append(payload)
        if quota_error:
            return SimpleNamespace(
                status_code=429,
                headers={"x-request-id": "req_offline_quota"},
                content=b'{"error":{"code":"insufficient_quota"}}',
                json=lambda: {"error": {"code": "insufficient_quota"}},
            )
        if not context["declarations_checked"]:
            tool, args = "compare_declarations", {"claims": []}
        elif not context["cashflow_current"]:
            tool, args = "inspect_cashflow", {}
        else:
            tool, args = "finish_review", {"reason": "ส่งหลักฐานให้เจ้าหน้าที่ตรวจสอบ"}
        assert tool in available
        response_body = {
            "status": "completed",
            "model": "gpt-6-luna",
            "service_tier": "default",
            "output": [{"type": "function_call", "name": tool, "arguments": json.dumps(args)}],
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 100,
                "total_tokens": 1100,
                "input_tokens_details": {"cached_tokens": 400},
                "output_tokens_details": {"reasoning_tokens": 60},
            },
        }
        return SimpleNamespace(
            status_code=200,
            headers={"x-request-id": "req_offline_loop"},
            content=json.dumps(response_body).encode(),
            json=lambda: response_body,
        )

    monkeypatch.setattr(agentic_openai.requests, "post", fake_post)
    monkeypatch.setattr(
        agentic_openai.requests.sessions.Session,
        "request",
        lambda *a, **kw: pytest.fail("Real network is forbidden"),
    )
    # Keep transient test data in the repository even for default Windows pytest temp paths.
    with workspace_tmp("pytest-luna-offline-") as tmp:
        source_manifest = write_current_manifest(Path(tmp))
        output = Path(tmp) / "run"
        code = runner.main(
            [
                "--output",
                str(output),
                "--cases",
                ",".join(selected),
                "--source-manifest",
                str(source_manifest),
            ]
        )
        report = runner.read(output / "report.json")
        rows = runner.read(output / "per-request-usage.json")
        assert report["manifest_drift"] == []
        assert report["frozen_after"] == report["frozen_preflight"]
        assert report["frozen_after"]["snapshot_kind"] == "EXPLICIT_SOURCE_SNAPSHOT"
        assert report["frozen_after"]["v4_acceptance"] is False
        assert runner.receipt(source_manifest) in runner.read(output / "manifest.json")
        if quota_error:
            assert code == 2 and report["run_status"] == "STOPPED"
            assert report["cases"][1]["status"] == "NOT_RUN"
            assert len(dispatched) == len(rows) == 1
            assert rows[0]["total_tokens"] is None
            assert report["budget"]["uncertain_calls"] == 1
        else:
            assert code == 0 and report["run_status"] == "COMPLETED"
            assert report["cases"][0]["status"] == "PASS"
            assert len(dispatched) == len(rows) == 3
            assert report["budget"]["total_tokens"] == 3300
            case = runner.read(output / "C01/case.json")
            assert case["decision"] is None and case["provider_api_calls"] == 3


@pytest.mark.historical_replay
@pytest.mark.parametrize("prepare_only", [False, True])
def test_lending_rechecks_manifest_identity_after_work(monkeypatch, prepare_only):
    from merchant_sandbox import agentic_openai

    require_historical(
        runner.BASELINE / "cases.sqlite3",
        runner.BASELINE / "C01/case.json",
        runner.BASELINE / "C01/oracle.json",
        runner.PREVIOUS / "agentic-v4-final/report.json",
    )
    with workspace_tmp("luna-postflight-") as temp:
        manifest = write_current_manifest(Path(temp))

        def change_manifest():
            manifest.write_text(manifest.read_text() + "\n", encoding="utf-8")

        if prepare_only:
            original = runner.load_input

            def load_input(sid):
                result = original(sid)
                change_manifest()
                return result

            monkeypatch.setattr(runner, "load_input", load_input)
        else:
            monkeypatch.setattr(
                agentic_openai.OpenAIConfig,
                "load",
                classmethod(lambda cls, *a, **kw: cls(api_key="offline-test-only")),
            )

            def review(case, *args, **kwargs):
                change_manifest()
                return case

            monkeypatch.setattr(runner, "run_review", review)
        monkeypatch.setattr(
            agentic_openai.requests.sessions.Session,
            "request",
            lambda *a, **kw: pytest.fail("Real network is forbidden"),
        )
        args = [
            "--output",
            str(Path(temp) / "run"),
            "--cases",
            "C01",
            "--source-manifest",
            str(manifest),
        ]
        if prepare_only:
            args.append("--prepare-only")
        with pytest.raises(RuntimeError, match="^frozen_source_drift:source_manifest_changed"):
            runner.main(args)
