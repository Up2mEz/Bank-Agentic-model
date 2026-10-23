"""Financial invariants for the isolated local agentic spike (no network)."""

import importlib.util
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from merchant_sandbox.core import SandboxError, default_input
from merchant_sandbox.statements import verify_statements

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "scenario_audit", ROOT / "agent_app/tools/run_lending_scenario_audit.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
FIXTURES = json.loads(
    (ROOT / "examples/merchant_sandbox/lending_scenarios_v1.json").read_text(encoding="utf-8")
)


def module():
    assert importlib.util.find_spec("merchant_sandbox.agentic_review") is not None, (
        "Local agentic evidence loop has not been implemented"
    )
    from merchant_sandbox import agentic_review

    return agentic_review


def sample(sid):
    scenario = next(s for s in FIXTURES["scenarios"] if s["id"] == sid)
    printed, truth = audit.build(scenario, FIXTURES)
    data = default_input()
    data.update(
        applicant_name="Mali Jaidee", message=scenario.get("message", "ตรวจเอกสารเพื่อเสนอให้เจ้าหน้าที่")
    )
    for key in ("living_cost_thb", "debt_thb", "requested_thb"):
        data[key] = scenario.get(key, FIXTURES["base"][key])
    case = {
        "id": "CASE-test",
        "version": 1,
        "snapshot": "CASE-test:v1",
        "created_at": FIXTURES["as_of"],
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
                "snapshot": audit.MockBank("test-owner").read("test-owner"),
            },
            "identity_verify": {"status": "PENDING_REVIEW", "real_identity_verified": False},
        },
    }
    docs = [
        {
            "id": f"DOC-{i}",
            "case_id": case["id"],
            "kind": "statement",
            "sha256": sha256(p["raw"]).hexdigest(),
            "pages": 1,
            "ocr_pages": [{"page": 1, "text": p["text"]}],
        }
        for i, p in enumerate(printed)
    ]
    case["results"]["evidence"] = verify_statements(docs, case)
    return case, docs, scenario, truth


def claims_for(session, sid):
    message = session.context()["message_untrusted"]
    if sid == "C09":
        return [
            {"kind": "monthly_revenue", "value": "300000", "quote": message},
            {"kind": "monthly_business_cost", "value": "10000", "quote": message},
        ]
    if sid == "C11":
        return [
            {"kind": "business_account", "value": "OWN-B", "quote": message},
            {"kind": "business_account", "value": "ACC-1", "quote": message},
        ]
    if sid == "C12":
        return [
            {"kind": "monthly_revenue", "value": "200000", "quote": message},
            {"kind": "unbanked_cash_sales", "value": "50000", "quote": message},
        ]
    return []


def replay_review(sid):
    m = module()
    case, docs, scenario, truth = sample(sid)
    session = m.ReviewSession(case, docs)
    session.execute("compare_declarations", {"claims": claims_for(session, sid)})
    transfer_refs = [r["ref"] for r in session.rows if r.get("transfer_candidate")]
    if transfer_refs:
        session.execute("match_transfers", {"refs": transfer_refs})
    pending = [
        i
        for i in session.issues
        if i["code"] in {"INCOME_SOURCE", "UNCLASSIFIED_INFLOW", "UNCLASSIFIED_OUTFLOW"}
    ]
    if pending:
        refs = sorted({ref for i in pending for ref in i["refs"]})
        observations = session.execute("read_transactions", {"refs": refs})
        findings = []
        for issue in pending:
            row = next(r for r in observations["rows"] if r["ref"] == issue["refs"][0])
            findings.append(
                {
                    "issue_id": issue["id"],
                    "interpretation": "ASSET_SALE" if sid == "C06" else "UNKNOWN",
                    "quotes": [{"ref": row["ref"], "quote": row["description"]}],
                    "question": f"ขอที่มาหรือประเภทค่าใช้จ่ายของรายการ {row['date']} และหลักฐานประกอบ",
                    "requested_evidence": ["หลักฐานที่มาของเงินหรือวัตถุประสงค์การโอน"],
                }
            )
        session.execute("propose_findings", {"findings": findings})
    session.execute("inspect_cashflow", {})
    session.execute("finish_review", {"reason": "ส่งหลักฐานและประเด็นค้างให้เจ้าหน้าที่"})
    return session.result(), scenario, truth


