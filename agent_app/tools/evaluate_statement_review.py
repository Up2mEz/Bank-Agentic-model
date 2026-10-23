"""Predeclared offline S01..S05 acceptance checks, independent of the renderer.

Interface: evaluate_new(sid, case, report, expected, records) -> JSON-safe dict.
The literal additional_v1 oracle is evaluation-only. Never pass it to a model.
No renderer/controller/fixture-builder imports, network, execution, or writes.

Two disjoint lanes are intentional: report_checks inspect descriptive renderer
output; agent_checks require accepted native choices linked to executed tool
receipts AND retained packet issues. Renderer discoveries never earn agent credit.
Native receipts are supplied audit evidence, not cryptographically authenticated.

Semantic limit: reference-linked free text is not mechanically proven neutral or
complete by keywords. Exact pre-reviewed literal oracle questions pass a bounded
question-content check. Other wording FAILS with NEEDS_HUMAN_SEMANTIC_REVIEW;
the accompanying cue result is explicitly lexical only. This is conservative:
valid paraphrases can fail. No private reasoning is inspected or reproduced.
All raw rows means inventory + amounts + partition conservation against literal
document totals, not source-PDF authenticity or an independent OCR audit.
Only these five synthetic cases are supported; old C11/H01 oracles stay separate.
"""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

