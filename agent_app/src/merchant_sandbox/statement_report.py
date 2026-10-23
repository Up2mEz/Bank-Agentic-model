"""Pure, descriptive staff report. No credit policy, provider, IO or state writes.

``case`` is a case snapshot (also ReviewSession.result()); ``documents`` are the
existing Documents.list() OCR metadata dictionaries. Agent categories, model
findings, confidence, declarations and legacy financial results NEVER authorize
income. Rows are reparsed from documents; even unreadable/quarantined table rows
retain their local provenance in raw_rows and the follow_up partition.

Optional APPLICATION-OWNED trust-boundary contract (not an LLM tool argument)::

    {"schema_version": "statement-corroboration-v1",
     "provided_by": "application", "evidence": [
       {"origin": "external_record", "evidence_id": "receipt-register:123",
        "transaction_refs": ["DOC-X:page-1:table-1:row-2"],
        "amount": "100.00", "supported_purpose": "SALES"}]}

The caller must construct this envelope from its structured evidence registry,
not deserialize model prose into it. This module validates binding, purpose,
direction, exact amount and conflicts; it cannot authenticate an external record
or prove who supplied a Python dictionary. Evidence IDs are audit pointers, not
an authenticity check. No booleans such as model ``verified`` are accepted.
Amounts bind to the COMPLETE sum of referenced rows, with no partial allocation.

Origins: external_record; statement_native_type (SALES only, one row, explicit
native_code=MERCHANT_SETTLEMENT normalized by the application from a native bank
transaction type field, never inferred from QR/memo text); and
bilateral_statement_match (INTERNAL_TRANSFER only: exactly two owned, distinct
accounts, same date, opposite equal amounts and reciprocal account descriptions).
Purposes: SALES, LOAN_PROCEEDS, CAPITAL, ASSET_SALE, INTERNAL_TRANSFER, RENT,
PAYROLL, DEBT_PAYMENT, BUSINESS_EXPENSE, OTHER_PAYMENT. All authenticity remains
UNVERIFIED, including native types and bilateral matches. Synthetic flags remain
visible. Invalid/conflicting records are follow-up questions, never fallback
permission to promote sales.

Output v1: sections has exactly four keys, each with items and separate credit /
debit totals. Only transaction_refs assigns ownership of a raw row; refs also
includes documentary/evidence/issue pointers and may repeat for questions.
Excluded duplicate/invalid/out-of-window rows retain observed amounts but do not
enter totals. Totals are observed row partitions, NOT an income or affordability
formula. Missing coverage yields null monthly values, never an invented zero.
The descriptive window reads policy_snapshot.assessment.history_complete_closed_months
(default six for compatibility); it applies no approval thresholds or policy rules.
"""

from __future__ import annotations

import re
from calendar import monthrange
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from html import escape

from .statements import Tables, get_tables, normal_name, parse_amount, parse_date, parse_statement

ZERO = Decimal(0)
SECTIONS = ("supported_sales", "non_sales_inflows", "identifiable_obligations", "follow_up")
INFLOW_PURPOSES = {"SALES", "LOAN_PROCEEDS", "CAPITAL", "ASSET_SALE", "INTERNAL_TRANSFER"}
PAYMENT_PURPOSES = {"RENT", "PAYROLL", "DEBT_PAYMENT", "BUSINESS_EXPENSE", "OTHER_PAYMENT"}