def test_full_context_preserves_rows_issues_and_refs_without_direct_identifiers():
    m = module()
    case, _, _, _ = sample("C06")
    case["input"].update(email="secret@example.test", phone="0891234567")
    context = m.full_context(case)
    encoded = json.dumps(context, ensure_ascii=False)
    assert "sales of old equipment" in encoded and "900000.00" in encoded
    assert case["results"]["evidence"]["rows"][-1]["ref"] in encoded
    assert (
        "Mali Jaidee" not in encoded
        and "secret@example.test" not in encoded
        and "0891234567" not in encoded
    )
    assert "oracle" not in encoded and "variant" not in encoded


@pytest.mark.parametrize("sid", [s["id"] for s in FIXTURES["scenarios"]])
def test_unchanged_eighteen_case_oracle_with_explicit_tool_replay(sid):
    result, scenario, truth = replay_review(sid)
    checked = audit.evaluate(scenario, truth, result)
    assert checked["status"] == "PASS", checked
    assert result["packet"]["experiment_only"] is True


def test_declaration_comparison_contains_actual_values_and_row_refs():
    result, _, _ = replay_review("C09")
    issues = [
        i for i in result["results"]["evidence"]["issues"] if i["code"] == "DECLARATION_MISMATCH"
    ]
    assert {(i["expected"], i["observed"]) for i in issues} == {
        ("300000.00", "200000.00"),
        ("10000.00", "145000.00"),
    }
    assert all(i["refs"] and i["question"] for i in issues)


def test_missing_account_and_unproven_cash_are_specific():
    missing, _, _ = replay_review("C11")
    cash, _, _ = replay_review("C12")
    assert "OWN-B" in " ".join(missing["feedback"])
    assert any(
        i["code"] == "UNPROVEN_CASH" and i["expected"] == "50000.00"
        for i in cash["results"]["evidence"]["issues"]
    )
    assert not missing["results"].get("financial_calculate") and not cash["results"].get(
        "financial_calculate"
    )


def test_equal_amount_and_day_without_counterparty_proof_are_not_own_transfer():
    m = module()
    case, docs, _, _ = sample("C04")
    for doc in docs:
        for page in doc["ocr_pages"]:
            page["text"] = (
                page["text"]
                .replace("to OWN-B", "to unrelated shop")
                .replace("from OWN-B", "from unrelated shop")
            )
    session = m.ReviewSession(case, docs)
    result = session.execute("match_transfers", {"refs": [r["ref"] for r in session.rows]})
    assert result["matched_pairs"] == []
    assert any(i["status"] == "OPEN" for i in session.issues)


def test_tools_reject_unknown_refs_quotes_and_income_promotion():
    m = module()
    case, docs, _, _ = sample("C05")
    session = m.ReviewSession(case, docs)
    with pytest.raises(SandboxError):
        session.execute("read_transactions", {"refs": ["another-case:row-1"]})
    with pytest.raises(SandboxError):
        session.execute(
            "compare_declarations",
            {"claims": [{"kind": "monthly_revenue", "value": "999999", "quote": "invented"}]},
        )
    issue = next(i for i in session.issues if i["code"] == "UNCLASSIFIED_INFLOW")
    session.execute("read_transactions", {"refs": issue["refs"]})
    row = next(r for r in session.rows if r["ref"] == issue["refs"][0])
    base = {
        "issue_id": issue["id"],
        "interpretation": "BUSINESS_SALES",
        "quotes": [{"ref": row["ref"], "quote": row["description"]}],
        "question": "ขอหลักฐานที่มา",
        "requested_evidence": ["ใบขาย"],
    }
    session.execute("propose_findings", {"findings": [base]})
    assert row["category"] != "R" and issue["status"] == "OPEN"
    with pytest.raises(SandboxError):
        session.execute(
            "propose_findings",
            {"findings": [{**base, "quotes": [{"ref": row["ref"], "quote": "not on document"}]}]},
        )
    with pytest.raises(SandboxError):
        session.execute("approve_loan", {})