ORACLE = (
    Path(__file__).resolve().parents[2]
    / "examples/merchant_sandbox/statement_review_additional_v1.json"
)
MONTHS = ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09")
SECTIONS = ("supported_sales", "non_sales_inflows", "identifiable_obligations", "follow_up")
DIMENSIONS = (
    "document_account_period_continuity",
    "inflow_source",
    "variability_and_trend",
    "outgoing_and_debt",
    "residual_and_liquidity",
    "patterns_and_questions",
)
NATIVE_TOOLS = {
    "read_transactions",
    "flag_transactions",
    "match_transfers",
    "compare_declarations",
    "inspect_cashflow",
    "propose_findings",
    "finish_review",
}
HUMAN = "NEEDS_HUMAN_SEMANTIC_REVIEW"
# These are bounded, manually reviewed neutral system templates, not a regex
# claiming to understand arbitrary assertions. They never satisfy case questions.
SAFE_REPORT_QUESTIONS = {
    "กรุณาตรวจรายการและเอกสารอ้างอิง",
    "กรุณาชี้แจงที่มาหรือวัตถุประสงค์ พร้อมหลักฐานประกอบ; เงินถอนสดยังไม่ระบุประเภทต้นทุน",
    "กรุณาตรวจและตอบประเด็นเดิมพร้อมหลักฐานอ้างอิง; ยังไม่สรุปความผิดปกติหรือผลสินเชื่อ",
    "กรุณาเทียบคำชี้แจง รวมถึงยอดขายเงินสดที่อาจไม่ได้เข้าบัญชี กับหลักฐานประกอบ; ไม่นำคำกล่าวอ้างมาบวกเป็นยอดขาย",
    "กรุณาระบุภาระต่อเดือนและหลักฐานประกอบ; ข้อมูลที่ขาดยังไม่เท่ากับศูนย์",
}
SAFE_ACTION_REASONS = {"Evidence required", "native tool choice"}


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _money(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _eq(left, right):
    return _money(left) is not None and _money(left) == _money(right)


def _sum(rows, key):
    values = [_money(_dict(row).get(key)) for row in rows]
    return sum(values, Decimal(0)) if all(v is not None for v in values) else None


def _refs(item):
    return [r for r in _list(_dict(item).get("refs")) if isinstance(r, str)]


def _covers(actual, expected):
    """A doc reference requires a ref in that doc; a row requires that exact row."""
    return bool(expected) and all(
        any(a == e or (":page-" not in e and a.startswith(e + ":page-")) for a in actual)
        for e in expected
    )


def _normalized(text):
    return " ".join(text.split()) if isinstance(text, str) else ""


def _questions(items, refs):
    return [
        i for i in items if isinstance(i, dict) and i.get("question") and _covers(_refs(i), refs)
    ]


def _cue(question, code):
    """Bounded diagnostics only; never claims semantic entailment/neutrality."""
    text = _normalized(question).casefold()
    groups = {
        "OWNER_MISMATCH": (("ชื่อ", "owner", "holder"), ("สัมพันธ์", "relationship")),
        "PERIOD_END_SHORT": (("2026-09-30",), ("statement", "เอกสาร")),
        "CROSS_DOCUMENT_DISCONTINUITY": (
            ("ยอด", "balance"),
            ("ต่อเนื่อง", "ยกมา", "closing", "opening"),
        ),
        "LOAN_SOURCE_AND_SCHEDULE": (("กู้", "loan"), ("ตาราง", "schedule", "ผ่อน")),
        "OWNER_CAPITAL_SOURCE": (("ทุน", "capital"), ("ต้นทาง", "source", "หลักฐาน")),
        "DECLINING_AND_ZERO_MONTH": (
            ("ลด", "declin"),
            ("กันยายน", "2026-09", "september"),
            ("สำรอง", "reserve", "shortage"),
        ),
        "LATE_INBOUND_RAPID_OUTBOUND": (
            ("ที่มา", "แหล่ง", "source"),
            ("วัตถุประสงค์", "purpose"),
            ("เกี่ยวข้อง", "relationship"),
        ),
        "ANONYMOUS_EXPENSE_PURPOSE": (("ผู้รับ", "recipient"), ("หลักฐาน", "evidence")),
        "DEBT_COMPLETENESS_UNKNOWN": (("หนี้ทั้งหมด", "total debt"), ("ตาราง", "schedule", "ผ่อน")),
    }
    return all(any(token in text for token in group) for group in groups.get(code, ()))


def _question_checks(add, items, expected_questions, prefix):
    for expected in expected_questions:
        code = expected["code"]
        candidates = _questions(items, expected["refs"])
        exact = any(
            _normalized(i.get("question")) == _normalized(expected["question"]) for i in candidates
        )
        lexical = any(_cue(i.get("question"), code) for i in candidates)
        add(
            prefix + code.lower(),
            exact,
            "literal reviewed question + linked refs"
            if exact
            else f"{HUMAN}; linked_questions={len(candidates)}; lexical_only_cues={lexical}",
        )


def _inventory(raw, items, expected):
    raw = [_dict(r) for r in raw]
    refs = [r.get("ref") for r in raw]
    expected_refs = {
        f"{doc['refs'][0]}:page-1:table-1:row-{index}"
        for doc in expected["document_totals"]
        for index in range(2, doc["rows"] + 2)
    }
    if any(not isinstance(ref, str) for ref in refs) or len(set(refs)) != len(refs):
        return False
    if set(refs) != expected_refs:
        return False
    for doc in expected["document_totals"]:
        rows = [r for r in raw if r.get("document_ref") == doc["refs"][0]]
        rows.sort(key=lambda r: int(r["ref"].rsplit("row-", 1)[1]))
        if len(rows) != doc["rows"] or not rows:
            return False
        if not _eq(_sum(rows, "credit"), doc["credit_thb"]) or not _eq(
            _sum(rows, "debit"), doc["debit_thb"]
        ):
            return False
        credit, debit, balance = (_money(rows[0].get(k)) for k in ("credit", "debit", "balance"))
        if None in (credit, debit, balance) or not _eq(
            balance - credit + debit, doc["opening_thb"]
        ):
            return False
        if not _eq(rows[-1].get("balance"), doc["closing_thb"]):
            return False
    assigned = [ref for item in items for ref in _list(item.get("transaction_refs"))]
    if any(not isinstance(ref, str) for ref in assigned):
        return False
    if Counter(assigned) != Counter(refs):
        return False
    by_ref = {r["ref"]: r for r in raw}
    for item in items:
        transaction_refs = _list(item.get("transaction_refs"))
        if not transaction_refs:
            continue
        if len(transaction_refs) != 1:
            return False
        row = by_ref[transaction_refs[0]]
        if not all(_eq(item.get(side + "_thb"), row.get(side)) for side in ("credit", "debit")):
            return False
        if item.get("date") != row.get("date") or item.get("description") != row.get("description"):
            return False
    return True


def _native_actions(case, records):
    """Return only controller-accepted choices backed by native + tool receipts."""
    trace = [_dict(e) for e in _list(case.get("trace"))]
    records = [_dict(r) for r in _list(records)]
    linked = []
    for index, action in enumerate(trace):
        if action.get("kind") != "agent_action" or action.get("status") != "ACCEPTED":
            continue
        if action.get("tool") not in NATIVE_TOOLS or not isinstance(action.get("arguments"), dict):
            continue
        native = [
            r
            for r in records
            if r.get("status") == "ACCEPTED"
            and r.get("attempt") == action.get("call")
            and r.get("tool") == action.get("tool")
            and r.get("arguments") == action.get("arguments")
        ]
        receipts = [
            e
            for e in trace[:index]
            if e.get("kind") == "tool"
            and e.get("actor") == "evidence_tool"
            and e.get("tool") == action.get("tool")
            and e.get("arguments") == action.get("arguments")
            and e.get("status") in {"OK", "UNKNOWN", "NEEDS_REVIEW"}
        ]
        if len(native) == 1 and receipts:
            linked.append((action, receipts[-1]))
    return linked


def _agent_questions(issues, linked):
    """No initial generic issues or renderer questions count as authored choices."""
    retained = []
    for issue in issues:
        if not isinstance(issue, dict) or issue.get("status") != "OPEN":
            continue
        for action, receipt in linked:
            args = action["arguments"]
            if action["tool"] == "flag_transactions":
                candidates = [args]
                result_issue = _dict(_dict(receipt.get("result")).get("issue"))
                if result_issue.get("id") != issue.get("id"):
                    continue
            elif action["tool"] == "propose_findings":
                candidates = [
                    {
                        **f,
                        "refs": [
                            q.get("ref") for q in _list(f.get("quotes")) if isinstance(q, dict)
                        ],
                    }
                    for f in _list(args.get("findings"))
                    if isinstance(f, dict) and f.get("issue_id") == issue.get("id")
                ]
                result_issues = _list(_dict(receipt.get("result")).get("issues"))
                if not any(_dict(i).get("id") == issue.get("id") for i in result_issues):
                    continue
            else:
                continue
            for candidate in candidates:
                if (
                    _normalized(candidate.get("question")) == _normalized(issue.get("question"))
                    and _covers(_refs(issue), _refs(candidate))
                    and _covers(_refs(candidate), _refs(issue))
                ):
                    retained.append({**candidate, "issue_id": issue.get("id")})
    return retained


def evaluate_new(sid, case, report, expected, records):
    """Evaluate frozen literal criteria; FAIL unless both named lanes all pass.

    Missing/malformed artifacts fail closed. Evidence contains only concise check
    diagnostics, reference IDs and public amounts, never model private reasoning.
    """
    report_checks, agent_checks = [], []

    def add_to(target):
        def add(requirement, passed, evidence=None):
            item = {"requirement": requirement, "passed": bool(passed)}
            if evidence is not None:
                item["evidence"] = evidence
            target.append(item)

        return add

    radd, aadd = add_to(report_checks), add_to(agent_checks)
    case, report, expected = _dict(case), _dict(report), _dict(expected)
    result = {
        "id": sid,
        "status": "FAIL",
        "state": case.get("state"),
        "decision": case.get("decision"),
        "report_checks": report_checks,
        "agent_checks": agent_checks,
    }
    try:
        literal = (
            json.loads(ORACLE.read_text(encoding="utf-8"))["cases"].get(sid, {}).get("expected")
        )
    except (OSError, ValueError, KeyError):
        literal = None
    valid_oracle = literal is not None and expected == literal
    radd("literal_oracle_unchanged", valid_oracle, "additional_v1 equality, no relaxed criteria")
    aadd("literal_oracle_unchanged", valid_oracle)
    if not valid_oracle:
        return result
    sections = _dict(report.get("sections"))
    section_items = {
        key: [_dict(i) for i in _list(_dict(sections.get(key)).get("items"))] for key in SECTIONS
    }
    items = [i for key in SECTIONS for i in section_items[key]]
    follow = section_items["follow_up"]
    raw = [_dict(r) for r in _list(report.get("raw_rows"))]
    checks = _dict(report.get("document_checks"))
    monthly = _dict(report.get("monthly_cashflow_summary"))
    rows = [_dict(row) for row in _list(monthly.get("rows"))]
    packet = _dict(case.get("packet"))
    issues = [_dict(i) for i in _list(packet.get("issues"))]
    records_list = [_dict(r) for r in _list(records)]
    linked = _native_actions(case, records_list)
    agent_questions = _agent_questions(issues, linked)
    cashflow = _dict(packet.get("monthly_cashflow"))
    evidence_rows = [
        _dict(r) for r in _list(_dict(_dict(case.get("results")).get("evidence")).get("rows"))
    ]
    radd(
        "four_exact_sections",
        set(sections) == set(SECTIONS)
        and all(isinstance(_dict(sections.get(key)).get("items"), list) for key in SECTIONS),
    )
    radd(
        "no_credit_decision",
        "decision" in report
        and report["decision"] is None
        and report.get("human_final_decision_required") is True,
    )
    radd(
        "authenticity_unverified",
        report.get("authenticity") == "UNVERIFIED"
        and _dict(checks.get(DIMENSIONS[0])).get("authenticity") == "UNVERIFIED"
        and all(
            _dict(d).get("authenticity", "UNVERIFIED") == "UNVERIFIED"
            for d in _list(_dict(checks.get(DIMENSIONS[0])).get("documents"))
        ),
    )
    radd(
        "six_dimensions_with_provenance",
        all(_dict(checks.get(key)).get("status") and _refs(checks.get(key)) for key in DIMENSIONS),
    )
    radd(
        "all_raw_rows_conserved",
        _inventory(raw, items, expected),
        "independent literal row-ref inventory, document totals and one-to-one partition; not self-reported conservation",
    )
    radd(
        "section_totals_reconcile",
        all(
            _eq(
                _dict(sections.get(key)).get(side + "_total_thb"),
                _sum(
                    [i for i in section_items[key] if i.get("included_in_totals") is True],
                    side + "_thb",
                ),
            )
            for key in SECTIONS
            for side in ("credit", "debit")
        ),
    )
    radd(
        "no_unproven_sales_from_R_or_memo",
        _eq(_dict(sections.get("supported_sales")).get("credit_total_thb"), "0")
        and not any(
            _money(i.get("credit_thb")) not in (None, Decimal(0))
            for i in section_items["supported_sales"]
        )
        and not any(i.get("purpose") == "SALES" for i in items)
        and all(
            row.get("supported_sales_thb") is None or _eq(row.get("supported_sales_thb"), "0")
            for row in rows
        ),
        "No corroboration in these literal probes; R is not sales proof",
    )
    radd(
        "six_month_window",
        monthly.get("window_months") == list(MONTHS)
        and [r.get("month") for r in rows] == list(MONTHS),
    )
    radd(
        "residual_not_invented",
        len(rows) == 6
        and all(
            "residual_thb" in row
            and row["residual_thb"] is None
            and row.get("residual_status") == "UNKNOWN"
            for row in rows
        ),
        "Descriptive bank net is not disposable income",
    )
    if "monthly_bank_net_thb" in expected:
        radd(
            "monthly_bank_net_including_worst_month",
            len(rows) == 6
            and all(
                _eq(row.get("observed_net_thb"), target)
                for row, target in zip(rows, expected["monthly_bank_net_thb"], strict=False)
            ),
            "All six visible bank-net rows must match the literal oracle; worst month cannot be masked by mean",
        )
    required_questions = expected["sections"]["unresolved_items_questions"]
    _question_checks(radd, follow, required_questions, "followup_")
    reviewed_questions = {_normalized(q["question"]) for q in required_questions}
    radd(
        "neutral_question_content_bounded_review",
        all(
            _normalized(i.get("question")) in reviewed_questions | SAFE_REPORT_QUESTIONS
            for i in items
            if i.get("question")
        ),
        f"{HUMAN} for any extra/unreviewed wording; exact reviewed question/template only, no universal semantic proof",
    )

    trace_actions = [
        e
        for e in _list(case.get("trace"))
        if isinstance(e, dict) and e.get("kind") == "agent_action" and e.get("status") == "ACCEPTED"
    ]
    calls = case.get("agent_calls")
    indices = [r.get("attempt") for r in records_list]
    mode = case.get("agent_mode")
    # The frozen controller intentionally reports llm_calls=0 for OpenAI.
    # Its actual native API attempts are accounted for by the runner instead.
    provider_counter_matches = (
        mode == "typhoon"
        and type(case.get("llm_calls")) is int
        and case["llm_calls"] == calls
        and case.get("provider_api_calls", calls) == calls
    ) or (
        mode == "openai"
        and type(case.get("provider_api_calls")) is int
        and case["provider_api_calls"] == calls
        and type(case.get("llm_calls")) is int
        and case["llm_calls"] == 0
    )
    aadd(
        "bounded_native_calls",
        type(calls) is int
        and 1 <= calls <= 8
        and len(records_list) == calls
        and indices == list(range(1, calls + 1))
        and provider_counter_matches,
        f"mode={mode}; agent_calls={calls}; receipts={len(records_list)}; max=8",
    )
    aadd(
        "accepted_actions_have_native_and_execution_receipts",
        bool(trace_actions)
        and len(linked) == len(trace_actions)
        and all(type(e.get("call")) is int for e in trace_actions)
        and len({e.get("call") for e in trace_actions}) == len(trace_actions),
    )
    finishes = [
        a for a, receipt in linked if a["tool"] == "finish_review" and receipt.get("status") == "OK"
    ]
    aadd(
        "accepted_native_finish",
        len(finishes) == 1 and bool(trace_actions) and trace_actions[-1] == finishes[0]
        if finishes
        else False,
    )
    aadd(
        "no_technical_review",
        case.get("state") in {"EXCEPTION_REVIEW", "WAIT_CUSTOMER", "REVIEW_READY"}
        and not any(i.get("code") == "AGENT_TECHNICAL_STOP" for i in issues),
    )
    aadd(
        "no_credit_decision",
        "decision" in case
        and case["decision"] is None
        and "decision" in packet
        and packet["decision"] is None
        and packet.get("human_final_decision_required") is True,
    )
    aadd("authenticity_unverified", packet.get("authenticity_verified") is False)
    _question_checks(aadd, agent_questions, required_questions, "accepted_question_")
    authored_questions = []
    reasons = []
    for action, _ in linked:
        args = action["arguments"]
        if action["tool"] == "flag_transactions":
            authored_questions.append(args.get("question"))
            reasons.append(args.get("reason"))
        elif action["tool"] == "propose_findings":
            authored_questions.extend(_dict(f).get("question") for f in _list(args.get("findings")))
        elif action["tool"] == "finish_review":
            reasons.append(args.get("reason"))
    aadd(
        "neutral_authored_content_bounded_review",
        all(_normalized(q) in reviewed_questions for q in authored_questions)
        and all(_normalized(reason) in SAFE_ACTION_REASONS for reason in reasons),
        f"{HUMAN} for unreviewed question/reason wording; exact reviewed templates only",
    )

    if sid == "S01":
        doccheck = _dict(checks.get(DIMENSIONS[0]))
        radd(
            "owner_mismatch_retained",
            any(
                "DOC-S01-B" in _refs(d)
                and d.get("status") == "NEEDS_REVIEW"
                and d.get("account_name") != "MATCHES_DECLARATION"
                for d in _list(doccheck.get("documents"))
                if isinstance(d, dict)
            ),
        )
        radd("partial_period_retained", "2026-09" in _list(doccheck.get("missing_months")))
        gap = expected["cross_document_continuity"]
        radd(
            "cross_document_gap_165000_retained",
            any(
                _eq(q.get("previous_closing_thb"), gap["previous_closing_thb"])
                and _eq(q.get("next_opening_thb"), gap["next_opening_thb"])
                and _eq(
                    q.get("difference_thb", q.get("unexplained_difference_thb")),
                    gap["unexplained_difference_thb"],
                )
                for q in _questions(follow, ["DOC-S01-A", "DOC-S01-B"])
            ),
        )
    elif sid == "S02":
        nonsales = section_items["non_sales_inflows"]
        radd(
            "nonsales_180000_loan_and_capital",
            _eq(
                _dict(sections.get("non_sales_inflows")).get("credit_total_thb"),
                expected["non_sales_total_thb"],
            )
            and all(
                any(
                    _covers(_refs(i), e["refs"])
                    and i.get("purpose") == e["type"]
                    and _eq(i.get("credit_thb"), e["amount_thb"])
                    for i in nonsales
                )
                for e in expected["sections"]["non_sales_inflows"]
            ),
        )
        radd(
            "candidate_inflows_exclude_nonsales",
            len(rows) == 6
            and all(
                _eq(row.get("eligible_unverified_inflows_thb"), value)
                for row, value in zip(rows, expected["candidate_sales_by_month_thb"], strict=False)
            ),
        )
        may = [
            r
            for r in evidence_rows
            if str(r.get("date", "")).startswith("2026-05") and r.get("category") == "R"
        ]
        candidate = _sum(may, "credit")
        aadd(
            "controller_May_candidate_at_most_200000",
            bool(evidence_rows)
            and candidate is not None
            and 0 <= candidate <= Decimal(expected["candidate_sales_by_month_thb"][1]),
            "Controller R is candidate-only; capital must not remain R",
        )
        aadd(
            "loan_and_capital_not_controller_sales",
            all(
                len([r for r in evidence_rows if r.get("ref") in e["refs"]]) == len(e["refs"])
                and all(
                    r.get("category") != "R" for r in evidence_rows if r.get("ref") in e["refs"]
                )
                for e in expected["sections"]["non_sales_inflows"]
            ),
        )
    elif sid == "S03":
        radd(
            "six_values_include_observed_zero_not_missing",
            len(rows) == 6
            and all(
                row.get("coverage") == "COMPLETE"
                and _eq(row.get("eligible_unverified_inflows_thb"), value)
                for row, value in zip(rows, expected["candidate_sales_by_month_thb"], strict=False)
            )
            and not _list(_dict(checks.get(DIMENSIONS[0])).get("missing_months")),
        )
        stats = _dict(monthly.get("eligible_unverified_inflow_statistics"))
        radd(
            "descriptive_mean_and_decline",
            stats.get("months_observed") == list(MONTHS)
            and _eq(stats.get("average_thb"), expected["candidate_sales_full_six_mean_thb"])
            and _eq(stats.get("first_to_last_change_thb"), "-240000.00")
            and _money(stats.get("trend_slope_thb_per_month")) is not None
            and _money(stats.get("trend_slope_thb_per_month")) < 0
            and stats.get("zero_supported_sales_months") == ["2026-09"],
            "Observed unverified inflows; six-month mean is descriptive, not proven sales",
        )
        cash_rows = [_dict(r) for r in _list(cashflow.get("rows"))]
        inspections = [(a, r) for a, r in linked if a["tool"] == "inspect_cashflow"]
        aadd(
            "accepted_cashflow_matches_packet",
            bool(inspections) and _dict(inspections[-1][1].get("result")) == cashflow,
        )
        aadd(
            "six_month_cashflow_shortage_evidence",
            [r.get("month") for r in cash_rows] == list(MONTHS)
            and all(
                _eq(r.get("residual_before_reserve_thb"), value)
                for r, value in zip(
                    cash_rows, expected["provisional_residual_before_reserve_thb"], strict=False
                )
            )
            and any(
                i.get("code") == "LIQUIDITY_GAP"
                and i.get("status") == "OPEN"
                and _refs(i)
                and i.get("question")
                for i in issues
            ),
            "Includes July/August/September shortages and worst September -170000 before reserve",
        )
    elif sid == "S04":
        pair = expected["pattern"]["refs"]
        pair_items = [
            i for i in items if set(_refs({"refs": i.get("transaction_refs")})) & set(pair)
        ]
        radd(
            "pair_purpose_and_relationship_unverified",
            len(pair_items) == 2
            and all(i.get("purpose") == "UNKNOWN" for i in pair_items)
            and all(i.get("relationship", "UNKNOWN") == "UNKNOWN" for i in pair_items),
            "No loan/internal-transfer/fraud assertion authorized; paired question checked separately",
        )
        pair_issues = [i for i in issues if set(_refs(i)) & set(pair)]
        aadd(
            "no_supported_pair_interpretation_without_evidence",
            bool(pair_issues)
            and all(
                _dict(i.get("proposal")).get("interpretation", "UNKNOWN") == "UNKNOWN"
                and i.get("relationship", "UNKNOWN") == "UNKNOWN"
                for i in pair_issues
            ),
            "Unknown purpose/relationship; no inferred own transfer or loan",
        )
        pair_rows = [r for r in evidence_rows if r.get("ref") in pair]
        aadd(
            "pair_not_controller_sales_or_proven_transfer",
            len(pair_rows) == 2
            and all(r.get("category") in {"UNKNOWN", "UNRESOLVED"} for r in pair_rows),
            "Both paired ledger refs remain unresolved; source questions do not verify sales or an own transfer",
        )
        september = [r for r in _list(cashflow.get("rows")) if _dict(r).get("month") == "2026-09"]
        aadd(
            "no_900000_retained_liquidity",
            all(
                _money(_dict(row).get("residual_before_reserve_thb")) is not None
                and _money(row.get("residual_before_reserve_thb"))
                <= Decimal(expected["monthly_bank_net_thb"][-1])
                for row in september
            ),
            "Conservative ceiling from literal September bank net 65000; no computed policy residual is required",
        )
    elif sid == "S05":
        repayment = expected["sections"]["identifiable_payment_obligations"][0]
        payment_items = [
            i
            for i in section_items["identifiable_obligations"]
            if i.get("purpose") == "DEBT_PAYMENT"
        ]
        radd(
            "observed_repayments_10000_each_month",
            all(
                _eq(
                    _sum(
                        [i for i in payment_items if str(i.get("date", "")).startswith(month)],
                        "debit_thb",
                    ),
                    expected["identifiable_monthly_repayment_thb"],
                )
                for month in MONTHS
            )
            and set(repayment["refs"])
            <= {ref for i in payment_items for ref in _refs({"refs": i.get("transaction_refs")})},
        )
        anonymous = [
            i
            for i in items
            if "ANON-A" in str(i.get("description", ""))
            or "ANON-B" in str(i.get("description", ""))
        ]
        radd(
            "anonymous_expenses_remain_unknown",
            len(anonymous) == 12
            and all(i.get("purpose") == "UNKNOWN" and i in follow for i in anonymous),
            "No forced raw-material/personal/debt guesses",
        )
        debtcheck = _dict(checks.get("outgoing_and_debt"))
        radd(
            "total_debt_remains_unknown",
            debtcheck.get("status") == "UNKNOWN"
            and debtcheck.get("total_monthly_debt_thb") is None,
        )
        inspections = [(a, r) for a, r in linked if a["tool"] == "inspect_cashflow"]
        aadd(
            "unknown_debt_blocks_final_residual",
            _dict(case.get("input")).get("debt_thb") is None
            and cashflow.get("status") == "UNKNOWN"
            and cashflow.get("rows") == []
            and "new_installment_max_thb" in cashflow
            and cashflow["new_installment_max_thb"] is None
            and bool(inspections)
            and _dict(inspections[-1][1].get("result")) == cashflow,
        )
        anonymous_rows = [
            r
            for r in evidence_rows
            if "ANON-A" in str(r.get("description", ""))
            or "ANON-B" in str(r.get("description", ""))
        ]
        anonymous_issues = [
            i for i in issues if any(r.get("ref") in _refs(i) for r in anonymous_rows)
        ]
        aadd(
            "anonymous_agent_expenses_not_guessed",
            len(anonymous_rows) == 12
            and all(r.get("category") in {"UNRESOLVED", "UNKNOWN"} for r in anonymous_rows)
            and all(
                _dict(i.get("proposal")).get("interpretation", "UNKNOWN")
                in {"UNKNOWN", "EXPENSE_UNKNOWN"}
                for i in anonymous_issues
            ),
            "Anonymous repetition does not establish goods/personal/debt purpose",
        )
        aadd(
            "total_agent_debt_unknown",
            packet.get("total_monthly_debt_thb") is None
            and cashflow.get("total_monthly_debt_thb") is None,
        )
    result["status"] = "PASS" if all(c["passed"] for c in report_checks + agent_checks) else "FAIL"
    return result
