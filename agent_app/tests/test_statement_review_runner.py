"""Offline experiment isolation and actual tool-argument accounting."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_source_manifest import forbid_credentials, workspace_tmp, write_current_manifest

ROOT = Path(__file__).resolve().parents[2]


def module():
    path = ROOT / "agent_app/tools/run_statement_review_experiment.py"
    assert path.exists(), "four-part runner missing"
    spec = importlib.util.spec_from_file_location("four_part_runner", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_luna_selection_refuses_passing_case_and_requires_typhoon():
    m = module()
    previous = {
        "provider": "typhoon",
        "cases": [{"id": "S03", "status": "PASS"}, {"id": "S01", "status": "FAIL"}],
    }
    assert m.select_cases("luna", None, previous) == ["S01"]
    with pytest.raises(SystemExit, match="non-passing"):
        m.select_cases("luna", "S03", previous)
    with pytest.raises(SystemExit, match="Typhoon"):
        m.select_cases("luna", None, None)


def test_evaluation_can_bind_actual_openai_choice_without_altering_provider_receipt():
    m = module()
    records = [
        {"attempt": 1, "status": "ACCEPTED", "tool": "compare_declarations", "model": "gpt-6-luna"}
    ]
    choices = [{"attempt": 1, "tool": "compare_declarations", "arguments": {"claims": []}}]
    result = m.evaluation_receipts(records, choices)
    assert result[0]["arguments"] == {"claims": []}
    assert result[0]["arguments_origin"] == "validated_native_choice_captured_by_wrapper"
    assert "arguments" not in records[0]
    choices[0]["tool"] = "finish_review"
    assert "arguments" not in m.evaluation_receipts(records, choices)[0]


def test_new_evaluation_accepts_openai_receipts_without_typhoon_llm_counter():
    m = module()
    path = ROOT / "agent_app/tests/test_statement_review_evaluation.py"
    spec = importlib.util.spec_from_file_location("independent_evaluator_fixture", path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    case, report, expected, records = fixture.valid_packet("S04")
    case.update(agent_mode="openai", llm_calls=0, provider_api_calls=len(records))
    for record in records:
        record["model"] = "gpt-6-luna"
    result = m.evaluate_case("S04", case, report, expected, {}, None, records)
    assert result["status"] == "PASS", result["agent_checks"]


def test_prepare_only_never_reads_credentials_or_sends_oracle(monkeypatch):
    m = module()
    forbid_credentials(monkeypatch)
    monkeypatch.setattr(
        m, "make_factory", lambda *a: pytest.fail("prepare must not touch providers")
    )
    with workspace_tmp("pytest-four-prepare-") as temp:
        source_manifest = write_current_manifest(Path(temp))
        output = Path(temp) / "run"
        assert (
            m.main(
                [
                    "--provider",
                    "typhoon",
                    "--cases",
                    "S01",
                    "--output",
                    str(output),
                    "--prepare-only",
                    "--source-manifest",
                    str(source_manifest),
                ]
            )
            == 0
        )
        context = m.read(output / "S01/initial-context.json")
        assert "expected" not in context and "evaluation_only" not in json.dumps(context)
        assert context["statement_document_facts"]["continuity_checks"][0]["matches"] is False
        assert m.read(output / "report.json")["run_status"] == "PREPARED"
        report = m.read(output / "report.json")
        assert report["frozen_after"] == report["frozen_preflight"]
        assert report["frozen_preflight"]["v4_acceptance"] is False
        assert m.receipt(source_manifest) in m.read(output / "manifest.json")


def test_paid_receipt_survives_report_failure(monkeypatch):
    m = module()
    inner = SimpleNamespace(
        mode="typhoon",
        call_records=[
            {
                "attempt": 1,
                "status": "ACCEPTED",
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
            }
        ],
    )
    monkeypatch.setattr(
        m, "make_factory", lambda *a: (lambda cb: inner, SimpleNamespace(summary=lambda: {}))
    )
    monkeypatch.setattr(m, "run_review", lambda case, *a, **kw: case)

    def failed_report(*a, **kw):
        raise RuntimeError("sensitive exception body")

    monkeypatch.setattr(m, "build_staff_report", failed_report)
    with workspace_tmp("pytest-four-receipt-") as temp:
        source_manifest = write_current_manifest(Path(temp))
        output = Path(temp) / "run"
        code = m.main(
            [
                "--provider",
                "typhoon",
                "--cases",
                "S03",
                "--output",
                str(output),
                "--source-manifest",
                str(source_manifest),
            ]
        )
        assert code == 2
        assert m.read(output / "S03/provider-calls.json")[0]["usage"]["total_tokens"] == 110
        result = m.read(output / "S03/result.json")
        assert result["status"] == "FAIL" and result["reason"] == "postprocess:RuntimeError"
        assert m.read(output / "report.json")["total_tokens"] == 110


@pytest.mark.parametrize("missing_usage", [False, True])
def test_bounded_offline_run_retains_choices_reports_and_unknown_usage_stop(
    monkeypatch, missing_usage
):
    m = module()

    class Fake:
        mode = "typhoon"

        def __init__(self):
            self.call_records = []

        def choose(self, context, tools, timeout):
            assert "expected" not in context and "truth" not in context
            assert "statement_document_facts" in context
            if not context["declarations_checked"]:
                tool, arguments = "compare_declarations", {"claims": []}
            elif not context["cashflow_current"]:
                tool, arguments = "inspect_cashflow", {}
            else:
                tool, arguments = "finish_review", {"reason": "ส่งให้เจ้าหน้าที่ตรวจ"}
            self.call_records.append(
                {
                    "attempt": len(self.call_records) + 1,
                    "tool": tool,
                    "status": "ACCEPTED",
                    "usage": None
                    if missing_usage
                    else {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100},
                }
            )
            return {
                "tool": tool,
                "arguments": arguments,
                "reason": "offline scripted choice",
                "model": "offline",
            }

    monkeypatch.setattr(
        m, "make_factory", lambda *a: (lambda callback: Fake(), SimpleNamespace(summary=lambda: {}))
    )
    monkeypatch.setattr(
        m,
        "evaluate_case",
        lambda sid, result, *a: {
            "id": sid,
            "status": "FAIL" if result["state"] == "TECHNICAL_REVIEW" else "PASS",
            "state": result["state"],
        },
    )
    with workspace_tmp("pytest-four-run-") as temp:
        source_manifest = write_current_manifest(Path(temp))
        output = Path(temp) / "run"
        code = m.main(
            [
                "--provider",
                "typhoon",
                "--cases",
                "S03,S01" if missing_usage else "S03",
                "--output",
                str(output),
                "--source-manifest",
                str(source_manifest),
            ]
        )
        report = m.read(output / "report.json")
        trace = m.read(output / "S03/public-trace.json")
        assert trace[0]["choice"]["arguments"] == {"claims": []}
        assert m.read(output / "S03/staff-report.json")["decision"] is None
        assert report["manifest_drift"] == []
        assert report["frozen_after"] == report["frozen_preflight"]
        if missing_usage:
            assert code == 2 and report["cases"][1]["status"] == "NOT_RUN"
            assert report["total_tokens"] is None
        else:
            assert code == 0 and len(trace) == 3 and report["total_tokens"] == 3300
            assert trace[-1]["controller"]["status"] == "ACCEPTED"
            assert trace[-1]["tool_observation"] is not None


@pytest.mark.parametrize("prepare_only", [False, True])
@pytest.mark.parametrize("drift", ["content", "missing", "manifest_replaced"])
def test_source_and_manifest_are_checked_again_after_work(monkeypatch, prepare_only, drift):
    m = module()
    with workspace_tmp("four-postflight-") as temp:
        folder = Path(temp)
        manifest = write_current_manifest(folder)
        extra = folder / "extra-source.txt"
        extra.write_text("before", encoding="utf-8")
        data = m.read(manifest)
        data["files"].append(m.receipt(extra))
        m.save(manifest, data)

        def change_snapshot():
            if drift == "content":
                extra.write_text("after", encoding="utf-8")
            elif drift == "missing":
                extra.unlink()
            else:
                # Still a valid matching source list, but no longer the same manifest bytes.
                manifest.write_text(manifest.read_text() + "\n", encoding="utf-8")

        if prepare_only:
            original = m.prepare

            def prepare(sid):
                result = original(sid)
                change_snapshot()
                return result

            monkeypatch.setattr(m, "prepare", prepare)
            monkeypatch.setattr(m, "make_factory", lambda *a: pytest.fail("provider touched"))
        else:
            inner = SimpleNamespace(mode="typhoon", call_records=[])
            monkeypatch.setattr(
                m,
                "make_factory",
                lambda *a: (lambda cb: inner, SimpleNamespace(summary=lambda: {})),
            )

            def review(case, *args, **kwargs):
                change_snapshot()
                return case

            monkeypatch.setattr(m, "run_review", review)
        args = [
            "--provider",
            "typhoon",
            "--cases",
            "S03",
            "--output",
            str(folder / "run"),
            "--source-manifest",
            str(manifest),
        ]
        if prepare_only:
            args.append("--prepare-only")
        with pytest.raises(RuntimeError, match="^frozen_source_drift:"):
            m.main(args)
