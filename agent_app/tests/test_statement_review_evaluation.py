"""Independent offline evaluator probes; no provider, runner, or renderer invocation.

The passing packet is constructed from frozen statement parsing + literal oracle
values, rather than calling the renderer/evaluator to generate its own answers.
Mutations name omissions that must be detected separately on report/agent sides.
"""

import importlib.util
import json
import sys
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent_app/tools"))
from statement_report_fixtures import build_cases  # noqa: E402

from merchant_sandbox.statements import parse_statement  # noqa: E402

MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
SECTIONS = ("supported_sales", "non_sales_inflows", "identifiable_obligations", "follow_up")


def evaluator():
    path = ROOT / "agent_app/tools/evaluate_statement_review.py"
    assert path.exists(), "Independent evaluator is not implemented"
    spec = importlib.util.spec_from_file_location("evaluate_statement_review", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.evaluate_new


def valid_packet(sid):
    fixture = build_cases()[sid]
    expected = fixture["expected"]
    case = fixture["case"]
    raw = []
    for document in fixture["documents"]:
        for row in parse_statement(document)["rows"]:
            raw.append(
                {
                    "ref": row["ref"],
                    "document_ref": document["id"],
                    "date": row["date"],
                    "description": row["description"],
                    "debit": str(row["debit"]),
                    "credit": str(row["credit"]),
                    "balance": str(row["balance"]),
                }
            )
    sections = {
        key: {"items": [], "credit_total_thb": "0.00", "debit_total_thb": "0.00"}
        for key in SECTIONS
    }
    nonsales = {
        ref: item for item in expected["sections"]["non_sales_inflows"] for ref in item["refs"]
    }
    for row in raw:
        purpose, section = "UNKNOWN", "follow_up"
        if row["ref"] in nonsales:
            purpose, section = nonsales[row["ref"]]["type"], "non_sales_inflows"
        elif row["description"].startswith("loan repayment"):
            purpose, section = "DEBT_PAYMENT", "identifiable_obligations"
        elif row["description"] == "rent":
            purpose, section = "RENT", "identifiable_obligations"
        sections[section]["items"].append(
            {
                "code": "TRANSACTION",
                "refs": [row["ref"]],
                "transaction_refs": [row["ref"]],
                "date": row["date"],
                "description": row["description"],
                "purpose": purpose,
                "credit_thb": row["credit"],
                "debit_thb": row["debit"],
                "included_in_totals": sid != "S01",
                "support_level": "UNVERIFIED",
            }
        )
    for section in sections.values():
        for side in ("credit", "debit"):
            section[f"{side}_total_thb"] = str(
                sum(
                    (
                        Decimal(item[f"{side}_thb"])
                        for item in section["items"]
                        if item["included_in_totals"]
                    ),
                    Decimal(0),
                )
            )
    questions = deepcopy(expected["sections"]["unresolved_items_questions"])
    for question in questions:
        question["transaction_refs"] = []
    sections["follow_up"]["items"].extend(questions)
    nets = expected.get("monthly_bank_net_thb", ["55000.00"] * 6)
    candidates = expected.get("candidate_sales_by_month_thb", ["200000.00"] * 6)
    rows = [
        {
            "month": month,
            "refs": [r["ref"] for r in raw if r["date"].startswith(month)],
            "coverage": "UNKNOWN" if sid == "S01" else "COMPLETE",
            "supported_sales_thb": None if sid == "S01" else "0.00",
            "eligible_unverified_inflows_thb": None if sid == "S01" else candidates[index],
            "observed_net_thb": nets[index],
            "residual_thb": None,
            "residual_status": "UNKNOWN",
        }
        for index, month in enumerate(MONTHS)
    ]
    dimensions = (
        "document_account_period_continuity",
        "inflow_source",
        "variability_and_trend",
        "outgoing_and_debt",
        "residual_and_liquidity",
        "patterns_and_questions",
    )
    report = {
        "decision": None,
        "authenticity": "UNVERIFIED",
        "human_final_decision_required": True,
        "sections": sections,
        "raw_rows": raw,
        "document_checks": {
            key: {"status": "UNKNOWN", "refs": [f"DOC-{sid}-A"]} for key in dimensions
        },
        "monthly_cashflow_summary": {"window_months": MONTHS[:], "rows": rows},
    }
    report["document_checks"]["document_account_period_continuity"].update(
        authenticity="UNVERIFIED", missing_months=["2026-09"] if sid == "S01" else []
    )
    if sid == "S01":
        report["document_checks"]["document_account_period_continuity"]["documents"] = [
            {
                "refs": ["DOC-S01-B"],
                "account_name": "UNKNOWN",
                "status": "NEEDS_REVIEW",
                "problems": ["Account owner mismatch"],
            }
        ]
        for question in questions:
            if question["code"] == "CROSS_DOCUMENT_DISCONTINUITY":
                question.update(expected["cross_document_continuity"])
    if sid == "S03":
        report["monthly_cashflow_summary"]["eligible_unverified_inflow_statistics"] = {
            "months_observed": MONTHS[:],
            "average_thb": "150000.00",
            "first_to_last_change_thb": "-240000.00",
            "trend_slope_thb_per_month": "-43714.29",
            "zero_supported_sales_months": ["2026-09"],
        }
    case.update(state="EXCEPTION_REVIEW", agent_mode="typhoon")
    issues = []
    actions = []
    for index, question in enumerate(questions):
        issue = {**deepcopy(question), "id": f"ISS-{index}", "status": "OPEN"}
        issues.append(issue)
        actions.append(
            (
                "flag_transactions",
                {
                    "refs": question["refs"],
                    "question": question["question"],
                    "reason": "Evidence required",
                },
                {"status": "OK", "issue": deepcopy(issue)},
            )
        )
    cashflow = {"status": "UNKNOWN", "rows": [], "new_installment_max_thb": None}
    if sid == "S03":
        cashflow = {
            "status": "OK",
            "rows": [
                {"month": month, "residual_before_reserve_thb": value, "refs": rows[i]["refs"]}
                for i, (month, value) in enumerate(
                    zip(MONTHS, expected["provisional_residual_before_reserve_thb"], strict=True)
                )
            ],
        }
        issues.append(
            {
                "id": "ISS-GAP",
                "code": "LIQUIDITY_GAP",
                "status": "OPEN",
                "refs": rows[-1]["refs"],
                "question": "Please explain shortage",
                "observed": cashflow["rows"][3:],
            }
        )
    actions.append(("inspect_cashflow", {}, deepcopy(cashflow)))
    actions.append(("finish_review", {"reason": "Evidence required"}, {"status": "OK"}))
    records = []
    trace = []
    for index, (tool, arguments, result) in enumerate(actions, 1):
        trace.append(
            {
                "kind": "tool",
                "actor": "evidence_tool",
                "tool": tool,
                "arguments": deepcopy(arguments),
                "status": result["status"],
                "result": result,
            }
        )
        trace.append(
            {
                "kind": "agent_action",
                "call": index,
                "tool": tool,
                "arguments": deepcopy(arguments),
                "status": "ACCEPTED",
            }
        )
        records.append(
            {
                "kind": "llm_attempt",
                "attempt": index,
                "tool": tool,
                "arguments": deepcopy(arguments),
                "status": "ACCEPTED",
            }
        )
    case.update(trace=trace, agent_calls=len(records), llm_calls=len(records))
    case["packet"] = {
        "decision": None,
        "human_final_decision_required": True,
        "authenticity_verified": False,
        "issues": issues,
        "monthly_cashflow": cashflow,
    }
    evidence_rows = [{**deepcopy(r), "category": "R" if Decimal(r["credit"]) else "V"} for r in raw]
    for row in evidence_rows:
        if "ANON-" in row["description"]:
            row["category"] = "UNRESOLVED"
        if sid == "S04" and row["ref"] in expected["pattern"]["refs"]:
            row["category"] = "UNRESOLVED"
    if sid == "S02":
        for row in evidence_rows:
            if row["ref"] in nonsales:
                row["category"] = nonsales[row["ref"]]["type"]
    case["results"]["evidence"] = {"rows": evidence_rows}
    return case, report, expected, records


def run(sid, bundle=None):
    return evaluator()(sid, *(bundle or valid_packet(sid)))


def failures(result, side):
    return [check["requirement"] for check in result[f"{side}_checks"] if not check["passed"]]


@pytest.mark.parametrize("sid", ["S01", "S02", "S03", "S04", "S05"])
def test_constructed_literal_valid_packet_passes_and_is_not_mutated(sid):
    bundle = valid_packet(sid)
    original = deepcopy(bundle)
    result = run(sid, bundle)
    assert result["status"] == "PASS", result
    assert result["id"] == sid and result["decision"] is None
    assert result["report_checks"] and result["agent_checks"]
    assert all(
        type(c["passed"]) is bool and c["requirement"]
        for side in ("report", "agent")
        for c in result[f"{side}_checks"]
    )
    assert bundle == original


@pytest.mark.parametrize("sid", ["S01", "S02", "S03", "S04", "S05"])
def test_renderer_questions_never_substitute_for_agent_choices(sid):
    bundle = valid_packet(sid)
    bundle[0]["trace"] = [e for e in bundle[0]["trace"] if e.get("tool") != "flag_transactions"]
    result = run(sid, bundle)
    assert result["status"] == "FAIL" and not failures(result, "report")
    assert failures(result, "agent")


@pytest.mark.parametrize(
    "mutation", ["missing", "rejected", "nonnative", "technical", "overbudget", "record_mismatch"]
)
def test_unfinished_or_non_native_review_cannot_pass(mutation):
    bundle = valid_packet("S04")
    case, _, _, records = bundle
    if mutation == "missing":
        case["trace"] = [e for e in case["trace"] if e.get("tool") != "finish_review"]
    elif mutation == "rejected":
        case["trace"][-1]["status"] = "REJECTED"
    elif mutation == "nonnative":
        records.clear()
    elif mutation == "technical":
        case["state"] = "TECHNICAL_REVIEW"
    elif mutation == "overbudget":
        case["agent_calls"] = 9
    else:
        records[-1]["arguments"] = {"reason": "different accepted payload"}
    result = run("S04", bundle)
    assert result["status"] == "FAIL" and failures(result, "agent")
    assert not failures(result, "report")


@pytest.mark.parametrize(
    "mutation",
    [
        "drop_raw",
        "duplicate_assignment",
        "drop_assignment",
        "tamper_amount",
        "extra_section",
        "decision",
        "authenticity",
        "dimension",
        "oracle",
    ],
)
def test_common_omissions_or_forged_conservation_do_not_pass(mutation):
    bundle = valid_packet("S04")
    _, report, expected, _ = bundle
    items = report["sections"]["follow_up"]["items"]
    if mutation == "drop_raw":
        report["raw_rows"].pop()
    elif mutation == "duplicate_assignment":
        items.append(deepcopy(items[0]))
    elif mutation == "drop_assignment":
        items.pop(0)
    elif mutation == "tamper_amount":
        items[0]["credit_thb"] = "900000.00"
    elif mutation == "extra_section":
        report["sections"]["recommendation"] = {"items": []}
    elif mutation == "decision":
        report["decision"] = "APPROVED"
    elif mutation == "authenticity":
        report["authenticity"] = "VERIFIED"
    elif mutation == "dimension":
        del report["document_checks"]["patterns_and_questions"]
    else:
        expected["pattern"]["pair_net_thb"] = "900000.00"
    report["raw_rows_conservation"] = {"unassigned_refs": [], "multiply_assigned_refs": []}
    assert run("S04", bundle)["status"] == "FAIL"


@pytest.mark.parametrize(
    "sid,code",
    [
        ("S01", "OWNER_MISMATCH"),
        ("S01", "PERIOD_END_SHORT"),
        ("S01", "CROSS_DOCUMENT_DISCONTINUITY"),
        ("S02", "LOAN_SOURCE_AND_SCHEDULE"),
        ("S02", "OWNER_CAPITAL_SOURCE"),
        ("S03", "DECLINING_AND_ZERO_MONTH"),
        ("S04", "LATE_INBOUND_RAPID_OUTBOUND"),
        ("S05", "ANONYMOUS_EXPENSE_PURPOSE"),
        ("S05", "DEBT_COMPLETENESS_UNKNOWN"),
    ],
)
def test_generic_only_report_question_does_not_meet_literal_followup(sid, code):
    bundle = valid_packet(sid)
    for question in bundle[1]["sections"]["follow_up"]["items"]:
        if question["code"] == code:
            question["question"] = "กรุณาตรวจรายการและแนบหลักฐาน"
    result = run(sid, bundle)
    assert result["status"] == "FAIL" and failures(result, "report")
    assert not failures(result, "agent")


@pytest.mark.parametrize(
    "sid,mutation",
    [
        ("S01", "crossdoc"),
        ("S02", "capital_in_sales"),
        ("S02", "R_salesproof"),
        ("S03", "zero_dropped"),
        ("S03", "wrong_mean"),
        ("S03", "zero_missing"),
        ("S03", "wrong_net"),
        ("S04", "split_refs"),
        ("S04", "retained900k"),
        ("S04", "internal_transfer"),
        ("S05", "forced_personal"),
        ("S05", "repayment_missing"),
        ("S05", "residual_guessed"),
    ],
)
def test_almost_right_report_rejects_case_specific_omission(sid, mutation):
    bundle = valid_packet(sid)
    _, report, _, _ = bundle
    follow = report["sections"]["follow_up"]["items"]
    monthly = report["monthly_cashflow_summary"]
    if mutation in {"crossdoc", "split_refs"}:
        code = "CROSS_DOCUMENT_DISCONTINUITY" if sid == "S01" else "LATE_INBOUND_RAPID_OUTBOUND"
        question = next(i for i in follow if i["code"] == code)
        question["refs"] = question["refs"][:1]
    elif mutation in {"capital_in_sales", "R_salesproof"}:
        report["sections"]["supported_sales"]["credit_total_thb"] = (
            "80000.00" if mutation == "capital_in_sales" else "1200000.00"
        )
    elif mutation == "zero_dropped":
        monthly["rows"].pop()
    elif mutation == "wrong_mean":
        monthly["eligible_unverified_inflow_statistics"]["average_thb"] = "180000.00"
    elif mutation == "zero_missing":
        monthly["rows"][-1]["coverage"] = "UNKNOWN"
    elif mutation in {"wrong_net", "retained900k"}:
        monthly["rows"][-1]["observed_net_thb"] = "900000.00"
    elif mutation == "internal_transfer":
        next(i for i in follow if i.get("description", "").startswith("incoming reference"))[
            "purpose"
        ] = "INTERNAL_TRANSFER"
    elif mutation == "forced_personal":
        next(i for i in follow if "ANON-A" in i.get("description", ""))["purpose"] = "PERSONAL"
    elif mutation == "repayment_missing":
        next(
            i
            for i in report["sections"]["identifiable_obligations"]["items"]
            if i["purpose"] == "DEBT_PAYMENT"
        )["purpose"] = "UNKNOWN"
    else:
        monthly["rows"][0]["residual_thb"] = "0.00"
    result = run(sid, bundle)
    assert result["status"] == "FAIL" and failures(result, "report")
    assert not failures(result, "agent")


@pytest.mark.parametrize(
    "sid,mutation",
    [
        ("S01", "crossdoc"),
        ("S02", "May280k"),
        ("S02", "generic_only"),
        ("S03", "cashflow_missing"),
        ("S03", "wrong_residual"),
        ("S04", "split_refs"),
        ("S04", "unsupported_interpretation"),
        ("S05", "debt10000"),
        ("S05", "generic_only"),
    ],
)
def test_almost_right_agent_is_not_rescued_by_renderer(sid, mutation):
    bundle = valid_packet(sid)
    case, _, _, records = bundle
    if mutation in {"crossdoc", "split_refs"}:
        case["packet"]["issues"][-1]["refs"] = case["packet"]["issues"][-1]["refs"][:1]
    elif mutation == "May280k":
        next(r for r in case["results"]["evidence"]["rows"] if "owner capital" in r["description"])[
            "category"
        ] = "R"
    elif mutation == "generic_only":
        case["packet"]["issues"][0]["question"] = "กรุณาตรวจรายการและแนบหลักฐาน"
    elif mutation == "cashflow_missing":
        case["trace"] = [e for e in case["trace"] if e.get("tool") != "inspect_cashflow"]
    elif mutation == "wrong_residual":
        case["packet"]["monthly_cashflow"]["rows"][-1]["residual_before_reserve_thb"] = "30000.00"
    elif mutation == "debt10000":
        case["packet"]["monthly_cashflow"].update(status="OK", new_installment_max_thb="10000.00")
    else:
        case["packet"]["issues"][0]["proposal"] = {"interpretation": "LOAN_PROCEEDS"}
    result = run(sid, bundle)
    assert result["status"] == "FAIL" and failures(result, "agent")
    assert not failures(result, "report")


def test_unreviewed_paraphrase_is_marked_for_human_semantic_review_not_proven():
    bundle = valid_packet("S04")
    question = next(
        i
        for i in bundle[1]["sections"]["follow_up"]["items"]
        if i["code"] == "LATE_INBOUND_RAPID_OUTBOUND"
    )
    question["question"] = "Please explain source, purpose and relationship, with evidence?"
    result = run("S04", bundle)
    assert result["status"] == "FAIL"
    assert "NEEDS_HUMAN_SEMANTIC_REVIEW" in json.dumps(result["report_checks"])


def test_invalid_money_or_missing_packet_fails_closed_without_crashing():
    bundle = valid_packet("S04")
    bundle[1]["raw_rows"][0]["credit"] = "NaN"
    bundle[0]["packet"] = None
    assert run("S04", bundle)["status"] == "FAIL"


@pytest.mark.parametrize("side", ["report", "agent"])
def test_unreviewed_extra_claim_is_not_hidden_by_correct_required_questions(side):
    bundle = valid_packet("S04")
    if side == "report":
        bundle[1]["sections"]["follow_up"]["items"].append(
            {
                "refs": ["DOC-S04-A"],
                "transaction_refs": [],
                "code": "EXTRA",
                "question": "This is certainly fraud; reject the applicant",
            }
        )
    else:
        # Change accepted arguments, execution receipt AND packet consistently;
        # correct oracle question still exists, but a claim in reason is unproven.
        for event in bundle[0]["trace"]:
            if event.get("tool") == "flag_transactions":
                event["arguments"]["reason"] = "The pair proves fraud and an own transfer"
        bundle[3][0]["arguments"]["reason"] = "The pair proves fraud and an own transfer"
    result = run("S04", bundle)
    assert result["status"] == "FAIL" and failures(result, side)
    assert HUMAN_MARKER in json.dumps(result[f"{side}_checks"])


HUMAN_MARKER = "NEEDS_HUMAN_SEMANTIC_REVIEW"


@pytest.mark.parametrize("mutation", ["anonymous_V", "anonymous_debt", "total_debt_10000"])
def test_agent_anonymous_expenses_and_total_debt_cannot_be_guessed(mutation):
    bundle = valid_packet("S05")
    case = bundle[0]
    if mutation == "anonymous_V":
        next(r for r in case["results"]["evidence"]["rows"] if "ANON-A" in r["description"])[
            "category"
        ] = "V"
    elif mutation == "anonymous_debt":
        case["packet"]["issues"][0]["proposal"] = {"interpretation": "LOAN_PROCEEDS"}
    else:
        case["packet"]["total_monthly_debt_thb"] = "10000.00"
    result = run("S05", bundle)
    assert result["status"] == "FAIL" and failures(result, "agent")
    assert not failures(result, "report")


@pytest.mark.parametrize(
    "mutation", ["invalid_assignment_ref", "invalid_call", "missing_raw_amount"]
)
def test_malformed_artifacts_fail_closed_instead_of_raising(mutation):
    bundle = valid_packet("S04")
    if mutation == "invalid_assignment_ref":
        bundle[1]["sections"]["follow_up"]["items"][0]["transaction_refs"] = [{}]
    elif mutation == "invalid_call":
        bundle[0]["trace"][-1]["call"] = {}
    else:
        del bundle[1]["raw_rows"][0]["debit"]
    assert run("S04", bundle)["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["pair_R", "pair_own_transfer", "retained900k"])
def test_agent_pair_is_unknown_and_not_900000_retained_liquidity(mutation):
    bundle = valid_packet("S04")
    case, _, expected, _ = bundle
    if mutation == "retained900k":
        cashflow = case["packet"]["monthly_cashflow"]
        cashflow.update(
            status="OK",
            rows=[
                {
                    "month": "2026-09",
                    "residual_before_reserve_thb": "900000.00",
                    "refs": expected["pattern"]["refs"],
                }
            ],
        )
        for event in case["trace"]:
            if event.get("kind") == "tool" and event.get("tool") == "inspect_cashflow":
                event["result"] = deepcopy(cashflow)
    else:
        next(
            r
            for r in case["results"]["evidence"]["rows"]
            if r["ref"] == expected["pattern"]["refs"][0]
        )["category"] = "R" if mutation == "pair_R" else "OWN_TRANSFER"
    result = run("S04", bundle)
    assert result["status"] == "FAIL" and failures(result, "agent")
    assert not failures(result, "report")


def test_native_propose_findings_requires_retained_issue_and_exact_cited_refs():
    bundle = valid_packet("S02")
    case, _, _, records = bundle
    issue = case["packet"]["issues"][0]
    finding = {
        "issue_id": issue["id"],
        "interpretation": "LOAN_PROCEEDS",
        "quotes": [{"ref": issue["refs"][0], "quote": "loan proceeds lender L1"}],
        "question": issue["question"],
        "requested_evidence": ["loan agreement and schedule"],
    }
    args = {"findings": [finding]}
    for event in case["trace"][:2]:
        event.update(tool="propose_findings", arguments=deepcopy(args))
        if event["kind"] == "tool":
            event["result"] = {"status": "OK", "issues": [deepcopy(issue)]}
    records[0].update(tool="propose_findings", arguments=deepcopy(args))
    assert run("S02", bundle)["status"] == "PASS"
    records[0]["arguments"]["findings"][0]["quotes"][0]["ref"] = "DOC-S02-A:page-1:table-1:row-7"
    assert run("S02", bundle)["status"] == "FAIL"
