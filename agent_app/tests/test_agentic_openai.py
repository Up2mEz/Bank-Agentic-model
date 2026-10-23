"""Offline Responses adapter boundaries; HTTP is always replaced, never retried."""

import hashlib
import importlib.util
import json
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest
import requests

from merchant_sandbox.agentic_review import TOOL_SPECS
from merchant_sandbox.core import SandboxError

SECRET = "offline-only-test-credential"


def module():
    assert importlib.util.find_spec("merchant_sandbox.agentic_openai"), "Responses adapter missing"
    from merchant_sandbox import agentic_openai

    return agentic_openai


def tools(*names):
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOL_SPECS[name][0],
                "parameters": deepcopy(TOOL_SPECS[name][1]),
            },
        }
        for name in (names or tuple(TOOL_SPECS))
    ]


def body(name="compare_declarations", arguments='{"claims":[]}'):
    return {
        "status": "completed",
        "model": "gpt-6-luna",
        "service_tier": "default",
        "output": [
            {"type": "reasoning", "summary": [], "secret_reasoning": "NEVER RETAIN"},
            {
                "type": "function_call",
                "name": name,
                "arguments": arguments,
                "call_id": "call_1",
                "status": "completed",
            },
        ],
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 100,
            "total_tokens": 1100,
            "input_tokens_details": {"cached_tokens": 400},
            "output_tokens_details": {"reasoning_tokens": 60},
        },
    }


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network I/O")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)


def transport(monkeypatch, response=None, *, status=200, failure=None, after=None):
    seen = []

    def post(url, **kwargs):
        seen.append((url, deepcopy(kwargs)))
        if after:
            after()
        if failure:
            raise failure
        return SimpleNamespace(
            status_code=status,
            headers={"x-request-id": "req_offline-1"},
            content=json.dumps(response).encode(),
            json=lambda: deepcopy(response),
        )

    monkeypatch.setattr(requests, "post", post)
    return seen


def agent(**kwargs):
    m = module()
    budget = kwargs.pop("budget", None) or m.TokenBudget()
    return m.OpenAIReviewAgent(m.OpenAIConfig(api_key=SECRET), budget=budget, **kwargs)


def test_complete_snapshot_once_per_turn_and_no_history(monkeypatch):
    m = module()
    seen = transport(monkeypatch, body())
    a = agent()
    context = {
        "observations": [
            {
                "evidence": "หลักฐาน",
                "source_groups": ["group-unique"],
                "months": ["2026-01"],
                "claims": ["claim-unique"],
                "unknowns": ["unknown-unique"],
            }
        ],
        "progress": {"remaining": 8},
    }
    original, supplied = deepcopy(context), tools()
    original_tools = deepcopy(supplied)
    first = a.choose(context, supplied, 10)
    assert first["tool"] == "compare_declarations" and first["arguments"] == {"claims": []}
    assert first["model"] == "gpt-6-luna" and a.mode == "openai"
    assert context == original and supplied == original_tools
    context["observations"].append({"tool": "compare_declarations", "result": {"claims": []}})
    a.choose(context, supplied, 10)
    for index, (url, kw) in enumerate(seen):
        p = kw["json"]
        assert url == "https://api.openai.com/v1/responses" and kw["allow_redirects"] is False
        assert p["instructions"] == m.SYSTEM
        assert p["input"] == [
            {
                "role": "user",
                "content": json.dumps(
                    original if index == 0 else context, ensure_ascii=False, separators=(",", ":")
                ),
            }
        ]
        assert "temperature" not in p and "previous_response_id" not in p
        assert p["reasoning"] == {"effort": "medium"}
        assert p["service_tier"] == "default"
        assert p["max_output_tokens"] == 4096 and p["store"] is False
        assert p["truncation"] == "disabled" and p["parallel_tool_calls"] is False
        assert p["tool_choice"] == "required"
        assert p["tools"][0] == {"type": "function", **supplied[0]["function"], "strict": True}
        assert kw["timeout"].total <= 10
    assert a.call_records[0]["context_mode"] == "COMPACT_STATELESS_COMPLETE_SNAPSHOT"
    assert "NEVER RETAIN" not in json.dumps(a.call_records)
    assert len(a.call_records[0]["request_sha256"]) == 64
    assert a.call_records[0]["context_bytes"] == len(
        seen[0][1]["json"]["input"][0]["content"].encode()
    )


