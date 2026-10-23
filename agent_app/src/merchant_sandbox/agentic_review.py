"""Local evidence-review experiment. No HTTP route, approval, or ledger writes.

Reuses the lending parser, Decimal calculator and versioned demo policy. Model
findings are proposals; only bilateral evidence checks can resolve own transfers.
The caller supplies an immutable, authorized case/document snapshot. This module
is deliberately not registered with the production reviewer endpoint.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal as D

from .core import FINAL, SandboxError, assessment, digest, financial, money, now
from .statements import normal_name, parse_statement, verify_statements


def scrubber(case, accounts=None):
    data = case["input"]
    private = [
        str(data.get(k, ""))
        for k in ("applicant_name", "email", "phone", "shop_name", "business_location")
    ]

    def scrub(value):
        if isinstance(value, str):
            for token in sorted((x for x in private if len(x) >= 4), key=len, reverse=True):
                value = value.replace(token, "[redacted]")
            for raw, alias in sorted(
                (accounts or {}).items(), key=lambda item: len(item[0]), reverse=True
            ):
                value = re.sub(r"(?<![\w-])" + re.escape(raw) + r"(?![\w-])", alias, value)
            value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted-email]", value)
            return re.sub(r"(?<!\d)\d{10,16}(?!\d)", "[redacted-identifier]", value)
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, dict):
            return {
                k: scrub(v)
                for k, v in value.items()
                if k not in {"account_holders", "extracted_names", "owner_id", "customer_id"}
            }
        return value

    return scrub


def full_context(case):
    """Context-only ablation: retain evidence; do not change legacy tools/rules."""
    observations = deepcopy(case.get("results", {}))
    if "onboarding_read" in observations:
        read = observations["onboarding_read"]
        bank = read.get("snapshot") or {}
        observations["onboarding_read"] = {
            "status": read.get("status"),
            "version": bank.get("version"),
            "kyc": bank.get("kyc", {}).get("status"),
            "kyb": bank.get("kyb", {}).get("status"),
            "wallet": bank.get("wallet", {}).get("status"),
            "is_mock": bank.get("is_mock"),
        }
    data = case["input"]
    return scrubber(case)(
        {
            "case_version": case["version"],
            "message_untrusted": data["message"],
            "consent": data["consent"],
            "declared_debt_thb": data["debt_thb"],
            "declared_living_cost_thb": data["living_cost_thb"],
            "requested_thb": data["requested_thb"],
            "business_profile_untrusted": {
                "business_type": data.get("business_type"),
                "loan_purpose": data.get("purpose"),
            },
            "observations": observations,
            "previous_actions": [
                e["tool"] for e in case.get("trace", []) if e.get("kind") == "tool"
            ],
        }
    )


def object_schema(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


TEXT = {"type": "string", "minLength": 1, "maxLength": 1000}
REFS = {"type": "array", "items": {**TEXT, "maxLength": 180}, "minItems": 1, "maxItems": 128}
CLAIM = object_schema(
    {
        "kind": {
            "type": "string",
            "enum": [
                "monthly_revenue",
                "monthly_business_cost",
                "unbanked_cash_sales",
                "business_account",
            ],
        },
        "value": {**TEXT, "maxLength": 80},
        "quote": {
            **TEXT,
            "description": "Exact substring of message_untrusted (input:message) ONLY. Never quote a statement memo, source_group, observation, or computed total as a customer declaration.",
        },
    }
)
FINDING = object_schema(
    {
        "issue_id": {**TEXT, "maxLength": 80},
        "interpretation": {
            "type": "string",
            "enum": [
                "ASSET_SALE",
                "LOAN_PROCEEDS",
                "CAPITAL",
                "BUSINESS_SALES",
                "EXPENSE_UNKNOWN",
                "UNKNOWN",
            ],
        },
        "quotes": {
            "type": "array",
            "items": object_schema({"ref": {**TEXT, "maxLength": 180}, "quote": TEXT}),
            "minItems": 1,
            "maxItems": 4,
        },
        "question": {"type": "string", "minLength": 8, "maxLength": 600},
        "requested_evidence": {"type": "array", "items": TEXT, "minItems": 1, "maxItems": 4},
    }
)
TOOL_SPECS = {
    "read_transactions": (
        "Read full transaction descriptions, amounts, accounts and provenance for selected case-local refs. Read before proposing an interpretation.",
        object_schema({"refs": REFS}),
    ),
    "flag_transactions": (
        "Raise a new evidence question about transactions already read, including normal source_groups. Keeps an open blocking issue for a human and quarantines any sales involved; never verifies income or resolves the question.",
        object_schema(
            {
                "refs": REFS,
                "question": {**TEXT, "minLength": 8, "maxLength": 600},
                "reason": {**TEXT, "maxLength": 600},
            }
        ),
    ),
    "match_transfers": (
        "Check bilateral own-account transfers. Supply all refs of a TRANSFER_PROVENANCE issue; the tool reads counterpart rows itself. Equal amounts alone do not prove an own transfer.",
        object_schema({"refs": REFS}),
    ),
    "compare_declarations": (
        "Extract explicit financial/account claims ONLY from message_untrusted (source input:message). A request to review documents is NOT a financial declaration: use claims=[] if that message states no amounts/accounts. NEVER invent a customer claim from statement memos or totals. Include exact quotes with local role and period. Code compares with statements and keeps omitted/uncertain spans blocking. Claims never increase income. Call once even if empty.",
        object_schema(
            {
                "claims": {
                    "type": "array",
                    "items": CLAIM,
                    "maxItems": 12,
                    "description": "Only claims actually stated in message_untrusted. Use [] when none; transaction descriptions and computed amounts are not customer claims.",
                }
            }
        ),
    ),
    "inspect_cashflow": (
        "Calculate monthly residuals with code, after transfer/classification work. Checks reserve and the existing calculator's capacity-limited new installment when evidence permits. Creates liquidity questions for shortfall months. Does not decide credit.",
        object_schema({}),
    ),
    "propose_findings": (
        "Propose transaction meanings and a neutral Thai follow-up question with exact observed quotes. Cannot resolve an issue or promote UNKNOWN to verified business income. Batch independent findings.",
        object_schema(
            {"findings": {"type": "array", "items": FINDING, "minItems": 1, "maxItems": 12}}
        ),
    ),
    "finish_review": (
        "Finish when declarations and current cashflow have been inspected, and source issues are investigated. Open issues remain for a human; never approve. No need to resolve questions without new evidence.",
        object_schema({"reason": {**TEXT, "maxLength": 600}}),
    ),
}


def validate(value, schema, path="arguments"):
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict) or set(value) != set(schema["required"]):
            raise SandboxError(f"{path}: required fields are {schema['required']}")
        for key, child in schema["properties"].items():
            validate(value[key], child, f"{path}.{key}")
    elif kind == "array":
        if not isinstance(value, list) or not schema.get("minItems", 0) <= len(value) <= schema.get(
            "maxItems", 128
        ):
            raise SandboxError(f"{path}: invalid array size")
        for item in value:
            validate(item, schema["items"], path)
    elif kind == "string":
        if not isinstance(value, str) or not schema.get("minLength", 0) <= len(value) <= schema.get(
            "maxLength", 1000
        ):
            raise SandboxError(f"{path}: invalid text")
        if "enum" in schema and value not in schema["enum"]:
            raise SandboxError(f"{path}: unsupported enum")


class ReviewSession:
    def __init__(self, case, documents):
        if not case["input"].get("consent") or case["state"] in FINAL or case.get("active"):
            raise SandboxError("ต้องมี consent และ snapshot ที่ยังไม่ final/active")
        if not documents or any(d.get("case_id") != case["id"] for d in documents):
            raise SandboxError("เอกสารไม่อยู่ในขอบเขตเจ้าของเคสนี้")
        self.case = deepcopy(case)
        self.case.update(
            trace=[], active=False, decision=None, packet=None, mode="local_agentic_experiment"
        )
        self.case["results"] = {
            k: deepcopy(v)
            for k, v in case.get("results", {}).items()
            if k in {"onboarding_read", "identity_verify", "intake_check"}
        }
        self.evidence = verify_statements(documents, case)
        self.rows = deepcopy(self.evidence["rows"])
        self.accounts, metadata = {}, {}
        for doc in documents:
            if doc["kind"] != "statement":
                continue
            try:
                parsed = parse_statement(doc)
            except (ValueError, TypeError, KeyError):
                continue  # verify_statements retains the integrity problem.
            alias = self.accounts.setdefault(parsed["account"], f"ACC-{len(self.accounts) + 1}")
            for row in parsed["rows"]:
                metadata[row["ref"]] = {
                    "account": alias,
                    "owner_name_matches": normal_name(parsed["account_holder"])
                    == normal_name(case["input"]["applicant_name"]),
                }
        self.scrub = scrubber(case, self.accounts)
        for row in self.rows:
            row.update(metadata[row["ref"]])
            row["description"] = self.scrub(row["description"])
            row["original_category"] = row["category"]
        if len(self.rows) > 500:
            raise SandboxError("local spike รองรับไม่เกิน 500 แถว; ต้องแบ่งงานอย่างชัดเจน")
        self.by_ref = {r["ref"]: r for r in self.rows}
        self.message = self.scrub(case["input"]["message"])
        self.issues, self.observations, self.receipts = [], [], {}
        self.seen_refs, self.investigated = set(), set()
        self.declarations_checked, self.finished = False, False
        self.declaration_coverage = None
        self.ledger_revision, self.cashflow_revision = 0, None
        self.cashflow = None
        self._prepare_issues()
        self._refresh()
        self.case["trace"].append(
            {
                "kind": "tool",
                "tool": "evidence_verify",
                "actor": "deterministic",
                "status": self.evidence["status"],
                "execution_mode": "REPLAYED_OCR_NOT_NEW_PROVIDER_CALL",
            }
        )

    def _issue(self, code, refs, question, *, blocking=True, expected=None, observed=None):
        refs = sorted(set(refs))
        ident = "ISS-" + digest([code, refs, expected, observed])[:12]
        existing = next((i for i in self.issues if i["id"] == ident), None)
        if existing:
            return existing
        issue = {
            "id": ident,
            "code": code,
            "status": "OPEN",
            "refs": refs,
            "ref": refs[0] if refs else None,
            "reason": code,
            "question": question,
            "blocking_calculation": blocking,
            "expected": expected,
            "observed": observed,
            "confidence": "UNVERIFIED",
            "case_version": self.case["version"],
        }
        self.issues.append(issue)
        return issue

    def _prepare_issues(self):
        for issue in self.evidence["issues"]:
            if not issue.get("ref"):
                self._issue(
                    "DOCUMENT_INTEGRITY",
                    [issue["document_id"]] if issue.get("document_id") else [],
                    "กรุณาตรวจเอกสารและยอด: " + issue["reason"],
                )
        missing = self.evidence["missing_months"]
        if missing:
            self._issue(
                "MISSING_PERIOD",
                [],
                "กรุณาเพิ่ม statement เดือน " + ", ".join(missing),
                expected=missing,
            )
        for field, code, question in [
            ("debt_thb", "DEBT_UNKNOWN", "กรุณาระบุภาระผ่อนหนี้ทั้งหมดต่อเดือน หากไม่มีให้ยืนยัน 0"),
            ("living_cost_thb", "LIVING_UNKNOWN", "กรุณาระบุค่าครองชีพจำเป็นต่อเดือนที่ไม่รวมซ้ำกับต้นทุนร้าน"),
        ]:
            if self.case["input"][field] is None:
                self._issue(code, [], question)
        parsed_months = defaultdict(set)
        for row in self.rows:
            if row["original_category"] == "R":
                parsed_months[row["description"].casefold()].add(row["date"][:7])
        groups = defaultdict(list)
        aliases = set(self.accounts.values())
        for row in self.rows:
            kind, memo = row["category"], row["description"]
            transfer = (
                kind == "OWN_TRANSFER"
                or (kind == "R" and bool(re.search(r"\btransfer(?:red)?\b|โอน", memo, re.I)))
                or any(
                    a != row["account"]
                    and re.search(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])", memo)
                    for a in aliases
                )
            )
            row["transfer_candidate"] = bool(transfer)
            if transfer:
                groups[("TRANSFER_PROVENANCE", "")].append(row["ref"])
                row["category"] = "UNRESOLVED"
            elif kind == "R" and len(parsed_months[memo.casefold()]) == 1:
                groups[("INCOME_SOURCE", memo)].append(row["ref"])
                row["category"] = "UNRESOLVED"
            elif kind == "UNRESOLVED":
                groups[
                    (
                        "UNCLASSIFIED_INFLOW" if D(row["credit"]) > 0 else "UNCLASSIFIED_OUTFLOW",
                        memo,
                    )
                ].append(row["ref"])
        for (code, _), refs in groups.items():
            row = self.by_ref[refs[0]]
            question = (
                "กรุณายืนยันบัญชีต้นทางและปลายทาง พร้อมหลักฐานคู่โอน"
                if code == "TRANSFER_PROVENANCE"
                else f"รายการ {row['date']} จำนวน {row['credit'] if D(row['credit']) else row['debit']} บาท มีที่มาหรือประเภทค่าใช้จ่ายใด กรุณาแนบหลักฐาน"
            )
            self._issue(code, refs, question)
        bank = self.case["results"].get("onboarding_read", {})
        snapshot = bank.get("snapshot") or {}
        if bank.get("status") != "OK" or not (
            snapshot.get("kyc", {}).get("status") == "APPROVED"
            and snapshot.get("kyb", {}).get("status") == "VERIFIED"
            and snapshot.get("wallet", {}).get("status") == "ACTIVE"
            and snapshot.get("phone", {}).get("verified") is True
        ):
            self._issue(
                "ONBOARDING_NOT_READY", [], "เจ้าหน้าที่ต้องตรวจสถานะ KYC / KYB / wallet ล่าสุดก่อนพิจารณา"
            )
        if self.case["results"].get("identity_verify", {}).get("status") == "CONFLICT":
            self._issue("IDENTITY_CONFLICT", [], "เจ้าหน้าที่ตรวจความสัมพันธ์ของชื่อผู้สมัครกับเอกสาร")

    def _refresh(self):
        months = {
            m: {"month": m, "R": D(0), "O": D(0), "V": D(0), "F": D(0), "refs": []}
            for m in self.evidence["expected_months"]
        }
        excluded = [
            deepcopy(x)
            for x in self.evidence["excluded"]
            if x["reason"]
            in {"DUPLICATE_TRANSACTION", "OUTSIDE_WINDOW", "DEBT_PAID_COUNTED_IN_DECLARED_D"}
        ]
        for row in self.rows:
            m, cat = row["date"][:7], row["category"]
            if m not in months:
                continue
            if cat in {"R", "O", "V", "F"}:
                months[m][cat] += D(row["credit"] if cat in {"R", "O"} else row["debit"])
                months[m]["refs"].append(row["ref"])
            elif cat in {"OWN_TRANSFER", "LOAN_PROCEEDS"}:
                excluded.append({"ref": row["ref"], "reason": cat})
            elif cat in {"ASSET_SALE", "CAPITAL"}:
                excluded.append(
                    {"ref": row["ref"], "reason": "NON_RECURRING_PENDING_HUMAN", "proposal": cat}
                )
        self.evidence.update(
            rows=self.rows,
            excluded=excluded,
            issues=self.issues,
            months=[
                {k: money(v) if isinstance(v, D) else v for k, v in x.items()}
                for x in months.values()
            ],
            status="NEEDS_REVIEW" if any(i["status"] == "OPEN" for i in self.issues) else "OK",
            evidence_refs=[r["ref"] for r in self.rows],
            account_aliases=sorted(self.accounts.values()),
        )
        if any(i["status"] == "OPEN" and i["code"] == "MISSING_ACCOUNT" for i in self.issues):
            self.evidence["coverage"] = "PARTIAL"

    def context(self):
        data = self.case["input"]
        return self.scrub(
            {
                "case_version": self.case["version"],
                "review_scope": digest(
                    [self.case["id"], self.case["version"], self.evidence["source_sha256"]]
                ),
                "message_untrusted": self.message,
                "evidence_source_boundaries": {
                    "customer_declarations": "input:message = message_untrusted only; no inference from bank transactions",
                    "statement_records": "source_groups / months / read_transactions; memos are not customer declarations or proof of income",
                    "computed_results": "inspect_cashflow / comparison outputs; never quote as customer declarations",
                    "redacted_identifiers": "ACC aliases and omitted names are privacy substitutions, not evidence of a contradiction",
                },
                "declared_debt_thb": data["debt_thb"],
                "declared_living_cost_thb": data["living_cost_thb"],
                "requested_thb": data["requested_thb"],
                "business_profile_untrusted": {
                    "business_type": data.get("business_type"),
                    "loan_purpose": data.get("purpose"),
                },
                "loan_assumptions": {
                    "policy_version": self.case["policy_snapshot"]["policy_version"],
                    "status": self.case["policy_snapshot"]["status"],
                    "affordability": self.case["policy_snapshot"]["affordability"],
                    "limit_fixture": self.case["policy_snapshot"]["limit_fixture"],
                    "installment_basis": "EXISTING_CALCULATOR_CAPACITY_LIMITED_OFFER_NOT_APPROVAL",
                },
                "accounts_present": sorted(self.accounts.values()),
                "expected_months": self.evidence["expected_months"],
                "months": self.evidence["months"],
                "issues": self.issues,
                "source_groups": self._source_groups(),
                "progress": {
                    "read_refs": sorted(self.seen_refs),
                    "ledger_revision": self.ledger_revision,
                    "cashflow_revision": self.cashflow_revision,
                    "executed_tools": [
                        e["tool"] for e in self.case["trace"] if e.get("kind") == "tool"
                    ],
                    "available_tools": [t["function"]["name"] for t in self.tools()],
                    "completed_work_is_not_a_request_to_repeat": True,
                    "phase": "HANDOFF" if not self.unfinished() else "EVIDENCE_REVIEW",
                    "cashflow_seals_review": "Investigate source groups and claims before inspect_cashflow. Once all required work and current cashflow are complete, hand off with open questions.",
                },
                "declarations_checked": self.declarations_checked,
                "declaration_coverage": self.declaration_coverage,
                "cashflow_current": self.cashflow_revision == self.ledger_revision,
                "investigated_issue_ids": sorted(self.investigated),
                "observations": self.observations,
                "required_before_finish": self.unfinished(),
                "human_final_decision_required": True,
            }
        )

    def _source_groups(self):
        groups = {}
        for row in self.rows:
            direction = "CREDIT" if D(row["credit"]) > 0 else "DEBIT"
            key = (row["account"], row["description"], row["category"], direction)
            group = groups.setdefault(
                key,
                {
                    "account": row["account"],
                    "description": row["description"],
                    "category": row["category"],
                    "direction": direction,
                    "count": 0,
                    "months": set(),
                    "debit_total_thb": D(0),
                    "credit_total_thb": D(0),
                    "refs": [],
                },
            )
            group["count"] += 1
            group["months"].add(row["date"][:7])
            group["debit_total_thb"] += D(row["debit"])
            group["credit_total_thb"] += D(row["credit"])
            group["refs"].append(row["ref"])
        return [
            {
                **g,
                "months": sorted(g["months"]),
                "unread_refs": [ref for ref in g["refs"] if ref not in self.seen_refs],
                "debit_total_thb": money(g["debit_total_thb"]),
                "credit_total_thb": money(g["credit_total_thb"]),
            }
            for g in groups.values()
        ]

    def unfinished(self):
        required = []
        # An audited gap is human follow-up, not an invitation to guess more claims.
        if self.declaration_coverage is None:
            required.append("compare_declarations")
        if self.cashflow_revision != self.ledger_revision:
            required.append("inspect_cashflow after any transaction reclassification")
        required += [
            i["id"]
            for i in self.issues
            if i["status"] == "OPEN"
            and i["code"]
            in {
                "TRANSFER_PROVENANCE",
                "INCOME_SOURCE",
                "UNCLASSIFIED_INFLOW",
                "UNCLASSIFIED_OUTFLOW",
            }
            and i["id"] not in self.investigated
        ]
        return required

    def tools(self):
        if self.finished:
            return []
        pending = [
            i for i in self.issues if i["status"] == "OPEN" and i["id"] not in self.investigated
        ]
        unread = sorted(set(self.by_ref) - self.seen_refs)
        flagged = {ref for i in self.issues if i["code"] == "AGENT_RAISED" for ref in i["refs"]}
        flaggable = sorted(self.seen_refs - flagged)
        outstanding = self.unfinished()
        ready_for_cashflow = not [
            task for task in outstanding if not task.startswith("inspect_cashflow")
        ]
        enabled = {
            "read_transactions": bool(unread),
            "match_transfers": any(i["code"] == "TRANSFER_PROVENANCE" for i in pending),
            "compare_declarations": self.declaration_coverage is None,
            "inspect_cashflow": self.cashflow_revision != self.ledger_revision
            and ready_for_cashflow,
            "propose_findings": any(
                i["code"] in {"INCOME_SOURCE", "UNCLASSIFIED_INFLOW", "UNCLASSIFIED_OUTFLOW"}
                and self.seen_refs.intersection(i["refs"])
                for i in pending
            ),
            "flag_transactions": bool(flaggable),
            "finish_review": not outstanding,
        }
        # Commit the investigated snapshot to handoff. Unresolved evidence is
        # retained; this does not close questions or imply a credit decision.
        # Another evidence version starts another review instead of an open loop.
        if not outstanding:
            enabled = {name: name == "finish_review" for name in enabled}
        tools = []
        for name, (desc, original) in TOOL_SPECS.items():
            if not enabled[name]:
                continue
            schema = deepcopy(original)
            if name in {"read_transactions", "flag_transactions"}:
                schema["properties"]["refs"]["items"]["enum"] = (
                    unread if name == "read_transactions" else flaggable
                )
            tools.append(
                {
                    "type": "function",
                    "function": {"name": name, "description": desc, "parameters": schema},
                }
            )
        return tools

    def _refs(self, refs):
        if len(set(refs)) != len(refs) or any(r not in self.by_ref for r in refs):
            raise SandboxError(
                "refs must be unique existing transaction refs in this case snapshot"
            )
        return [self.by_ref[r] for r in refs]

    def execute(self, tool, arguments):
        if tool not in TOOL_SPECS:
            raise SandboxError("tool is outside the read/review allowlist")
        validate(arguments, TOOL_SPECS[tool][1])
        key = digest(
            [
                self.case["version"],
                tool,
                arguments,
                self.ledger_revision if tool in {"read_transactions", "inspect_cashflow"} else None,
            ]
        )
        if key in self.receipts:
            result = {**deepcopy(self.receipts[key]), "replayed": True, "new_evidence": False}
            self.observations.append({"tool": tool, "result": deepcopy(result)})
            return result
        if self.finished:
            raise SandboxError("review is already finished")
        # Batch proposals/claims are atomic: a later invalid item undoes earlier items.
        backup = deepcopy(self.__dict__)
        try:
            result = getattr(self, "_" + tool)(**arguments)
            self._refresh()
        except (SandboxError, ValueError, TypeError, KeyError) as exc:
            self.__dict__.clear()
            self.__dict__.update(backup)
            if isinstance(exc, SandboxError):
                raise
            raise SandboxError("invalid evidence/tool input") from None
        self.receipts[key] = deepcopy(result)
        event = {
            "kind": "tool",
            "tool": tool,
            "actor": "evidence_tool",
            "arguments": deepcopy(arguments),
            "status": result["status"],
            "result": deepcopy(result),
            "at": now(),
            "case_version": self.case["version"],
        }
        self.case["trace"].append(event)
        self.observations.append({"tool": tool, "result": deepcopy(result)})
        return result

    def _read_transactions(self, refs):
        rows = self._refs(refs)
        self.seen_refs.update(refs)
        return {"status": "OK", "rows": deepcopy(rows), "authenticity_verified": False}

    @staticmethod
    def _neutral(text):
        if re.search(
            r"โกหก|ฉ้อโกง|ทุจริต|ฟอกเงิน|อนุมัติ(?:แล้ว|ให้|สินเชื่อ|วงเงิน)|\b(?:fraud(?:ulent)?|liar|lying|money laundering|approv(?:e[sd]?|al))\b",
            text,
            re.I,
        ):
            raise SandboxError("use neutral evidence questions, not accusations or an approval")

    def _flag_transactions(self, refs, question, reason):
        rows = self._refs(refs)
        if not set(refs) <= self.seen_refs:
            raise SandboxError("read case-local transactions before flagging them")
        self._neutral(question)
        self._neutral(reason)
        issue = self._issue("AGENT_RAISED", refs, self.scrub(question))
        if issue["id"] not in self.investigated:
            issue.update(
                reason=self.scrub(reason),
                origin="AGENT_EVIDENCE_QUESTION",
                income_status="UNVERIFIED_PENDING_HUMAN",
            )
            for row in rows:
                if row["category"] == "R":
                    row["category"] = "UNRESOLVED"
            self.investigated.add(issue["id"])
            # A new question invalidates prior inspection even if no R was changed.
            self.ledger_revision += 1
        return {
            "status": "OK",
            "issue": deepcopy(issue),
            "ledger_revision": self.ledger_revision,
            "verified_income_promotions": 0,
        }

    @staticmethod
    def _mentions(memo, direction, alias):
        words = r"(?:to|ไป|ไปยัง)" if direction == "to" else r"(?:from|จาก)"
        return bool(re.search(words + r"\s+" + re.escape(alias) + r"(?![\w-])", memo, re.I))

    def _match_transfers(self, refs):
        selected = self._refs(refs)
        matched, pairs = set(), []
        credits = [
            r
            for r in self.rows
            if D(r["credit"]) > 0 and D(r["debit"]) == 0 and r["owner_name_matches"]
        ]
        debits = [
            r
            for r in self.rows
            if D(r["debit"]) > 0 and D(r["credit"]) == 0 and r["owner_name_matches"]
        ]
        forward, reverse = defaultdict(list), defaultdict(list)
        # Build the whole-snapshot graph before mutating anything. A selected subset
        # cannot hide another credit competing for the same debit (or vice versa).
        for credit in credits:
            for debit in debits:
                if (
                    debit["account"] != credit["account"]
                    and debit["date"] == credit["date"]
                    and D(debit["debit"]) == D(credit["credit"])
                    and self._mentions(credit["description"], "from", debit["account"])
                    and self._mentions(debit["description"], "to", credit["account"])
                ):
                    forward[credit["ref"]].append(debit)
                    reverse[debit["ref"]].append(credit)
        for credit in selected:
            candidates = forward[credit["ref"]]
            if len(candidates) == 1 and len(reverse[candidates[0]["ref"]]) == 1:
                debit = candidates[0]
                matched.update([credit["ref"], debit["ref"]])
                pairs.append(
                    {
                        "credit_ref": credit["ref"],
                        "debit_ref": debit["ref"],
                        "amount_thb": credit["credit"],
                        "proof": "BILATERAL_OCR_ACCOUNTS_DATE_AMOUNT_DIRECTION",
                        "authenticity_verified": False,
                    }
                )
        changed = False
        for ref in matched:
            changed |= self.by_ref[ref]["category"] != "OWN_TRANSFER"
            self.by_ref[ref]["category"] = "OWN_TRANSFER"
        for issue in self.issues:
            if issue["code"] == "TRANSFER_PROVENANCE" and set(issue["refs"]) & set(refs):
                self.investigated.add(issue["id"])
                if set(issue["refs"]) <= matched:
                    issue.update(
                        status="RESOLVED", resolution="BILATERAL_OCR_MATCH_PROVISIONAL", proof=pairs
                    )
        if changed:
            self.ledger_revision += 1
        self.seen_refs.update(matched)
        return {
            "status": "OK",
            "matched_pairs": pairs,
            "unmatched_refs": sorted(set(refs) - matched),
            "authenticity_verified": False,
        }

    def _declaration_spans(self):
        """Conservative local coverage grammar, NOT a general Thai/English parser.

        Scan the entire scrubbed message independently of model claims. A cue plus
        an adjacent amount separated only by listed modifiers supports a local
        role; a keyword or a number elsewhere in a quote does not. Account cue
        spans require every identifier, including repeated/missing accounts.
        Bank deposits are contextual only when explicit total/cash declarations
        account for their sum. No inferred facts become income or verification.

        Spelled amounts, unlisted modifiers/roles, ambiguous extra numbers,
        multipliers, non-monthly/unspecified revenue/cost periods and cue spans
        without parseable values remain blocking with their exact text. Cash in
        an explicit monthly total's breakdown can inherit that period; the bank
        component still needs the total/cash arithmetic check below.
        This bounded grammar cannot prove unrestricted NLP completeness: unknown
        synonyms, implicit declarations and arbitrary prose outside these cues
        are outside its scope. A coverage result only describes this grammar.
        """
        cue = re.compile(
            r"(?P<bank>เงินเข้าบัญชี|ยอดเข้าบัญชี|bank\s+deposits?)"
            r"|(?P<monthly_revenue>ยอดขาย|รายได้|(?:monthly\s+)?revenue|sales)"
            r"|(?P<monthly_business_cost>ค่าใช้จ่าย(?:ต้นทุน)?|ต้นทุน|(?:business\s+)?costs?|expenses?)"
            r"|(?P<unbanked_cash_sales>เงินสด(?:ที่ไม่ได้ฝาก|ที่ไม่ได้นำฝาก|ไม่ได้ฝาก)|unbanked\s+cash(?:\s+sales)?)"
            r"|(?P<business_account>บัญชี|accounts?)"
            r"|(?P<unknown>(?<!สมุดขาย)เงินสด|cash|กำไร|รายรับ|รายจ่าย|ภาระหนี้|หนี้|ค่าครองชีพ|ค่าเช่า|ค่าแรง)",
            re.I,
        )
        modifiers = re.compile(
            r"(?:\s|รวม|ของร้าน|ร้าน|ธุรกิจ|ทั้งหมด|เดือนละ|ต่อเดือน|จำนวน|ประมาณ|อยู่ที่|เท่ากับ|นอกบัญชี|[:=]"
            r"|total|monthly|per\s+month|of)*",
            re.I,
        )
        amount = re.compile(r"(?<![\w-])\d[\d,]*(?:\.\d+)?(?![\w-])")
        identifier = re.compile(
            r"(?<![A-Za-z0-9_-])(?:[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+"
            r"|[A-Za-z]+\d[A-Za-z0-9]*|\d{6,})(?![A-Za-z0-9_-])"
        )
        monthly = re.compile(r"เดือนละ|ต่อเดือน|monthly|per\s+month", re.I)
        other_period = re.compile(
            r"ปีละ|ต่อปี|วันละ|ต่อวัน|ต่อสัปดาห์|สัปดาห์ละ|ต่อไตรมาส|yearly|annually|daily|weekly|per\s+(?:year|day|week)",
            re.I,
        )
        cues = list(cue.finditer(self.message))
        facts, gaps = [], []
        for index, match in enumerate(cues):
            end = cues[index + 1].start() if index + 1 < len(cues) else len(self.message)
            span = self.message[match.start() : end].strip()
            kind = match.lastgroup
            tail = self.message[match.end() : end]
            values = list((identifier if kind == "business_account" else amount).finditer(tail))
            if not values:
                gaps.append({"span": span, "kind": kind, "value": None})
            for value in values:
                raw = value.group()
                local = self.message[match.start() : match.end() + value.end()]
                period = monthly.search(span)
                breakdown = (
                    kind in {"bank", "unbanked_cash_sales"}
                    and any(f["kind"] == "monthly_revenue" for f in facts)
                    and "แบ่งเป็น" in self.message[: match.start()]
                )
                if kind != "business_account" and (
                    kind == "unknown"
                    or not re.fullmatch(r"(?:\d{1,9}|\d{1,3}(?:,\d{3}){1,2})(?:\.\d{1,2})?", raw)
                    or not modifiers.fullmatch(tail[: value.start()])
                    or other_period.search(span)
                    or re.match(
                        r"\s*(?:ล้าน|พัน|หมื่น|แสน|million|thousand|[%$€]|USD|k\b|m\b)",
                        tail[value.end() :],
                        re.I,
                    )
                    or (kind != "bank" and not period and not breakdown)
                ):
                    gaps.append({"span": span, "kind": "unknown", "value": raw.replace(",", "")})
                    continue
                if period and kind != "business_account":
                    local = span[: max(len(local), period.end())]
                facts.append(
                    {
                        "span": local,
                        "kind": kind,
                        "value": raw
                        if kind == "business_account"
                        else money(D(raw.replace(",", ""))),
                    }
                )
        # Money before the first recognized cue must not disappear from the audit.
        prefix = self.message[: cues[0].start()] if cues else self.message
        if re.search(r"\d[\d,.]*\s*(?:บาท|THB|baht)", prefix, re.I):
            gaps.append({"span": prefix.strip(), "kind": "unknown", "value": None})
        return facts, gaps

    def _compare_declarations(self, claims):
        """Audit local coverage; gaps can finish for a human but never calculate.

        declarations_checked means covered within _declaration_spans' limits.
        declaration_coverage being present means the audit ran, even with gaps.
        Existing blocking gaps are sticky: another model proposal cannot resolve
        missing evidence or certify completeness. Model 'complete' flags have no API.
        """
        accepted = []
        before = len(self.issues)
        # Validate the entire batch before deriving coverage or comparing amounts.
        for claim in claims:
            kind, value, quote = claim["kind"], claim["value"], claim["quote"]
            if quote not in self.message:
                raise SandboxError("claim.quote must be an exact substring of message_untrusted")
            if kind == "business_account":
                if value not in quote:
                    raise SandboxError("account must occur in the quoted customer message")
            else:
                clean = value.replace(",", "")
                if not re.fullmatch(r"\d+(?:\.\d{1,2})?", clean) or D(clean) > D("999999999.99"):
                    raise SandboxError("claim value is not a bounded money amount")
                numbers = re.findall(r"(?<!\d)\d[\d,]*(?:\.\d+)?(?!\d)", quote)
                if not any(D(n.replace(",", "")) == D(clean) for n in numbers):
                    raise SandboxError("claim amount must be present in its exact quote")

        facts, gaps = self._declaration_spans()
        supported, covered = set(), set()
        for index, claim in enumerate(claims):
            value = (
                claim["value"]
                if claim["kind"] == "business_account"
                else money(D(claim["value"].replace(",", "")))
            )
            matches = [
                n
                for n, fact in enumerate(facts)
                if fact["kind"] == claim["kind"]
                and fact["value"] == value
                and fact["span"] in claim["quote"]
            ]
            if matches:
                supported.add(index)
                covered.update(matches)
            else:
                self._issue(
                    "DECLARATION_UNVERIFIED",
                    ["input:message"],
                    f"ยังผูกประเภท {claim['kind']} กับค่า {value} ในข้อความไม่ได้ กรุณายืนยันความหมายและหลักฐาน",
                    expected={"kind": claim["kind"], "value": value},
                    observed={"source": "input:message", "span": claim["quote"]},
                )
        totals = [D(facts[n]["value"]) for n in covered if facts[n]["kind"] == "monthly_revenue"]
        cash = [D(facts[n]["value"]) for n in covered if facts[n]["kind"] == "unbanked_cash_sales"]
        for n, fact in enumerate(facts):
            if fact["kind"] == "bank" and len(set(totals)) == len(set(cash)) == 1:
                if totals[0] == D(fact["value"]) + cash[0]:
                    covered.add(n)
            if n not in covered:
                gaps.append(fact)
        for gap in gaps:
            self._issue(
                "DECLARATION_UNPARSED",
                ["input:message"],
                f"ข้อความส่วนนี้ยังตรวจคำแจ้งไม่ครบ: {gap['span']} กรุณายืนยันจำนวนเงิน/บัญชีและหลักฐาน",
                expected={"kind": gap["kind"], "value": gap["value"]},
                observed={"source": "input:message", "span": gap["span"], "value": gap["value"]},
            )

        for index, claim in enumerate(claims):
            if index not in supported:
                continue
            kind, value = claim["kind"], claim["value"]
            if kind == "business_account":
                if value not in self.accounts.values():
                    self._issue(
                        "MISSING_ACCOUNT",
                        [],
                        f"กรุณาแนบ statement บัญชี {value} ครบช่วง "
                        + ", ".join(self.evidence["expected_months"]),
                        expected=value,
                    )
            else:
                clean = value.replace(",", "")
                expected = money(D(clean))
                if kind == "unbanked_cash_sales":
                    if D(clean) > 0:
                        self._issue(
                            "UNPROVEN_CASH",
                            [],
                            f"ยอดเงินสดที่แจ้ง {expected} บาทต่อเดือนยังไม่มีหลักฐาน กรุณาแนบสมุดขาย/ใบขายเพื่อพิสูจน์ที่มา",
                            expected=expected,
                            observed="NOT_PROVEN",
                        )
                else:
                    values = [
                        D(m["R"]) if kind == "monthly_revenue" else D(m["V"]) + D(m["F"])
                        for m in self.evidence["months"]
                        if m["month"] not in self.evidence["missing_months"]
                    ]
                    if not values:
                        self._issue(
                            "DECLARATION_UNVERIFIED",
                            [],
                            "ยังเทียบคำแจ้งกับ statement ไม่ได้ กรุณาส่งหลักฐานเพิ่ม",
                            expected=expected,
                        )
                        continue
                    observed = money(statistics.median(values))
                    if D(expected) != D(observed):
                        kinds = {"R"} if kind == "monthly_revenue" else {"V", "F"}
                        refs = [r["ref"] for r in self.rows if r["category"] in kinds]
                        label = "ยอดขาย" if kind == "monthly_revenue" else "ต้นทุนธุรกิจ"
                        self._issue(
                            "DECLARATION_MISMATCH",
                            refs,
                            f"{label}ที่แจ้ง {expected} บาท/เดือน เทียบกับค่ากลางจาก statement {observed} บาท ต่างกันเพราะเงินสด บัญชีอื่น หรือประเภทค่าใช้จ่ายใด กรุณาชี้รายการและหลักฐาน",
                            expected=expected,
                            observed=observed,
                        )
            accepted.append(
                {**claim, "evidence_ref": "input:message", "status": "CUSTOMER_DECLARATION_ONLY"}
            )
        self.declarations_checked = not any(
            i["status"] == "OPEN"
            and i["code"] in {"DECLARATION_UNPARSED", "DECLARATION_UNVERIFIED"}
            for i in self.issues
        )
        self.declaration_coverage = {
            "status": "COVERED_WITHIN_LOCAL_GRAMMAR" if self.declarations_checked else "UNVERIFIED",
            "source": "input:message",
            "unrestricted_nlp_completeness_proven": False,
        }
        if len(self.issues) != before:
            self.ledger_revision += 1  # New evidence questions invalidate earlier cashflow.
        return {
            "status": "OK",
            "claims": accepted,
            "comparison": "STATEMENT_MEDIAN_NOT_INCOME_VERIFICATION",
            "coverage": deepcopy(self.declaration_coverage),
            "issues": deepcopy(
                [
                    i
                    for i in self.issues
                    if i["code"]
                    in {
                        "MISSING_ACCOUNT",
                        "UNPROVEN_CASH",
                        "DECLARATION_MISMATCH",
                        "DECLARATION_UNPARSED",
                        "DECLARATION_UNVERIFIED",
                    }
                ]
            ),
        }

    def _inspect_cashflow(self):
        data = self.case["input"]
        self.cashflow_revision = self.ledger_revision
        if data["debt_thb"] is None or data["living_cost_thb"] is None:
            self.cashflow = {
                "status": "UNKNOWN",
                "reason": "ภาระหนี้/ค่าครองชีพไม่ครบ ไม่มีการแทนด้วย 0",
                "rows": [],
                "new_installment_max_thb": None,
            }
            return self.cashflow
        policy = self.case["policy_snapshot"]
        reserve = D(policy["affordability"]["reserve_thb"])
        assumptions = {
            "requested_thb": data["requested_thb"],
            "proposed_limit_thb": None,
            "basis": "EXISTING_CALCULATOR_CAPACITY_LIMITED_OFFER_NOT_APPROVAL",
            "policy_version": policy["policy_version"],
            "terms": deepcopy(policy["limit_fixture"]),
            "reserve_thb": money(reserve),
            "status": "BLOCKED_BY_EVIDENCE",
        }
        payment = None
        if self.evidence["coverage"] == "COMPLETE" and not any(
            i["status"] == "OPEN" and i["blocking_calculation"] for i in self.issues
        ):
            calculation = financial(data, self.evidence, policy)
            payment = max(D(r["payment_thb"]) for r in calculation["schedule"])
            assumptions.update(
                status="PROVISIONAL",
                proposed_limit_thb=calculation["proposed_limit_thb"],
                capacity_thb=calculation["capacity_thb"],
            )
        rows = []
        for month in self.evidence["months"]:
            if month["month"] in self.evidence["missing_months"]:
                continue
            residual = (
                D(month["R"])
                + D(month["O"])
                - D(month["V"])
                - D(month["F"])
                - D(data["debt_thb"])
                - D(data["living_cost_thb"])
            )
            rows.append(
                {
                    "month": month["month"],
                    "residual_before_reserve_thb": money(residual),
                    "after_reserve_thb": money(residual - reserve),
                    "after_reserve_and_new_installment_thb": money(residual - reserve - payment)
                    if payment is not None
                    else None,
                    "refs": month["refs"],
                }
            )
        negative = [
            r
            for r in rows
            if D(r["after_reserve_thb"]) < 0
            or (
                r["after_reserve_and_new_installment_thb"] is not None
                and D(r["after_reserve_and_new_installment_thb"]) < 0
            )
        ]
        if negative:
            self._issue(
                "LIQUIDITY_GAP",
                [ref for r in negative for ref in r["refs"]],
                "เดือน "
                + ", ".join(r["month"] for r in negative)
                + " เงินเหลือหลังกันสำรอง/ค่างวดใหม่ไม่พอ กรุณาอธิบายช่วงขาดมือ ฤดูกาล และหลักฐานเงินสำรอง/แผนชำระ",
                blocking=False,
                observed=negative,
            )
        self.cashflow = {
            "status": "OK",
            "rows": rows,
            "scope": "OBSERVED_ACCOUNTS_ONLY",
            "debt_status": "CUSTOMER_DECLARED_NOT_BUREAU_VERIFIED",
            "new_installment_max_thb": money(payment) if payment is not None else None,
            "installment_assumptions": assumptions,
        }
        return self.cashflow

    def _propose_findings(self, findings):
        for finding in findings:
            issue = next(
                (
                    i
                    for i in self.issues
                    if i["id"] == finding["issue_id"] and i["status"] == "OPEN"
                ),
                None,
            )
            if issue is None or issue["code"] not in {
                "INCOME_SOURCE",
                "UNCLASSIFIED_INFLOW",
                "UNCLASSIFIED_OUTFLOW",
            }:
                raise SandboxError(
                    "finding must address an open transaction-source issue; use matching for transfers"
                )
            for cited in finding["quotes"]:
                ref = cited["ref"]
                if (
                    ref not in issue["refs"]
                    or ref not in self.seen_refs
                    or cited["quote"] not in self.by_ref[ref]["description"]
                ):
                    raise SandboxError(
                        "finding requires an exact quote from a transaction read in this case"
                    )
            self._neutral(finding["question"])
            cited_refs = sorted({cited["ref"] for cited in finding["quotes"]})
            issue.update(
                proposal=deepcopy(finding),
                proposal_applies_to_refs=cited_refs,
                unclassified_group_refs=sorted(set(issue["refs"]) - set(cited_refs)),
                question=finding["question"],
                requested_evidence=finding["requested_evidence"],
            )
            self.investigated.add(issue["id"])
            kind = finding["interpretation"]
            if kind in {"ASSET_SALE", "LOAN_PROCEEDS", "CAPITAL"}:
                # Similar memos are a search group, not proof of the same meaning.
                # A proposal may change only the rows actually read and cited.
                for ref in cited_refs:
                    row = self.by_ref[ref]
                    if D(row["credit"]) > 0 and row["category"] != kind:
                        row["category"] = kind
                        self.ledger_revision += 1
            # BUSINESS_SALES is a hypothesis, never authority to insert R or close the issue.
        return {
            "status": "OK",
            "proposals_recorded": len(findings),
            "verified_income_promotions": 0,
            "issues": deepcopy(
                [i for i in self.issues if i["id"] in {f["issue_id"] for f in findings}]
            ),
        }

    def _finish_review(self, reason):
        self._neutral(reason)
        if self.unfinished():
            raise SandboxError(
                "Required evidence work remains: "
                + json.dumps(self.unfinished(), ensure_ascii=False)
            )
        self.finished = True
        self._finalize(reason)
        return {
            "status": "OK",
            "state": self.case["state"],
            "open_issues": sum(i["status"] == "OPEN" for i in self.issues),
            "decision": None,
        }

    def _finalize(self, reason, technical=False):
        self._refresh()
        current = [i for i in self.issues if i["status"] == "OPEN"]
        blocking = (
            technical
            or any(i["blocking_calculation"] for i in current)
            or self.evidence["coverage"] != "COMPLETE"
        )
        r = self.case["results"]
        r["evidence"] = deepcopy(self.evidence)
        if not blocking:
            r["financial_calculate"] = financial(
                self.case["input"], self.evidence, self.case["policy_snapshot"]
            )
            r["policy_evaluate"] = assessment(
                self.case["input"],
                self.evidence,
                r["financial_calculate"],
                self.case["policy_snapshot"],
            )
            for tool in ("financial_calculate", "policy_evaluate"):
                self.case["trace"].append(
                    {"kind": "tool", "tool": tool, "actor": "deterministic", "status": "OK"}
                )
        base_recommendation = r.get("policy_evaluate", {}).get("recommendation")
        missing_only = {
            "MISSING_PERIOD",
            "MISSING_ACCOUNT",
            "DEBT_UNKNOWN",
            "LIVING_UNKNOWN",
            "UNPROVEN_CASH",
            "DECLARATION_UNPARSED",
            "DECLARATION_UNVERIFIED",
        }
        state = (
            "TECHNICAL_REVIEW"
            if technical
            else "WAIT_CUSTOMER"
            if current and all(i["code"] in missing_only for i in current)
            else "EXCEPTION_REVIEW"
            if current or base_recommendation == "EXCEPTION_REVIEW"
            else "REVIEW_READY"
        )
        recommendation = (
            "NO_CREDIT_CONCLUSION"
            if technical
            else "EXCEPTION_REVIEW"
            if current
            else base_recommendation
        )
        self.case.update(
            state=state,
            active=False,
            feedback=[i["question"] for i in current] or ["เตรียมแฟ้มเพื่อให้เจ้าหน้าที่ตัดสิน ยังไม่มีการอนุมัติ"],
        )
        r["monthly_cashflow"] = deepcopy(self.cashflow)
        self.case["packet"] = {
            "case_id": self.case["id"],
            "case_version": self.case["version"],
            "experiment_only": True,
            "not_for_decision_endpoint": True,
            "human_final_decision_required": True,
            "decision": None,
            "recommendation": recommendation,
            "base_policy_recommendation": base_recommendation,
            "review_reason": "งานตรวจหยุดทางเทคนิค ให้เจ้าหน้าที่ตรวจต่อ ยังไม่มีข้อสรุปเครดิต"
            if technical
            else "เตรียมหลักฐานและประเด็นค้างเพื่อให้เจ้าหน้าที่พิจารณา ยังไม่มีคำตัดสินสินเชื่อ",
            "review_reason_origin": "SYSTEM_HANDOFF_TEMPLATE",
            "financial": r.get("financial_calculate"),
            "assessment": r.get("policy_evaluate"),
            "issues": deepcopy(self.issues),
            "monthly_cashflow": deepcopy(self.cashflow),
            "policy_sha256": digest(self.case["policy_snapshot"]),
            "evidence_sha256": self.evidence["source_sha256"],
            "authenticity_verified": False,
            "onboarding_is_mock": (r.get("onboarding_read", {}).get("snapshot") or {}).get(
                "is_mock", False
            ),
        }

    def stop(self, reason):
        self._issue(
            "AGENT_TECHNICAL_STOP",
            [],
            "งาน Agent หยุด: " + reason + " ให้ตรวจต่อโดยเจ้าหน้าที่ ไม่มีข้อสรุปทางเครดิตจากการหยุดนี้",
        )
        self.finished = True
        self._finalize(reason, technical=True)

    def result(self):
        if not self.finished:
            raise SandboxError("review has not finished")
        return deepcopy(self.case)


def run_review(case, documents, agent, *, max_calls=8, max_seconds=240, on_event=None):
    """Cooperative deadline with a bounded timeout passed to the provider adapter.

    An adapter must honor that HTTP timeout. This cannot preempt a blocking choose
    at OS level; a response returned after the deadline is discarded before tools.
    """
    if type(max_calls) is not int or not 1 <= max_calls <= 8 or not 1 <= max_seconds <= 600:
        raise SandboxError("local experiment budget must be 1..8 calls and 1..600 seconds")
    session = ReviewSession(case, documents)
    started, repeats = time.monotonic(), 0
    attempts, protocol_repairs = 0, 0
    for _ in range(max_calls):
        remaining = max_seconds - (time.monotonic() - started)
        if remaining <= 0:
            session.stop("active deadline reached")
            break
        attempts += 1
        available = session.tools()
        context = session.context()
        context["progress"].update(
            model_calls_used=attempts - 1, model_calls_remaining=max_calls - attempts + 1
        )
        try:
            choice = agent.choose(context, available, min(45, remaining))
        except (SandboxError, OSError) as exc:
            records = getattr(agent, "call_records", [])
            rejection = records[-1].get("rejection", {}) if records else {}
            stage = rejection.get("stage")
            # One repair opportunity for malformed model output; still consumes
            # the same case/HTTP budget. Never retry refusals, credential checks,
            # transport errors, or execute a rejected action as a fallback.
            if (
                str(exc) == "typhoon_invalid_native_tool_response"
                and stage
                in {
                    "finish_reason",
                    "content",
                    "tool_count",
                    "unknown_tool",
                    "arguments_json",
                    "schema_validation",
                }
                and protocol_repairs == 0
                and attempts < max_calls
            ):
                protocol_repairs += 1
                feedback = {
                    "status": "REJECTED",
                    "error": "native tool response invalid; no action executed",
                    "protocol_repair": True,
                    "stage": stage,
                    "required_response": "Exactly one currently available native tool call with schema-valid arguments and existing refs. No prose. Continue required_before_finish; if it is empty, call finish_review.",
                }
                session.observations.append({"tool": "action_validator", "result": feedback})
                event = {
                    "kind": "agent_action",
                    "call": attempts,
                    "tool": None,
                    "status": "REJECTED",
                    "error": feedback["error"],
                    "protocol_repair": True,
                    "stage": stage,
                }
                session.case["trace"].append(event)
                if on_event:
                    on_event(event)
                continue
            session.stop(str(exc))
            break
        if time.monotonic() - started >= max_seconds:
            event = {
                "kind": "agent_action",
                "call": attempts,
                "tool": choice.get("tool") if isinstance(choice, dict) else None,
                "usage": choice.get("usage") if isinstance(choice, dict) else None,
                "status": "REJECTED",
                "error": "active deadline reached after model response; action not executed",
            }
            session.case["trace"].append(event)
            if on_event:
                on_event(event)
            session.stop("active deadline reached after model response")
            break
        try:
            tool, arguments = choice["tool"], choice["arguments"]
            if tool not in {t["function"]["name"] for t in available}:
                raise SandboxError(
                    "tool is not available in the current review state; use progress and required_before_finish"
                )
            result = session.execute(tool, arguments)
            repeats = repeats + 1 if result.get("replayed") else 0
            event = {
                "kind": "agent_action",
                "call": attempts,
                "tool": tool,
                "arguments": arguments,
                "reason": choice.get("reason", "native tool choice"),
                "usage": choice.get("usage"),
                "duration_ms": choice.get("duration_ms"),
                "model": choice.get("model"),
                "replayed": bool(result.get("replayed")),
                "status": "ACCEPTED",
            }
        except (SandboxError, KeyError, TypeError) as exc:
            event = {
                "kind": "agent_action",
                "call": attempts,
                "tool": choice.get("tool") if isinstance(choice, dict) else None,
                "usage": choice.get("usage") if isinstance(choice, dict) else None,
                "status": "REJECTED",
                "error": str(exc),
            }
            session.observations.append(
                {"tool": "action_validator", "result": {"status": "REJECTED", "error": str(exc)}}
            )
        session.case["trace"].append(event)
        if on_event:
            on_event(event)
        if session.finished:
            break
        if repeats >= 2:
            session.stop("repeated action without new evidence")
            break
    if not session.finished:
        session.stop("model-call budget reached with unresolved work")
    result = session.result()
    result.update(
        llm_calls=attempts if getattr(agent, "mode", "") == "typhoon" else 0,
        agent_calls=attempts,
        active_duration_ms=round((time.monotonic() - started) * 1000),
        agent_mode=getattr(agent, "mode", "unknown"),
    )
    return result