def test_foreign_document_consent_and_final_case_rejected_before_model():
    m = module()
    case, docs, _, _ = sample("C01")
    foreign = deepcopy(docs)
    foreign[0]["case_id"] = "other"
    with pytest.raises(SandboxError):
        m.ReviewSession(case, foreign)
    no_consent = deepcopy(case)
    no_consent["input"]["consent"] = False
    with pytest.raises(SandboxError):
        m.ReviewSession(no_consent, docs)
    final = deepcopy(case)
    final["state"] = "APPROVED"
    with pytest.raises(SandboxError):
        m.ReviewSession(final, docs)


def test_budget_and_failed_provider_stop_without_credit_decline():
    m = module()
    case, docs, _, _ = sample("C01")

    class Repeater:
        mode = "scripted_test_only"
        calls = 0

        def choose(self, context, tools, timeout):
            self.calls += 1
            return {
                "tool": "compare_declarations",
                "arguments": {"claims": []},
                "reason": "repeat",
                "usage": None,
            }

    agent = Repeater()
    result = m.run_review(case, docs, agent, max_calls=3)
    assert agent.calls <= 3 and not result["active"]
    assert result["state"] == "TECHNICAL_REVIEW" and result.get("decision") is None
    assert result["packet"]["recommendation"] != "RECOMMEND_DECLINE"

    class Broken(Repeater):
        def choose(self, context, tools, timeout):
            raise SandboxError("provider timeout")

    failed = m.run_review(case, docs, Broken(), max_calls=3)
    assert failed["state"] == "TECHNICAL_REVIEW" and not failed["results"].get(
        "financial_calculate"
    )


def test_positive_low_month_still_requires_review_after_new_installment():
    m = module()
    case, docs, _, _ = sample("C01")
    modified = {
        "id": "heldout-low-month",
        "variant": "regular",
        "sales": [200000, 178000, 200000, 200000, 200000, 200000],
    }
    printed, _ = audit.build(modified, FIXTURES)
    docs[0]["ocr_pages"][0]["text"] = printed[0]["text"]
    session = m.ReviewSession(case, docs)
    session.execute("compare_declarations", {"claims": []})
    session.execute("inspect_cashflow", {})
    session.execute("finish_review", {"reason": "ตรวจสภาพคล่อง"})
    result = session.result()
    assert result["state"] == "EXCEPTION_REVIEW"
    may = next(r for r in result["packet"]["monthly_cashflow"]["rows"] if r["month"] == "2026-05")
    assert may["residual_before_reserve_thb"] == "8000.00"
    assert float(may["after_reserve_and_new_installment_thb"]) < 0


def test_agent_can_raise_new_evidence_issue_and_invalidates_cashflow():
    m = module()
    case, docs, _, _ = sample("C01")
    session = m.ReviewSession(case, docs)
    session.execute("compare_declarations", {"claims": []})
    session.execute("inspect_cashflow", {})
    row = session.rows[0]
    session.execute("read_transactions", {"refs": [row["ref"]]})
    session.execute(
        "flag_transactions",
        {
            "refs": [row["ref"]],
            "question": "กรุณาแนบหลักฐานที่มาของยอดขายรายการนี้",
            "reason": "ตรวจหลักฐานเพิ่มเติมก่อนถือเป็นรายได้",
        },
    )
    assert row["category"] != "R"
    with pytest.raises(SandboxError):
        session.execute("finish_review", {"reason": "ยังใช้ cashflow เก่าไม่ได้"})
    session.execute("inspect_cashflow", {})
    session.execute("finish_review", {"reason": "ส่งข้อสงสัยที่เพิ่งพบให้คนตรวจ"})
    result = session.result()
    assert result["state"] == "EXCEPTION_REVIEW" and not result["results"].get(
        "financial_calculate"
    )


def test_transfer_pairing_requires_unique_match_in_both_directions():
    m = module()
    case, docs, _, _ = sample("C04")
    # A second incoming row with the same date, amount and counterparty creates ambiguity.
    rows = [
        ("2026-04-21", "sales transfer from OWN-B", 0, 80000),
        ("2026-04-21", "sales transfer from OWN-B", 0, 80000),
    ]
    other = [("2026-04-21", "own transfer to OWN-A", 80000, 0)]
    printed = [audit.make_document(rows), audit.make_document(other, account="OWN-B")]
    for doc, p in zip(docs, printed, strict=True):
        doc["ocr_pages"][0]["text"] = p["text"]
    session = m.ReviewSession(case, docs)
    result = session.execute("match_transfers", {"refs": [r["ref"] for r in session.rows]})
    assert result["matched_pairs"] == []


