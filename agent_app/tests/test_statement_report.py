"""Independent, synthetic statement-report expectations; no providers or database."""

import importlib
import importlib.util
import json
from copy import deepcopy
from decimal import Decimal

import pytest


def api():
    assert importlib.util.find_spec("merchant_sandbox.statement_report") is not None, (
        "The derived four-part staff report has not been implemented"
    )
    return importlib.import_module("merchant_sandbox.statement_report")


def case():
    return {
        "id": "CASE-report",
        "version": 2,
        "created_at": "2026-10-23T00:00:00+00:00",
        "input": {
            "applicant_name": "Mali Jaidee",
            "message": "cash sales 9999",
            "debt_thb": None,
            "living_cost_thb": None,
        },
        "is_mock": True,
        "results": {},
        "decision": "APPROVED",
    }


def document(rows, ident="DOC-A", account="ACCOUNT-A", holder="Mali Jaidee"):
    """Rows use explicit balances so expected values do not share report arithmetic."""
    text = (
        f"Account holder: {holder}\nAccount: {account}\n"
        "Period: 2026-04-01 to 2026-09-30\nOpening balance: 1000.00\n"
        "| Date | Description | Debit | Credit | Balance |\n"
        "|---|---|---|---|---|\n"
        + "\n".join("| " + " | ".join(r) + " |" for r in rows)
        + f"\nClosing balance: {rows[-1][-1]}"
    )
    return {
        "id": ident,
        "case_id": "CASE-report",
        "kind": "statement",
        "sha256": "synthetic",
        "is_mock": True,
        "ocr_pages": [{"page": 1, "text": text}],
    }


def ref(row=2, doc="DOC-A"):
    return f"{doc}:page-1:table-1:row-{row}"


def evidence(purpose="SALES", amount="100.00", refs=None, origin="external_record", **extra):
    return {
        "schema_version": "statement-corroboration-v1",
        "provided_by": "application",
        "evidence": [
            {
                "origin": origin,
                "evidence_id": "RECEIPT-1",
                "transaction_refs": refs or [ref()],
                "amount": amount,
                "supported_purpose": purpose,
                **extra,
            }
        ],
    }


def build(rows, *, data=None, proof=None):
    return api().build_staff_report(data or case(), [document(rows)], corroboration=proof)


def items(report, section):
    return report["sections"][section]["items"]


def test_r_category_sales_memo_and_model_confidence_never_prove_sales():
    data = case()
    data["results"] = {
        "evidence": {
            "rows": [{"ref": ref(), "category": "R", "confidence": "1.0", "verified": True}],
            "issues": [],
        }
    }
    report = build([["2026-04-01", "shop sales QR", "0", "100", "1100"]], data=data)
    assert report["sections"]["supported_sales"]["credit_total_thb"] == "0.00"
    assert items(report, "follow_up")[0]["transaction_refs"] == [ref()]
    assert (
        report["monthly_cashflow_summary"]["rows"][0]["eligible_unverified_inflows_thb"] == "100.00"
    )
    assert report["human_final_decision_required"] is True and report["decision"] is None


@pytest.mark.parametrize(
    "memo,purpose",
    [
        ("loan proceeds", "LOAN_PROCEEDS"),
        ("capital injection", "CAPITAL"),
        ("sale of old equipment", "ASSET_SALE"),
        ("own transfer", "INTERNAL_TRANSFER"),
    ],
)
def test_explicit_non_sales_description_is_not_independent_verification(memo, purpose):
    report = build([["2026-04-01", memo, "0", "100", "1100"]])
    row = items(report, "non_sales_inflows")[0]
    assert (row["purpose"], row["support_level"], row["amount_thb"]) == (
        purpose,
        "STATEMENT_DESCRIBED",
        "100.00",
    )
    assert row["authenticity"] == "UNVERIFIED"


