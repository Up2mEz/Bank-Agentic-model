"""Evidence assistant adapter, without case writes or credit-decision authority.

Existing native financial semantics remain unresolved. Their policy/financial
packets are deliberately absent from the service result. Offline output is a
descriptive report of supplied OCR, never simulated native model execution.
"""

from __future__ import annotations

import base64
import re
from copy import deepcopy
from pathlib import Path

from .agentic_review import ReviewSession, run_review
from .agentic_typhoon import TyphoonReviewAgent
from .ocr import TyphoonOCR
from .review_service import MAX_OCR_TEXT, ReviewExecutionFailure, validate_payload
from .statement_experiment import TracedAgent, statement_context
from .statement_report import build_staff_report
from .typhoon import Config

LIMITATIONS = {
    "financial_semantics": "UNRESOLVED_EXISTING_MODEL_SEMANTICS",
    "scope": "EVIDENCE_ASSISTANT_ONLY",
    "native_execution": "EXPERIMENTAL_NOT_UNDERWRITING_VALIDATION",
    "authenticity": "UNVERIFIED",
}
TRACE_FIELDS = frozenset(
    {
        "kind",
        "tool",
        "actor",
        "status",
        "call",
        "usage",
        "duration_ms",
        "model",
        "replayed",
        "execution_mode",
        "protocol_repair",
        "stage",
        # Public action rationale and actual tool observations, not private
        # model reasoning. These derive from the bounded local review session.
        "arguments",
        "reason",
        "result",
        "error",
        "case_version",
    }
)
USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")
REJECTION_ENUMS = {
    "stage": {
        "transport",
        "http",
        "envelope",
        "deadline",
        "finish_reason",
        "content",
        "refusal",
        "tool_count",
        "tool_envelope",
        "unknown_tool",
        "arguments_json",
        "schema_validation",
        "reason_validation",
        "credential_guard",
        "history",
    },
    "kind": {
        "request_failed",
        "status_error",
        "response_size",
        "response_json",
        "body_type",
        "response_late",
        "choices_type",
        "choices_count",
        "choice_type",
        "message_type",
        "unexpected_finish_reason",
        "nonempty_content",
        "refusal_present",
        "calls_type",
        "calls_count",
        "call_type",
        "tool_type",
        "function_type",
        "name_type",
        "unknown_name",
        "arguments_type",
        "invalid_json",
        "duplicate_member",
        "nonfinite_constant",
        "too_deep",
        "unclassified",
        "type",
        "object_fields",
        "array_size",
        "text_length",
        "enum",
        "invalid_reason",
        "secret_in_arguments",
        "validation_late",
        "invalid_call_id",
    },
    "finish_reason": {
        "tool_calls",
        "stop",
        "length",
        "content_filter",
        "function_call",
        "missing",
        "other",
    },
    "content_kind": {"null", "empty", "text", "other"},
    "allowed_function": {
        "match_transfers",
        "compare_declarations",
        "inspect_cashflow",
        "propose_findings",
        "flag_transactions",
        "finish_review",
    },
}


def _attempt_receipts(records):
    """One allowlisted receipt per actual adapter attempt, including terminal rejects."""
    receipts = []
    for n, record in enumerate(records, 1):
        event = {
            "kind": "llm_attempt",
            "attempt": n,
            "status": "ACCEPTED" if record.get("status") == "ACCEPTED" else "REJECTED",
        }
        event["usage"] = {
            k: v
            for k, v in (record.get("usage") or {}).items()
            if k in USAGE_FIELDS and type(v) is int and v >= 0
        }
        for key in ("duration_ms", "http_status"):
            if type(record.get(key)) is int and record[key] >= 0:
                event[key] = record[key]
        model = record.get("model")
        if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,120}", model):
            event["model"] = model
        if record.get("error") in {
            "typhoon_invalid_native_tool_response",
            "typhoon_transport_failed",
            "typhoon_http_failed",
            "case_model_deadline_reached",
        }:
            event["error"] = record["error"]
        rejection = record.get("rejection") or {}
        safe = {
            k: v
            for k, v in rejection.items()
            if k in REJECTION_ENUMS and isinstance(v, str) and v in REJECTION_ENUMS[k]
        }
        for key in ("choice_count", "tool_count"):
            if type(rejection.get(key)) is int and rejection[key] >= 0:
                safe[key] = rejection[key]
        if type(rejection.get("refusal_present")) is bool:
            safe["refusal_present"] = rejection["refusal_present"]
        if safe:
            event["rejection"] = safe
        # Existing adapter only stores non-200 statuses. These stages can only
        # occur after its exact HTTP 200 branch, never after transport failure.
        if "http_status" not in event and (
            event["status"] == "ACCEPTED" or safe.get("stage") not in {None, "transport", "http"}
        ):
            event["http_status"] = 200
        receipts.append(event)
    return receipts


def _usage_summary(ocr_records, agent_records):
    records = []
    for kind, sources in (("ocr", ocr_records), ("agent", agent_records)):
        for record in sources:
            usage = record.get("usage") or {}
            records.append(
                {
                    "kind": kind,
                    "usage": {
                        k: usage[k]
                        for k in USAGE_FIELDS
                        if type(usage.get(k)) is int and usage[k] >= 0
                    },
                }
            )
    totals = [r["usage"].get("total_tokens") for r in records]
    return {
        "provider_calls": len(records),
        "ocr_calls": len(ocr_records),
        "agent_calls": len(agent_records),
        "records": records,
        "total_tokens": sum(totals) if all(type(t) is int for t in totals) else None,
    }