def test_recurring_transfer_label_does_not_prove_sales_without_other_account():
    m = module()
    case, docs, _, _ = sample("C01")
    docs[0]["ocr_pages"][0]["text"] = docs[0]["ocr_pages"][0]["text"].replace(
        "shop sales", "sales transfer from outside account"
    )
    session = m.ReviewSession(case, docs)
    assert all(row["category"] != "R" for row in session.rows)
    assert any(i["blocking_calculation"] for i in session.issues)


def test_late_model_action_is_rejected_before_evidence_changes(monkeypatch):
    m = module()
    case, docs, _, _ = sample("C01")
    clock = [0.0]
    monkeypatch.setattr(m.time, "monotonic", lambda: clock[0])

    class LateAgent:
        mode = "scripted_test_only"

        def choose(self, context, tools, timeout):
            assert 0 < timeout <= 1
            clock[0] = 1.01  # Response arrives after the cooperative one-second budget.
            return {"tool": "compare_declarations", "arguments": {"claims": []}}

    result = m.run_review(case, docs, LateAgent(), max_seconds=1)
    assert result["state"] == "TECHNICAL_REVIEW" and result["decision"] is None
    assert result["packet"]["recommendation"] == "NO_CREDIT_CONCLUSION"
    assert not any(
        e.get("tool") == "compare_declarations" and e["kind"] == "tool" for e in result["trace"]
    )
    assert any(i["code"] == "AGENT_TECHNICAL_STOP" for i in result["packet"]["issues"])
    assert result["agent_calls"] == 1 and not result["results"].get("financial_calculate")


def test_normal_source_groups_allow_read_and_discovery_without_initial_issue():
    m = module()
    case, docs, _, _ = sample("C01")
    session = m.ReviewSession(case, docs)
    context = session.context()
    group = next(g for g in context["source_groups"] if g["description"] == "shop sales")
    assert group["account"] == "ACC-1" and group["count"] == 6
    assert group["months"] == ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
    assert group["credit_total_thb"] == "1200000.00" and group["debit_total_thb"] == "0.00"
    assert len(group["refs"]) == 6
    assert not any(set(i["refs"]) & set(group["refs"]) for i in context["issues"])
    assert context["requested_thb"] == "30000.00"
    assert context["loan_assumptions"]["limit_fixture"]["repayment_intervals"] == 6
    encoded = json.dumps(context, ensure_ascii=False)
    assert "Mali Jaidee" not in encoded and "OWN-A" not in encoded
    assert "oracle" not in encoded and "scenario" not in encoded
    session.execute("read_transactions", {"refs": group["refs"]})
    result = session.execute(
        "flag_transactions",
        {
            "refs": group["refs"],
            "question": "กรุณาแนบหลักฐานที่มาของรายการรับเงินเหล่านี้",
            "reason": "ขอตรวจที่มาประกอบรายการ",
        },
    )
    assert result["issue"]["code"] == "AGENT_RAISED" and result["issue"]["status"] == "OPEN"
    assert result["issue"]["id"] in session.investigated


def test_cashflow_inspection_reports_capacity_offer_and_new_installment():
    m = module()
    case, docs, _, _ = sample("C01")
    session = m.ReviewSession(case, docs)
    result = session.execute("inspect_cashflow", {})
    assert result["installment_assumptions"]["requested_thb"] == "30000.00"
    assert result["installment_assumptions"]["proposed_limit_thb"] == "28400.00"
    assert result["new_installment_max_thb"] == "4984.92"
    assert result["rows"][0]["after_reserve_and_new_installment_thb"] == "20015.08"