def test_unknown_debits_and_cash_withdrawals_are_never_raw_material_expenses():
    report = build(
        [
            ["2026-04-01", "cash withdrawal", "40", "0", "960"],
            ["2026-04-02", "payment mixed household and shop", "60", "0", "900"],
        ]
    )
    assert items(report, "identifiable_obligations") == []
    assert [x["purpose"] for x in items(report, "follow_up") if x["transaction_refs"]] == [
        "UNKNOWN",
        "UNKNOWN",
    ]
    row = report["monthly_cashflow_summary"]["rows"][0]
    assert (row["observed_debits_thb"], row["observed_net_thb"], row["residual_thb"]) == (
        "100.00",
        "-100.00",
        None,
    )


@pytest.mark.parametrize(
    "memo,purpose", [("rent", "RENT"), ("payroll", "PAYROLL"), ("loan repayment", "DEBT_PAYMENT")]
)
def test_identifiable_payments_are_statement_described_not_assumed_all_debt(memo, purpose):
    report = build([["2026-04-01", memo, "100", "0", "900"]])
    row = items(report, "identifiable_obligations")[0]
    assert row["purpose"] == purpose and row["debit_thb"] == "100.00"
    assert report["document_checks"]["outgoing_and_debt"]["status"] == "UNKNOWN"


def test_application_external_record_can_support_sales_but_not_authenticity():
    report = build([["2026-04-01", "shop sales", "0", "100", "1100"]], proof=evidence())
    row = items(report, "supported_sales")[0]
    assert row["support_level"] == "EXTERNALLY_SUPPORTED"
    assert row["refs"] == [ref(), "RECEIPT-1"]
    assert row["amount_thb"] == "100.00" and row["authenticity"] == "UNVERIFIED"
    assert report["synthetic"] is True


def test_native_settlement_requires_explicit_structured_code_not_qr_memo():
    report = build(
        [["2026-04-01", "QR settlement", "0", "100", "1100"]],
        proof=evidence(origin="statement_native_type", native_code="MERCHANT_SETTLEMENT"),
    )
    assert items(report, "supported_sales")[0]["support_level"] == "STATEMENT_SUPPORTED"


@pytest.mark.parametrize(
    "proof",
    [
        {"verified": True, "sales": True},
        evidence(amount="99.99"),
        evidence(refs=["DOC-absent:row-2"]),
        evidence(refs=[ref(), ref()]),
        evidence(amount="NaN"),
        evidence(origin="model"),
        evidence(origin="statement_native_type", native_code="QR"),
        evidence(purpose="UNKNOWN"),
        evidence(origin="bilateral_statement_match"),
        {**evidence(), "provided_by": "model"},
    ],
)
def test_broken_or_model_corroboration_cannot_promote_inflows(proof):
    report = build([["2026-04-01", "shop sales", "0", "100", "1100"]], proof=proof)
    assert items(report, "supported_sales") == []
    assert any(x["code"] == "CORROBORATION_REJECTED" for x in items(report, "follow_up"))


def test_conflicting_evidence_quarantines_instead_of_first_or_last_wins():
    proof = evidence()
    proof["evidence"].append(
        {**proof["evidence"][0], "evidence_id": "R-2", "supported_purpose": "CAPITAL"}
    )
    report = build([["2026-04-01", "shop sales", "0", "100", "1100"]], proof=proof)
    assert items(report, "supported_sales") == []
    assert items(report, "non_sales_inflows") == []
    assert any(x["code"] == "CORROBORATION_CONFLICT" for x in items(report, "follow_up"))


def test_bilateral_transfer_requires_owned_counterpart_not_equal_amounts():
    docs = [
        document([["2026-04-01", "own transfer from ACCOUNT-B", "0", "100", "1100"]]),
        document(
            [["2026-04-01", "own transfer to ACCOUNT-A", "100", "0", "900"]], "DOC-B", "ACCOUNT-B"
        ),
    ]
    proof = evidence(
        "INTERNAL_TRANSFER", refs=[ref(), ref(doc="DOC-B")], origin="bilateral_statement_match"
    )
    report = api().build_staff_report(case(), docs, corroboration=proof)
    assert items(report, "non_sales_inflows")[0]["support_level"] == "BILATERAL_VERIFIED"
    assert report["raw_rows_conservation"]["assigned_rows"] == 2
    docs[1]["ocr_pages"][0]["text"] = docs[1]["ocr_pages"][0]["text"].replace(
        "to ACCOUNT-A", "to unrelated"
    )
    report = api().build_staff_report(case(), docs, corroboration=proof)
    assert items(report, "non_sales_inflows")[0]["support_level"] == "STATEMENT_DESCRIBED"