class ReviewPipeline:
    def __init__(
        self,
        *,
        config: Config | None = None,
        env_file: Path | None = None,
        max_calls=8,
        max_seconds=240,
        max_total_tokens=300_000,
    ):
        if type(max_calls) is not int or not 1 <= max_calls <= 8:
            raise ValueError("max_calls must be 1..8")
        if type(max_seconds) is not int or not 1 <= max_seconds <= 600:
            raise ValueError("max_seconds must be 1..600")
        if type(max_total_tokens) is not int or max_total_tokens <= 0:
            raise ValueError("positive token bound required")
        self.config, self.env_file = config, env_file
        self.max_calls, self.max_seconds = max_calls, max_seconds
        self.max_total_tokens = max_total_tokens

    def capabilities(self) -> dict:
        configured = self.config is not None and bool(self.config.api_key)
        return {
            "ready": True,
            "modes": ["offline", "typhoon"] if configured else ["offline"],
            "typhoon_configured": configured,
        }

    def __call__(self, payload: dict) -> dict:
        accepted = validate_payload(payload)
        case, documents = accepted["case"], accepted["documents"]
        if accepted["mode"] == "offline":
            # No config load, file lookup, transport, or legacy planner on this path.
            return {
                "report": build_staff_report(case, documents),
                "trace": [
                    {
                        "kind": "evidence_report",
                        "actor": "deterministic",
                        "status": "OK",
                        "execution_mode": "OFFLINE_SUPPLIED_OCR",
                    }
                ],
                "usage": _usage_summary([], []),
                "review_state": "OFFLINE_EVIDENCE_ONLY",
                "stage": "OFFLINE_REPORT",
                "model_execution": "NOT_RUN_OFFLINE_SUPPLIED_OCR",
                "execution_mode": "OFFLINE_SUPPLIED_OCR",
                "decision": None,
                "human_final_decision_required": True,
                "limitations": deepcopy(LIMITATIONS),
            }
        config = self.config if self.config is not None else Config.load(self.env_file)
        # Construct the strict native client before any paid OCR work, so invalid
        # provider configuration fails before an OCR attempt can be charged.
        inner = TyphoonReviewAgent(config, max_calls=self.max_calls, max_seconds=self.max_seconds)
        ocr_records = []
        try:
            return self._native(case, documents, config, inner, ocr_records)
        except Exception:
            raise ReviewExecutionFailure(
                _usage_summary(ocr_records, inner.call_records),
                trace=_attempt_receipts(inner.call_records),
            ) from None

    def _native(self, case, documents, config, inner, ocr_records):
        for doc in documents:
            have = {p["page"] for p in doc["ocr_pages"]}
            missing = [n for n in range(1, doc["pages"] + 1) if n not in have]
            if missing:
                raw = base64.b64decode(doc["content_base64"], validate=True)
                ocr = TyphoonOCR(config)
                for n in missing:
                    # Record attempted calls too. A failed response has unknown
                    # usage; earlier paid pages must remain visible in receipts.
                    attempt = {"usage": {}}
                    ocr_records.append(attempt)
                    try:
                        page = ocr.extract_page(raw, doc["mime_type"], n)
                    except Exception:
                        raise ReviewExecutionFailure(_usage_summary(ocr_records, [])) from None
                    if (
                        not isinstance(page, dict)
                        or type(page.get("page")) is not int
                        or page["page"] != n
                        or not isinstance(page.get("text"), str)
                        or not 1 <= len(page["text"]) <= MAX_OCR_TEXT
                        or not page["text"].strip()
                    ):
                        raise ReviewExecutionFailure(_usage_summary(ocr_records, [])) from None
                    doc["ocr_pages"].append(page)
                    attempt.update(usage=page.get("usage") or {})
            doc.pop("content_base64", None)
            doc["ocr_pages"].sort(key=lambda page: page["page"])
        # Same scoped session and native controller as the existing experiment.
        # The initial session enforces evidence/row limits before the first LLM call.
        ReviewSession(case, documents)
        agent = TracedAgent(
            inner,
            max_total_tokens=self.max_total_tokens,
            evidence_context=statement_context(case, documents),
        )
        reviewed = run_review(
            case, documents, agent, max_calls=self.max_calls, max_seconds=self.max_seconds
        )
        return {
            "report": build_staff_report(reviewed, documents),
            "trace": [
                {k: v for k, v in event.items() if k in TRACE_FIELDS} for event in reviewed["trace"]
            ]
            + _attempt_receipts(agent.call_records),
            "usage": _usage_summary(ocr_records, agent.call_records),
            "review_state": reviewed["state"],
            "stage": "NATIVE_REPORT",
            "model_execution": "TYPHOON_NATIVE_EXPERIMENTAL",
            "execution_mode": "TYPHOON_NATIVE",
            "decision": None,
            "human_final_decision_required": True,
            "limitations": deepcopy(LIMITATIONS),
        }