def test_flag_requires_read_local_refs_and_neutral_language_without_partial_writes():
    m = module()
    case, docs, _, _ = sample("C01")
    session = m.ReviewSession(case, docs)
    refs = [r["ref"] for r in session.rows if r["category"] == "R"][:2]
    arguments = {
        "refs": refs,
        "question": "กรุณาแนบหลักฐานที่มาของรายการเหล่านี้",
        "reason": "ตรวจหลักฐานเพิ่มเติม",
    }
    session.execute("read_transactions", {"refs": refs[:1]})
    baseline = deepcopy((session.rows, session.issues, session.ledger_revision))
    with pytest.raises(SandboxError):
        session.execute("flag_transactions", arguments)
    assert (session.rows, session.issues, session.ledger_revision) == baseline
    with pytest.raises(SandboxError):
        session.execute("flag_transactions", {**arguments, "refs": [refs[0], "other-case:row-2"]})
    assert (session.rows, session.issues, session.ledger_revision) == baseline
    session.execute("read_transactions", {"refs": refs})
    for question, reason in [
        ("คุณโกหกเรื่องยอดขายใช่หรือไม่", arguments["reason"]),
        (arguments["question"], "fraudulent customer"),
    ]:
        with pytest.raises(SandboxError):
            session.execute(
                "flag_transactions", {**arguments, "question": question, "reason": reason}
            )
        assert (session.rows, session.issues, session.ledger_revision) == baseline


def test_replayed_flag_does_not_invalidate_recomputed_cashflow_or_create_duplicate():
    m = module()
    case, docs, _, _ = sample("C01")
    session = m.ReviewSession(case, docs)
    session.execute("compare_declarations", {"claims": []})
    original = session.execute("inspect_cashflow", {})
    ref = session.rows[0]["ref"]
    session.execute("read_transactions", {"refs": [ref]})
    arguments = {"refs": [ref], "question": "กรุณาแนบหลักฐานที่มาของรายการนี้", "reason": "ตรวจที่มาเพิ่มเติม"}
    session.execute("flag_transactions", arguments)
    assert session.ledger_revision == 1 and not session.context()["cashflow_current"]
    refreshed = session.execute("inspect_cashflow", {})
    assert not refreshed.get("replayed") and refreshed != original
    assert refreshed["new_installment_max_thb"] is None
    assert (
        next(r for r in refreshed["rows"] if r["month"] == "2026-04")["residual_before_reserve_thb"]
        == "-170000.00"
    )
    replay = session.execute("flag_transactions", arguments)
    assert (
        replay["replayed"]
        and session.ledger_revision == 1
        and session.context()["cashflow_current"]
    )
    assert sum(i["code"] == "AGENT_RAISED" for i in session.issues) == 1
    session.execute("finish_review", {"reason": "ส่งประเด็นใหม่ให้เจ้าหน้าที่ตรวจ"})
    result = session.result()
    assert result["state"] == "EXCEPTION_REVIEW" and result["packet"]["financial"] is None


def test_invalid_later_finding_rolls_back_prior_reclassification_and_receipt():
    m = module()
    case, docs, _, _ = sample("C06")
    session = m.ReviewSession(case, docs)
    issue = next(i for i in session.issues if i["code"] == "INCOME_SOURCE")
    row = session.execute("read_transactions", {"refs": issue["refs"]})["rows"][0]
    valid = {
        "issue_id": issue["id"],
        "interpretation": "ASSET_SALE",
        "quotes": [{"ref": row["ref"], "quote": row["description"]}],
        "question": "กรุณาแนบหลักฐานที่มาของเงินรายการนี้",
        "requested_evidence": ["หลักฐานรายการ"],
    }
    baseline = deepcopy(
        (
            session.rows,
            session.issues,
            session.ledger_revision,
            session.receipts,
            session.investigated,
        )
    )
    with pytest.raises(SandboxError):
        session.execute(
            "propose_findings",
            {
                "findings": [
                    valid,
                    {**valid, "quotes": [{"ref": row["ref"], "quote": "invented description"}]},
                ]
            },
        )
    assert (
        session.rows,
        session.issues,
        session.ledger_revision,
        session.receipts,
        session.investigated,
    ) == baseline
    session.execute("propose_findings", {"findings": [valid]})
    assert session.by_ref[row["ref"]]["category"] == "ASSET_SALE" and session.ledger_revision == 1


