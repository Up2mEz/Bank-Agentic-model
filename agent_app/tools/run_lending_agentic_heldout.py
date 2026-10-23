"""Four predeclared synthetic probes, live Typhoon reasoning and fixture OCR.

No network OCR, onboarding, HTTP service or database writes. Expectations are
evaluated only after each model run and never enter its context.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent_app/src"))
sys.path.insert(0, str(ROOT / "agent_app/tools"))

from run_lending_scenario_audit import MockBank, make_document, save  # noqa: E402

from merchant_sandbox.agentic_review import ReviewSession, run_review  # noqa: E402
from merchant_sandbox.agentic_typhoon import TyphoonReviewAgent  # noqa: E402
from merchant_sandbox.core import default_input  # noqa: E402
from merchant_sandbox.typhoon import Config  # noqa: E402


def build(sid, fixtures):
    amounts = [200000] * 6
    memo = "shop sales"
    message = "ตรวจเอกสารเพื่อเสนอให้เจ้าหน้าที่"
    if sid == "H01":
        memo = "shop sales - old equipment disposal proceeds"
    if sid == "H02":
        memo = "sales transfer from outside account"
    if sid == "H03":
        message = "แจ้งยอดขายรวมของร้านเดือนละ 275,000 บาท ค่าใช้จ่ายต้นทุนธุรกิจทั้งหมด 25,000 บาทต่อเดือน"
    if sid == "H04":
        amounts[1] = 178000
    rows = [
        (f"{month}-{day}", label, debit, credit)
        for month, sales in zip(fixtures["months"], amounts, strict=True)
        for day, label, debit, credit in [
            ("02", memo, 0, sales),
            ("10", "cost of goods", 100000, 0),
            ("15", "rent", 45000, 0),
        ]
    ]
    printed = make_document(rows)
    data = default_input()
    data.update(applicant_name="Mali Jaidee", message=message)
    for key in ("living_cost_thb", "debt_thb", "requested_thb"):
        data[key] = fixtures["base"][key]
    case = {
        "id": "CASE-synthetic",
        "version": 1,
        "snapshot": "CASE-synthetic:v1",
        "created_at": fixtures["as_of"],
        "input": data,
        "state": "DRAFT",
        "active": False,
        "decision": None,
        "trace": [],
        "is_mock": True,
        "policy_snapshot": json.loads(
            (ROOT / "docs/merchant_lending/demo_parameters.json").read_text(encoding="utf-8")
        ),
        "results": {
            "onboarding_read": {
                "status": "OK",
                "snapshot": MockBank("synthetic-owner").read("synthetic-owner"),
            },
            "identity_verify": {"status": "PENDING_REVIEW", "real_identity_verified": False},
        },
    }
    documents = [
        {
            "id": "DOC-evidence",
            "case_id": case["id"],
            "kind": "statement",
            "sha256": hashlib.sha256(printed["raw"]).hexdigest(),
            "pages": 1,
            "ocr_pages": [{"page": 1, "text": printed["text"]}],
        }
    ]
    return case, documents, printed


def evaluate(sid, result, initial):
    packet = result.get("packet") or {}
    issues = packet.get("issues", [])
    evidence = result.get("results", {}).get("evidence", {})
    actions = [
        e
        for e in result.get("trace", [])
        if e.get("kind") == "agent_action" and e.get("status") == "ACCEPTED"
    ]
    checks = []

    def check(name, value):
        checks.append({"requirement": name, "passed": bool(value)})

    check(
        "bounded human handoff, not technical stop or automatic decision",
        any(e.get("tool") == "finish_review" for e in actions)
        and result.get("state") in {"EXCEPTION_REVIEW", "WAIT_CUSTOMER"}
        and result.get("decision") is None
        and packet.get("not_for_decision_endpoint") is True,
    )
    if sid == "H01":
        check("initial detector did not flag the recurring source", not initial["issues"])
        check(
            "model read and raised a novel evidence issue",
            any(e.get("tool") == "read_transactions" for e in actions)
            and any(e.get("tool") == "flag_transactions" for e in actions),
        )
    if sid in {"H01", "H02"}:
        check(
            "uncertain incoming money not included in recurring revenue",
            all(m.get("R") == "0.00" for m in evidence.get("months", []))
            and not result.get("results", {}).get("financial_calculate"),
        )
        check(
            "specific evidence request remains open",
            any(i.get("status") == "OPEN" and i.get("refs") and i.get("question") for i in issues),
        )
    if sid == "H02":
        check(
            "missing counterparty cannot be proven own transfer",
            not any(x.get("reason") == "OWN_TRANSFER" for x in evidence.get("excluded", [])),
        )
    if sid == "H03":
        mismatches = [i for i in issues if i.get("code") == "DECLARATION_MISMATCH"]
        check(
            "novel comma-formatted amounts both extracted and compared",
            {(i.get("expected"), i.get("observed")) for i in mismatches}
            == {("275000.00", "200000.00"), ("25000.00", "145000.00")}
            and all(i.get("refs") for i in mismatches),
        )
    if sid == "H04":
        rows = (packet.get("monthly_cashflow") or {}).get("rows", [])
        check(
            "positive 8000 residual fails after reserve and offered new installment",
            any(
                r.get("month") == "2026-05"
                and r.get("residual_before_reserve_thb") == "8000.00"
                and float(r.get("after_reserve_and_new_installment_thb", "0")) < 0
                for r in rows
            )
            and any(
                i.get("code") == "LIQUIDITY_GAP" and "2026-05" in i.get("question", "")
                for i in issues
            ),
        )
    return {
        "id": sid,
        "status": "PASS" if all(c["passed"] for c in checks) else "FAIL",
        "checks": checks,
        "calls": result.get("llm_calls"),
        "state": result.get("state"),
        "actions": [e["tool"] for e in actions],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--cases", default="H01,H02,H03,H04")
    args = parser.parse_args()
    selected = args.cases.split(",")
    if len(set(selected)) != len(selected) or set(selected) - {"H01", "H02", "H03", "H04"}:
        raise SystemExit("Unknown or repeated held-out case")
    args.output = args.output.resolve()
    if args.output.exists() or not args.output.is_relative_to((ROOT / "outputs").resolve()):
        raise SystemExit("Refusing preexisting output or output outside repository outputs")
    config = Config.load(args.credential_file)
    TyphoonReviewAgent(config)
    fixtures = json.loads(
        (ROOT / "examples/merchant_sandbox/lending_scenarios_v1.json").read_text(encoding="utf-8")
    )
    args.output.mkdir(parents=True)
    sources = [
        Path(__file__),
        ROOT / "agent_app/tools/run_lending_scenario_audit.py",
        ROOT / "examples/merchant_sandbox/lending_scenarios_v1.json",
        ROOT / "docs/merchant_lending/demo_parameters.json",
        ROOT / "docs/merchant_lending/LOCAL_AGENTIC_EXPERIMENT_DESIGN_TH.md",
        *sorted((ROOT / "agent_app/src/merchant_sandbox").glob("*.py")),
    ]
    save(
        args.output / "manifest.json",
        [
            {"path": str(p.relative_to(ROOT)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sources
        ],
    )
    reports = []
    for sid in selected:
        print(f"{sid} START", flush=True)
        case, documents, printed = build(sid, fixtures)
        directory = args.output / sid
        directory.mkdir()
        (directory / "statement.pdf").write_bytes(printed["raw"])
        save(directory / "input-case.json", case)
        save(directory / "replayed-documents.json", documents)
        initial = ReviewSession(case, documents).context()
        save(directory / "initial-context.json", initial)
        with (directory / "events.jsonl").open("w", encoding="utf-8") as stream:

            def event(value, sid=sid):
                stream.write(json.dumps(value, ensure_ascii=False) + "\n")
                stream.flush()
                print(
                    f"{sid} {value.get('kind')} call={value.get('call', value.get('attempt'))} tool={value.get('tool')} status={value.get('status')}",
                    flush=True,
                )

            agent = TyphoonReviewAgent(config, max_calls=8, max_seconds=240, on_record=event)
            result = run_review(
                case, documents, agent, max_calls=8, max_seconds=240, on_event=event
            )
        save(directory / "case.json", result)
        save(directory / "provider-calls.json", agent.call_records)
        report = evaluate(sid, result, initial)
        save(directory / "result.json", report)
        reports.append(report)
        save(
            args.output / "report.json",
            {
                "mode": "LIVE_TYPHOON_LLM_FIXTURE_OCR_MOCK_ONBOARDING",
                "external_validation": False,
                "summary": dict(Counter(r["status"] for r in reports)),
                "llm_calls": sum(r["calls"] for r in reports),
                "cases": reports,
            },
        )
        print(f"{sid} {report['status']} {report['state']}", flush=True)


if __name__ == "__main__":
    main()
