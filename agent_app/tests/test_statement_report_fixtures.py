"""Independent arithmetic and real-parser checks for NEW synthetic probes only.

Breaks caught: omitted rows/months, accidentally treated zero as missing coverage,
wrong balances/ref provenance, oracle leakage, and overstated evidence support.
No provider, database, HTTP service, policy change or old oracle is involved.
"""

import importlib.util
import json
import re
import sys
from copy import deepcopy
from decimal import Decimal as D
from hashlib import sha256
from pathlib import Path

import pytest

from merchant_sandbox.agentic_review import ReviewSession
from merchant_sandbox.statements import parse_statement, verify_statements

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent_app/tools"))


def test_additional_builder_exposes_review_session_inputs():
    path = ROOT / "agent_app/tools/statement_report_fixtures.py"
    assert path.is_file(), "New additional fixture builder has not been implemented"
    from statement_report_fixtures import build_cases

    built = build_cases()
    assert len(built) == 5
    for item in built.values():
        assert ReviewSession(item["case"], item["documents"]).context()["accounts_present"]


@pytest.fixture(scope="module")
def cases():
    path = ROOT / "agent_app/tools/statement_report_fixtures.py"
    if not path.is_file():
        pytest.skip("Dependent arithmetic checks await the missing builder contract")
    spec = importlib.util.spec_from_file_location("statement_report_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_cases()


# Literal expected values were hand-derived BEFORE the builder. These do not
# call the fixture's expectation generator (there must not be one).
@pytest.mark.parametrize(
    "sid,wants",
    [
        (
            "S01",
            [
                (9, "1000000.00", "600000.00", "435000.00", "1165000.00"),
                (9, "1000000.00", "600000.00", "435000.00", "1165000.00"),
            ],
        ),
        ("S02", [(20, "1000000.00", "1380000.00", "870000.00", "1510000.00")]),
        ("S03", [(17, "1000000.00", "900000.00", "870000.00", "1030000.00")]),
        ("S04", [(20, "1000000.00", "2100000.00", "1760000.00", "1340000.00")]),
        ("S05", [(36, "1000000.00", "1200000.00", "1212000.00", "988000.00")]),
    ],
)
def test_every_document_parses_and_reconciles_to_hand_checked_totals(cases, sid, wants):
    fixture = cases[sid]
    assert set(fixture) == {"case", "documents", "corroboration", "expected"}
    assert fixture["corroboration"] is None
    assert len(fixture["documents"]) == len(wants)
    for doc, (count, opening, credit, debit, closing), oracle in zip(
        fixture["documents"], wants, fixture["expected"]["document_totals"], strict=True
    ):
        assert (
            oracle["rows"],
            oracle["opening_thb"],
            oracle["credit_thb"],
            oracle["debit_thb"],
            oracle["closing_thb"],
        ) == (count, opening, credit, debit, closing)
        parsed = parse_statement(doc)
        rows = parsed["rows"]
        assert len(rows) == count
        assert sum(D(r["credit"]) for r in rows) == D(credit)
        assert sum(D(r["debit"]) for r in rows) == D(debit)
        assert rows[-1]["balance"] == closing
        balance = D(opening)
        for index, row in enumerate(rows, 2):
            balance += D(row["credit"]) - D(row["debit"])
            assert D(row["balance"]) == balance
            assert row["ref"] == f"{doc['id']}:page-1:table-1:row-{index}"
        text = doc["ocr_pages"][0]["text"]
        assert doc["sha256"] == sha256(text.encode("utf-8")).hexdigest()
        assert doc["fixture_provenance"]["sha256_basis"] == "UTF8_OCR_TEXT_NOT_SOURCE_PDF"


def test_declining_case_has_a_real_zero_month_not_a_missing_statement(cases):
    item = cases["S03"]
    evidence = verify_statements(item["documents"], item["case"])
    assert evidence["coverage"] == "COMPLETE" and evidence["missing_months"] == []
    assert [m["R"] for m in evidence["months"]] == [
        "240000.00",
        "210000.00",
        "180000.00",
        "150000.00",
        "120000.00",
        "0.00",
    ]
    assert [m["F"] for m in evidence["months"]] == ["45000.00"] * 6
    # Characterization of the EXISTING provisional formula; this does not
    # establish supported sales, debt completeness or approval capacity.
    session = ReviewSession(item["case"], item["documents"])
    session.execute("compare_declarations", {"claims": []})
    result = session.execute("inspect_cashflow", {})
    assert [r["residual_before_reserve_thb"] for r in result["rows"]] == [
        "70000.00",
        "40000.00",
        "10000.00",
        "-20000.00",
        "-50000.00",
        "-170000.00",
    ]


def test_internally_balanced_documents_preserve_owner_period_and_cross_document_conflict(cases):
    item = cases["S01"]
    first, second = map(parse_statement, item["documents"])
    assert first["account"] == second["account"] == "OWN-A"
    assert first["account_holder"] == "Mali Jaidee"
    assert second["account_holder"] == "Other Person"
    assert second["end"].isoformat() == "2026-09-29"
    # Each file balances. The next file nevertheless starts 165000 lower.
    second_opening = D(second["rows"][0]["balance"]) - D(second["rows"][0]["credit"])
    assert D(first["rows"][-1]["balance"]) - second_opening == D("165000.00")
    evidence = verify_statements(item["documents"], item["case"])
    assert evidence["status"] == "NEEDS_REVIEW"
    assert evidence["missing_months"] == ["2026-09"]
    assert any(i.get("document_id") == "DOC-S01-B" for i in evidence["issues"])
    oracle = item["expected"]["cross_document_continuity"]
    assert oracle["previous_closing_thb"] == "1165000.00"
    assert oracle["next_opening_thb"] == "1000000.00"
    assert oracle["unexplained_difference_thb"] == "-165000.00"


@pytest.mark.xfail(
    strict=True,
    reason="Frozen V4 does not check cross-document opening/closing continuity; preserve this unmet expectation",
)
def test_s01_continuity_alone_must_require_review_even_if_each_file_balances(cases):
    # Diagnostic ablation of S01, not a sixth model case. Remove the two
    # independently detected issues so they cannot hide the missing validator.
    item = cases["S01"]
    documents = deepcopy(item["documents"])
    documents[1]["ocr_pages"][0]["text"] = (
        documents[1]["ocr_pages"][0]["text"]
        .replace("Other Person", "Mali Jaidee")
        .replace("2026-09-29", "2026-09-30")
    )
    documents[1]["sha256"] = sha256(
        documents[1]["ocr_pages"][0]["text"].encode("utf-8")
    ).hexdigest()
    # Both parse; a 165000 cross-period opening shortfall still must be surfaced.
    assert all(parse_statement(doc)["rows"] for doc in documents)
    evidence = verify_statements(documents, item["case"])
    assert evidence["coverage"] == "COMPLETE"
    assert evidence["status"] == "NEEDS_REVIEW"


def test_loan_capital_and_fast_flow_have_distinct_literal_refs_and_amounts(cases):
    loan_rows = {r["ref"]: r for r in parse_statement(cases["S02"]["documents"][0])["rows"]}
    assert loan_rows["DOC-S02-A:page-1:table-1:row-3"]["credit"] == "100000.00"
    assert loan_rows["DOC-S02-A:page-1:table-1:row-7"]["credit"] == "80000.00"
    assert (
        loan_rows["DOC-S02-A:page-1:table-1:row-7"]["description"]
        == "shop sales - owner capital contribution"
    )
    fast_rows = parse_statement(cases["S04"]["documents"][0])["rows"][-2:]
    assert [(r["date"], r["debit"], r["credit"], r["ref"]) for r in fast_rows] == [
        ("2026-09-29", "0.00", "900000.00", "DOC-S04-A:page-1:table-1:row-20"),
        ("2026-09-30", "890000.00", "0.00", "DOC-S04-A:page-1:table-1:row-21"),
    ]


def test_anonymous_payments_and_identifiable_debt_do_not_fill_unknown_total_debt(cases):
    item = cases["S05"]
    rows = parse_statement(item["documents"][0])["rows"]
    anonymous = [r for r in rows if r["description"].startswith("payment ref ANON-")]
    assert len(anonymous) == 12
    assert sum(D(r["debit"]) for r in anonymous) == D("282000.00")
    repayments = [r for r in rows if r["description"] == "loan repayment lender L1"]
    assert len(repayments) == 6
    assert sum(D(r["debit"]) for r in repayments) == D("60000.00")
    assert item["case"]["input"]["debt_thb"] is None
    session = ReviewSession(item["case"], item["documents"])
    session.execute("compare_declarations", {"claims": []})
    result = session.execute("inspect_cashflow", {})
    assert result["status"] == "UNKNOWN" and result["new_installment_max_thb"] is None


def test_oracles_are_literal_separate_and_every_evidence_ref_resolves(cases):
    spec = json.loads(
        (ROOT / "examples/merchant_sandbox/statement_review_additional_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(cases) == {"S01", "S02", "S03", "S04", "S05"}
    for sid, item in cases.items():
        assert item["expected"] == spec["cases"][sid]["expected"]
        assert set(item["expected"]["sections"]) == {
            "supported_sales_receipts",
            "non_sales_inflows",
            "identifiable_payment_obligations",
            "unresolved_items_questions",
        }
        supported = item["expected"]["sections"]["supported_sales_receipts"]
        assert supported["confirmed_total_thb"] is None and supported["receipts"] == []
        valid_refs = {"input:debt_thb", "input:living_cost_thb", "input:message"}
        for doc in item["documents"]:
            valid_refs.add(doc["id"])
            valid_refs.update(r["ref"] for r in parse_statement(doc)["rows"])

        def check_refs(value, allowed_refs):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "refs":
                        assert child and set(child) <= allowed_refs
                    else:
                        check_refs(child, allowed_refs)
            elif isinstance(value, list):
                for child in value:
                    check_refs(child, allowed_refs)

        check_refs(item["expected"], valid_refs)
        session = ReviewSession(item["case"], item["documents"])
        model_payload = json.dumps(
            {"context": session.context(), "documents": item["documents"], "case": item["case"]},
            ensure_ascii=False,
        )
        assert "evaluation_only" not in model_payload
        assert "confirmed_total_thb" not in model_payload
        assert "cross_document_continuity" not in model_payload
        assert re.search(r'"expected"\s*:', json.dumps(item["case"])) is None