def test_finish_is_forced_and_callback_cannot_mutate_receipt(monkeypatch):
    seen = transport(monkeypatch, body("finish_review", '{"reason":"ให้คนตรวจ"}'))
    a = agent(on_record=lambda r: r.clear())
    a.choose({}, tools("finish_review"), 5)
    assert seen[0][1]["json"]["tool_choice"] == {"type": "function", "name": "finish_review"}
    assert a.call_records[0]["status"] == "ACCEPTED"


def test_usage_reasoning_and_cached_are_subsets_not_added(monkeypatch):
    transport(monkeypatch, body())
    a = agent()
    result = a.choose({}, tools(), 5)
    r, s = a.call_records[0], a.budget.summary()
    assert result["usage"]["total_tokens"] == 1100
    assert r["usage_complete"] is True
    assert r["cost_estimate_usd"] == "0.000114"
    assert s["input_tokens"] == 1000 and s["output_tokens"] == 100
    assert s["total_tokens"] == 1100 and s["cost_estimate_usd"] == "0.000114"
    assert r["returned_model"] == "gpt-6-luna" and r["service_tier"] == "default"
    reserve = r["reservation"]
    assert reserve["input_tokens_estimate"] >= r["input_bytes"]
    assert reserve["output_tokens"] == 4096
    expected = (
        Decimal(reserve["input_tokens_estimate"]) * Decimal("0.125")
        + Decimal(4096) * Decimal("0.50")
    ) / 1000000
    assert Decimal(reserve["cost_upper_estimate_usd"]) == expected


@pytest.mark.parametrize(
    "limits",
    [
        {"max_calls": 0},
        {"max_input_tokens": 1},
        {"max_output_tokens": 1},
        {"max_cost_usd": "0.000001"},
    ],
)
def test_budget_rejects_before_dispatch(monkeypatch, limits):
    m = module()
    seen = transport(monkeypatch, body())
    a = agent(budget=m.TokenBudget(**limits))
    with pytest.raises(SandboxError, match="^openai_budget_exhausted$"):
        a.choose({}, tools(), 5)
    assert not seen and not a.call_records


@pytest.mark.parametrize(
    "failure,status,response",
    [
        (requests.Timeout(SECRET), 200, None),
        (None, 503, {"error": {"message": SECRET}}),
        (None, 200, {**body(), "usage": None}),
    ],
)
def test_unknown_spend_keeps_reservation_and_blocks_other_case(
    monkeypatch, failure, status, response
):
    m = module()
    seen = transport(monkeypatch, response, failure=failure, status=status)
    budget = m.TokenBudget()
    a = agent(budget=budget)
    with pytest.raises(SandboxError):
        a.choose({}, tools(), 5)
    assert a.call_records[0]["spend_uncertain"] is True
    summary = budget.summary()
    assert summary["uncertain_calls"] == 1 and summary["blocked"] is True
    assert summary["reserved_output_tokens"] == 4096
    with pytest.raises(SandboxError, match="^openai_budget_blocked$"):
        agent(budget=budget).choose({}, tools(), 5)
    assert len(seen) == 1
    assert SECRET not in json.dumps(a.call_records) and SECRET not in json.dumps(summary)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(status="incomplete"),
        lambda b: b["output"].append(
            {"type": "message", "content": [{"type": "refusal", "refusal": SECRET}]}
        ),
        lambda b: b["output"].append(
            {"type": "message", "content": [{"type": "output_text", "text": SECRET}]}
        ),
        lambda b: b["output"].append(deepcopy(b["output"][1])),
        lambda b: b["output"][1].update(name="approve_credit"),
        lambda b: b["output"][1].update(arguments='{"claims":[],"claims":[]}'),
        lambda b: b["output"][1].update(arguments='{"claims":NaN}'),
        lambda b: b["output"][1].update(arguments='{"claims":1e999}'),
        lambda b: b["output"][1].update(arguments='{"claims":['),
        lambda b: b["output"][1].update(arguments='{"claims":[],"extra":"private"}'),
        lambda b: b["output"][1].update(
            name="finish_review", arguments=json.dumps({"reason": SECRET})
        ),
    ],
)
def test_invalid_choice_still_reconciles_usage_without_response_text(monkeypatch, mutate):
    response = body()
    mutate(response)
    transport(monkeypatch, response)
    a = agent()
    with pytest.raises(SandboxError, match="^openai_invalid_native_tool_response$"):
        a.choose({}, tools(), 5)
    r = a.call_records[0]
    assert r["status"] == "REJECTED" and r["usage"]["total_tokens"] == 1100
    assert a.budget.summary()["output_tokens"] == 100
    assert SECRET not in json.dumps(r) and "NEVER RETAIN" not in json.dumps(r)


