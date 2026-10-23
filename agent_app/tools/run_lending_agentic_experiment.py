"""Local live-planner experiment using immutable replayed OCR and mock onboarding.

Both CLI modes make live Typhoon planning calls when invoked by the run owner.
No OCR call, server, production DB, or approval endpoint is used. All writable
state is confined to a newly created outputs directory. Offline tests mock HTTP.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
import time
import uuid
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent_app/src"))

from merchant_sandbox.agentic_review import run_review  # noqa: E402
from merchant_sandbox.agentic_typhoon import (  # noqa: E402
    CallBudget,
    ContextCompletePlanner,
    TyphoonReviewAgent,
)
from merchant_sandbox.core import SandboxError, Store  # noqa: E402
from merchant_sandbox.lending import Documents, LendingController, app_input  # noqa: E402
from merchant_sandbox.typhoon import Config  # noqa: E402

BASELINE = ROOT / "outputs/lending-case-audit-20261023/offline-final"
FIXTURE = ROOT / "examples/merchant_sandbox/lending_scenarios_v1.json"
POLICY = ROOT / "docs/merchant_lending/demo_parameters.json"
EXECUTION_MODE = "LIVE_TYPHOON_LLM_REPLAYED_OCR_MOCK_ONBOARDING"


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def save(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )


def file_receipt(path, role):
    raw = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)),
        "role": role,
        "size": len(raw),
        "sha256": sha256(raw),
    }


def load_baseline(sid, baseline=BASELINE):
    """Only read the frozen per-case snapshot and document blobs; never Store it.

    The source DB contains a later human-revision boundary test for C01; use its
    original case.json rather than the mutable case payload in that DB.
    """
    if not re.fullmatch(r"C(?:0[1-9]|1[0-8])", sid):
        raise SandboxError("invalid_scenario_selection")
    path = baseline / sid / "case.json"
    raw_case = path.read_bytes()
    case = json.loads(raw_case)
    documents, receipts = (
        [],
        [
            {
                "path": str(path.relative_to(ROOT)),
                "role": "baseline_case",
                "sha256": sha256(raw_case),
            }
        ],
    )
    uri = (baseline / "cases.sqlite3").resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        for doc_id in case["document_ids"]:
            row = db.execute(
                "SELECT raw,metadata FROM documents WHERE id=? AND case_id=?", (doc_id, case["id"])
            ).fetchone()
            if row is None:
                raise SandboxError("baseline_document_missing")
            raw, raw_metadata = bytes(row[0]), row[1]
            metadata = json.loads(raw_metadata)
            pages = metadata.get("ocr_pages", [])
            if (
                metadata.get("id") != doc_id
                or metadata.get("case_id") != case["id"]
                or sha256(raw) != metadata.get("sha256")
                or sorted(p.get("page") for p in pages) != list(range(1, metadata["pages"] + 1))
                or any(not isinstance(p.get("text"), str) for p in pages)
            ):
                raise SandboxError("baseline_document_or_ocr_integrity_failed")
            documents.append({"raw": raw, "metadata": metadata})
            receipts.append(
                {
                    "role": "replayed_document",
                    "document_id": doc_id,
                    "raw_sha256": sha256(raw),
                    "metadata_sha256": sha256(raw_metadata.encode("utf-8")),
                    "ocr_sha256": sha256(json_bytes(pages)),
                    "ocr_page_count": len(pages),
                }
            )
    return case, documents, receipts


def fresh_context_case(store, documents, base, loaded):
    """New isolated Store/Documents, exact baseline OCR replay, same as_of time."""
    data = {k: v for k, v in deepcopy(base["input"]).items() if k != "scenario"}
    case = store.create(
        app_input(data), "local-replay-" + uuid.uuid4().hex, owner_id=base["owner_id"]
    )
    case["created_at"] = base["created_at"]
    case["decision"] = None
    case["policy_snapshot"] = deepcopy(base["policy_snapshot"])
    # Preserve the evidence version without carrying any old analysis forward.
    case["version"] = base["version"]
    case["snapshot"] = case["id"] + ":v" + str(case["version"])
    with store.connect() as db:
        for item in loaded:
            doc = deepcopy(item["metadata"])
            doc.update(id="DOC-" + uuid.uuid4().hex[:16], case_id=case["id"])
            db.execute(
                "INSERT INTO documents VALUES (?,?,?,?)",
                (doc["id"], case["id"], item["raw"], json.dumps(doc, ensure_ascii=False)),
            )
            case["document_ids"].append(doc["id"])
    store.save(case)
    # Fail closed before the legacy controller can consider an extraction call.
    if any(len(d["ocr_pages"]) != d["pages"] for d in documents.list(case)):
        raise SandboxError("ocr_replay_incomplete")
    return case


def audit_module():
    path = ROOT / "agent_app/tools/run_lending_scenario_audit.py"
    spec = importlib.util.spec_from_file_location("immutable_scenario_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def technical_case(base, code):
    case = deepcopy(base)
    results = {
        k: v
        for k, v in case.get("results", {}).items()
        if k not in {"financial_calculate", "policy_evaluate"}
    }
    trace = case.get("trace", []) + [{"kind": "technical_stop", "error": code}]
    case.update(
        state="TECHNICAL_REVIEW",
        active=False,
        decision=None,
        packet=None,
        results=results,
        trace=trace,
        feedback=["การทดลองหยุดทางเทคนิค ให้เจ้าหน้าที่ตรวจต่อ ไม่มีข้อสรุปเครดิต"],
        llm_calls=0,
    )
    return case


def aggregate_usage(records):
    total = {}
    for record in records:
        for key, value in (record.get("usage") or {}).items():
            total[key] = total.get(key, 0) + value
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("agentic", "context-only"), required=True)
    parser.add_argument("--cases", default="")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--max-calls", type=int, default=8)
    parser.add_argument("--max-seconds", type=float, default=240)
    parser.add_argument("--max-total-calls", type=int)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if (
        output.exists()
        or not output.is_relative_to((ROOT / "outputs").resolve())
        or output == (ROOT / "outputs").resolve()
    ):
        raise SystemExit("Refusing preexisting output or output outside repository outputs/")
    if not 1 <= args.max_calls <= 8 or not 1 <= args.max_seconds <= 600:
        raise SystemExit("Budgets require 1..8 calls and 1..600 seconds per case")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    selected = args.cases.split(",") if args.cases else [s["id"] for s in fixture["scenarios"]]
    known = {s["id"] for s in fixture["scenarios"]}
    if len(set(selected)) != len(selected) or any(s not in known for s in selected):
        raise SystemExit("Unknown or duplicate scenario IDs")
    total_limit = (
        args.max_total_calls if args.max_total_calls is not None else len(selected) * args.max_calls
    )
    if not 1 <= total_limit <= len(selected) * args.max_calls:
        raise SystemExit("Total budget must be positive and at most selected cases * max-calls")
    budget = CallBudget(total_limit)
    audit = audit_module()
    baseline_report = json.loads((BASELINE / "report.json").read_text(encoding="utf-8"))
    if baseline_report.get("fixture_sha256") != sha256(FIXTURE.read_bytes()) or baseline_report.get(
        "policy_sha256"
    ) != sha256(POLICY.read_bytes()):
        raise SystemExit("Fixture/policy differ from the immutable baseline")
    manifest = [
        file_receipt(path, role)
        for path, role in [
            (FIXTURE, "fixture"),
            (POLICY, "policy"),
            (BASELINE / "report.json", "baseline_report"),
            (BASELINE / "cases.sqlite3", "baseline_database"),
            (Path(__file__).resolve(), "runner_source"),
            (ROOT / "agent_app/tools/run_lending_scenario_audit.py", "unchanged_evaluator_source"),
        ]
    ]
    manifest.extend(
        file_receipt(p, "source")
        for p in sorted((ROOT / "agent_app/src/merchant_sandbox").glob("*.py"))
    )
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "execution_mode": EXECUTION_MODE,
        "mode": args.mode,
        "experiment_only": True,
        "human_final_decision_required": True,
        "not_for_decision_endpoint": True,
        "customer_data": "SYNTHETIC_ONLY",
        "ocr_calls": 0,
        "onboarding": "MOCK_NOT_REAL_KYC",
        "baseline_mode": baseline_report.get("mode"),
        "baseline_summary": baseline_report.get("summary"),
        "provenance": "Exact per-case frozen case.json plus baseline SQLite raw/metadata/OCR pages; no regenerated OCR. Context-only uses a new isolated Store/Documents and MockBank.",
        "trace_warning": "Legacy document_extract trace may say LIVE_PROVIDER; all OCR is preloaded. Execution mode and OCR hashes in this report are authoritative.",
        "budget": {
            "max_calls": args.max_calls,
            "max_seconds": args.max_seconds,
            "max_total_calls": total_limit,
        },
        "manifest": manifest,
        "cases": [],
        "summary": {"PASS": 0, "PARTIAL": 0, "FAIL": 0},
        "llm_calls": 0,
        "llm_call_attempts": 0,
        "usage": {},
        "duration_ms": 0,
        "run_status": "RUNNING",
    }
    save(output / "report.json", report)
    started = time.monotonic()
    all_records = []
    try:
        cfg = Config.load(args.credential_file)
        # Validate before any case is entered; never print credentials/config repr.
        TyphoonReviewAgent(cfg)
        store = Store(output / "cases.sqlite3") if args.mode == "context-only" else None
        documents = Documents(store) if store else None
        for sid in selected:
            folder = output / sid
            folder.mkdir()
            base, case, agent, inputs = {}, {}, None, []
            case_started = time.monotonic()
            technical = None
            with (folder / "events.jsonl").open("x", encoding="utf-8") as event_file:

                def event(value):
                    event_file.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
                    event_file.flush()

                try:
                    base, loaded, inputs = load_baseline(sid)
                    if base["created_at"] != fixture["as_of"]:
                        raise SandboxError("fixture_as_of_mismatch")
                    if base["policy_snapshot"] != json.loads(POLICY.read_text(encoding="utf-8")):
                        raise SandboxError("baseline_case_policy_mismatch")
                    spec = next(s for s in fixture["scenarios"] if s["id"] == sid)
                    oracle_path = BASELINE / sid / "oracle.json"
                    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
                    if oracle["scenario"] != spec:
                        raise SandboxError("fixture_oracle_mismatch")
                    inputs.append(
                        file_receipt(oracle_path, "evaluation_oracle_never_sent_to_model")
                    )
                    case = deepcopy(base)
                    case.update(
                        state="DRAFT",
                        active=False,
                        decision=None,
                        trace=[],
                        packet=None,
                        attempts={},
                    )
                    options = dict(
                        max_calls=args.max_calls,
                        max_seconds=args.max_seconds,
                        budget=budget,
                        on_record=event,
                    )
                    if args.mode == "agentic":
                        agent = TyphoonReviewAgent(cfg, **options)
                        case = run_review(
                            case,
                            [d["metadata"] for d in loaded],
                            agent,
                            max_calls=args.max_calls,
                            max_seconds=args.max_seconds,
                            on_event=event,
                        )
                    else:
                        case = fresh_context_case(store, documents, base, loaded)
                        agent = ContextCompletePlanner(cfg, **options)
                        controller = LendingController(
                            store, documents, cfg, bank=audit.MockBank(case["owner_id"])
                        )
                        case = controller.run(case["id"], agent, case["version"])
                    # Exactly the same evaluator function and oracle as baseline.
                    result = audit.evaluate(spec, oracle["truth"], case)
                    if case["state"] == "TECHNICAL_REVIEW":
                        technical = "bounded_review_technical_stop"
                except Exception as exc:
                    # Never serialize exception text, provider response or credentials.
                    # Preserve already completed actions and partial case if available.
                    technical = "case_execution_failed:" + type(exc).__name__
                    if case and agent and agent.call_records and args.mode == "context-only":
                        try:
                            case = store.get(case["id"])
                        except (SandboxError, sqlite3.Error):
                            pass
                    case = technical_case(case or base, technical)
                    result = {
                        "id": sid,
                        "status": "FAIL",
                        "checks": [],
                        "state": "TECHNICAL_REVIEW",
                        "technical_error": technical,
                    }
                    event({"kind": "technical_stop", "error": technical})
                records = agent.call_records if agent else []
                all_records.extend(records)
                if technical:
                    result.update(status="FAIL", technical_error=technical)
                for trace_event in case.get("trace", []):
                    if trace_event.get("kind") != "agent_action":
                        event({"kind": "case_trace", "event": trace_event})
                result.update(
                    execution_mode=EXECUTION_MODE,
                    llm_calls=len(records),
                    llm_call_attempts=len(records),
                    controller_llm_attempts=case.get("llm_calls", 0),
                    attempts=records,
                    usage=aggregate_usage(records),
                    duration_ms=round((time.monotonic() - case_started) * 1000),
                    inputs=inputs,
                )
                save(folder / "case.json", case)
                save(folder / "result.json", result)
                save(folder / "input-manifest.json", inputs)
                manifest.extend(inputs)
                report["cases"].append(result)
                report["summary"][result["status"]] += 1
                report.update(
                    llm_calls=budget.used,
                    llm_call_attempts=budget.used,
                    usage=aggregate_usage(all_records),
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
                save(output / "report.json", report)
                print(
                    f"{sid} {result['status']} {case.get('state', 'TECHNICAL_REVIEW')} llm_calls={len(records)}",
                    flush=True,
                )
        report["run_status"] = (
            "COMPLETE_WITH_TECHNICAL_FAILURES"
            if any(r.get("technical_error") for r in report["cases"])
            else "COMPLETE"
        )
    except Exception as exc:
        report.update(
            run_status="TECHNICAL_FAILURE", technical_error="run_failed:" + type(exc).__name__
        )
        raise SystemExit("Experiment failed; redacted receipt retained in output") from None
    finally:
        report["duration_ms"] = round((time.monotonic() - started) * 1000)
        unchanged = all(
            (ROOT / r["path"]).is_file() and sha256((ROOT / r["path"]).read_bytes()) == r["sha256"]
            for r in manifest
            if "path" in r and "sha256" in r
        )
        report["manifest_inputs_unchanged"] = unchanged
        if not unchanged:
            report["run_status"] = "INPUT_DRIFT_DETECTED"
        save(output / "report.json", report)
    print(
        json.dumps(
            {
                "summary": report["summary"],
                "llm_calls": budget.used,
                "run_status": report["run_status"],
            }
        ),
        flush=True,
    )
    return report


if __name__ == "__main__":
    main()
