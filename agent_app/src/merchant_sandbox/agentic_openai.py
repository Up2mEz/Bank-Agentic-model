"""Bounded Responses transport; stateless complete context, not a pure model ablation.

No retry, redirect, fallback, history, reasoning retention, or global dotenv changes.
Prices below are experiment estimates in USD, not provider billing receipts.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import Lock

import requests
from urllib3.util import Timeout

from .agentic_review import validate
from .agentic_typhoon import REVIEW_TOOLS, SYSTEM, _reject_json_constant, _unique_object
from .core import SandboxError

CONTEXT_MODE = "COMPACT_STATELESS_COMPLETE_SNAPSHOT"
ENDPOINT = "https://api.openai.com/v1/responses"
MODEL = "gpt-6-luna"
CACHE_KEYS = frozenset(
    {
        "cache_creation_tokens",
        "cache_write_tokens",
        "cache_creation_input_tokens",
        "cache_write_input_tokens",
    }
)
MILLION = Decimal(1_000_000)
INPUT_RATE, CACHED_RATE = Decimal("0.10"), Decimal("0.01")
WRITE_RATE, OUTPUT_RATE = Decimal("0.125"), Decimal("0.50")


def _dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError
    return number


def _safe(value, secret):
    """Bounded metadata only; even syntactically safe secret echoes are discarded."""
    return (
        value
        if (
            isinstance(value, str)
            and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", value)
            and secret not in value
        )
        else None
    )


def _count(value):
    return type(value) is int and value >= 0


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str = field(default="", repr=False)
    model: str = MODEL
    endpoint: str = ENDPOINT
    timeout: float = 45
    reasoning_effort: str = "medium"
    max_output_tokens: int = 4096

    def __post_init__(self):
        if (
            self.model != MODEL
            or self.endpoint != ENDPOINT
            or self.reasoning_effort not in ("none", "low", "medium", "high")
            or type(self.timeout) not in (int, float)
            or not math.isfinite(self.timeout)
            or not 0 < self.timeout <= 45
            or type(self.max_output_tokens) is not int
            or not 1 <= self.max_output_tokens <= 16384
            or not isinstance(self.api_key, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", self.api_key)
        ):
            raise SandboxError("invalid_openai_configuration")

    @classmethod
    def load(cls, credential_file=None, credential_env="OPENAI"):
        """Read only the selected variable or explicitly supplied single-line dotenv.

        Both sources being present is ambiguous, even when their values match.
        No implicit .env read, interpolation, escaping, export, or shell syntax.
        """
        if not isinstance(credential_env, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", credential_env
        ):
            raise SandboxError("openai_credential_invalid")
        found = []
        if credential_file is not None:
            try:
                lines = Path(credential_file).read_text(encoding="utf-8-sig").splitlines()
            except (OSError, UnicodeError, TypeError, ValueError):
                raise SandboxError("openai_credential_file_unreadable") from None
            for line in lines:
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                key, sep, raw = line.partition("=")
                if key.strip() != credential_env:
                    continue
                if not sep:
                    raise SandboxError("openai_credential_invalid")
                raw = raw.strip()
                if raw[:1] in ("'", '"'):
                    quote = raw[0]
                    if len(raw) < 2 or raw[-1] != quote:
                        raise SandboxError("openai_credential_invalid")
                    raw = raw[1:-1]
                found.append(raw)
        if credential_env in os.environ:
            found.append(os.environ[credential_env])
        if len(found) > 1:
            raise SandboxError("openai_credential_ambiguous")
        if not found:
            raise SandboxError("openai_credential_missing")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", found[0]):
            raise SandboxError("openai_credential_invalid")
        return cls(api_key=found[0])


def _usage(raw):
    """Copy numeric allowlist only. Cached input/reasoning output are subsets."""
    if not isinstance(raw, dict):
        return None, False, False, None
    usage = {
        k: raw.get(k) if _count(raw.get(k)) else None
        for k in ("input_tokens", "output_tokens", "total_tokens")
    }
    valid = all(v is not None for v in usage.values())
    if valid:
        valid = usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
    complete = valid
    for detail, key, parent in (
        ("input_tokens_details", "cached_tokens", "input_tokens"),
        ("output_tokens_details", "reasoning_tokens", "output_tokens"),
    ):
        source = raw.get(detail)
        source = source if isinstance(source, dict) else {}
        n = source.get(key)
        usage[detail] = {key: n if _count(n) else None}
        complete = complete and _count(n)
        if key in source and (not _count(n) or (usage[parent] is not None and n > usage[parent])):
            valid = False
        for extra in sorted(CACHE_KEYS if detail == "input_tokens_details" else ()):
            if extra in source:
                usage[detail][extra] = source[extra] if _count(source[extra]) else None
                complete = complete and _count(source[extra])
                if not _count(source[extra]):
                    valid = False
    for key in sorted(CACHE_KEYS):
        if key in raw:
            usage[key] = raw[key] if _count(raw[key]) else None
            if not _count(raw[key]):
                valid = False
    if not valid:
        return usage, False, False, None
    cached = usage["input_tokens_details"]["cached_tokens"]
    if cached is None:
        cost = Decimal(usage["input_tokens"]) * WRITE_RATE
    else:
        uncached = usage["input_tokens"] - cached
        # Unknown overlapping write counters are never added to token totals.
        # Sum/cap their price premium conservatively if both aliases are supplied.
        writes = sum(usage.get(k, 0) + usage["input_tokens_details"].get(k, 0) for k in CACHE_KEYS)
        cost = (
            Decimal(uncached) * INPUT_RATE
            + Decimal(cached) * CACHED_RATE
            + Decimal(min(uncached, writes)) * (WRITE_RATE - INPUT_RATE)
        )
    cost = (cost + Decimal(usage["output_tokens"]) * OUTPUT_RATE) / MILLION
    return usage, bool(complete), True, cost


class TokenBudget:
    """Shared reservation ledger. Unknown dispatch spend blocks all further calls.

    Input estimates use one token per UTF-8 byte plus generous protocol overhead;
    these are deliberately not reported as provider token counts. Settled actual
    usage replaces reservations; pending/uncertain spend remains fully charged.
    """

    def __init__(
        self, max_calls=80, max_input_tokens=400000, max_output_tokens=64000, max_cost_usd="0.10"
    ):
        try:
            cost = Decimal(str(max_cost_usd))
            if (
                any(
                    type(n) is not int or n < 0
                    for n in (max_calls, max_input_tokens, max_output_tokens)
                )
                or not cost.is_finite()
                or cost < 0
            ):
                raise ValueError
        except (InvalidOperation, ValueError):
            raise SandboxError("invalid_openai_budget") from None
        self.max_calls, self.max_input_tokens = max_calls, max_input_tokens
        self.max_output_tokens, self.max_cost_usd = max_output_tokens, cost
        self._lock = Lock()
        self._reservations = {}
        self._calls = self._input = self._output = self._uncertain = 0
        self._cost = Decimal(0)
        self._blocked = False

    def reserve(self, input_tokens_estimate, output_tokens):
        if not _count(input_tokens_estimate) or not _count(output_tokens):
            raise SandboxError("invalid_openai_reservation")
        cost = (
            Decimal(input_tokens_estimate) * WRITE_RATE + Decimal(output_tokens) * OUTPUT_RATE
        ) / MILLION
        with self._lock:
            if self._blocked:
                raise SandboxError("openai_budget_blocked")
            pending = list(self._reservations.values())
            if (
                self._calls >= self.max_calls
                or self._input
                + sum(r["input_tokens_estimate"] for r in pending)
                + input_tokens_estimate
                > self.max_input_tokens
                or self._output + sum(r["output_tokens"] for r in pending) + output_tokens
                > self.max_output_tokens
                or self._cost
                + sum((Decimal(r["cost_upper_estimate_usd"]) for r in pending), Decimal(0))
                + cost
                > self.max_cost_usd
            ):
                raise SandboxError("openai_budget_exhausted")
            self._calls += 1
            reservation = {
                "input_tokens_estimate": input_tokens_estimate,
                "input_estimate_method": "utf8_bytes_plus_protocol_overhead",
                "output_tokens": output_tokens,
                "cost_upper_estimate_usd": str(cost),
                "input_reservation_usd_per_million": str(WRITE_RATE),
            }
            self._reservations[self._calls] = reservation
            return self._calls, deepcopy(reservation)

    def settle(self, ticket, usage, cost):
        with self._lock:
            del self._reservations[ticket]
            self._input += usage["input_tokens"]
            self._output += usage["output_tokens"]
            self._cost += cost
            if (
                self._input > self.max_input_tokens
                or self._output > self.max_output_tokens
                or self._cost > self.max_cost_usd
            ):
                self._blocked = True

    def uncertain(self):
        with self._lock:
            self._uncertain += 1
            self._blocked = True

    def stop(self):
        """Stop the shared generation batch even when fatal HTTP usage is known."""
        with self._lock:
            self._blocked = True

    def summary(self):
        with self._lock:
            pending = list(self._reservations.values())
            reserved_cost = sum(
                (Decimal(r["cost_upper_estimate_usd"]) for r in pending), Decimal(0)
            )
            return {
                "calls": self._calls,
                "input_tokens": self._input,
                "output_tokens": self._output,
                "total_tokens": self._input + self._output,
                "cost_estimate_usd": str(self._cost),
                "reserved_input_tokens_estimate": sum(r["input_tokens_estimate"] for r in pending),
                "reserved_output_tokens": sum(r["output_tokens"] for r in pending),
                "reserved_cost_upper_estimate_usd": str(reserved_cost),
                "accounted_cost_upper_estimate_usd": str(self._cost + reserved_cost),
                "uncertain_calls": self._uncertain,
                "blocked": self._blocked,
                "max_calls": self.max_calls,
                "max_input_tokens": self.max_input_tokens,
                "max_output_tokens": self.max_output_tokens,
                "max_cost_usd": str(self.max_cost_usd),
            }


def _arguments(body, schemas, secret):
    if body.get("status") != "completed" or body.get("error") or body.get("incomplete_details"):
        raise ValueError
    output, calls = body.get("output"), []
    if not isinstance(output, list):
        raise ValueError
    for item in output:
        if not isinstance(item, dict):
            raise ValueError
        kind = item.get("type")
        if kind == "reasoning":
            continue  # Discard entirely; no history, summary request or receipt.
        if kind == "function_call":
            calls.append(item)
        elif kind == "message":
            if item.get("refusal") or item.get("role", "assistant") != "assistant":
                raise ValueError
            content = item.get("content")
            if content not in (None, "", []):
                if not isinstance(content, list) or any(
                    not isinstance(c, dict) or c.get("type") != "output_text" or c.get("text") != ""
                    for c in content
                ):
                    raise ValueError
        else:
            raise ValueError
    if len(calls) != 1:
        raise ValueError
    call = calls[0]
    name = call.get("name")
    if (
        not isinstance(name, str)
        or name not in schemas
        or call.get("status") not in (None, "completed")
        or not isinstance(call.get("arguments"), str)
    ):
        raise ValueError
    arguments = json.loads(
        call["arguments"],
        object_pairs_hook=_unique_object,
        parse_constant=_reject_json_constant,
        parse_float=_finite_float,
    )
    # Also reject exponent overflows such as 1e999, not just NaN/Infinity literals.
    serialized = _dump(arguments)
    if secret in serialized:
        raise ValueError
    validate(arguments, schemas[name])
    return name, arguments


class OpenAIReviewAgent:
    mode = "openai"
    context_mode = CONTEXT_MODE

    def __init__(self, config, *, budget, max_calls=8, max_seconds=240, on_record=None):
        if not isinstance(config, OpenAIConfig):
            raise SandboxError("invalid_openai_configuration")
        if (
            not isinstance(budget, TokenBudget)
            or type(max_calls) is not int
            or not 1 <= max_calls <= 8
            or type(max_seconds) not in (int, float)
            or not math.isfinite(max_seconds)
            or not 0 < max_seconds <= 600
        ):
            raise SandboxError("invalid_openai_case_budget")
        self.config, self.budget = config, budget
        self.max_calls, self.max_seconds, self.on_record = max_calls, max_seconds, on_record
        self.call_records = []
        self.started = None

    def choose(self, context, tools, timeout_seconds):
        now = time.monotonic()
        if self.started is None:
            self.started = now
        if len(self.call_records) >= self.max_calls:
            raise SandboxError("case_model_call_budget_reached")
        try:
            requested = float(timeout_seconds)
            if not math.isfinite(requested):
                raise ValueError
            seconds = min(
                requested, self.config.timeout, self.max_seconds - (now - self.started), 45
            )
            if seconds <= 0:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise SandboxError("case_model_deadline_reached") from None
        deadline = now + seconds
        schemas, converted = {}, []
        try:
            for tool in tools:
                function = tool["function"]
                name = function["name"]
                if tool["type"] != "function" or name not in REVIEW_TOOLS or name in schemas:
                    raise ValueError
                schemas[name] = deepcopy(function["parameters"])
                converted.append(
                    {
                        "type": "function",
                        "name": name,
                        "description": function["description"],
                        "parameters": deepcopy(function["parameters"]),
                        "strict": True,
                    }
                )
            if not schemas:
                raise ValueError
            snapshot = _dump(context)
            tool_json = _dump(converted)
        except (TypeError, KeyError, ValueError, RecursionError, OverflowError):
            raise SandboxError("invalid_openai_request") from None
        payload = {
            "model": self.config.model,
            "instructions": SYSTEM,
            "input": [{"role": "user", "content": snapshot}],
            "tools": converted,
            "tool_choice": (
                {"type": "function", "name": "finish_review"}
                if schemas.keys() == {"finish_review"}
                else "required"
            ),
            "reasoning": {"effort": self.config.reasoning_effort},
            "service_tier": "default",
            "max_output_tokens": self.config.max_output_tokens,
            "store": False,
            "truncation": "disabled",
            "parallel_tool_calls": False,
        }
        if self.config.api_key in snapshot or self.config.api_key in tool_json:
            raise SandboxError("openai_secret_in_request")
        # requests' json= serialization uses these defaults. Hash excludes headers.
        encoded = json.dumps(payload, allow_nan=False).encode("utf-8")
        context_bytes, tool_bytes = len(snapshot.encode("utf-8")), len(tool_json.encode("utf-8"))
        input_bytes = len(SYSTEM.encode("utf-8")) + context_bytes + tool_bytes
        seconds = min(seconds, deadline - time.monotonic())
        if seconds <= 0:
            raise SandboxError("case_model_deadline_reached")
        # Last pre-dispatch operation: reserve full output and conservative input.
        ticket, reservation = self.budget.reserve(
            input_bytes + 8192 + 128 * len(converted), self.config.max_output_tokens
        )
        record = {
            "kind": "llm_attempt",
            "attempt": len(self.call_records) + 1,
            "model": MODEL,
            "context_mode": CONTEXT_MODE,
            "status": "REJECTED",
            "http_status": None,
            "request_id": None,
            "returned_model": None,
            "service_tier": None,
            "usage": None,
            "usage_complete": False,
            "cost_estimate_usd": None,
            "spend_uncertain": True,
            "stop_batch": False,
            "input_bytes": input_bytes,
            "context_bytes": context_bytes,
            "tool_bytes": tool_bytes,
            "request_sha256": hashlib.sha256(encoded).hexdigest(),
            "reservation": reservation,
        }
        error, stage, settled = "openai_invalid_native_tool_response", "transport", False
        try:
            try:
                response = requests.post(
                    self.config.endpoint,
                    headers={
                        "Authorization": "Bearer " + self.config.api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=Timeout(total=seconds, connect=min(10, seconds), read=seconds),
                    allow_redirects=False,
                )
            except (requests.RequestException, OSError):
                raise SandboxError("openai_transport_failed") from None
            record["http_status"] = response.status_code
            record["request_id"] = _safe(response.headers.get("x-request-id"), self.config.api_key)
            stage = "envelope"
            try:
                body = json.loads(
                    response.content,
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_json_constant,
                    parse_float=_finite_float,
                )
            except (ValueError, TypeError, RecursionError):
                body = None
            identity_matches = False
            if isinstance(body, dict):
                record["returned_model"] = _safe(body.get("model"), self.config.api_key)
                record["service_tier"] = _safe(body.get("service_tier"), self.config.api_key)
                identity_matches = bool(
                    re.fullmatch(
                        re.escape(MODEL) + r"(?:-\d{4}-\d{2}-\d{2})?",
                        record["returned_model"] or "",
                    )
                    and record["service_tier"] == "default"
                )
                usage, complete, valid, cost = _usage(body.get("usage"))
                record.update(usage=usage, usage_complete=complete)
                if valid and identity_matches:
                    self.budget.settle(ticket, usage, cost)
                    settled = True
                    record.update(spend_uncertain=False, cost_estimate_usd=str(cost))
            if response.status_code != 200:
                stage = "http"
                details = body.get("error") if isinstance(body, dict) else None
                details = details if isinstance(details, dict) else {}
                record["error_code"] = _safe(details.get("code"), self.config.api_key)
                record["error_param"] = _safe(details.get("param"), self.config.api_key)
                record["stop_batch"] = (
                    response.status_code in (401, 403, 404, 429)
                    or record["error_param"] == "model"
                    or record["error_code"]
                    in {
                        "invalid_api_key",
                        "insufficient_quota",
                        "model_not_found",
                        "model_not_available",
                        "billing_hard_limit_reached",
                        "authentication_error",
                        "quota_exceeded",
                        "invalid_model",
                        "unsupported_model",
                        "model_access_denied",
                    }
                )
                if record["stop_batch"]:
                    self.budget.stop()
                raise SandboxError("openai_http_failed")
            if isinstance(body, dict) and not identity_matches:
                stage = "identity"
                raise SandboxError("openai_model_or_service_mismatch")
            if not settled:
                raise SandboxError("openai_usage_unavailable")
            if time.monotonic() >= deadline:
                stage = "deadline"
                raise SandboxError("case_model_deadline_reached")
            stage = "action"
            name, arguments = _arguments(body, schemas, self.config.api_key)
            if time.monotonic() >= deadline:
                stage = "deadline"
                raise SandboxError("case_model_deadline_reached")
            record.update(status="ACCEPTED", tool=name)
            return {
                "tool": name,
                "arguments": arguments,
                "reason": arguments.get("reason") or "native tool choice: " + name,
                "usage": deepcopy(record["usage"]),
                "model": MODEL,
                "duration_ms": round((time.monotonic() - now) * 1000),
            }
        except SandboxError as exc:
            # Validator exceptions include arbitrary values: never propagate those.
            error = str(exc) if stage != "action" else "openai_invalid_native_tool_response"
            raise SandboxError(error) from None
        except (
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            RecursionError,
            OverflowError,
        ):
            raise SandboxError(error) from None
        finally:
            if not settled:
                self.budget.uncertain()
                record["stop_batch"] = True
            record["duration_ms"] = round((time.monotonic() - now) * 1000)
            if record["status"] != "ACCEPTED":
                record.update(error=error, rejection={"stage": stage})
            self.call_records.append(deepcopy(record))
            if self.on_record:
                self.on_record(deepcopy(record))
