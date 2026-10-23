"""Additional, pre-registered checks; never replaces the original scenario oracle.

This evaluator only reads saved results. Its scenario expectations must never be
passed to a planner. PASS on this finite synthetic suite is not credit accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def additional_checks(scenario_id, case):
    results = case.get("results", {})
    evidence = results.get("evidence", {})
    issues = evidence.get("issues", [])
    packet = case.get("packet") or {}
    actions = [e for e in case.get("trace", []) if e.get("kind") == "agent_action"]
    accepted = [e for e in actions if e.get("status") == "ACCEPTED"]
    checks = []

    def check(name, passed):
        checks.append({"requirement": name, "passed": bool(passed)})

    check(
        "live model calls recorded with accepted native tool choices",
        case.get("agent_mode") == "typhoon"
        and bool(accepted)
        and all(e.get("model") for e in accepted),
    )
    check(
        "bounded completion includes finish_review",
        1 <= case.get("llm_calls", 0) <= 8
        and any(e.get("tool") == "finish_review" for e in accepted)
        and case.get("state") != "TECHNICAL_REVIEW",
    )
    check(
        "experiment packet remains human-only",
        packet.get("experiment_only") is True
        and packet.get("not_for_decision_endpoint") is True
        and packet.get("human_final_decision_required") is True
        and case.get("decision") is None
        and not case.get("active"),
    )
    if scenario_id == "C04":
        matches = [
            e
            for e in case.get("trace", [])
            if e.get("kind") == "tool" and e.get("tool") == "match_transfers"
        ]
        check(
            "model requested proven cross-account transfer matching",
            any(e.get("tool") == "match_transfers" for e in accepted)
            and any(e.get("result", {}).get("matched_pairs") for e in matches),
        )
    if scenario_id == "C06":
        proposals = [i.get("proposal", {}) for i in issues]
        check(
            "asset-sale interpretation carries exact evidence quote",
            any(
                p.get("interpretation") == "ASSET_SALE"
                and any(
                    "old equipment" in q.get("quote", "").lower() and q.get("ref")
                    for q in p.get("quotes", [])
                )
                for p in proposals
            ),
        )
    if scenario_id == "C07":
        rows = (packet.get("monthly_cashflow") or {}).get("rows", [])
        check(
            "May and July cash shortages remain explicit",
            {r["month"] for r in rows if float(r["residual_before_reserve_thb"]) < 0}
            == {"2026-05", "2026-07"},
        )
    if scenario_id == "C09":
        mismatches = [i for i in issues if i.get("code") == "DECLARATION_MISMATCH"]
        check(
            "both declared versus observed comparisons have row references",
            {(i.get("expected"), i.get("observed")) for i in mismatches}
            == {("300000.00", "200000.00"), ("10000.00", "145000.00")}
            and all(i.get("refs") and i.get("question") for i in mismatches),
        )
    if scenario_id == "C11":
        check(
            "missing second account is specifically requested",
            any(
                i.get("code") == "MISSING_ACCOUNT"
                and i.get("expected") == "OWN-B"
                and "OWN-B" in i.get("question", "")
                for i in issues
            )
            and not results.get("financial_calculate"),
        )
    if scenario_id == "C12":
        check(
            "unbanked 50000 stays unproven and is not added to bank revenue",
            any(
                i.get("code") == "UNPROVEN_CASH" and i.get("expected") == "50000.00" for i in issues
            )
            and all(m.get("R") == "150000.00" for m in evidence.get("months", []))
            and not results.get("financial_calculate"),
        )
    if scenario_id == "C14":
        check(
            "both missing July and unresolved source survive handoff",
            any(
                i.get("code") == "MISSING_PERIOD" and "2026-07" in i.get("question", "")
                for i in issues
            )
            and any(
                i.get("code") == "UNCLASSIFIED_INFLOW"
                and i.get("proposal", {}).get("requested_evidence")
                for i in issues
            ),
        )
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite evaluation output")
    report = json.loads((args.run / "report.json").read_text(encoding="utf-8-sig"))
    rows = []
    for original in report["cases"]:
        sid = original["id"]
        case_path = args.run / sid / "case.json"
        case = json.loads(case_path.read_text(encoding="utf-8-sig"))
        checks = additional_checks(sid, case)
        rows.append(
            {
                "id": sid,
                "original_oracle_status": original["status"],
                "additional_status": "PASS" if all(c["passed"] for c in checks) else "FAIL",
                "checks": checks,
                "case_sha256": hashlib.sha256(case_path.read_bytes()).hexdigest(),
                "model_calls": case.get("llm_calls"),
                "actions": [
                    e["tool"]
                    for e in case.get("trace", [])
                    if e.get("kind") == "agent_action" and e.get("status") == "ACCEPTED"
                ],
            }
        )
    output = {
        "scope": "Additional semantic assertions and real model tool-call evidence; original oracle unchanged",
        "run": str(args.run.resolve()),
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "summary": dict(Counter(r["additional_status"] for r in rows)),
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(output["summary"]))


if __name__ == "__main__":
    main()