def test_monthly_stats_use_zero_supported_months_not_invented_sales_or_thresholds():
    rows = [
        ["2026-04-01", "payment", "0", "100", "1100"],
        ["2026-09-01", "payment", "0", "300", "1400"],
    ]
    proof = evidence()
    proof["evidence"].append(
        {
            **proof["evidence"][0],
            "evidence_id": "R-2",
            "transaction_refs": [ref(3)],
            "amount": "300",
        }
    )
    report = build(rows, proof=proof)
    summary = report["monthly_cashflow_summary"]
    assert [r["supported_sales_thb"] for r in summary["rows"]] == [
        "100.00",
        "0.00",
        "0.00",
        "0.00",
        "0.00",
        "300.00",
    ]
    stats = summary["supported_sales_statistics"]
    assert (
        stats["average_thb"],
        stats["min_thb"],
        stats["max_thb"],
        stats["first_to_last_change_thb"],
    ) == ("66.67", "0.00", "300.00", "200.00")
    assert stats["zero_supported_sales_months"] == ["2026-05", "2026-06", "2026-07", "2026-08"]
    assert stats["population_stddev_thb"] == "110.55"
    assert stats["trend_slope_thb_per_month"] == "28.57"


def test_missing_documents_leave_all_six_dimensions_unknown_and_cash_claim_unverified():
    report = api().build_staff_report(case(), [])
    assert len(report["document_checks"]) == 6
    assert all(x["status"] == "UNKNOWN" for x in report["document_checks"].values())
    assert report["monthly_cashflow_summary"]["supported_sales_statistics"]["average_thb"] is None
    assert any(x["code"] == "CUSTOMER_MESSAGE_UNVERIFIED" for x in items(report, "follow_up"))


@pytest.mark.parametrize("change", ["balance", "holder", "case_id"])
def test_document_mismatch_conserves_raw_rows_without_income_promotion(change):
    doc = document([["2026-04-01", "shop sales", "0", "100", "1100"]])
    if change == "balance":
        doc["ocr_pages"][0]["text"] = doc["ocr_pages"][0]["text"].replace("1100", "1101")
    elif change == "holder":
        doc["ocr_pages"][0]["text"] = doc["ocr_pages"][0]["text"].replace(
            "Mali Jaidee", "Another Person"
        )
    else:
        doc["case_id"] = "OTHER-CASE"
    report = api().build_staff_report(case(), [doc], corroboration=evidence())
    assert items(report, "supported_sales") == []
    assert report["raw_rows"][0]["ref"] == ref()
    assert report["raw_rows_conservation"] == {
        "raw_rows": 1,
        "assigned_rows": 1,
        "unassigned_refs": [],
        "multiply_assigned_refs": [],
    }
    assert any(x["code"] == "DOCUMENT_REVIEW" for x in items(report, "follow_up"))
    assert (
        report["document_checks"]["document_account_period_continuity"]["authenticity"]
        == "UNVERIFIED"
    )


def test_duplicate_documents_and_outside_period_do_not_double_count():
    doc = document([["2026-04-01", "shop sales", "0", "100", "1100"]])
    duplicate = deepcopy(doc)
    duplicate["id"] = "DOC-copy"
    report = api().build_staff_report(case(), [doc, duplicate], corroboration=evidence())
    assert report["sections"]["supported_sales"]["credit_total_thb"] == "100.00"
    assert report["sections"]["follow_up"]["credit_total_thb"] == "0.00"
    assert report["raw_rows_conservation"]["assigned_rows"] == 2


