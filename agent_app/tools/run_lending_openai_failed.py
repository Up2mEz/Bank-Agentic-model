"""Bounded Luna comparison on frozen synthetic cases; never a lending endpoint.

Uses unchanged financial controller and original oracles. OCR is replayed. Every
generation request is recorded separately; no API or model fallback is allowed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent_app/src"))
sys.path.insert(0, str(ROOT / "agent_app/tools"))

from evaluate_lending_agentic_experiment import additional_checks  # noqa: E402
from run_lending_agentic_experiment import (  # noqa: E402
    BASELINE,
    FIXTURE,
    POLICY,
    audit_module,
    load_baseline,
    technical_case,
)
from run_lending_agentic_heldout import evaluate as evaluate_heldout  # noqa: E402

from merchant_sandbox.agentic_review import ReviewSession, run_review  # noqa: E402

PREVIOUS = ROOT / "outputs/lending-agentic-local-20261023"
ORDER = ["H01", "C01", "C03", "C05", "C06", "C08", "C09", "C11", "C12", "C14", "C16"]
ACTION_LABELS = {
    "read_transactions": "อ่านรายการและหลักฐานอ้างอิง",
    "match_transfers": "ตรวจคู่โอนระหว่างบัญชี",
    "compare_declarations": "เทียบคำแจ้งลูกค้ากับหลักฐาน",
    "flag_transactions": "เปิดประเด็นที่ต้องตรวจเพิ่ม",
    "propose_findings": "เสนอความหมายและหลักฐานที่ต้องขอ",
    "inspect_cashflow": "เรียกเครื่องมือคำนวณกระแสเงินสด",
    "finish_review": "ส่งข้อมูลและข้อค้างให้เจ้าหน้าที่",
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )


def receipt(path):
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def required_source_paths():
    """Shared source coverage for both runners; replay inputs have run receipts."""
    tools = (
        "run_lending_openai_failed.py",
        "run_statement_review_experiment.py",
        "run_lending_scenario_audit.py",
        "run_lending_agentic_experiment.py",
        "run_lending_agentic_heldout.py",
        "evaluate_lending_agentic_experiment.py",
        "statement_report_fixtures.py",
        "evaluate_statement_review.py",
    )
    return {
        *(
            p.relative_to(ROOT).as_posix()
            for p in (ROOT / "agent_app/src/merchant_sandbox").rglob("*.py")
        ),
        *("agent_app/tools/" + name for name in tools),
        POLICY.relative_to(ROOT).as_posix(),
        FIXTURE.relative_to(ROOT).as_posix(),
        "examples/merchant_sandbox/statement_review_additional_v1.json",
    }


def verify_frozen(manifest_path=None):
    """Default to the unchanged V4 guard; an explicit manifest is a NEW snapshot.

    JSON shape: {"files": [{"path": "repository/relative/file", "sha256": "64 hex"}]}.
    Explicit snapshots must cover required_source_paths(), never confer V4
    acceptance, and must themselves reside in this repository for run receipts.
    """
    explicit = manifest_path is not None
    path = Path(manifest_path) if explicit else PREVIOUS / "source-v4-manifest.json"
    try:
        path = path.resolve()
        if not path.is_relative_to(ROOT.resolve()):
            raise ValueError("manifest_path_escape")
        raw = path.read_bytes()
        manifest = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
            raise ValueError("invalid_manifest")
        if not manifest["files"]:
            raise ValueError("empty_manifest")
        entries, identities = {}, set()
        for entry in manifest["files"]:
            if not isinstance(entry, dict):
                raise ValueError("invalid_entry")
            name, digest = entry.get("path"), entry.get("sha256")
            if (
                not isinstance(name, str)
                or not name
                or "\\" in name
                or ":" in name
                or "\x00" in name
                or PurePosixPath(name).is_absolute()
                or ".." in PurePosixPath(name).parts
                or PurePosixPath(name).as_posix() != name
            ):
                raise ValueError("invalid_repository_path")
            target = (ROOT / name).resolve()
            if not target.is_relative_to(ROOT.resolve()):
                raise ValueError("source_path_escape")
            identity = target.as_posix().casefold()
            if identity in identities:
                raise ValueError("duplicate_source_path")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                raise ValueError("invalid_sha256")
            identities.add(identity)
            entries[name] = (target, digest.lower())
        if explicit and (missing := required_source_paths() - entries.keys()):
            raise ValueError("incomplete_source_coverage:" + ",".join(sorted(missing)))
    except (OSError, ValueError, TypeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "manifest_unreadable"
        raise RuntimeError("frozen_source_drift:" + reason) from None
    drift = []
    for name, (target, digest) in entries.items():
        try:
            matches = hashlib.sha256(target.read_bytes()).hexdigest() == digest
        except OSError:
            matches = False
        if not matches:
            drift.append(name)
    if drift:
        raise RuntimeError("frozen_source_drift:" + ",".join(drift))
    return {
        "files": len(entries),
        "drift": [],
        "snapshot_kind": "EXPLICIT_SOURCE_SNAPSHOT" if explicit else "V4_FROZEN_SOURCE",
        "v4_acceptance": False if explicit else None,
        "manifest": {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
    }


def verify_frozen_after(before, manifest_path=None):
    after = verify_frozen(manifest_path)
    if after != before:
        raise RuntimeError("frozen_source_drift:source_manifest_changed")
    return after


def load_input(sid):
    if sid.startswith("C"):
        case, loaded, inputs = load_baseline(sid)
        docs = [d["metadata"] for d in loaded]
        case.update(state="DRAFT", active=False, decision=None, trace=[], packet=None, attempts={})
        oracle_path = BASELINE / sid / "oracle.json"
        inputs.append({**receipt(oracle_path), "role": "evaluation_only_never_sent_to_model"})
        oracle = read(oracle_path)
    else:
        folder = PREVIOUS / "heldout-v4-final" / sid
        case = read(folder / "input-case.json")
        docs = read(folder / "replayed-documents.json")
        inputs = [receipt(folder / p) for p in ("input-case.json", "replayed-documents.json")]
        oracle = None
    if case["policy_snapshot"] != read(POLICY):
        raise RuntimeError("policy_snapshot_mismatch")
    initial = ReviewSession(deepcopy(case), deepcopy(docs)).context()
    return case, docs, initial, oracle, inputs


def native_checks(case, records):
    accepted = [
        x
        for x in case.get("trace", [])
        if x.get("kind") == "agent_action" and x.get("status") == "ACCEPTED"
    ]
    return [
        {
            "requirement": "live OpenAI choices and provider receipts",
            "passed": case.get("agent_mode") == "openai"
            and bool(accepted)
            and bool(records)
            and all(x.get("model") == "gpt-6-luna" for x in accepted),
        },
        {
            "requirement": "bounded human handoff completed",
            "passed": 1 <= len(records) <= 8
            and any(x.get("tool") == "finish_review" for x in accepted)
            and case.get("state") != "TECHNICAL_REVIEW",
        },
    ]


def evaluate(sid, case, initial, oracle, records):
    if sid.startswith("C"):
        result = audit_module().evaluate(oracle["scenario"], oracle["truth"], case)
        # The first two original supplemental assertions hardcode Typhoon mode
        # and its llm_calls field. Keep their financial assertions unchanged and
        # report the explicit provider-equivalent replacements separately.
        extra = native_checks(case, records) + additional_checks(sid, case)[2:]
    else:
        result = evaluate_heldout(sid, case, initial)
        extra = native_checks(case, records)
    status = result["status"]
    if case.get("state") == "TECHNICAL_REVIEW" or not all(x["passed"] for x in extra):
        status = "FAIL"
    return {
        "id": sid,
        "status": status,
        "original_oracle_status": result["status"],
        "oracle": result,
        "supplemental_checks": extra,
        "state": case.get("state"),
        "decision": case.get("decision"),
        "api_calls": len(records),
    }


def usage_row(sid, record):
    usage = record.get("usage") or {}
    input_detail = usage.get("input_tokens_details") or {}
    output_detail = usage.get("output_tokens_details") or {}
    cached = usage.get("cached_input_tokens", input_detail.get("cached_tokens"))
    reasoning = usage.get("reasoning_tokens", output_detail.get("reasoning_tokens"))
    inp, out = usage.get("input_tokens"), usage.get("output_tokens")
    estimated = None
    if all(type(v) is int for v in (inp, out, cached)):
        estimated = str(
            (
                Decimal(inp - cached) * Decimal("0.10")
                + Decimal(cached) * Decimal("0.01")
                + Decimal(out) * Decimal("0.50")
            )
            / Decimal(1000000)
        )
    return {
        "case": sid,
        "request": record.get("attempt"),
        "tool": record.get("tool"),
        "action_summary_th": ACTION_LABELS.get(record.get("tool"), "ไม่ได้รับ tool call ที่ใช้ได้"),
        "status": record.get("status"),
        "input_tokens": inp,
        "cached_input_tokens": cached,
        "output_tokens": out,
        "reasoning_tokens": reasoning,
        "total_tokens": usage.get("total_tokens"),
        "estimated_standard_cost_usd_excluding_cache_writes": estimated,
        "accounted_cost_estimate_usd": record.get("cost_estimate_usd"),
        "context_bytes": record.get("context_bytes"),
        "tool_schema_bytes": record.get("tool_bytes"),
        "duration_ms": record.get("duration_ms"),
        "http_status": record.get("http_status"),
        "request_id": record.get("request_id"),
    }


def write_usage(output, calls):
    rows = [usage_row(sid, record) for sid, records in calls.items() for record in records]
    save(output / "per-request-usage.json", rows)
    if rows:
        with (output / "per-request-usage.csv").open(
            "w", newline="", encoding="utf-8-sig"
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    totals = []
    for sid, records in calls.items():
        own = [row for row in rows if row["case"] == sid]
        total = {
            "case": sid,
            "api_calls": len(records),
            "usage_missing_requests": sum(row["total_tokens"] is None for row in own),
        }
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        ):
            total[key] = (
                sum(row[key] for row in own) if all(type(row[key]) is int for row in own) else None
            )
        costs = [row["accounted_cost_estimate_usd"] for row in own]
        total["accounted_cost_estimate_usd"] = (
            str(sum((Decimal(cost) for cost in costs), Decimal(0)))
            if costs and all(cost is not None for cost in costs)
            else None
        )
        totals.append(total)
    save(output / "per-case-usage.json", totals)
    return totals


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", default=",".join(ORDER))
    parser.add_argument("--credential-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--source-manifest",
        type=Path,
        help="Repository JSON source snapshot; explicit use records NEW provenance, not V4 acceptance",
    )
    args = parser.parse_args(argv)
    selected = args.cases.split(",")
    if len(set(selected)) != len(selected) or set(selected) - set(ORDER) or not selected:
        raise SystemExit("Select unique previously non-passing cases only")
    output = args.output.resolve()
    if output.exists() or output == ROOT / "outputs" or not output.is_relative_to(ROOT / "outputs"):
        raise SystemExit("Output must be a NEW directory below repository outputs")
    frozen = verify_frozen(args.source_manifest)
    previous = {
        r["id"]: r["status"] for r in read(PREVIOUS / "agentic-v4-final/report.json")["cases"]
    }
    previous["H01"] = "FAIL"
    if any(previous[sid] == "PASS" for sid in selected):
        raise SystemExit("Selection includes a passing case")
    output.mkdir(parents=True)
    prepared, inputs = {}, []
    for sid in selected:
        prepared[sid] = load_input(sid)
        case, documents, initial, _, source_inputs = prepared[sid]
        directory = output / sid
        directory.mkdir()
        save(directory / "input-case.json", case)
        save(directory / "replayed-documents.json", documents)
        save(directory / "initial-context.json", initial)
        save(directory / "input-manifest.json", source_inputs)
        inputs.extend(source_inputs)
    sources = [
        Path(__file__),
        FIXTURE,
        POLICY,
        BASELINE / "cases.sqlite3",
        ROOT / frozen["manifest"]["path"],
        PREVIOUS / "agentic-v4-final/report.json",
        ROOT / "agent_app/tools/run_lending_scenario_audit.py",
        ROOT / "agent_app/tools/run_lending_agentic_experiment.py",
        ROOT / "agent_app/tools/run_lending_agentic_heldout.py",
        ROOT / "agent_app/tools/evaluate_lending_agentic_experiment.py",
        *sorted((ROOT / "agent_app/src/merchant_sandbox").glob("*.py")),
    ]
    manifest = [receipt(p) for p in sources] + inputs
    save(output / "manifest.json", manifest)
    report = {
        "run_status": "PREPARED",
        "model": "gpt-6-luna",
        "reasoning_effort": "medium",
        "context_mode": "COMPACT_STATELESS_COMPLETE_SNAPSHOT",
        "comparison_limit": "Provider/API/strict schema/context serialization differ; not a pure model-only ablation. Failed-case subset only, no whole-suite accuracy claim.",
        "customer_data": "SYNTHETIC_ONLY",
        "ocr": "EXACT_FROZEN_REPLAY_NO_NEW_OCR",
        "onboarding": "MOCK",
        "experiment_only": True,
        "human_final_decision_required": True,
        "selected": selected,
        "previous_status": previous,
        "frozen_preflight": frozen,
        "cases": [],
        "case_budget": {"max_calls": 8, "max_seconds": 240, "max_output_tokens_per_request": 4096},
        "batch_budget": {
            "max_calls": min(88, len(selected) * 8),
            "max_input_tokens": 400000,
            "max_output_tokens": 64000,
            "max_cost_usd": "0.10",
        },
        "usage_note": "Input includes cached tokens; output includes reasoning. Subsets must not be added again. Missing usage is unknown, not free. Estimates are not an account balance or invoice.",
    }
    save(output / "report.json", report)
    if args.prepare_only:
        report["frozen_after"] = verify_frozen_after(frozen, args.source_manifest)
        save(output / "report.json", report)
        print(
            json.dumps(
                {
                    "status": "PREPARED_NO_API_CALLS",
                    "cases": selected,
                    "source_files": len(manifest),
                }
            )
        )
        return 0
    from merchant_sandbox.agentic_openai import OpenAIConfig, OpenAIReviewAgent, TokenBudget

    config = OpenAIConfig.load(args.credential_file, credential_env="OPENAI")
    budget = TokenBudget(**report["batch_budget"])
    all_calls = {}
    report["run_status"] = "RUNNING"
    save(output / "report.json", report)
    fatal = False
    for sid in selected:
        if fatal:
            report["cases"].append(
                {
                    "id": sid,
                    "status": "NOT_RUN",
                    "reason": "batch_stopped_on_provider_or_budget_failure",
                }
            )
            continue
        case, docs, initial, oracle, _ = prepared[sid]
        directory = output / sid
        print(sid + " START", flush=True)
        with (directory / "events.jsonl").open("x", encoding="utf-8") as stream:

            def event(value, sid=sid, stream=stream):
                stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                if value.get("kind") == "llm_attempt":
                    print(
                        json.dumps(
                            {
                                "case": sid,
                                "request": value.get("attempt"),
                                "tool": value.get("tool"),
                                "status": value.get("status"),
                                "usage": value.get("usage"),
                            }
                        ),
                        flush=True,
                    )

            agent = OpenAIReviewAgent(
                config, budget=budget, max_calls=8, max_seconds=240, on_record=event
            )
            try:
                result = run_review(case, docs, agent, max_calls=8, max_seconds=240, on_event=event)
            except Exception as exc:
                result = technical_case(case, "runner_error:" + type(exc).__name__)
                fatal = True
            records = agent.call_records
            result["provider_api_calls"] = len(records)
            all_calls[sid] = records
            evaluated = evaluate(sid, result, initial, oracle, records)
            evaluated["previous_status"] = previous[sid]
            save(directory / "case.json", result)
            save(directory / "provider-calls.json", records)
            save(directory / "result.json", evaluated)
            report["cases"].append(evaluated)
            # Do not spend repeated requests diagnosing account/endpoint faults.
            if any(
                r.get("stop_batch")
                or (isinstance(r.get("http_status"), int) and r["http_status"] >= 400)
                or not r.get("usage")
                for r in records
            ):
                fatal = True
            if not records:
                fatal = True
            report["usage_by_case"] = write_usage(output, all_calls)
            report["budget"] = budget.summary()
            save(output / "report.json", report)
            print(
                sid + " " + evaluated["status"] + " " + result.get("state", "unknown"), flush=True
            )
    report["summary"] = dict(Counter(row["status"] for row in report["cases"]))
    report["frozen_after"] = verify_frozen_after(frozen, args.source_manifest)
    report["manifest_drift"] = [
        entry["path"]
        for entry in manifest
        if "path" in entry
        and "sha256" in entry
        and receipt(ROOT / entry["path"])["sha256"].lower() != entry["sha256"].lower()
    ]
    report["run_status"] = "STOPPED" if fatal else "COMPLETED"
    report["coverage_complete"] = len(report["cases"]) == len(selected) and all(
        row["status"] != "NOT_RUN" for row in report["cases"]
    )
    report["budget"] = budget.summary()
    save(output / "report.json", report)
    print(
        json.dumps(
            {
                "status": report["run_status"],
                "summary": report["summary"],
                "budget": report["budget"],
            }
        ),
        flush=True,
    )
    return 0 if not fatal and report["coverage_complete"] and not report["manifest_drift"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