@pytest.mark.parametrize("duplicate_side", ["credit", "debit"])
def test_subset_refs_cannot_hide_ambiguous_transfer_counterparts(duplicate_side):
    m = module()
    case, docs, _, _ = sample("C04")
    credit = [("2026-04-21", "sales transfer from OWN-B", 0, 80000)]
    debit = [("2026-04-21", "own transfer to OWN-A", 80000, 0)]
    printed = [
        audit.make_document(credit * (2 if duplicate_side == "credit" else 1)),
        audit.make_document(debit * (2 if duplicate_side == "debit" else 1), account="OWN-B"),
    ]
    for doc, p in zip(docs, printed, strict=True):
        doc["ocr_pages"][0]["text"] = p["text"]
    session = m.ReviewSession(case, docs)
    ref = next(r["ref"] for r in session.rows if r["credit"] == "80000.00")
    result = session.execute("match_transfers", {"refs": [ref]})
    assert result["matched_pairs"] == [] and result["unmatched_refs"] == [ref]
    assert all(r["category"] != "OWN_TRANSFER" for r in session.rows)
    assert all(i["status"] == "OPEN" for i in session.issues)


@pytest.mark.parametrize("unknown_field", ["living_cost_thb", "debt_thb"])
def test_unknown_household_cost_or_debt_remains_unknown(unknown_field):
    m = module()
    case, docs, _, _ = sample("C01")
    case["input"][unknown_field] = None
    session = m.ReviewSession(case, docs)
    session.execute("compare_declarations", {"claims": []})
    cashflow = session.execute("inspect_cashflow", {})
    assert cashflow["status"] == "UNKNOWN" and cashflow["new_installment_max_thb"] is None
    assert cashflow["rows"] == [] and session.context()["declared_" + unknown_field] is None
    session.execute("finish_review", {"reason": "ขอข้อมูลที่ยังไม่ทราบ"})
    assert session.result()["packet"]["financial"] is None


@pytest.mark.parametrize("finish_on_last_call", [True, False])
def test_default_call_budget_and_tool_trace_stay_bounded(finish_on_last_call):
    m = module()
    case, docs, _, _ = sample("C01")

    class EightActions:
        mode = "scripted_test_only"
        calls = 0

        def choose(self, context, tools, timeout):
            self.calls += 1
            assert 0 < timeout <= 45
            if self.calls == 1:
                return {"tool": "compare_declarations", "arguments": {"claims": []}}
            if self.calls == 7:
                return {"tool": "inspect_cashflow", "arguments": {}}
            if self.calls == 8 and finish_on_last_call:
                return {"tool": "finish_review", "arguments": {"reason": "ส่งให้เจ้าหน้าที่ตรวจและตัดสิน"}}
            refs = next(
                g["refs"] for g in context["source_groups"] if g["description"] == "shop sales"
            )
            return {
                "tool": "read_transactions",
                "arguments": {"refs": [refs[min(self.calls - 2, 5)]]},
            }

    agent = EightActions()
    result = m.run_review(case, docs, agent)
    assert result["agent_calls"] == agent.calls == 8
    assert len([e for e in result["trace"] if e["kind"] == "tool"]) <= 12
    assert result["state"] == ("REVIEW_READY" if finish_on_last_call else "TECHNICAL_REVIEW")
    assert result["decision"] is None and not result["active"]
    assert result["packet"]["experiment_only"] and result["packet"]["not_for_decision_endpoint"]
    assert result["packet"]["human_final_decision_required"]


@pytest.mark.parametrize(
    "sid,claims,missed",
    [
        ("C11", [("business_account", "ACC-1")], "OWN-B"),
        ("C11", [], "OWN-B"),
        ("C11", [("business_account", "OWN-B")], "ACC-1"),
        ("C12", [("monthly_revenue", "150000")], "200000"),
        ("C12", [], "50000"),
        ("C12", [("monthly_revenue", "200000")], "50000"),
        ("C12", [("unbanked_cash_sales", "50000")], "200000"),
        (
            "C12",
            [("monthly_revenue", "150000"), ("monthly_business_cost", "50000")],
            "200000",
        ),
    ],
)
def test_partial_declarations_cannot_hide_unaddressed_message_spans(sid, claims, missed):
    case, docs, _, _ = sample(sid)
    session = module().ReviewSession(case, docs)
    session.execute(
        "compare_declarations",
        {"claims": [{"kind": k, "value": v, "quote": session.message} for k, v in claims]},
    )
    gaps = [i for i in session.issues if i["code"] == "DECLARATION_UNPARSED"]
    assert gaps and any(missed in json.dumps(i, ensure_ascii=False) for i in gaps)
    assert all(i["refs"] == ["input:message"] and i["blocking_calculation"] for i in gaps)
    assert not session.context()["declarations_checked"]
    cashflow = session.execute("inspect_cashflow", {})
    assert cashflow["new_installment_max_thb"] is None
    session.execute("finish_review", {"reason": "ส่งส่วนที่ยังแยกไม่ได้ให้เจ้าหน้าที่ตรวจ"})
    result = session.result()
    assert result["state"] != "REVIEW_READY" and result["decision"] is None
    assert result["packet"]["financial"] is None
    assert result["packet"]["recommendation"] != "RECOMMEND_DECLINE"