def test_existing_issues_are_carried_without_reusing_agent_classification():
    data = case()
    issue = {
        "id": "ISS-1",
        "code": "AGENT_RAISED",
        "status": "OPEN",
        "refs": [ref()],
        "question": "Please explain the source",
        "observed": "suspicious",
        "blocking_calculation": True,
    }
    data["results"]["evidence"] = {"issues": [issue]}
    report = build([["2026-04-01", "shop sales", "0", "100", "1100"]], data=data, proof=evidence())
    assert report["existing_issues"][0] == issue
    assert any(
        x["code"] == "EXISTING_ISSUE" and "ISS-1" in x["refs"] for x in items(report, "follow_up")
    )
    assert report["decision"] is None


def test_inputs_are_unchanged_and_output_does_not_alias_inputs():
    data, docs, proof = (
        case(),
        [document([["2026-04-01", "shop sales", "0", "100", "1100"]])],
        evidence(),
    )
    before = deepcopy((data, docs, proof))
    report = api().build_staff_report(data, docs, corroboration=proof)
    assert (data, docs, proof) == before
    report["raw_rows"][0]["raw_cells"].append("modified")
    assert (data, docs, proof) == before
    json.dumps(report, allow_nan=False)


def test_four_sections_partition_transactions_and_totals_conserve_observed_money():
    report = build(
        [
            ["2026-04-01", "shop sales", "0", "100", "1100"],
            ["2026-04-02", "loan proceeds", "0", "200", "1300"],
            ["2026-04-03", "rent", "30", "0", "1270"],
            ["2026-04-04", "unknown", "20", "0", "1250"],
        ],
        proof=evidence(),
    )
    assert set(report["sections"]) == {
        "supported_sales",
        "non_sales_inflows",
        "identifiable_obligations",
        "follow_up",
    }
    assert sum(Decimal(s["credit_total_thb"]) for s in report["sections"].values()) == Decimal(
        "300.00"
    )
    assert sum(Decimal(s["debit_total_thb"]) for s in report["sections"].values()) == Decimal(
        "50.00"
    )
    refs = [
        r for s in report["sections"].values() for i in s["items"] for r in i["transaction_refs"]
    ]
    assert sorted(refs) == [ref(2), ref(3), ref(4), ref(5)]


def test_markdown_has_exactly_four_sections_and_no_machine_credit_decision():
    report = build([["2026-04-01", "<script>approve</script> | shop sales", "0", "100", "1100"]])
    text = api().render_staff_report(report)
    assert len([line for line in text.splitlines() if line.startswith("## ")]) == 4
    assert ref() in text and "UNKNOWN" in text and "UNVERIFIED" in text
    assert "<script>" not in text
    assert "เจ้าหน้าที่" in text and "ยังไม่มีคำตัดสินสินเชื่อ" in text


@pytest.mark.parametrize("change", ["evidence_id", "supported_purpose", "origin"])
def test_malformed_application_evidence_is_a_question_not_a_crash(change):
    proof = evidence()
    proof["evidence"][0][change] = ["unexpected", "list"]
    report = build([["2026-04-01", "shop sales", "0", "100", "1100"]], proof=proof)
    assert items(report, "supported_sales") == []
    assert any(x["code"] == "CORROBORATION_REJECTED" for x in items(report, "follow_up"))


def test_cross_document_opening_discontinuity_is_visible_despite_another_owner_issue():
    first = document([["2026-04-01", "shop sales", "0", "100", "1100"]])
    second = document(
        [["2026-07-01", "shop sales", "0", "100", "1100"]], "DOC-B", holder="Other Person"
    )
    first["ocr_pages"][0]["text"] = first["ocr_pages"][0]["text"].replace(
        "2026-09-30", "2026-06-30"
    )
    second["ocr_pages"][0]["text"] = second["ocr_pages"][0]["text"].replace(
        "2026-04-01", "2026-07-01"
    )
    report = api().build_staff_report(case(), [first, second])
    continuity = [x for x in items(report, "follow_up") if x["code"] == "CONTINUITY_MISMATCH"]
    assert len(continuity) == 1
    assert continuity[0]["previous_closing_thb"] == "1100.00"
    assert continuity[0]["next_opening_thb"] == "1000.00"
    assert continuity[0]["difference_thb"] == "-100.00"


