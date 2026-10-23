"""Experiment-only trace/context wrapper; no routes, approval, or financial changes.

Records public tool choices, not private model reasoning. Provider adapters still
validate native output and protect secrets. The caller supplies scrubbed context.
"""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal

from .agentic_typhoon import SYSTEM
from .core import SandboxError
from .statements import normal_name, parse_statement

REVIEW_CONTRACT = {
    "version": "STAFF_FOUR_PART_V1",
    "sections": ["supported_sales", "non_sales_inflows", "identifiable_obligations", "follow_up"],
    "raw_material_classification_required": False,
    "evidence_standard": "A sales memo/category or repeated incoming amount is not proof of business sales. Keep unexplained receipts unverified. Arithmetic consistency is not document authenticity.",
    "check_dimensions": [
        "Account holder, declared accounts, required product-specific period, continuous dates/balances and missing records",
        "Inflow origin: sales vs loan, owner capital, asset disposal or internal transfer; compare occupation and declarations",
        "All available months: average/minimum/variation, zero-income months, sustained decline, not best month alone",
        "Known payments and claimed expenses/debt; unknown or invisible debt/cash outflows remain unknown",
        "Residual liquidity in low-income months after known obligations and proposed installment, computed by tools",
        "Large near-submission inflows/rapid exits or inconsistencies require neutral evidence questions, never fraud or automatic rejection",
    ],
    "handoff": "Use available tools to inspect evidence and preserve open questions. A deterministic renderer will make four sections from evidence and your accepted findings. Do not invent a check or claim a tool ran if unavailable. Do not force raw-material/personal labels.",
    "value_format": "One account per business_account claim, use the exact alias seen in message_untrusted. Monetary value is only digits/optional commas/decimal point, no currency words or time period. Quote exact message, not transaction memo.",
}


def _usage_total(record):
    usage = record.get("usage")
    if not isinstance(usage, dict) or type(usage.get("total_tokens")) is not int:
        raise SandboxError("experiment_usage_unknown")
    if usage["total_tokens"] < 0:
        raise SandboxError("experiment_usage_unknown")
    return usage["total_tokens"]


def statement_context(case, documents):
    """Source-derived document facts only; no oracle, identity proof or policy change."""
    accounts, parsed_documents = {}, []
    for doc in documents:
        if doc.get("kind") != "statement":
            continue
        item = {"document_id": doc["id"], "authenticity": "UNVERIFIED"}
        try:
            parsed = parse_statement(doc)
        except (ValueError, KeyError, TypeError):
            item["parse_status"] = "UNREADABLE_OR_INCONSISTENT"
            parsed_documents.append(item)
            continue
        rows = parsed["rows"]
        opening = (
            Decimal(rows[0]["balance"]) + Decimal(rows[0]["debit"]) - Decimal(rows[0]["credit"])
        )
        item.update(
            parse_status="ARITHMETIC_CONSISTENT_ONLY",
            account_alias=accounts.setdefault(parsed["account"], f"ACC-{len(accounts) + 1}"),
            holder_matches_applicant=normal_name(parsed["account_holder"])
            == normal_name(case["input"]["applicant_name"]),
            period_start=parsed["start"].isoformat(),
            period_end=parsed["end"].isoformat(),
            opening_thb=format(opening, ".2f"),
            closing_thb=rows[-1]["balance"],
            row_count=len(rows),
            first_row_ref=rows[0]["ref"],
            last_row_ref=rows[-1]["ref"],
        )
        parsed_documents.append(item)
    continuity = []
    for alias in accounts.values():
        group = sorted(
            (d for d in parsed_documents if d.get("account_alias") == alias),
            key=lambda d: d["period_start"],
        )
        for previous, following in zip(group, group[1:], strict=False):
            difference = Decimal(following["opening_thb"]) - Decimal(previous["closing_thb"])
            continuity.append(
                {
                    "account_alias": alias,
                    "document_refs": [previous["document_id"], following["document_id"]],
                    "row_refs": [previous["last_row_ref"], following["first_row_ref"]],
                    "previous_period_end": previous["period_end"],
                    "next_period_start": following["period_start"],
                    "previous_closing_thb": previous["closing_thb"],
                    "next_opening_thb": following["opening_thb"],
                    "difference_thb": format(difference, ".2f"),
                    "matches": difference == 0,
                }
            )
    return {
        "documents": parsed_documents,
        "continuity_checks": continuity,
        "authenticity": "UNVERIFIED",
    }


class TracedAgent:
    def __init__(
        self, inner, *, max_total_tokens=300000, previous_records=None, evidence_context=None
    ):
        if type(max_total_tokens) is not int or max_total_tokens <= 0:
            raise ValueError("positive token budget required")
        self.inner = inner
        self.mode = inner.mode
        self.max_total_tokens = max_total_tokens
        self.previous_records = previous_records if previous_records is not None else []
        self.contexts, self.choices, self.errors = [], [], []
        self.stopped = False
        self.evidence_context = deepcopy(evidence_context)

    @property
    def call_records(self):
        return self.inner.call_records

    def choose(self, context, tools, timeout_seconds):
        if {"expected", "oracle", "truth", "scenario_id", "evaluation"} & context.keys():
            raise ValueError("evaluation-only fields cannot enter model context")
        current, supplied = deepcopy(context), deepcopy(tools)
        current["review_contract"] = deepcopy(REVIEW_CONTRACT)
        if self.evidence_context is not None:
            current["statement_document_facts"] = deepcopy(self.evidence_context)
        for tool in supplied:
            if tool["function"]["name"] == "compare_declarations":
                fields = tool["function"]["parameters"]["properties"]["claims"]["items"][
                    "properties"
                ]
                fields["value"]["description"] = (
                    "EXACTLY ONE account alias from the quote for business_account. For money: digits, optional commas and decimal point ONLY; no currency or period text. Separate claims for each account."
                )
        try:
            spent = sum(_usage_total(r) for r in [*self.previous_records, *self.call_records])
            # Bound the current snapshot and native receipt/argument overhead by
            # UTF-8 bytes, not a guessed provider tokenizer. Actual usage is separate.
            bytes_now = len(json.dumps([current, supplied, SYSTEM], ensure_ascii=False).encode())
            reserve = 2 * bytes_now + 8192 + 4096
            if spent + reserve > self.max_total_tokens:
                raise SandboxError("experiment_token_budget_reached")
        except SandboxError:
            self.stopped = True
            raise
        attempt = len(self.contexts) + 1
        self.contexts.append(
            {
                "attempt": attempt,
                "context": current,
                "tools": supplied,
                "token_reservation_estimate": reserve,
            }
        )
        try:
            choice = self.inner.choose(current, supplied, timeout_seconds)
        except Exception as exc:
            self.errors.append({"attempt": attempt, "type": type(exc).__name__})
            raise
        self.choices.append({"attempt": attempt, **deepcopy(choice)})
        return choice