def test_late_response_reconciled_but_never_accepted(monkeypatch):
    m = module()
    clock = [100.0]
    monkeypatch.setattr(m.time, "monotonic", lambda: clock[0])
    transport(monkeypatch, body(), after=lambda: clock.__setitem__(0, 111.0))
    a = agent()
    with pytest.raises(SandboxError, match="^case_model_deadline_reached$"):
        a.choose({}, tools(), 10)
    assert a.call_records[0]["usage"]["total_tokens"] == 1100
    assert a.call_records[0]["status"] == "REJECTED"


@pytest.mark.parametrize(
    "status,code", [(401, "invalid_api_key"), (429, "insufficient_quota"), (404, "model_not_found")]
)
def test_fatal_http_stops_shared_batch_and_only_safe_metadata(monkeypatch, status, code):
    response = {"error": {"code": code, "param": "model", "message": SECRET}}
    seen = transport(monkeypatch, response, status=status)
    a = agent()
    with pytest.raises(SandboxError, match="^openai_http_failed$"):
        a.choose({}, tools(), 5)
    r = a.call_records[0]
    assert r["stop_batch"] is True and r["http_status"] == status
    assert r["error_code"] == code and r["error_param"] == "model"
    assert r["request_id"] == "req_offline-1" and SECRET not in json.dumps(r)
    with pytest.raises(SandboxError):
        a.choose({}, tools(), 5)
    assert len(seen) == 1


def test_missing_optional_usage_details_remain_unknown(monkeypatch):
    b = body()
    del b["usage"]["input_tokens_details"]
    del b["usage"]["output_tokens_details"]
    transport(monkeypatch, b)
    a = agent()
    a.choose({}, tools(), 5)
    r = a.call_records[0]
    assert r["usage_complete"] is False
    assert r["usage"]["input_tokens_details"]["cached_tokens"] is None
    assert r["usage"]["output_tokens_details"]["reasoning_tokens"] is None
    assert r["cost_estimate_usd"] == "0.000175"


def test_cache_write_numeric_whitelist_accounted_conservatively(monkeypatch):
    b = body()
    b["usage"]["input_tokens_details"].update(cache_creation_tokens=200, private_text=SECRET)
    transport(monkeypatch, b)
    a = agent()
    a.choose({}, tools(), 5)
    r = a.call_records[0]
    assert r["cost_estimate_usd"] == "0.000119"
    assert r["usage"]["input_tokens_details"]["cache_creation_tokens"] == 200
    assert SECRET not in json.dumps(r)


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": 100, "output_tokens": 10, "total_tokens": 999},
        {"input_tokens": True, "output_tokens": 10, "total_tokens": 11},
        {
            "input_tokens": 100,
            "output_tokens": 10,
            "total_tokens": 110,
            "input_tokens_details": {"cached_tokens": 101},
        },
    ],
)
def test_inconsistent_usage_fails_closed(monkeypatch, usage):
    transport(monkeypatch, {**body(), "usage": usage})
    a = agent()
    with pytest.raises(SandboxError, match="^openai_usage_unavailable$"):
        a.choose({}, tools(), 5)
    assert a.budget.summary()["blocked"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("endpoint", "https://evil.test/v1/responses"),
        ("endpoint", "https://api.openai.com/v1/chat/completions"),
        ("model", "gpt-other"),
        ("reasoning_effort", "max"),
        ("timeout", 46),
        ("max_output_tokens", 0),
    ],
)
def test_direct_configuration_cannot_bypass_bounds(field, value):
    m = module()
    with pytest.raises(SandboxError, match="^invalid_openai_configuration$"):
        m.OpenAIConfig(api_key=SECRET, **{field: value})