def test_overlapping_nonidentical_documents_are_quarantined_not_summed():
    first = document([["2026-04-01", "shop sales", "0", "100", "1100"]])
    second = document([["2026-04-01", "shop sales", "0", "200", "1200"]], "DOC-B")
    report = api().build_staff_report(case(), [first, second], corroboration=evidence())
    assert items(report, "supported_sales") == []
    assert report["sections"]["follow_up"]["credit_total_thb"] == "0.00"
    assert any(x["code"] == "OVERLAPPING_DOCUMENTS" for x in items(report, "follow_up"))


def test_configured_product_window_and_incomplete_months_never_become_zero_income():
    data = case()
    data["policy_snapshot"] = {"assessment": {"history_complete_closed_months": 3}}
    doc = document([["2026-07-01", "shop sales", "0", "100", "1100"]])
    doc["ocr_pages"][0]["text"] = (
        doc["ocr_pages"][0]["text"]
        .replace("2026-04-01", "2026-07-01")
        .replace("2026-09-30", "2026-09-29")
    )
    report = api().build_staff_report(data, [doc], corroboration=evidence())
    summary = report["monthly_cashflow_summary"]
    assert summary["window_months"] == ["2026-07", "2026-08", "2026-09"]
    assert [x["supported_sales_thb"] for x in summary["rows"]] == ["100.00", "0.00", None]
    assert summary["supported_sales_statistics"]["average_thb"] == "50.00"
    assert summary["supported_sales_statistics"]["zero_supported_sales_months"] == ["2026-08"]


def test_invalid_merged_table_preserves_raw_row_refs():
    doc = document([["2026-04-01", "shop sales", "0", "100", "1100"]])
    doc["ocr_pages"][0]["text"] = (
        "Account holder: Mali Jaidee\nAccount: ACCOUNT-A\nPeriod: 2026-04-01 to 2026-09-30\n"
        "Opening balance: 1000\n<table><tr><td colspan='2'>Date</td><td>Description</td><td>Debit</td><td>Credit</td><td>Balance</td></tr>"
        "<tr><td>2026-04-01</td><td>shop sales</td><td>0</td><td>100</td><td>1100</td></tr></table>\nClosing balance: 1100"
    )
    report = api().build_staff_report(case(), [doc])
    assert report["raw_rows_conservation"]["raw_rows"] == 1
    assert report["raw_rows_conservation"]["unassigned_refs"] == []
    assert report["raw_rows"][0]["ref"] == ref()
    assert items(report, "supported_sales") == []


def test_invalid_configured_window_is_unknown_instead_of_silently_claiming_six_month_policy():
    data = case()
    data["policy_snapshot"] = {"assessment": {"history_complete_closed_months": "bad"}}
    report = build([["2026-04-01", "shop sales", "0", "100", "1100"]], data=data)
    assert report["monthly_cashflow_summary"]["window_months"] == []
    assert report["document_checks"]["variability_and_trend"]["status"] == "UNKNOWN"
    assert any(x["code"] == "WINDOW_UNKNOWN" for x in items(report, "follow_up"))


def test_missing_document_monthly_items_still_have_a_provenance_pointer():
    report = api().build_staff_report(case(), [])
    assert all(
        row["refs"] == ["case:document_ids"] for row in report["monthly_cashflow_summary"]["rows"]
    )