@pytest.mark.parametrize("sid", ["C01", "C09", "C11", "C12"])
def test_complete_local_declaration_coverage_preserves_existing_cases(sid):
    case, docs, _, _ = sample(sid)
    session = module().ReviewSession(case, docs)
    session.execute("compare_declarations", {"claims": claims_for(session, sid)})
    assert session.context()["declarations_checked"]
    assert not any(i["code"] == "DECLARATION_UNPARSED" for i in session.issues)


def test_altered_account_identifiers_still_require_each_account_claim():
    case, docs, _, _ = sample("C01")
    docs[0]["ocr_pages"][0]["text"] = docs[0]["ocr_pages"][0]["text"].replace("OWN-A", "BIZ-71")
    case["input"]["message"] = "ร้านใช้บัญชี BIZ-71 และ BIZ-92 ยังไม่ได้แนบ statement ของ BIZ-92"
    session = module().ReviewSession(case, docs)
    session.execute(
        "compare_declarations",
        {"claims": [{"kind": "business_account", "value": "ACC-1", "quote": session.message}]},
    )
    assert any(
        i["code"] == "DECLARATION_UNPARSED" and "BIZ-92" in str(i["observed"])
        for i in session.issues
    )


@pytest.mark.parametrize("total,bank,cash", [(275000, 210000, 65000), (321000, 245000, 76000)])
def test_altered_cash_amounts_cannot_be_hidden_by_bank_amount(total, bank, cash):
    case, docs, _, _ = sample("C01")
    case["input"]["message"] = (
        f"ยอดขายรวม {total:,} บาทต่อเดือน แบ่งเป็นเงินเข้าบัญชี {bank:,} บาท และเงินสดที่ไม่ได้ฝาก {cash:,} บาท"
    )
    session = module().ReviewSession(case, docs)
    session.execute(
        "compare_declarations",
        {"claims": [{"kind": "monthly_revenue", "value": str(bank), "quote": session.message}]},
    )
    gaps = str([i for i in session.issues if i["code"] == "DECLARATION_UNPARSED"])
    assert str(total) in gaps and str(cash) in gaps
    assert any(i["code"] == "DECLARATION_UNVERIFIED" for i in session.issues)


def test_whole_message_quote_cannot_swap_revenue_and_cost_meaning():
    case, docs, _, _ = sample("C01")
    case["input"]["message"] = "ค่าใช้จ่ายต้นทุนธุรกิจทั้งหมด 200000 บาท ยอดขายรวมของร้านเดือนละ 145000 บาท"
    session = module().ReviewSession(case, docs)
    session.execute(
        "compare_declarations",
        {
            "claims": [
                {"kind": "monthly_revenue", "value": "200000", "quote": session.message},
                {"kind": "monthly_business_cost", "value": "145000", "quote": session.message},
            ]
        },
    )
    assert not session.declarations_checked
    assert any(i["code"] == "DECLARATION_UNVERIFIED" for i in session.issues)
    session.execute("inspect_cashflow", {})
    session.execute("finish_review", {"reason": "ขอตรวจความหมายของยอดเงิน"})
    assert session.result()["packet"]["financial"] is None


def test_h03_correct_revenue_and_cost_keep_specific_comparisons():
    case, docs, _, _ = sample("C01")
    case["input"]["message"] = (
        "แจ้งยอดขายรวมของร้านเดือนละ 275,000 บาท ค่าใช้จ่ายต้นทุนธุรกิจทั้งหมด 25,000 บาทต่อเดือน"
    )
    session = module().ReviewSession(case, docs)
    session.execute(
        "compare_declarations",
        {
            "claims": [
                {"kind": "monthly_revenue", "value": "275000", "quote": session.message},
                {"kind": "monthly_business_cost", "value": "25000", "quote": session.message},
            ]
        },
    )
    assert session.declarations_checked
    assert {(i["expected"], i["observed"]) for i in session.issues} == {
        ("275000.00", "200000.00"),
        ("25000.00", "145000.00"),
    }