def test_config_explicit_environment_or_safe_dotenv_only(monkeypatch, tmp_path):
    m = module()
    monkeypatch.setattr(m.os, "environ", {})
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-variable")
    with pytest.raises(SandboxError, match="^openai_credential_missing$"):
        m.OpenAIConfig.load()
    p = tmp_path / "synthetic.env"
    p.write_text("OTHER=ignored\nOPENAI='" + SECRET + "'\n", encoding="utf-8")
    c = m.OpenAIConfig.load(p)
    assert c.api_key == SECRET and SECRET not in repr(c)
    assert "OPENAI" not in m.os.environ
    monkeypatch.setenv("OPENAI", "another-offline-key")
    with pytest.raises(SandboxError, match="^openai_credential_ambiguous$"):
        m.OpenAIConfig.load(p)
    assert m.OpenAIConfig.load().api_key == "another-offline-key"


@pytest.mark.parametrize(
    "line",
    [
        "OPENAI=a\nOPENAI=b",
        'OPENAI="unterminated',
        "OPENAI=$(command)",
        "OPENAI='a' trailing",
        "OPENAI=",
    ],
)
def test_dotenv_rejects_ambiguous_or_unsafe_key_without_leak(monkeypatch, tmp_path, line):
    m = module()
    monkeypatch.setattr(m.os, "environ", {})
    p = tmp_path / "synthetic.env"
    p.write_text(line, encoding="utf-8")
    with pytest.raises(SandboxError) as exc:
        m.OpenAIConfig.load(p)
    assert str(exc.value) in {"openai_credential_ambiguous", "openai_credential_invalid"}


def test_preflight_secret_context_and_case_caps_never_dispatch(monkeypatch):
    seen = transport(monkeypatch, body())
    a = agent(max_calls=1)
    with pytest.raises(SandboxError, match="^openai_secret_in_request$"):
        a.choose({"untrusted": SECRET}, tools(), 5)
    assert not seen
    a.choose({}, tools(), 5)
    with pytest.raises(SandboxError, match="^case_model_call_budget_reached$"):
        a.choose({}, tools(), 5)
    assert len(seen) == 1


def test_fatal_http_with_usage_still_blocks_shared_batch(monkeypatch):
    b = body()
    b["error"] = {"code": "model_not_found", "param": "model", "message": SECRET}
    seen = transport(monkeypatch, b, status=404)
    a = agent()
    with pytest.raises(SandboxError, match="^openai_http_failed$"):
        a.choose({}, tools(), 5)
    assert a.call_records[0]["spend_uncertain"] is False
    assert a.budget.summary()["blocked"] is True
    with pytest.raises(SandboxError, match="^openai_budget_blocked$"):
        agent(budget=a.budget).choose({}, tools(), 5)
    assert len(seen) == 1


def test_shared_call_cap_counts_failed_choices(monkeypatch):
    m = module()
    b = body()
    b["output"][1]["arguments"] = "broken"
    seen = transport(monkeypatch, b)
    budget = m.TokenBudget(max_calls=1)
    with pytest.raises(SandboxError, match="^openai_invalid_native_tool_response$"):
        agent(budget=budget).choose({}, tools(), 5)
    with pytest.raises(SandboxError, match="^openai_budget_exhausted$"):
        agent(budget=budget).choose({}, tools(), 5)
    assert len(seen) == 1 and budget.summary()["calls"] == 1


def test_request_hash_matches_requests_wire_serialization(monkeypatch):
    seen = transport(monkeypatch, body())
    a = agent()
    a.choose({"observations": ["ภาษาไทย", "✓"]}, tools(), 5)
    prepared = requests.Request("POST", seen[0][0], json=seen[0][1]["json"]).prepare()
    assert a.call_records[0]["request_sha256"] == hashlib.sha256(prepared.body).hexdigest()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"input_tokens_estimate": -1, "output_tokens": 1},
        {"input_tokens_estimate": 1, "output_tokens": True},
    ],
)
def test_invalid_reservations_cannot_bypass_budget(kwargs):
    with pytest.raises(SandboxError, match="^invalid_openai_reservation$"):
        module().TokenBudget().reserve(**kwargs)


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf")])
def test_invalid_deadline_does_not_spend_or_dispatch(monkeypatch, seconds):
    seen = transport(monkeypatch, body())
    a = agent()
    with pytest.raises(SandboxError, match="^case_model_deadline_reached$"):
        a.choose({}, tools(), seconds)
    assert not seen and a.budget.summary()["calls"] == 0