def test_external_non_sales_records_and_external_payment_obligations_remain_distinct():
    report = build(
        [
            ["2026-04-01", "unknown deposit", "0", "100", "1100"],
            ["2026-04-02", "unknown payment", "50", "0", "1050"],
        ],
        proof={
            **evidence("CAPITAL"),
            "evidence": [
                evidence("CAPITAL")["evidence"][0],
                {
                    **evidence("BUSINESS_EXPENSE", "50", [ref(3)])["evidence"][0],
                    "evidence_id": "INVOICE-1",
                },
            ],
        },
    )
    assert items(report, "non_sales_inflows")[0]["support_level"] == "EXTERNALLY_SUPPORTED"
    assert items(report, "identifiable_obligations")[0]["purpose"] == "BUSINESS_EXPENSE"
    assert report["sections"]["supported_sales"]["credit_total_thb"] == "0.00"


def test_carried_issue_amounts_are_decimal_strings_without_mutating_source():
    data = case()
    data["results"]["evidence"] = {
        "issues": [
            {
                "id": "ISS-amount",
                "code": "UNRESOLVED",
                "amount_thb": 12.5,
                "expected": Decimal("20.00"),
                "observed": {"debit": 12},
                "refs": [ref()],
            }
        ]
    }
    before = deepcopy(data)
    report = build([["2026-04-01", "shop sales", "0", "100", "1100"]], data=data)
    assert report["existing_issues"][0]["amount_thb"] == "12.50"
    assert report["existing_issues"][0]["expected"] == "20.00"
    assert report["existing_issues"][0]["observed"]["debit"] == "12.00"
    assert data == before
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize(
    "memo,debit,credit,balance,section,purpose",
    [
        ("loan proceeds lender L1", "0", "100", "1100", "non_sales_inflows", "LOAN_PROCEEDS"),
        ("loan repayment lender L1", "100", "0", "900", "identifiable_obligations", "DEBT_PAYMENT"),
    ],
)
def test_structured_lender_label_is_described_only(memo, debit, credit, balance, section, purpose):
    report = build([["2026-04-01", memo, debit, credit, balance]])
    row = items(report, section)[0]
    assert row["purpose"] == purpose
    assert row["support_level"] == "STATEMENT_DESCRIBED"
    assert row["authenticity"] == "UNVERIFIED"
    assert row["refs"] == [ref()]
    assert items(report, "supported_sales") == []


@pytest.mark.parametrize(
    "memo,debit,credit,balance",
    [
        ("not loan proceeds lender L1", "0", "100", "1100"),
        ("loan proceeds lender L1 and shop sales", "0", "100", "1100"),
        ("loan proceeds lender L1 - owner capital contribution", "0", "100", "1100"),
        ("loan proceeds lender", "0", "100", "1100"),
        ("loan proceeds lender L1?", "0", "100", "1100"),
        ("loan repayment lender L1 or rent", "100", "0", "900"),
        ("not loan repayment lender L1", "100", "0", "900"),
        ("loan proceeds lender L1", "100", "0", "900"),
        ("loan repayment lender L1", "0", "100", "1100"),
    ],
)
def test_negative_mixed_or_wrong_direction_lender_memos_stay_unknown(memo, debit, credit, balance):
    report = build([["2026-04-01", memo, debit, credit, balance]])
    row = next(x for x in items(report, "follow_up") if x["transaction_refs"])
    assert row["purpose"] == "UNKNOWN" and row["support_level"] == "UNVERIFIED"
    assert row["included_in_totals"] is True
    assert items(report, "supported_sales") == []


@pytest.mark.parametrize("proof", [None, evidence(), evidence("CAPITAL")])
def test_sales_and_capital_memo_conflict_retains_source_question_without_promoting(proof):
    memo = "shop sales - owner capital contribution"
    report = build([["2026-04-01", memo, "0", "100", "1100"]], proof=proof)
    assert items(report, "supported_sales") == []
    assert items(report, "non_sales_inflows") == []
    conflict = next(x for x in items(report, "follow_up") if x["code"] == "DESCRIPTION_CONFLICT")
    assert conflict["refs"] == [ref()]
    assert conflict["described_purposes"] == ["CAPITAL", "SALES"]
    assert "capital" in conflict["question"].casefold()
    assert "sales" in conflict["question"].casefold()
    assert conflict["transaction_refs"] == []
    row = next(x for x in items(report, "follow_up") if x["transaction_refs"])
    assert row["description"] == memo and row["purpose"] == "UNKNOWN"
    assert row["support_level"] == "UNVERIFIED"
    assert report["sections"]["follow_up"]["credit_total_thb"] == "100.00"
    assert report["raw_rows_conservation"]["assigned_rows"] == 1
    assert "capital" in api().render_staff_report(report).casefold()