def test_unparsed_free_text_is_not_covered_by_an_unrelated_valid_account_claim():
    case, docs, _, _ = sample("C01")
    case["input"]["message"] = "บัญชี OWN-A และรายได้เดือนละสองแสนบาท ยังไม่ได้ส่งหลักฐาน"
    session = module().ReviewSession(case, docs)
    session.execute(
        "compare_declarations",
        {"claims": [{"kind": "business_account", "value": "ACC-1", "quote": session.message}]},
    )
    assert any(
        i["code"] == "DECLARATION_UNPARSED" and "สองแสน" in str(i["observed"])
        for i in session.issues
    )
    assert not session.declarations_checked


def test_incomplete_declaration_replay_is_idempotent_and_invalidates_old_cashflow():
    case, docs, _, _ = sample("C11")
    session = module().ReviewSession(case, docs)
    session.execute("inspect_cashflow", {})
    arguments = {
        "claims": [{"kind": "business_account", "value": "ACC-1", "quote": session.message}]
    }
    session.execute("compare_declarations", arguments)
    assert not session.context()["cashflow_current"]
    baseline = deepcopy((session.issues, session.ledger_revision))
    assert session.execute("compare_declarations", arguments)["replayed"]
    assert (session.issues, session.ledger_revision) == baseline
    with pytest.raises(SandboxError):
        session.execute("finish_review", {"reason": "ต้องตรวจ cashflow ใหม่หลังพบประเด็น"})


def test_later_invalid_declaration_rolls_back_coverage_issues_and_receipts():
    case, docs, _, _ = sample("C11")
    session = module().ReviewSession(case, docs)
    baseline = deepcopy(session.__dict__)
    with pytest.raises(SandboxError):
        session.execute(
            "compare_declarations",
            {
                "claims": [
                    {"kind": "business_account", "value": "OWN-B", "quote": session.message},
                    {"kind": "monthly_revenue", "value": "999999", "quote": "invented"},
                ]
            },
        )
    assert session.__dict__ == baseline


@pytest.mark.parametrize(
    "message,claims,missed",
    [
        (
            "ยังมีอีก 75000 บาทที่ต้องพิสูจน์ บัญชี OWN-A",
            [("business_account", "ACC-1")],
            "75000",
        ),
        ("ยอดขาย 200000 บาทต่อปี", [("monthly_revenue", "200000")], "ต่อปี"),
        ("ยอดขายเดือนละ 200000 ล้านบาท", [("monthly_revenue", "200000")], "ล้านบาท"),
        ("ยอดขาย 200000 บาท", [("monthly_revenue", "200000")], "ยอดขาย"),
    ],
)
def test_uncertain_money_span_or_period_cannot_be_assumed_monthly(message, claims, missed):
    case, docs, _, _ = sample("C01")
    case["input"]["message"] = message
    session = module().ReviewSession(case, docs)
    session.execute(
        "compare_declarations",
        {"claims": [{"kind": k, "value": v, "quote": session.message} for k, v in claims]},
    )
    gaps = [i for i in session.issues if i["code"] == "DECLARATION_UNPARSED"]
    assert gaps and any(missed in str(i["observed"]) for i in gaps)
    assert not session.declarations_checked
    session.execute("inspect_cashflow", {})
    session.execute("finish_review", {"reason": "ขอความหมายของยอดเงินและช่วงเวลา"})
    assert session.result()["packet"]["financial"] is None


def test_out_of_bound_message_amount_stays_unparsed_without_breaking_the_audit():
    case, docs, _, _ = sample("C01")
    case["input"]["message"] = "ยอดขายเดือนละ " + "9" * 80 + " บาท"
    session = module().ReviewSession(case, docs)
    session.execute("compare_declarations", {"claims": []})
    assert not session.declarations_checked
    assert any(i["code"] == "DECLARATION_UNPARSED" for i in session.issues)
    session.execute("inspect_cashflow", {})
    session.execute("finish_review", {"reason": "ขอยืนยันยอดที่เกินขอบเขตของเครื่องมือนี้"})
    assert session.result()["packet"]["financial"] is None
