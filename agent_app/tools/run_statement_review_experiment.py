"""Isolated four-part statement trial: Typhoon first, Luna non-passing cases only."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent_app/src"))
sys.path.insert(0, str(ROOT / "agent_app/tools"))

import run_lending_openai_failed as prior  # noqa: E402
from evaluate_lending_agentic_experiment import additional_checks  # noqa: E402
from statement_report_fixtures import SPEC, build_cases  # noqa: E402

from merchant_sandbox.agentic_review import ReviewSession, run_review  # noqa: E402
from merchant_sandbox.statement_experiment import TracedAgent, statement_context  # noqa: E402
from merchant_sandbox.statement_report import build_staff_report, render_staff_report  # noqa: E402

read, save, receipt, verify_frozen = prior.read, prior.save, prior.receipt, prior.verify_frozen
ORDER = ["S01", "S02", "S03", "S04", "S05", "C11", "H01"]


def select_cases(provider, requested, previous):
    if provider == "luna":
        if not previous or previous.get("provider") != "typhoon":
            raise SystemExit("Luna requires a completed Typhoon experiment report")
        allowed = [c["id"] for c in previous["cases"] if c["status"] in {"FAIL", "PARTIAL"}]
    else:
        allowed = ORDER
    selected = requested.split(",") if requested else allowed
    if not selected or len(set(selected)) != len(selected) or set(selected) - set(allowed):
        raise SystemExit("Select unique allowed cases; Luna accepts only Typhoon non-passing cases")
    return selected


def prepare(sid):
    if sid.startswith("S"):
        fixture = build_cases()[sid]
        case, docs = fixture["case"], fixture["documents"]
        expected, oracle = fixture["expected"], None
        inputs = [{**receipt(SPEC), "role": "fixture_and_evaluation_separated"}]
    else:
        case, docs, _, oracle, inputs = prior.load_input(sid)
        expected = None
    initial = ReviewSession(deepcopy(case), deepcopy(docs)).context()
    initial["statement_document_facts"] = statement_context(case, docs)
    return case, docs, initial, expected, oracle, inputs


def make_factory(provider, credential, count):
    if provider == "typhoon":
        from merchant_sandbox.agentic_typhoon import CallBudget, Config, TyphoonReviewAgent

        config, budget = Config.load(credential), CallBudget(count * 8)
        return lambda callback: TyphoonReviewAgent(
            config, budget=budget, max_calls=8, max_seconds=240, on_record=callback
        ), budget
    from merchant_sandbox.agentic_openai import OpenAIConfig, OpenAIReviewAgent, TokenBudget

    config = OpenAIConfig.load(credential, credential_env="OPENAI")
    budget = TokenBudget(
        max_calls=count * 8, max_input_tokens=240000, max_output_tokens=32000, max_cost_usd="0.04"
    )
    return lambda callback: OpenAIReviewAgent(
        config, budget=budget, max_calls=8, max_seconds=240, on_record=callback
    ), budget


def evaluate_case(sid, result, staff, expected, initial, oracle, records):
    if sid.startswith("S"):
        from evaluate_statement_review import evaluate_new

        return evaluate_new(sid, result, staff, expected, records)
    if sid.startswith("C"):
        original = prior.audit_module().evaluate(oracle["scenario"], oracle["truth"], result)
        checks = additional_checks(sid, result)[2:]
    else:
        original = prior.evaluate_heldout(sid, result, initial)
        checks = []
    accepted = [
        t
        for t in result.get("trace", [])
        if t.get("kind") == "agent_action" and t.get("status") == "ACCEPTED"
    ]
    checks.append(
        {
            "requirement": "bounded native human handoff",
            "passed": bool(records)
            and len(records) <= 8
            and any(t["tool"] == "finish_review" for t in accepted)
            and result["state"] != "TECHNICAL_REVIEW",
        }
    )
    report_checks = [
        {
            "requirement": "four sections, human decision and no unsupported sales",
            "passed": set(staff["sections"])
            == {"supported_sales", "non_sales_inflows", "identifiable_obligations", "follow_up"}
            and staff["decision"] is None
            and not staff["sections"]["supported_sales"]["items"],
        },
        {
            "requirement": "raw row conservation",
            "passed": not staff["raw_rows_conservation"]["unassigned_refs"]
            and not staff["raw_rows_conservation"]["multiply_assigned_refs"],
        },
    ]
    status = original["status"] if all(c["passed"] for c in checks + report_checks) else "FAIL"
    return {
        "id": sid,
        "status": status,
        "state": result["state"],
        "decision": result["decision"],
        "oracle": original,
        "agent_checks": checks,
        "report_checks": report_checks,
    }


def usage_rows(sid, provider, records):
    rows = []
    for record in records:
        if provider == "luna":
            row = prior.usage_row(sid, record)
        else:
            usage = record.get("usage") or {}
            row = {
                "case": sid,
                "attempt": record.get("attempt"),
                "tool": record.get("tool"),
                "status": record.get("status"),
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "accounted_cost_estimate_usd": None,
            }
        row["provider"] = provider
        rows.append(row)
    return rows


def evaluation_receipts(records, choices):
    """Bind captured, adapter-validated choices; never rewrite raw provider receipts."""
    by_attempt = {c["attempt"]: c for c in choices}
    normalized = deepcopy(records)
    for record in normalized:
        choice = by_attempt.get(record.get("attempt"), {})
        if (
            record.get("status") == "ACCEPTED"
            and record.get("tool") == choice.get("tool")
            and "arguments" not in record
            and isinstance(choice.get("arguments"), dict)
        ):
            record["arguments"] = deepcopy(choice["arguments"])
            record["arguments_origin"] = "validated_native_choice_captured_by_wrapper"
    return normalized


def public_trace(agent, result):
    actions = {e["call"]: e for e in result["trace"] if e.get("kind") == "agent_action"}
    choices = {e["attempt"]: e for e in agent.choices}
    observations, last_tool = {}, None
    for event in result["trace"]:
        if event.get("kind") == "tool":
            last_tool = event
        elif event.get("kind") == "agent_action":
            if (
                last_tool
                and last_tool["tool"] == event.get("tool")
                and event.get("status") == "ACCEPTED"
            ):
                observations[event["call"]] = last_tool.get("result")
            last_tool = None
    rows = []
    for entry in agent.contexts:
        attempt = entry["attempt"]
        # Receipts are real controller observations in the next snapshot, including rejected actions.
        following = (
            agent.contexts[attempt]["context"]["observations"]
            if attempt < len(agent.contexts)
            else None
        )
        rows.append(
            {
                "attempt": attempt,
                "choice": choices.get(attempt),
                "controller": actions.get(attempt),
                "tool_observation": observations.get(attempt),
                "observations_after": following,
                "context_file": "model-contexts.json",
                "private_reasoning": "NOT_COLLECTED",
            }
        )
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["typhoon", "luna"], required=True)
    parser.add_argument("--cases")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--typhoon-run", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--source-manifest",
        type=Path,
        help="Repository JSON source snapshot; explicit use records NEW provenance, not V4 acceptance",
    )
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists() or output == ROOT / "outputs" or not output.is_relative_to(ROOT / "outputs"):
        raise SystemExit("Output must be a NEW directory below repository outputs")
    previous = read(args.typhoon_run / "report.json") if args.typhoon_run else None
    selected = select_cases(args.provider, args.cases, previous)
    frozen = verify_frozen(args.source_manifest)
    prepared = {sid: prepare(sid) for sid in selected}
    if args.provider == "luna":
        for sid, data in prepared.items():
            if data[0] != read(args.typhoon_run / sid / "input-case.json") or data[1] != read(
                args.typhoon_run / sid / "replayed-documents.json"
            ):
                raise SystemExit("Typhoon input drift; comparison refused")
    output.mkdir(parents=True)
    for sid, (case, docs, initial, expected, oracle, inputs) in prepared.items():
        folder = output / sid
        folder.mkdir()
        for name, data in (
            ("input-case", case),
            ("replayed-documents", docs),
            ("initial-context", initial),
            ("expected-evaluation-only", expected or oracle),
            ("input-manifest", inputs),
        ):
            save(folder / (name + ".json"), data)
    sources = [
        Path(__file__),
        ROOT / frozen["manifest"]["path"],
        SPEC,
        ROOT / "agent_app/tools/statement_report_fixtures.py",
        ROOT / "agent_app/tools/evaluate_statement_review.py",
        ROOT / "agent_app/tools/run_lending_openai_failed.py",
        *sorted((ROOT / "agent_app/src/merchant_sandbox").glob("*.py")),
        *sorted((ROOT / "agent_app/tests").glob("test_statement*.py")),
    ]
    for data in prepared.values():
        sources.extend(ROOT / entry["path"] for entry in data[5] if "path" in entry)
    if any(sid.startswith("C") for sid in selected):
        sources.append(prior.BASELINE / "cases.sqlite3")
    manifest = [receipt(p) for p in dict.fromkeys(sources) if p.exists()]
    save(output / "manifest.json", manifest)
    snapshot = output / "source-snapshot"
    for item in manifest:
        dest = snapshot / item["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT / item["path"]).read_bytes())
    report = {
        "run_status": "PREPARED",
        "provider": args.provider,
        "selected": selected,
        "cases": [],
        "frozen_preflight": frozen,
        "model": "typhoon-v2.5-30b-a3b-instruct" if args.provider == "typhoon" else "gpt-6-luna",
        "mode": "LIVE_PLANNER_SYNTHETIC_OCR_REPLAY_MOCK_ONBOARDING",
        "experiment_only": True,
        "human_final_decision_required": True,
        "max_total_tokens": 400000 if args.provider == "typhoon" else 300000,
        "luna_max_cost_estimate_usd": "0.04" if args.provider == "luna" else None,
        "comparison": "Same four-part/context-facts wrapper, frozen controller and oracles; provider transport/history differs. Not a pure model ablation.",
        "trace_scope": "Public tool choices, concise reasons and real observations; no private reasoning.",
    }
    save(output / "report.json", report)
    if args.prepare_only:
        report["frozen_after"] = prior.verify_frozen_after(frozen, args.source_manifest)
        save(output / "report.json", report)
        print(json.dumps({"status": "PREPARED_NO_API", "cases": selected}))
        return 0
    factory, budget = make_factory(
        args.provider, args.credential_file or ROOT / ".env", len(selected)
    )
    all_records, all_usage, stopped = [], [], False
    report["run_status"] = "RUNNING"
    for sid, (case, docs, initial, expected, oracle, _) in prepared.items():
        if stopped:
            report["cases"].append(
                {"id": sid, "status": "NOT_RUN", "reason": "provider_or_budget_stop"}
            )
            continue
        folder = output / sid
        print(sid + " START", flush=True)
        with (folder / "events.jsonl").open("x", encoding="utf-8") as stream:

            def event(value, sid=sid, stream=stream):
                stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                if value.get("kind") == "llm_attempt":
                    print(
                        json.dumps(
                            {
                                "case": sid,
                                "attempt": value.get("attempt"),
                                "tool": value.get("tool"),
                                "status": value.get("status"),
                                "usage": value.get("usage"),
                            }
                        ),
                        flush=True,
                    )

            agent = TracedAgent(
                factory(event),
                max_total_tokens=report["max_total_tokens"],
                previous_records=all_records,
                evidence_context=initial["statement_document_facts"],
            )
            try:
                result = run_review(case, docs, agent, max_calls=8, max_seconds=240, on_event=event)
            except Exception as exc:
                result = prior.technical_case(case, "runner_error:" + type(exc).__name__)
                stopped = True
            records = agent.call_records
            evaluation_records = evaluation_receipts(records, agent.choices)
            result["provider_api_calls"] = len(records)
            for name, data in (
                ("case", result),
                ("provider-calls", records),
                ("evaluation-receipts", evaluation_records),
                ("model-contexts", agent.contexts),
                ("public-choices", agent.choices),
                ("public-trace", public_trace(agent, result)),
                ("adapter-errors", agent.errors),
            ):
                save(folder / (name + ".json"), data)
            try:
                staff = build_staff_report(result, docs)
                save(folder / "staff-report.json", staff)
                (folder / "staff-report.md").write_text(
                    render_staff_report(staff), encoding="utf-8"
                )
                evaluated = evaluate_case(
                    sid, result, staff, expected, initial, oracle, evaluation_records
                )
            except Exception as exc:
                evaluated = {
                    "id": sid,
                    "status": "FAIL",
                    "state": result["state"],
                    "reason": "postprocess:" + type(exc).__name__,
                }
                stopped = True
            save(folder / "result.json", evaluated)
            all_records.extend(records)
            all_usage.extend(usage_rows(sid, args.provider, records))
            report["cases"].append(evaluated)
            stopped |= (
                agent.stopped
                or not records
                or any(
                    r.get("stop_batch") or not r.get("usage") or (r.get("http_status") or 0) >= 400
                    for r in records
                )
            )
            report["total_tokens"] = (
                sum(r["total_tokens"] for r in all_usage)
                if all(type(r["total_tokens"]) is int for r in all_usage)
                else None
            )
            report["provider_api_calls"] = len(all_records)
            report["budget"] = (
                budget.summary()
                if hasattr(budget, "summary")
                else {"calls_used": budget.used, "limit": budget.limit}
            )
            save(output / "per-request-usage.json", all_usage)
            save(output / "report.json", report)
            print(sid + " " + evaluated["status"] + " " + result["state"], flush=True)
    report["summary"] = dict(Counter(c["status"] for c in report["cases"]))
    report["run_status"] = "STOPPED" if stopped else "COMPLETED"
    report["frozen_after"] = prior.verify_frozen_after(frozen, args.source_manifest)
    report["manifest_drift"] = [
        p["path"] for p in manifest if receipt(ROOT / p["path"])["sha256"] != p["sha256"]
    ]
    save(output / "report.json", report)
    if all_usage:
        with (output / "per-request-usage.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as stream:
            writer = csv.DictWriter(
                stream, fieldnames=list(dict.fromkeys(k for row in all_usage for k in row))
            )
            writer.writeheader()
            writer.writerows(all_usage)
    print(
        json.dumps(
            {
                k: report.get(k)
                for k in (
                    "run_status",
                    "summary",
                    "provider_api_calls",
                    "total_tokens",
                    "budget",
                    "manifest_drift",
                )
            }
        ),
        flush=True,
    )
    return 2 if stopped or report["manifest_drift"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