def _money(value):
    with localcontext() as ctx:
        ctx.prec = 50
        return format(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _amount(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d{1,2})?", value):
        raise ValueError("Amount must be a nonnegative decimal string with at most two decimals")
    result = Decimal(value)
    if not result.is_finite() or result > Decimal("999999999.99"):
        raise ValueError("Amount outside supported range")
    return result


def _question(code, refs, message, **details):
    return {
        "code": code,
        "refs": list(refs),
        "transaction_refs": [],
        "question": message,
        "amount_thb": None,
        "credit_thb": "0.00",
        "debit_thb": "0.00",
        "included_in_totals": False,
        **details,
    }


def _copy_issue(value, monetary=False):
    """Retain source issues while making inherited amounts JSON decimal strings."""
    if isinstance(value, dict):
        return {
            key: _copy_issue(
                item,
                monetary
                or key.endswith("_thb")
                or key in {"amount", "debit", "credit", "balance", "expected", "observed"},
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_copy_issue(item, monetary) for item in value]
    if isinstance(value, Decimal) or (monetary and type(value) in (int, float)):
        decimal = Decimal(str(value))
        return _money(decimal) if decimal.is_finite() else None
    return deepcopy(value)


def _window(case):
    count = (
        case.get("policy_snapshot", {})
        .get("assessment", {})
        .get("history_complete_closed_months", 6)
    )
    if type(count) is not int or not 1 <= count <= 120:
        return [], "UNKNOWN"
    try:
        current = date.fromisoformat(case.get("created_at", "")[:10]).replace(day=1)
    except (ValueError, TypeError):
        return [], "UNKNOWN"
    months = []
    for _ in range(count):
        current = (current - timedelta(days=1)).replace(day=1)
        months.append(current.strftime("%Y-%m"))
    return sorted(months), "case:policy_snapshot:assessment:history_complete_closed_months" if (
        "history_complete_closed_months" in case.get("policy_snapshot", {}).get("assessment", {})
    ) else "DEFAULT_SIX_CLOSED_MONTHS_DESCRIPTIVE_ONLY"


def _raw_rows(doc, ident):
    rows = []
    for page_index, page in enumerate(doc.get("ocr_pages") or [], 1):
        page_no = page.get("page", page_index)
        text = page.get("text", "")
        try:
            tables = get_tables(text)
        except (ValueError, TypeError):
            parser = Tables()
            parser.feed(text if isinstance(text, str) else "")
            tables = parser.tables  # Salvage provenance only; never validates merged cells.
        for table_no, table in enumerate(tables, 1):
            for row_no, cells in enumerate(table[1:], 2):
                row = {
                    "ref": f"{ident}:page-{page_no}:table-{table_no}:row-{row_no}",
                    "document_ref": ident,
                    "raw_cells": deepcopy(cells),
                    "date": None,
                    "description": cells[1] if len(cells) > 1 else "",
                    "debit": None,
                    "credit": None,
                    "balance": None,
                }
                if len(cells) == 5:
                    try:
                        row["date"] = parse_date(cells[0]).isoformat()
                        row.update(
                            zip(
                                ("debit", "credit", "balance"),
                                (_money(parse_amount(x)) for x in cells[2:]),
                                strict=True,
                            )
                        )
                    except (ValueError, TypeError, InvalidOperation):
                        pass
                rows.append(row)
    # Repeated page numbers must not collapse refs or become admissible evidence.
    occurrences = Counter()
    for row in rows:
        occurrences[row["ref"]] += 1
        if occurrences[row["ref"]] > 1:
            row["ref"] += f":occurrence-{occurrences[row['ref']]}"
    return rows


def _document_inventory(case, documents, follow):
    raw, parsed_docs, checks = [], [], []
    ids = Counter(d.get("id") for d in documents)
    occurrences = Counter()
    for index, doc in enumerate(documents, 1):
        ident = str(doc.get("id") or f"document-{index}")
        occurrences[ident] += 1
        local_id = (
            ident
            if occurrences[ident] == 1
            else f"{ident}:document-occurrence-{occurrences[ident]}"
        )
        if doc.get("kind") != "statement":
            checks.append(
                {
                    "refs": [local_id],
                    "kind": doc.get("kind"),
                    "status": "NOT_ASSESSED",
                    "authenticity": "UNVERIFIED",
                }
            )
            continue
        rows = _raw_rows(doc, local_id)
        raw.extend(rows)
        errors = []
        parsed = None
        try:
            parsed = parse_statement(doc)
        except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
            errors.append("Statement table/period/balance could not be reconciled: " + str(exc))
        if doc.get("case_id") not in (None, case.get("id")):
            errors.append("Document belongs to a different case")
        if ids[doc.get("id")] > 1:
            errors.append("Duplicate document identifier; transaction references are ambiguous")
        if parsed:
            declared_name = case.get("input", {}).get("applicant_name")
            if not declared_name or normal_name(parsed["account_holder"]) != normal_name(
                declared_name
            ):
                errors.append(
                    "Account name does not match an available applicant name; ownership needs review"
                )
            if [r["ref"] for r in rows] != [r["ref"] for r in parsed["rows"]]:
                errors.append("Raw row/reference inventory differs from parsed statement")
        check = {
            "refs": [local_id],
            "kind": "statement",
            "status": "NEEDS_REVIEW" if errors else "CHECKED",
            "arithmetic": "CONSISTENT" if parsed else "UNKNOWN",
            "authenticity": "UNVERIFIED",
            "account_name": "MATCHES_DECLARATION" if parsed and not errors else "UNKNOWN",
            "problems": errors,
        }
        checks.append(check)
        if parsed:
            parsed_docs.append({"parsed": parsed, "raw": rows, "check": check, "id": local_id})
        for row in rows:
            row["eligible_document"] = bool(parsed and not errors)
            row["account"] = parsed["account"] if parsed else None
            row["account_holder"] = parsed["account_holder"] if parsed else None
        if errors:
            follow.append(
                _question(
                    "DOCUMENT_REVIEW",
                    [local_id],
                    "กรุณาตรวจเอกสาร ชื่อบัญชี ช่วงเวลา และยอดรายการ พร้อมเอกสารประกอบ",
                    problems=deepcopy(errors),
                )
            )
    # Compare adjacent periods per account; arithmetic checks never establish authenticity.
    accounts = defaultdict(list)
    for doc in parsed_docs:
        # Observed continuity can still be checked when a separate name/case
        # problem already prevents use of the rows. Do not hide a second issue.
        accounts[doc["parsed"]["account"]].append(doc)
    for docs in accounts.values():
        docs.sort(key=lambda d: d["parsed"]["start"])
        for previous, current in zip(docs, docs[1:], strict=False):
            left, right = previous["parsed"], current["parsed"]
            if left["end"] + timedelta(days=1) == right["start"]:
                first = right["rows"][0]
                opening = (
                    Decimal(first["balance"]) - Decimal(first["credit"]) + Decimal(first["debit"])
                )
                if Decimal(left["rows"][-1]["balance"]) != opening:
                    for doc in (previous, current):
                        doc["check"]["status"] = "NEEDS_REVIEW"
                        doc["check"]["problems"].append(
                            "Adjacent statement closing/opening balances disagree"
                        )
                        for row in doc["raw"]:
                            row["eligible_document"] = False
                    follow.append(
                        _question(
                            "CONTINUITY_MISMATCH",
                            [previous["id"], current["id"]],
                            "กรุณาตรวจยอดต่อเนื่องระหว่างเอกสารสองช่วงเวลา",
                            previous_closing_thb=left["rows"][-1]["balance"],
                            next_opening_thb=_money(opening),
                            difference_thb=_money(opening - Decimal(left["rows"][-1]["balance"])),
                        )
                    )
            elif right["start"] <= left["end"]:

                def signature(parsed):
                    return [
                        (r["date"], r["description"], r["debit"], r["credit"], r["balance"])
                        for r in parsed["rows"]
                    ]

                same = (
                    left["start"] == right["start"]
                    and left["end"] == right["end"]
                    and signature(left) == signature(right)
                )
                if not same:
                    for doc in (previous, current):
                        doc["check"]["status"] = "NEEDS_REVIEW"
                        doc["check"]["problems"].append(
                            "Overlapping nonidentical statement periods need reconciliation"
                        )
                        for row in doc["raw"]:
                            row["eligible_document"] = False
                    follow.append(
                        _question(
                            "OVERLAPPING_DOCUMENTS",
                            [previous["id"], current["id"]],
                            "กรุณาเทียบเอกสารช่วงเวลาทับซ้อนก่อนรวมยอดรายการ",
                        )
                    )
    return raw, parsed_docs, checks


def _coverage(parsed_docs, months, *, checked_only=True):
    accounts = defaultdict(list)
    for doc in parsed_docs:
        # Invalid accounts still constrain completeness instead of disappearing.
        accounts[doc["parsed"]["account"]]
        if not checked_only or doc["check"]["status"] == "CHECKED":
            accounts[doc["parsed"]["account"]].append(
                (doc["parsed"]["start"], doc["parsed"]["end"])
            )
    coverage = {}
    for account, spans in accounts.items():
        covered = []
        for month in months:
            year, number = map(int, month.split("-"))
            cursor, end = date(year, number, 1), date(year, number, monthrange(year, number)[1])
            for start, stop in sorted(spans):
                if start <= cursor <= stop:
                    cursor = stop + timedelta(days=1)
            if cursor > end:
                covered.append(month)
        coverage[account] = covered
    return coverage


def _physical_period_missing_dates(parsed_docs, months):
    """Observed parsed date spans only; never authorize money or ownership."""
    accounts = defaultdict(list)
    for doc in parsed_docs:
        parsed = doc["parsed"]
        accounts[parsed["account"]].append((parsed["start"], parsed["end"]))
    missing = {}
    for account, spans in accounts.items():
        dates = []
        for month in months:
            year, number = map(int, month.split("-"))
            for day in range(1, monthrange(year, number)[1] + 1):
                observed_date = date(year, number, day)
                if not any(start <= observed_date <= end for start, end in spans):
                    dates.append(observed_date.isoformat())
        missing[account] = dates
    return missing


def _described_purpose(row):
    # Explicit descriptions only. No generic sales/QR/purpose keyword classifier.
    text = " ".join(row["description"].casefold().split())
    credit = Decimal(row["credit"] or "0") > 0
    labels = (
        {
            "loan proceeds": "LOAN_PROCEEDS",
            "capital injection": "CAPITAL",
            "sale of old equipment": "ASSET_SALE",
            "sales of old equipment": "ASSET_SALE",
            "asset sale proceeds": "ASSET_SALE",
            "own transfer": "INTERNAL_TRANSFER",
        }
        if credit
        else {"rent": "RENT", "payroll": "PAYROLL", "loan repayment": "DEBT_PAYMENT"}
    )
    for label, purpose in labels.items():
        # A structured lender ID is a memo label, not lender verification.
        # Full matching excludes negation, appended purposes and free prose.
        if purpose in {"LOAN_PROCEEDS", "DEBT_PAYMENT"} and re.fullmatch(
            re.escape(label) + r"\s+lender\s+[a-z0-9][a-z0-9._-]*", text
        ):
            return purpose
        if re.fullmatch(re.escape(label) + r"(?:\s+(?:from|to|ref)\s+.+)?", text):
            return purpose
    return "UNKNOWN"


def _corroborate(corroboration, by_ref, follow):
    if corroboration is None:
        return {}, set()
    if (
        not isinstance(corroboration, dict)
        or set(corroboration) != {"schema_version", "provided_by", "evidence"}
        or (
            corroboration.get("schema_version") != "statement-corroboration-v1"
            or corroboration.get("provided_by") != "application"
            or not isinstance(corroboration.get("evidence"), list)
        )
    ):
        follow.append(
            _question(
                "CORROBORATION_REJECTED",
                ["input:corroboration"],
                "กรุณาส่งหลักฐานจากทะเบียนข้อมูลของแอปตามสัญญา structured evidence",
            )
        )
        return {}, set()
    bindings = defaultdict(list)
    used_ids = Counter(
        e.get("evidence_id")
        for e in corroboration["evidence"]
        if isinstance(e, dict) and isinstance(e.get("evidence_id"), str)
    )
    for index, evidence in enumerate(corroboration["evidence"]):
        pointer = f"input:corroboration:evidence:{index}"
        try:
            if not isinstance(evidence, dict):
                raise ValueError("Evidence must be an object")
            required = {"origin", "evidence_id", "transaction_refs", "amount", "supported_purpose"}
            optional = (
                {"native_code"} if evidence.get("origin") == "statement_native_type" else set()
            )
            if not required <= set(evidence) or set(evidence) - required - optional:
                raise ValueError("Unsupported evidence fields")
            ident, refs, purpose = (
                evidence["evidence_id"],
                evidence["transaction_refs"],
                evidence["supported_purpose"],
            )
            if (
                not isinstance(ident, str)
                or not ident.strip()
                or ident in by_ref
                or used_ids[ident] != 1
            ):
                raise ValueError("Evidence ID must be a unique non-transaction audit pointer")
            if (
                not isinstance(refs, list)
                or not refs
                or not all(isinstance(r, str) for r in refs)
                or len(set(refs)) != len(refs)
            ):
                raise ValueError("Transaction refs must be nonempty and unique")
            if any(r not in by_ref or not by_ref[r]["eligible"] for r in refs):
                raise ValueError("References must bind to eligible rows in this snapshot/window")
            selected = [by_ref[r] for r in refs]
            amount = _amount(evidence["amount"])
            if amount <= 0 or purpose not in INFLOW_PURPOSES | PAYMENT_PURPOSES:
                raise ValueError("Unsupported purpose or nonpositive amount")
            origin = evidence["origin"]
            if origin == "bilateral_statement_match":
                if purpose != "INTERNAL_TRANSFER" or len(selected) != 2:
                    raise ValueError("A bilateral own transfer needs exactly two rows")
                left, right = selected
                if (
                    left["account"] == right["account"]
                    or left["date"] != right["date"]
                    or not (
                        Decimal(left["credit"]) == Decimal(right["debit"])
                        and Decimal(left["debit"]) == Decimal(right["credit"])
                        and max(Decimal(left["credit"]), Decimal(left["debit"])) == amount
                    )
                ):
                    raise ValueError("Counterpart account/date/direction/amount mismatch")
                for row, other in ((left, right), (right, left)):
                    if not re.search(
                        r"(?<![\w-])" + re.escape(other["account"]) + r"(?![\w-])",
                        row["description"],
                        re.I,
                    ):
                        raise ValueError("Reciprocal account provenance is missing")
                level = "BILATERAL_VERIFIED"
            else:
                side = "credit" if purpose in INFLOW_PURPOSES else "debit"
                other_side = "debit" if side == "credit" else "credit"
                if (
                    any(Decimal(r[side]) <= 0 or Decimal(r[other_side]) != 0 for r in selected)
                    or sum((Decimal(r[side]) for r in selected), ZERO) != amount
                ):
                    raise ValueError(
                        "Evidence amount/direction does not exactly match referenced rows"
                    )
                if origin == "statement_native_type":
                    if (
                        purpose != "SALES"
                        or len(selected) != 1
                        or evidence.get("native_code") != "MERCHANT_SETTLEMENT"
                    ):
                        raise ValueError(
                            "Only an explicit native merchant-settlement type supports sales"
                        )
                    level = "STATEMENT_SUPPORTED"
                elif origin == "external_record":
                    level = "EXTERNALLY_SUPPORTED"
                else:
                    raise ValueError("Origin is not application-admissible")
            for row in selected:
                bindings[row["ref"]].append(
                    {"purpose": purpose, "support_level": level, "evidence_ref": ident}
                )
        except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
            follow.append(
                _question(
                    "CORROBORATION_REJECTED",
                    [pointer],
                    "กรุณาตรวจที่มา ยอด และรายการอ้างอิงของหลักฐานประกอบ",
                    reason=str(exc),
                )
            )
    accepted, conflicts = {}, set()
    for ref, proofs in bindings.items():
        described = _described_purpose(by_ref[ref])
        if len({p["purpose"] for p in proofs}) != 1 or (
            described != "UNKNOWN" and any(p["purpose"] != described for p in proofs)
        ):
            conflicts.add(ref)
            follow.append(
                _question(
                    "CORROBORATION_CONFLICT",
                    [ref, *[p["evidence_ref"] for p in proofs]],
                    "กรุณาชี้แจงหลักฐานที่ระบุวัตถุประสงค์แตกต่างกัน",
                )
            )
        else:
            accepted[ref] = proofs
    return accepted, conflicts


def _statistics(rows, key):
    observations = [
        (index, Decimal(r[key]), r) for index, r in enumerate(rows) if r[key] is not None
    ]
    refs = sorted({ref for _, _, row in observations for ref in row["refs"]})
    if not observations:
        return {
            "status": "UNKNOWN",
            "refs": refs,
            "months_observed": [],
            "average_thb": None,
            "min_thb": None,
            "max_thb": None,
            "population_stddev_thb": None,
            "coefficient_of_variation": None,
            "first_to_last_change_thb": None,
            "trend_slope_thb_per_month": None,
            "zero_supported_sales_months": [],
        }
    values = [v for _, v, _ in observations]
    with localcontext() as ctx:
        ctx.prec = 50
        mean = sum(values, ZERO) / len(values)
        stddev = (sum(((v - mean) ** 2 for v in values), ZERO) / len(values)).sqrt()
        xmean = sum(Decimal(x) for x, _, _ in observations) / len(values)
        denominator = sum(((Decimal(x) - xmean) ** 2 for x, _, _ in observations), ZERO)
        slope = (
            sum(((Decimal(x) - xmean) * (v - mean) for x, v, _ in observations), ZERO) / denominator
            if denominator
            else None
        )
        return {
            "status": "AVAILABLE",
            "refs": refs,
            "months_observed": [r["month"] for _, _, r in observations],
            "average_thb": _money(mean),
            "min_thb": _money(min(values)),
            "max_thb": _money(max(values)),
            "population_stddev_thb": _money(stddev),
            "coefficient_of_variation": format((stddev / mean).quantize(Decimal("0.000001")), "f")
            if mean
            else None,
            "first_to_last_change_thb": _money(values[-1] - values[0]) if len(values) > 1 else None,
            "trend_slope_thb_per_month": _money(slope) if slope is not None else None,
            "zero_supported_sales_months": [r["month"] for _, v, r in observations if v == 0],
        }


def build_staff_report(case, documents, *, corroboration=None):
    """Return a new JSON-compatible descriptive report; never mutate any input."""
    report = {
        "schema_version": "statement-staff-report-v1",
        "case_id": case.get("id"),
        "case_version": case.get("version"),
        "currency": "THB",
        "human_final_decision_required": True,
        "decision": None,
        "authenticity": "UNVERIFIED",
        "synthetic": bool(
            case.get("is_mock") or any(d.get("is_mock") or d.get("synthetic") for d in documents)
        ),
        "sections": {
            s: {"items": [], "credit_total_thb": "0.00", "debit_total_thb": "0.00"}
            for s in SECTIONS
        },
    }
    follow = report["sections"]["follow_up"]["items"]
    months, window_source = _window(case)
    if not months:
        follow.append(
            _question(
                "WINDOW_UNKNOWN",
                [
                    "case:created_at",
                    "case:policy_snapshot:assessment:history_complete_closed_months",
                ],
                "กรุณาระบุวันอ้างอิงและช่วงเดือนของผลิตภัณฑ์ก่อนสรุปประวัติรายเดือน",
            )
        )
    raw, parsed_docs, docs_checks = _document_inventory(case, documents, follow)
    coverage = _coverage(parsed_docs, months)
    physical_coverage = _coverage(parsed_docs, months, checked_only=False)
    physical_missing = [
        m
        for m in months
        if not physical_coverage or any(m not in covered for covered in physical_coverage.values())
    ]
    physical_missing_dates = _physical_period_missing_dates(parsed_docs, months)
    if any(physical_missing_dates.values()):
        follow.append(
            _question(
                "PHYSICAL_PERIOD_GAP",
                [d["id"] for d in parsed_docs],
                "กรุณาเพิ่มเอกสารให้ครอบคลุมวันที่ "
                + "; ".join(
                    account + ": " + ", ".join(dates)
                    for account, dates in physical_missing_dates.items()
                    if dates
                )
                + "; ช่วงวันที่อ่านได้ยังไม่ยืนยันความถูกต้องหรือความเป็นเจ้าของบัญชี",
                months=physical_missing,
                missing_dates_by_account=deepcopy(physical_missing_dates),
            )
        )
    all_statement_docs_checked = bool(parsed_docs) and all(
        c["status"] == "CHECKED" for c in docs_checks if c["kind"] == "statement"
    )
    complete_months = [
        m
        for m in months
        if coverage
        and all(m in covered for covered in coverage.values())
        and all_statement_docs_checked
    ]
    missing = [m for m in months if m not in complete_months]
    if not any(d.get("kind") == "statement" for d in documents):
        follow.append(
            _question(
                "MISSING_DOCUMENTS",
                ["case:document_ids"],
                "กรุณาแนบ statement ของบัญชีที่เกี่ยวข้องตามช่วงเวลาของผลิตภัณฑ์",
            )
        )
    if missing:
        follow.append(
            _question(
                "MISSING_PERIOD",
                ["case:created_at", *[d["id"] for d in parsed_docs]],
                "กรุณาเพิ่มหรือชี้แจงเอกสารที่ครอบคลุมเดือน " + ", ".join(missing),
                months=missing,
            )
        )
    by_ref, seen = {}, set()
    for row in raw:
        row["exclusion_reason"] = None
        if not row["eligible_document"]:
            row["exclusion_reason"] = "DOCUMENT_REVIEW"
        elif not row["date"] or row["date"][:7] not in months:
            row["exclusion_reason"] = "OUTSIDE_WINDOW"
        else:
            signature = (
                row["account_holder"],
                row["account"],
                row["date"],
                row["description"],
                row["debit"],
                row["credit"],
                row["balance"],
            )
            if signature in seen:
                row["exclusion_reason"] = "DUPLICATE_TRANSACTION"
            seen.add(signature)
        row["eligible"] = row["exclusion_reason"] is None
        by_ref[row["ref"]] = row
    accepted, conflicts = _corroborate(corroboration, by_ref, follow)
    for row in raw:
        proofs = accepted.get(row["ref"], [])
        # Two explicit incompatible claims need clarification, not a guessed
        # whole-row allocation. Do not let corroboration silently choose one.
        memo_clauses = set(re.split(r"\s+-\s+", " ".join(row["description"].casefold().split())))
        description_conflict = {"shop sales", "owner capital contribution"} <= memo_clauses
        if description_conflict:
            follow.append(
                _question(
                    "DESCRIPTION_CONFLICT",
                    [row["ref"]],
                    "กรุณาชี้แจงแหล่งเงิน capital contribution ที่ระบุร่วมกับ shop sales "
                    "พร้อมหลักฐานและการแยกยอด; sales ยังไม่มีข้อยุติจาก memo ที่ขัดกัน",
                    described_purposes=["CAPITAL", "SALES"],
                )
            )
        purpose = proofs[0]["purpose"] if proofs else _described_purpose(row)
        level = (
            proofs[0]["support_level"]
            if proofs
            else "STATEMENT_DESCRIBED"
            if purpose != "UNKNOWN"
            else "UNVERIFIED"
        )
        if not row["eligible"] or row["ref"] in conflicts or description_conflict:
            purpose, level = "UNKNOWN", "UNVERIFIED"
        credit, debit = Decimal(row["credit"] or "0"), Decimal(row["debit"] or "0")
        section = (
            "supported_sales"
            if purpose == "SALES"
            else "non_sales_inflows"
            if purpose in INFLOW_PURPOSES and credit > 0
            else "identifiable_obligations"
            if purpose in PAYMENT_PURPOSES and debit > 0
            else "follow_up"
        )
        item = {
            "code": row["exclusion_reason"] or "TRANSACTION",
            "transaction_refs": [row["ref"]],
            "refs": [row["ref"], *dict.fromkeys(p["evidence_ref"] for p in proofs)],
            "date": row["date"],
            "description": row["description"],
            "purpose": purpose,
            "support_level": level,
            "authenticity": "UNVERIFIED",
            "amount_thb": _money(credit + debit)
            if row["credit"] is not None and row["debit"] is not None
            else None,
            "credit_thb": row["credit"],
            "debit_thb": row["debit"],
            "included_in_totals": row["eligible"],
            "exclusion_reason": row["exclusion_reason"],
        }
        if section == "follow_up":
            item["question"] = (
                "กรุณาตรวจรายการและเอกสารอ้างอิง"
                if row["exclusion_reason"]
                else "กรุณาชี้แจงที่มาหรือวัตถุประสงค์ พร้อมหลักฐานประกอบ; เงินถอนสดยังไม่ระบุประเภทต้นทุน"
            )
        report["sections"][section]["items"].append(item)
    existing = []
    sources = [
        case.get("issues", []),
        case.get("packet", {}).get("issues", []) if isinstance(case.get("packet"), dict) else [],
    ]
    for value in case.get("results", {}).values():
        if isinstance(value, dict):
            sources.append(value.get("issues", []))
    for source in sources:
        for issue in source if isinstance(source, list) else []:
            if issue in existing:
                continue
            existing.append(_copy_issue(issue))
            refs = list(issue.get("refs") or ([issue["ref"]] if issue.get("ref") else []))
            refs += [issue.get("id") or issue.get("document_id") or "case:results:issues"]
            follow.append(
                _question(
                    "EXISTING_ISSUE",
                    list(dict.fromkeys(refs)),
                    "กรุณาตรวจและตอบประเด็นเดิมพร้อมหลักฐานอ้างอิง; ยังไม่สรุปความผิดปกติหรือผลสินเชื่อ",
                    original_status=issue.get("status", "UNKNOWN"),
                )
            )
    report["existing_issues"] = existing
    if case.get("input", {}).get("message"):
        follow.append(
            _question(
                "CUSTOMER_MESSAGE_UNVERIFIED",
                ["input:message"],
                "กรุณาเทียบคำชี้แจง รวมถึงยอดขายเงินสดที่อาจไม่ได้เข้าบัญชี กับหลักฐานประกอบ; ไม่นำคำกล่าวอ้างมาบวกเป็นยอดขาย",
            )
        )
    for field, code in (("debt_thb", "DEBT_UNKNOWN"), ("living_cost_thb", "LIVING_COST_UNKNOWN")):
        if case.get("input", {}).get(field) is None:
            follow.append(
                _question(
                    code,
                    [f"input:{field}"],
                    "กรุณาระบุภาระต่อเดือนและหลักฐานประกอบ; ข้อมูลที่ขาดยังไม่เท่ากับศูนย์",
                )
            )
    assignments = Counter(
        r for s in report["sections"].values() for i in s["items"] for r in i["transaction_refs"]
    )
    report["raw_rows"] = raw
    report["raw_rows_conservation"] = {
        "raw_rows": len(raw),
        "assigned_rows": sum(assignments.values()),
        "unassigned_refs": [r["ref"] for r in raw if not assignments[r["ref"]]],
        "multiply_assigned_refs": [r for r, count in assignments.items() if count > 1],
    }
    for section in report["sections"].values():
        for side in ("credit", "debit"):
            section[f"{side}_total_thb"] = _money(
                sum(
                    (
                        Decimal(i[f"{side}_thb"] or "0")
                        for i in section["items"]
                        if i["included_in_totals"]
                    ),
                    ZERO,
                )
            )
    monthly = []
    transactions = [
        i
        for s in report["sections"].values()
        for i in s["items"]
        if i["transaction_refs"] and i["included_in_totals"]
    ]
    for month in months:
        current = [i for i in transactions if i["date"][:7] == month]
        observed_credits = sum((Decimal(i["credit_thb"]) for i in current), ZERO)
        observed_debits = sum((Decimal(i["debit_thb"]) for i in current), ZERO)
        sales = sum((Decimal(i["credit_thb"]) for i in current if i["purpose"] == "SALES"), ZERO)
        unverified = sum(
            (Decimal(i["credit_thb"]) for i in current if i["purpose"] == "UNKNOWN"), ZERO
        )
        complete = month in complete_months
        monthly.append(
            {
                "month": month,
                "refs": (
                    [i["transaction_refs"][0] for i in current] + [d["id"] for d in parsed_docs]
                )
                or ["case:document_ids"],
                "coverage": "COMPLETE" if complete else "UNKNOWN",
                "supported_sales_thb": _money(sales) if complete else None,
                "observed_supported_sales_thb": _money(sales),
                "eligible_unverified_inflows_thb": _money(unverified) if complete else None,
                "observed_eligible_unverified_inflows_thb": _money(unverified),
                "observed_credits_thb": _money(observed_credits),
                "observed_debits_thb": _money(observed_debits),
                "observed_net_thb": _money(observed_credits - observed_debits),
                "residual_thb": None,
                "residual_status": "UNKNOWN",
            }
        )
    report["monthly_cashflow_summary"] = {
        "window_months": months,
        "window_source_ref": window_source,
        "scope": "OBSERVED_ACCOUNTS_ONLY_NOT_UNDERWRITING_RESIDUAL",
        "rows": monthly,
        "supported_sales_statistics": _statistics(monthly, "supported_sales_thb"),
        "eligible_unverified_inflow_statistics": _statistics(
            monthly, "eligible_unverified_inflows_thb"
        ),
        "policy_cashflow": {
            "status": "NOT_RECALCULATED",
            "refs": ["case:results:monthly_cashflow"],
            "legacy_output_present": bool(case.get("results", {}).get("monthly_cashflow")),
        },
    }
    all_refs = [r["ref"] for r in raw] or ["case:document_ids"]
    usable = any(r["eligible"] for r in raw)
    unknown_inflows = any(
        i["purpose"] == "UNKNOWN" and Decimal(i["credit_thb"] or "0") > 0 for i in transactions
    )
    report["document_checks"] = {
        "document_account_period_continuity": {
            "status": "CHECKED"
            if usable and not missing and all_statement_docs_checked
            else "NEEDS_REVIEW"
            if raw or parsed_docs
            else "UNKNOWN",
            "refs": [d.get("id", "document:unknown") for d in documents] or ["case:document_ids"],
            "documents": docs_checks,
            "account_coverage": coverage,
            "missing_months": missing,
            "physical_period_account_coverage": physical_coverage,
            "physical_period_missing_months": physical_missing,
            "physical_period_missing_dates": physical_missing_dates,
            "authenticity": "UNVERIFIED",
        },
        "inflow_source": {
            "status": "UNKNOWN" if not usable or unknown_inflows else "DESCRIBED_OR_SUPPORTED",
            "refs": all_refs,
        },
        "variability_and_trend": {
            "status": "AVAILABLE" if complete_months else "UNKNOWN",
            "refs": all_refs,
        },
        "outgoing_and_debt": {
            "status": "UNKNOWN",
            "refs": [*all_refs, "input:debt_thb"],
            "reason": "Statement payments are not a complete debt/expense inventory; declarations are not independent verification",
        },
        "residual_and_liquidity": {
            "status": "UNKNOWN",
            "refs": all_refs,
            "reason": "Observed bank net is not disposable income; no policy/financial formula is recomputed",
        },
        "patterns_and_questions": {
            "status": "QUESTIONS_FOR_HUMAN" if usable else "UNKNOWN",
            "refs": all_refs,
            "reason": "No fraud label, automatic rejection, or invented pattern threshold",
        },
    }
    report["limitations"] = [
        "Arithmetic consistency and matching account names do not establish authenticity or ownership; authenticity UNVERIFIED.",
        "Supported sales means linked evidence support, not proof of all business income; zero supported sales is not proof of zero actual income.",
        "Eligible but unverified inflows are observed credits with unresolved purpose, not presumed sales.",
        "Payments and withdrawals do not establish raw-material costs or a complete debt inventory.",
        "Observed bank net excludes unobserved accounts/cash and is not a policy residual, affordability calculation, or credit decision.",
        "External evidence origin is an application trust boundary, not cryptographic verification; synthetic/unverified evidence remains visible.",
    ]
    return report


def _md(value):
    return (
        escape(str(value), quote=False)
        .replace("|", "\\|")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("`", "\\`")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def render_staff_report(report):
    """Render four Thai sections with provenance, checks and descriptive liquidity."""
    labels = (
        "รายรับจากการขายที่มีหลักฐานรองรับ",
        "เงินเข้าที่ไม่ใช่ยอดขาย",
        "ภาระจ่ายที่ระบุได้",
        "ประเด็นค้างและคำถาม",
    )
    lines = [
        "# รายงานตรวจ statement สำหรับเจ้าหน้าที่",
        "",
        "ต้องให้เจ้าหน้าที่ตัดสินใจขั้นสุดท้าย — ยังไม่มีคำตัดสินสินเชื่อ",
        "",
        f"Case: {_md(report.get('case_id'))} · Authenticity: UNVERIFIED · Synthetic: {_md(report.get('synthetic'))}",
        "",
    ]
    for key, label in zip(SECTIONS, labels, strict=True):
        section = report["sections"][key]
        lines.extend(
            [
                f"## {label}",
                "",
                f"ยอดรับที่รวม: {section['credit_total_thb']} THB · ยอดจ่ายที่รวม: {section['debit_total_thb']} THB",
                "",
            ]
        )
        for item in section["items"]:
            text = item.get("description") or item.get("question") or item["code"]
            lines.append(
                f"- {_md(text)} · {_md(item.get('purpose', item['code']))} · {_md(item.get('amount_thb') or 'UNKNOWN')} THB · {_md(item.get('support_level', 'UNVERIFIED'))} · refs: {_md(', '.join(item['refs']))}"
            )
            if item.get("exclusion_reason"):
                lines.append(f"  ไม่รวมยอด: {_md(item['exclusion_reason'])}")
            if item.get("description") and item.get("question"):
                lines.append(f"  {_md(item['question'])}")
        if not section["items"]:
            lines.append("ยังไม่มีรายการที่มีหลักฐานรองรับในส่วนนี้")
        lines.append("")
    lines.extend(["**การตรวจหกมิติ**", ""])
    for name, check in report["document_checks"].items():
        lines.append(
            f"- {_md(name)}: {_md(check['status'])} · refs: {_md(', '.join(check['refs']))}"
        )
    lines.extend(["", "**กระแสเงินรายเดือน (ยอดสุทธิในบัญชี ยังไม่ใช่เงินเหลือใช้)**", ""])
    for row in report["monthly_cashflow_summary"]["rows"]:
        lines.append(
            f"- {row['month']}: supported sales {_md(row['supported_sales_thb'] or 'UNKNOWN')}; unverified inflows {_md(row['eligible_unverified_inflows_thb'] or 'UNKNOWN')}; observed net {row['observed_net_thb']} THB; residual UNKNOWN; refs: {_md(', '.join(row['refs']))}"
        )
    for name in ("supported_sales_statistics", "eligible_unverified_inflow_statistics"):
        stats = report["monthly_cashflow_summary"][name]
        lines.extend(
            [
                "",
                f"**{_md(name)}**",
                "",
                f"Average {_md(stats['average_thb'])}; min {_md(stats['min_thb'])}; max {_md(stats['max_thb'])}; population stddev {_md(stats['population_stddev_thb'])}; CV {_md(stats['coefficient_of_variation'])}; trend slope {_md(stats['trend_slope_thb_per_month'])} THB/month; zero supported/observed months {_md(', '.join(stats['zero_supported_sales_months']))}; refs: {_md(', '.join(stats['refs']))}",
            ]
        )
    lines.extend(["", "**ข้อจำกัด**", "", *["- " + _md(x) for x in report["limitations"]]])
    return "\n".join(lines) + "\n"
