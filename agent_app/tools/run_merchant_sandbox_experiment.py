"""Run synthetic scenarios, with real Typhoon calls only when explicitly selected."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from merchant_sandbox.core import ROOT, BaselinePlanner, Controller, Store, default_input
from merchant_sandbox.typhoon import Config, TyphoonPlanner

ORACLE = {
    "complete": ("REVIEW_READY", "RECOMMEND_APPROVE", "28400.00"),
    "no_wallet": ("REVIEW_READY", "RECOMMEND_APPROVE", "28400.00"),
    "missing_months": ("WAIT_CUSTOMER", None, None),
    "unknown_debt": ("WAIT_CUSTOMER", None, None),
    "low_capacity": ("REVIEW_READY", "RECOMMEND_DECLINE", "0.00"),
    "identity_conflict": ("EXCEPTION_REVIEW", "EXCEPTION_REVIEW", None),
    "timeout_once": ("REVIEW_READY", "RECOMMEND_APPROVE", "28400.00"),
    "provider_down": ("TECHNICAL_REVIEW", None, None),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["baseline", "typhoon"], default="baseline")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--scenario", choices=list(ORACLE), action="append")
    args = parser.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    folder = ROOT / "outputs/merchant_sandbox" / (args.mode + "-" + stamp)
    folder.mkdir(parents=True)
    planner = (
        BaselinePlanner() if args.mode == "baseline" else TyphoonPlanner(Config.load(args.env_file))
    )
    store = Store(folder / "cases.sqlite3")
    controller = Controller(store)
    sources = [
        *sorted((ROOT / "agent_app/src/merchant_sandbox").glob("*.py")),
        ROOT / "agent_app/src/merchant_sandbox/static/index.html",
        ROOT / "examples/merchant_sandbox/transactions.csv",
        ROOT / "docs/merchant_lending/demo_parameters.json",
        Path(__file__).resolve(),
    ]
    report = {
        "at": datetime.now(UTC).isoformat(),
        "mode": args.mode,
        "model": planner.config.model if args.mode == "typhoon" else None,
        "source_sha256": {
            str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources
        },
        "scope": "SYNTHETIC_CONSTRAINED_TOOL_SELECTION_SINGLE_RUN_PER_SCENARIO",
        "cost_actual": None,
        "cost_note": "No tariff/invoice was supplied; tokens are usage, not money.",
        "cases": [],
    }
    for scenario in args.scenario or ORACLE:
        case = store.create(default_input(scenario), stamp + ":" + scenario)
        result = controller.run(case["id"], planner, 1)
        packet = result["packet"] or {}
        financial = packet.get("financial") or {}
        actual = (
            result["state"],
            packet.get("recommendation"),
            financial.get("proposed_limit_thb"),
        )
        events = [x for x in result["trace"] if x.get("kind") == "tool"]
        receipts = [x["usage"] for x in events if x.get("actor") == "typhoon" and x.get("usage")]
        row = {
            "scenario": scenario,
            "case_id": result["id"],
            "passed": actual == ORACLE[scenario] and packet.get("decision") is None,
            "expected": ORACLE[scenario],
            "actual": actual,
            "llm_calls": result["llm_calls"],
            "active_duration_ms": result["active_duration_ms"],
            "usage": {
                k: sum(x.get(k, 0) for x in receipts)
                for k in ("prompt_tokens", "completion_tokens", "total_tokens")
            },
            "usage_complete": len(receipts) == result["llm_calls"],
            "tools": [x["tool"] for x in events],
            "feedback": result["feedback"],
            "trace_file": scenario + ".json",
        }
        report["cases"].append(row)
        (folder / (scenario + ".json")).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (folder / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    k: row[k]
                    for k in ("scenario", "passed", "actual", "llm_calls", "active_duration_ms")
                }
            ),
            flush=True,
        )
        if any("Typhoon HTTP 401" in x or "Typhoon HTTP 403" in x for x in result["feedback"]):
            break
    print(str(folder / "report.json"), flush=True)
    return (
        0
        if len(report["cases"]) == len(args.scenario or ORACLE)
        and all(x["passed"] for x in report["cases"])
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