def test_physical_period_gap_remains_visible_when_all_documents_are_quarantined():
    first = document([["2026-04-01", "shop sales", "0", "100", "1100"]])
    second = document([["2026-07-01", "rent", "100", "0", "900"]], "DOC-B", holder="Other Person")
    first["ocr_pages"][0]["text"] = first["ocr_pages"][0]["text"].replace(
        "2026-09-30", "2026-06-30"
    )
    second["ocr_pages"][0]["text"] = (
        second["ocr_pages"][0]["text"]
        .replace("2026-04-01", "2026-07-01")
        .replace("2026-09-30", "2026-09-29")
    )
    report = api().build_staff_report(case(), [first, second], corroboration=evidence())
    check = report["document_checks"]["document_account_period_continuity"]
    assert check["account_coverage"] == {"ACCOUNT-A": []}
    assert check["missing_months"] == [
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
    ]
    assert check["physical_period_account_coverage"] == {
        "ACCOUNT-A": ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    }
    assert check["physical_period_missing_months"] == ["2026-09"]
    assert check["physical_period_missing_dates"] == {"ACCOUNT-A": ["2026-09-30"]}
    assert all(d["status"] == "NEEDS_REVIEW" for d in check["documents"])
    assert any("ownership" in p for d in check["documents"] for p in d["problems"])
    assert any(x["code"] == "CONTINUITY_MISMATCH" for x in items(report, "follow_up"))
    gap = next(x for x in items(report, "follow_up") if x["code"] == "PHYSICAL_PERIOD_GAP")
    assert "2026-09-30" in gap["question"]
    assert gap["refs"] == ["DOC-A", "DOC-B"]
    assert "2026-09-30" in api().render_staff_report(report)
    assert all(not row["eligible"] for row in report["raw_rows"])
    assert all(
        row["coverage"] == "UNKNOWN" and row["supported_sales_thb"] is None
        for row in report["monthly_cashflow_summary"]["rows"]
    )
    assert all(
        s["credit_total_thb"] == "0.00" and s["debit_total_thb"] == "0.00"
        for s in report["sections"].values()
    )


def test_physical_period_coverage_is_per_account_and_cannot_mask_another_accounts_gap():
    first = document([["2026-04-01", "shop sales", "0", "100", "1100"]])
    second = document([["2026-04-01", "shop sales", "0", "100", "1100"]], "DOC-B", "ACCOUNT-B")
    second["ocr_pages"][0]["text"] = second["ocr_pages"][0]["text"].replace(
        "2026-09-30", "2026-09-29"
    )
    report = api().build_staff_report(case(), [first, second])
    check = report["document_checks"]["document_account_period_continuity"]
    assert check["physical_period_missing_months"] == ["2026-09"]
    assert check["physical_period_missing_dates"] == {"ACCOUNT-A": [], "ACCOUNT-B": ["2026-09-30"]}
    assert report["monthly_cashflow_summary"]["rows"][-1]["coverage"] == "UNKNOWN"


def test_unparseable_period_does_not_invent_physical_coverage():
    doc = document([["2026-04-01", "shop sales", "0", "100", "1100"]])
    doc["ocr_pages"][0]["text"] = doc["ocr_pages"][0]["text"].replace("2026-09-30", "unreadable")
    report = api().build_staff_report(case(), [doc])
    check = report["document_checks"]["document_account_period_continuity"]
    assert check["physical_period_account_coverage"] == {}
    assert check["physical_period_missing_dates"] == {}
    assert check["physical_period_missing_months"] == [
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
    ]
    assert any(x["code"] == "DOCUMENT_REVIEW" for x in items(report, "follow_up"))
