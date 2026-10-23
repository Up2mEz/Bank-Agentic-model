"""Independent review regressions for proposal scope and customer-facing language."""

import pytest
from test_local_agentic_review import audit, module, sample

from merchant_sandbox.core import SandboxError
from merchant_sandbox.statements import parse_statement


def test_single_quote_does_not_reclassify_unread_group_members():
    case, docs, _, _ = sample("C05")
    rows = [
        (r["date"], r["description"], r["debit"], r["credit"])
        for r in parse_statement(docs[0])["rows"]
    ]
    rows.append(("2026-08-22", "incoming transfer reference X", 0, 500000))
    docs[0]["ocr_pages"][0]["text"] = audit.make_document(rows)["text"]
    session = module().ReviewSession(case, docs)
    issue = next(i for i in session.issues if i["code"] == "UNCLASSIFIED_INFLOW")
    assert len(issue["refs"]) == 2
    first, second = issue["refs"]
    session.execute("read_transactions", {"refs": [first]})
    session.execute(
        "propose_findings",
        {
            "findings": [
                {
                    "issue_id": issue["id"],
                    "interpretation": "ASSET_SALE",
                    "quotes": [{"ref": first, "quote": session.by_ref[first]["description"]}],
                    "question": "โปรดส่งหลักฐานที่มาของรายการนี้",
                    "requested_evidence": ["หลักฐานที่มาของเงิน"],
                }
            ]
        },
    )
    assert session.by_ref[first]["category"] == "ASSET_SALE"
    assert session.by_ref[second]["category"] == "UNRESOLVED"
    assert issue["status"] == "OPEN" and issue["blocking_calculation"]
    assert issue["proposal_applies_to_refs"] == [first]


@pytest.mark.parametrize(
    "reason", ["อนุมัติแล้ว ให้ลูกค้ารับเงินได้", "อนุมัติให้กู้", "approve loan", "approval granted"]
)
def test_finish_reason_cannot_present_an_approval(reason):
    case, docs, _, _ = sample("C01")
    session = module().ReviewSession(case, docs)
    session.execute("compare_declarations", {"claims": []})
    session.execute("inspect_cashflow", {})
    with pytest.raises(SandboxError):
        session.execute("finish_review", {"reason": reason})
    assert not session.finished


def test_business_context_available_for_transaction_interpretation():
    case, docs, _, _ = sample("C01")
    expected = {
        "business_type": case["input"]["business_type"],
        "loan_purpose": case["input"]["purpose"],
    }
    assert module().ReviewSession(case, docs).context()["business_profile_untrusted"] == expected
    assert module().full_context(case)["business_profile_untrusted"] == expected


def test_available_tools_follow_observed_progress_without_forcing_a_fixed_route():
    case, docs, _, _ = sample("C04")
    session = module().ReviewSession(case, docs)

    def names():
        return {t["function"]["name"] for t in session.tools()}

    assert {
        "read_transactions",
        "match_transfers",
        "compare_declarations",
    } <= names()
    assert "inspect_cashflow" not in names()
    assert "finish_review" not in names()
    session.execute("read_transactions", {"refs": list(session.by_ref)})
    assert "read_transactions" not in names() and "flag_transactions" in names()
    session.execute(
        "match_transfers", {"refs": [r["ref"] for r in session.rows if r["transfer_candidate"]]}
    )
    assert "match_transfers" not in names()
    session.execute("compare_declarations", {"claims": []})
    assert "compare_declarations" not in names() and "inspect_cashflow" in names()
    session.execute("inspect_cashflow", {})
    assert names() == {"finish_review"}


def test_protocol_repair_is_once_within_original_budget_and_no_tool_exec_on_failure():
    case, docs, _, _ = sample("C01")

    class Repairable:
        mode = "typhoon"

        def __init__(self):
            self.call_records = []

        def choose(self, context, tools, timeout):
            if not self.call_records:
                self.call_records.append(
                    {"status": "REJECTED", "rejection": {"stage": "finish_reason"}}
                )
                raise SandboxError("typhoon_invalid_native_tool_response")
            assert any(
                o["result"].get("protocol_repair")
                for o in context["observations"]
                if o["tool"] == "action_validator"
            )
            name = (
                "compare_declarations"
                if not context["declaration_coverage"]
                else ("inspect_cashflow" if not context["cashflow_current"] else "finish_review")
            )
            self.call_records.append({"status": "ACCEPTED"})
            args = (
                {"claims": []}
                if name == "compare_declarations"
                else ({"reason": "ส่งหลักฐานให้เจ้าหน้าที่ตรวจ"} if name == "finish_review" else {})
            )
            return {"tool": name, "arguments": args, "model": "test-only"}

    agent = Repairable()
    result = module().run_review(case, docs, agent, max_calls=4)
    assert len(agent.call_records) == result["llm_calls"] == 4
    assert result["state"] == "REVIEW_READY" and result["decision"] is None
    assert len([e for e in result["trace"] if e.get("kind") == "agent_action"]) == 4
    assert result["trace"][1]["status"] == "REJECTED"


@pytest.mark.parametrize(
    "stage,expected_calls", [("finish_reason", 2), ("credential_guard", 1), ("refusal", 1)]
)
def test_repeated_or_nonrepairable_protocol_errors_stop_without_financial_conclusion(
    stage, expected_calls
):
    case, docs, _, _ = sample("C01")

    class Broken:
        mode = "typhoon"

        def __init__(self):
            self.call_records = []

        def choose(self, context, tools, timeout):
            self.call_records.append({"status": "REJECTED", "rejection": {"stage": stage}})
            raise SandboxError("typhoon_invalid_native_tool_response")

    agent = Broken()
    result = module().run_review(case, docs, agent, max_calls=8)
    assert len(agent.call_records) == expected_calls
    assert result["state"] == "TECHNICAL_REVIEW"
    assert not result["results"].get("financial_calculate")
    assert result["decision"] is None


def test_replayed_read_is_visible_as_no_new_evidence_and_group_read_progress():
    case, docs, _, _ = sample("C01")
    session = module().ReviewSession(case, docs)
    ref = session.rows[0]["ref"]
    session.execute("read_transactions", {"refs": [ref]})
    result = session.execute("read_transactions", {"refs": [ref]})
    assert result["replayed"]
    assert session.context()["observations"][-1]["result"]["replayed"]
    assert ref in session.context()["progress"]["read_refs"]
    assert all(ref not in g["unread_refs"] for g in session.context()["source_groups"])


def test_packet_summary_is_system_authored_not_model_verdict():
    case, docs, _, _ = sample("C01")
    session = module().ReviewSession(case, docs)
    session.execute("compare_declarations", {"claims": []})
    session.execute("inspect_cashflow", {})
    session.execute("finish_review", {"reason": "model-authored-free-text"})
    packet = session.result()["packet"]
    assert packet["review_reason"] != "model-authored-free-text"
    assert packet["review_reason_origin"] == "SYSTEM_HANDOFF_TEMPLATE"