def test_exhausted_case_deadline_never_dispatches_again(monkeypatch):
    m = module()
    clock = [0.0]
    monkeypatch.setattr(m.time, "monotonic", lambda: clock[0])
    seen = transport(monkeypatch, body())
    a = agent(max_seconds=1)
    a.choose({}, tools(), 45)
    assert seen[0][1]["timeout"].total == 1
    clock[0] = 2.0
    with pytest.raises(SandboxError, match="^case_model_deadline_reached$"):
        a.choose({}, tools(), 45)
    assert len(seen) == 1


def test_numeric_metadata_and_response_secrets_do_not_enter_receipts(monkeypatch):
    b = body()
    b.update(model=SECRET, service_tier=SECRET, metadata={"private": SECRET})
    b["usage"]["private"] = SECRET
    transport(monkeypatch, b)
    a = agent()
    with pytest.raises(SandboxError, match="^openai_model_or_service_mismatch$"):
        a.choose({}, tools(), 5)
    assert a.call_records[0]["returned_model"] is None
    assert a.call_records[0]["service_tier"] is None
    assert SECRET not in json.dumps(a.call_records)


@pytest.mark.parametrize("change", [{"model": "gpt-other"}, {"service_tier": "priority"}])
def test_unrequested_model_or_service_stops_before_tool_and_does_not_guess_cost(
    monkeypatch, change
):
    b = body()
    b.update(change)
    seen = transport(monkeypatch, b)
    a = agent()
    with pytest.raises(SandboxError, match="^openai_model_or_service_mismatch$"):
        a.choose({}, tools(), 5)
    r = a.call_records[0]
    assert len(seen) == 1 and r["status"] == "REJECTED" and r["stop_batch"]
    assert r["usage"]["total_tokens"] == 1100
    assert r["cost_estimate_usd"] is None and a.budget.summary()["blocked"]


@pytest.mark.parametrize(
    "change",
    [
        lambda ts: ts.clear(),
        lambda ts: ts.append(deepcopy(ts[0])),
        lambda ts: ts[0]["function"].update(name="approve_credit"),
    ],
)
def test_invalid_allowlist_does_not_reserve_or_dispatch(monkeypatch, change):
    seen = transport(monkeypatch, body())
    a, supplied = agent(), tools()
    change(supplied)
    with pytest.raises(SandboxError, match="^invalid_openai_request$"):
        a.choose({}, supplied, 5)
    assert not seen and a.budget.summary()["calls"] == 0


def test_existing_run_review_uses_real_adapter_interface_and_receipts(monkeypatch):
    from test_local_agentic_review import sample

    from merchant_sandbox.agentic_review import run_review

    case, documents, _, _ = sample("C01")
    original = deepcopy(case), deepcopy(documents)
    transport(monkeypatch, body())
    a = agent()
    result = run_review(case, documents, a, max_calls=1)
    assert result["agent_mode"] == "openai" and result["agent_calls"] == 1
    # Frozen controller's Typhoon-only counter is intentionally not impersonated.
    assert result["llm_calls"] == 0 and len(a.call_records) == 1
    assert a.call_records[0]["status"] == "ACCEPTED"
    assert a.call_records[0]["usage"]["total_tokens"] == 1100
    assert (case, documents) == original and result["decision"] is None


@pytest.mark.parametrize("variant", ["duplicate", "nan", "overflow", "malformed"])
def test_invalid_wire_json_cannot_be_hidden_by_permissive_decoder(monkeypatch, variant):
    raw = json.dumps(body())
    if variant == "duplicate":
        raw = raw.replace(
            '"status": "completed"', '"status": "completed", "status": "completed"', 1
        )
    elif variant == "nan":
        raw = '{"extra":NaN,' + raw[1:]
    elif variant == "overflow":
        raw = '{"extra":1e999,' + raw[1:]
    else:
        raw = "broken-json"

    def post(*args, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response._content = raw.encode()
        return response

    monkeypatch.setattr(requests, "post", post)
    a = agent()
    with pytest.raises(SandboxError, match="^openai_usage_unavailable$"):
        a.choose({}, tools(), 5)
    assert a.budget.summary()["blocked"] is True
    assert a.call_records[0]["stop_batch"] is True
