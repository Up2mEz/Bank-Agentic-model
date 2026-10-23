"""Offline boundary tests: provider data is hostile; baseline inputs are immutable."""

import importlib.util
import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import requests

from merchant_sandbox.core import SandboxError
from merchant_sandbox.typhoon import Config

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "outputs/lending-case-audit-20261023/offline-final"


@pytest.fixture
def historical_baseline():
    if not BASELINE.exists():
        pytest.skip("Historical OCR replay artifacts are not included in a fresh checkout")


@pytest.fixture
def experiment_path():
    # The real CLI deliberately requires outputs/. Do not depend on pytest's
    # caller choosing a special --basetemp or weaken the production preflight.
    return ROOT / "outputs" / "agentic-offline-tests" / uuid4().hex


def client_module():
    assert importlib.util.find_spec("merchant_sandbox.agentic_typhoon"), (
        "Typhoon review client missing"
    )
    from merchant_sandbox import agentic_typhoon

    return agentic_typhoon


def runner_module():
    path = ROOT / "agent_app/tools/run_lending_agentic_experiment.py"
    assert path.exists(), "Isolated experiment runner missing"
    spec = importlib.util.spec_from_file_location("local_experiment", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tools():
    from merchant_sandbox.agentic_review import TOOL_SPECS

    return [
        {"type": "function", "function": {"name": k, "description": v[0], "parameters": v[1]}}
        for k, v in TOOL_SPECS.items()
    ]


def body(name="compare_declarations", arguments=None):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(
                                    arguments if arguments is not None else {"claims": []}
                                ),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 4,
            "total_tokens": 16,
            "secret": "do-not-log",
            "completion_tokens_details": {"text": "do-not-log"},
        },
    }


def mock_response(monkeypatch, payload, status=200):
    seen = []

    def post(url, **kwargs):
        seen.append((url, kwargs))
        return SimpleNamespace(
            status_code=status, content=json.dumps(payload).encode(), json=lambda: deepcopy(payload)
        )

    monkeypatch.setattr(requests, "post", post)
    return seen


def mock_conversation(monkeypatch, responses):
    """Capture real client payloads while replacing only external HTTP I/O."""
    pending, seen = iter(responses), []

    def post(url, **kwargs):
        seen.append(deepcopy(kwargs["json"]))
        response = next(pending)
        return SimpleNamespace(
            status_code=200, content=json.dumps(response).encode(), json=lambda: deepcopy(response)
        )

    monkeypatch.setattr(requests, "post", post)
    return seen


def native_response(name, arguments, call_id):
    response = body(name, arguments)
    call = response["choices"][0]["message"]["tool_calls"][0]
    if call_id is None:
        call.pop("id")
    else:
        call["id"] = call_id
    return response


def tool_pairs(payload):
    """Validate role order and return the actual assistant/tool receipt pairs."""
    messages = payload["messages"]
    assert messages[0]["role"] == "system" and messages[-1]["role"] == "user"
    pairs = []
    for index, message in enumerate(messages):
        if message["role"] == "assistant":
            receipt = messages[index + 1]
            (call,) = message["tool_calls"]
            assert receipt["role"] == "tool"
            assert receipt["tool_call_id"] == call["id"]
            pairs.append((call, json.loads(receipt["content"])))
        elif message["role"] == "tool":
            assert messages[index - 1]["role"] == "assistant"
    return pairs


def test_native_conversation_preserves_actual_and_replayed_results(monkeypatch):
    m = client_module()
    seen = mock_conversation(
        monkeypatch,
        [
            native_response("read_transactions", {"refs": ["r1"]}, "read_1"),
            native_response("read_transactions", {"refs": ["r1"]}, None),
            native_response("inspect_cashflow", {}, "inspect_3"),
        ],
    )
    agent = m.TyphoonReviewAgent(Config(api_key="private-key"))
    context = {"case_version": 1, "observations": [], "progress": {"calls_remaining": 8}}
    agent.choose(context, tools(), 5)
    first = {"tool": "read_transactions", "result": {"rows": [{"ref": "r1", "credit": "17"}]}}
    context["observations"].append(first)
    context["progress"]["calls_remaining"] = 7
    agent.choose(context, tools(), 5)
    # Historical snapshots must not change when the caller refreshes its context.
    context["progress"]["calls_remaining"] = 6
    repeated = {
        "tool": "read_transactions",
        "result": {"replayed": True, "rows": [{"ref": "r1", "credit": "17"}]},
    }
    context["observations"].append(repeated)
    before = deepcopy(context)
    agent.choose(context, tools(), 5)

    assert len(seen[0]["messages"]) == 2
    pairs = tool_pairs(seen[2])
    assert len(pairs) == 2
    assert pairs[0][0]["id"] == "read_1"
    assert pairs[0][0]["function"] == {"name": "read_transactions", "arguments": '{"refs": ["r1"]}'}
    assert pairs[0][1] == first
    assert pairs[1][0]["id"] and pairs[1][0]["id"] != "read_1"
    assert pairs[1][1] == repeated
    assert tool_pairs(seen[1])[0][1] == first
    assert json.loads(seen[1]["messages"][-1]["content"])["progress"] == {"calls_remaining": 7}
    assert context == before
    assert json.loads(seen[2]["messages"][-1]["content"]) == {**context, "observations": []}
    # Only the latest full context is kept; earlier turns contain compact receipts.
    assert sum('"case_version"' in (msg.get("content") or "") for msg in seen[2]["messages"]) == 1
    assert len(agent.call_records) == 3


def test_prompt_dedup_retains_unmatched_validation_feedback_and_full_current_context(monkeypatch):
    # Dropping all observations, or matching by value instead of receipt position,
    # loses controller feedback after an invalid provider response with no pending call.
    invalid = body()
    invalid["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{}"
    seen = mock_conversation(monkeypatch, [body(), invalid, body(), body()])
    agent = client_module().TyphoonReviewAgent(Config(api_key="private-key"))
    initial = {
        "tool": "read_transactions",
        "result": {"rows": [{"ref": "r1", "memo": "raw quote"}]},
    }
    context = {
        "review_scope": "same-case",
        "observations": [initial],
        "progress": {"calls_remaining": 8},
        "required_before_finish": ["inspect_cashflow"],
        "available_tools": ["compare_declarations", "inspect_cashflow"],
        "new_controller_field": {"nested": ["retain all non-observation data"]},
    }

    def choose_immutable():
        before = deepcopy(context)
        try:
            return agent.choose(context, tools(), 5)
        finally:
            assert context == before

    choose_immutable()
    feedback = {
        "tool": "action_validator",
        "result": {"status": "REJECTED", "error": "refs not observed"},
    }
    context["observations"].append(deepcopy(feedback))
    with pytest.raises(SandboxError, match="^typhoon_invalid_native_tool_response$"):
        choose_immutable()
    # Same value as a matched receipt, but this occurrence has no accepted call.
    context["observations"].append(deepcopy(feedback))
    context["progress"]["calls_remaining"] = 6
    choose_immutable()
    checked = {"tool": "compare_declarations", "result": {"status": "CHECKED", "claims": []}}
    context["observations"].append(checked)
    context["progress"]["calls_remaining"] = 5
    choose_immutable()

    assert json.loads(seen[0]["messages"][-1]["content"]) == {
        **context,
        "observations": [initial],
        "progress": {"calls_remaining": 8},
    }
    assert json.loads(seen[2]["messages"][-1]["content"]) == {
        **context,
        "observations": [initial, feedback],
        "progress": {"calls_remaining": 6},
    }
    assert json.loads(seen[3]["messages"][-1]["content"]) == {
        **context,
        "observations": [initial, feedback],
    }
    assert [result for _, result in tool_pairs(seen[3])] == [feedback, checked]
    assert [record["status"] for record in agent.call_records] == [
        "ACCEPTED",
        "REJECTED",
        "ACCEPTED",
        "ACCEPTED",
    ]


@pytest.mark.parametrize(
    "available", [["finish_review"], ["inspect_cashflow"], ["inspect_cashflow", "finish_review"]]
)
def test_only_sole_finish_tool_forces_native_function_choice(monkeypatch, available):
    name = available[0]
    arguments = {"reason": "ส่งคำถามที่ยังเปิดให้เจ้าหน้าที่"} if name == "finish_review" else {}
    seen = mock_response(monkeypatch, body(name, arguments))
    supplied = [tool for tool in tools() if tool["function"]["name"] in available]
    context = {"observations": [], "required_before_finish": []}
    before_context, before_tools = deepcopy(context), deepcopy(supplied)
    agent = client_module().TyphoonReviewAgent(Config(api_key="private-key"))
    action = agent.choose(context, supplied, 5)
    payload = seen[0][1]["json"]
    expected = (
        {"type": "function", "function": {"name": "finish_review"}}
        if available == ["finish_review"]
        else "required"
    )
    assert payload["tool_choice"] == expected
    assert payload["tools"] == before_tools
    assert payload["parallel_tool_calls"] is False
    assert payload["temperature"] == 0 and payload["max_tokens"] == 4000
    assert context == before_context and supplied == before_tools
    assert action["tool"] == name and action["arguments"] == arguments
    assert len(agent.call_records) == len(seen) == 1


@pytest.mark.parametrize(
    "variant",
    [
        "stop_text",
        "empty_stop",
        "missing_calls",
        "wrong_tool",
        "invalid_arguments",
        "extra_arguments",
        "multiple_calls",
    ],
)
def test_forced_finish_still_rejects_invalid_native_response_without_auto_finish(
    monkeypatch, variant
):
    response = body("finish_review", {"reason": "ส่งเจ้าหน้าที่พร้อมคำถามเปิด"})
    choice = response["choices"][0]
    message = choice["message"]
    if variant in {"stop_text", "empty_stop"}:
        choice["finish_reason"] = "stop"
        message["content"] = "Finished" if variant == "stop_text" else None
        message["tool_calls"] = []
    elif variant == "missing_calls":
        message.pop("tool_calls")
    elif variant == "wrong_tool":
        message["tool_calls"][0]["function"] = {"name": "inspect_cashflow", "arguments": "{}"}
    elif variant == "invalid_arguments":
        message["tool_calls"][0]["function"]["arguments"] = "{}"
    elif variant == "extra_arguments":
        message["tool_calls"][0]["function"]["arguments"] = '{"reason": "done", "approve": true}'
    else:
        message["tool_calls"] *= 2
    seen = mock_response(monkeypatch, response)
    agent = client_module().TyphoonReviewAgent(Config(api_key="private-key"))
    supplied = [tool for tool in tools() if tool["function"]["name"] == "finish_review"]
    with pytest.raises(SandboxError, match="^typhoon_invalid_native_tool_response$"):
        agent.choose({"observations": []}, supplied, 5)
    assert seen[0][1]["json"]["tool_choice"] == {
        "type": "function",
        "function": {"name": "finish_review"},
    }
    assert len(seen) == len(agent.call_records) == 1
    assert agent.call_records[0]["status"] == "REJECTED"
    assert "tool" not in agent.call_records[0]


def test_legacy_full_context_keeps_observations_and_auto_choice(monkeypatch):
    m = client_module()
    seen = mock_response(monkeypatch, body("statement_read", {"reason": "ตรวจหลักฐาน"}))
    observation = {
        "tool": "action_validator",
        "result": {"status": "REJECTED", "error": "retain legacy"},
    }
    context = {"observations": [observation], "progress": {"calls_remaining": 1}}
    case = {"fixture": "legacy full context"}
    # Only context construction and external HTTP are replaced; use the real
    # legacy planner and shared native payload builder/strict parser.
    monkeypatch.setattr(m, "full_context", lambda supplied_case: deepcopy(context))
    before = deepcopy(context)
    planner = m.ContextCompletePlanner(Config(api_key="private-key"))
    planner.choose(case, ["statement_read"])
    planner.choose(case, ["statement_read"])
    first, second = [request[1]["json"] for request in seen]
    assert first == second
    assert [message["role"] for message in second["messages"]] == ["system", "user"]
    assert json.loads(second["messages"][-1]["content"]) == before
    assert context == before and case == {"fixture": "legacy full context"}
    assert second["tool_choice"] == "auto"
    assert second["max_tokens"] == 400 and "parallel_tool_calls" not in second


def test_native_conversation_attaches_action_validator_error_to_rejected_call(monkeypatch):
    m = client_module()
    seen = mock_conversation(
        monkeypatch,
        [native_response("match_transfers", {"refs": ["r1", "r2"]}, "match_1"), body()],
    )
    agent = m.TyphoonReviewAgent(Config(api_key="private-key"))
    context = {"observations": []}
    agent.choose(context, tools(), 5)
    rejected = {
        "tool": "action_validator",
        "result": {"status": "REJECTED", "error": "refs not observed"},
    }
    context["observations"].append(rejected)
    agent.choose(context, tools(), 5)
    call, result = tool_pairs(seen[1])[0]
    assert call["id"] == "match_1" and call["function"]["name"] == "match_transfers"
    assert result == rejected


def test_invalid_native_response_does_not_leave_dangling_history(monkeypatch):
    m = client_module()
    invalid = body()
    invalid["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{}"
    seen = mock_conversation(monkeypatch, [body(), invalid, body()])
    agent = m.TyphoonReviewAgent(Config(api_key="private-key"))
    context = {"observations": []}
    agent.choose(context, tools(), 5)
    observation = {"tool": "compare_declarations", "result": {"status": "CHECKED"}}
    context["observations"].append(observation)
    with pytest.raises(SandboxError):
        agent.choose(context, tools(), 5)
    agent.choose(context, tools(), 5)
    assert len(tool_pairs(seen[2])) == 1
    assert tool_pairs(seen[2])[0][1] == observation
    assert [record["status"] for record in agent.call_records] == [
        "ACCEPTED",
        "REJECTED",
        "ACCEPTED",
    ]


def test_native_history_is_instance_local_and_cleared_on_scope_change(monkeypatch):
    m = client_module()
    seen = mock_conversation(monkeypatch, [body()] * 4)
    first = m.TyphoonReviewAgent(Config(api_key="private-key"))
    second = m.TyphoonReviewAgent(Config(api_key="private-key"))
    context = {"message_untrusted": "first merchant", "observations": []}
    first.choose(context, tools(), 5)
    context["observations"].append(
        {"tool": "compare_declarations", "result": {"marker": "first-only"}}
    )
    first.choose(context, tools(), 5)
    second.choose({"message_untrusted": "second merchant", "observations": []}, tools(), 5)
    first.choose({"message_untrusted": "third merchant", "observations": []}, tools(), 5)
    assert len(tool_pairs(seen[1])) == 1
    for payload in seen[2:]:
        assert len(payload["messages"]) == 2
        assert "first-only" not in json.dumps(payload)


@pytest.mark.parametrize("observations", [[], [{"tool": "inspect_cashflow", "result": {}}]])
def test_native_never_fabricates_a_missing_or_mismatched_tool_receipt(monkeypatch, observations):
    m = client_module()
    seen = mock_conversation(monkeypatch, [body(), body()])
    agent = m.TyphoonReviewAgent(Config(api_key="private-key"))
    agent.choose({"observations": []}, tools(), 5)
    with pytest.raises(SandboxError, match="observation"):
        agent.choose({"observations": observations}, tools(), 5)
    assert len(seen) == len(agent.call_records) == 1


def test_native_changed_observation_scope_discards_prior_case_history(monkeypatch):
    m = client_module()
    seen = mock_conversation(monkeypatch, [body()] * 3)
    agent = m.TyphoonReviewAgent(Config(api_key="private-key"))
    context = {
        "case_version": 1,
        "observations": [{"tool": "read_transactions", "result": {"ref": "old-only"}}],
    }
    agent.choose(context, tools(), 5)
    context["observations"].append(
        {"tool": "compare_declarations", "result": {"status": "CHECKED"}}
    )
    agent.choose(context, tools(), 5)
    agent.choose(
        {
            "case_version": 1,
            "observations": [{"tool": "read_transactions", "result": {"ref": "new-only"}}],
        },
        tools(),
        5,
    )
    assert len(tool_pairs(seen[1])) == 1
    assert len(seen[2]["messages"]) == 2
    assert "old-only" not in json.dumps(seen[2])


def test_native_conversation_stays_within_eight_http_attempts(monkeypatch):
    m = client_module()
    seen = mock_conversation(monkeypatch, [body()] * 9)
    agent = m.TyphoonReviewAgent(Config(api_key="private-key"))
    context = {"observations": []}
    for index in range(8):
        agent.choose(context, tools(), 5)
        context["observations"].append(
            {"tool": "compare_declarations", "result": {"replayed": index > 0}}
        )
    with pytest.raises(SandboxError, match="case_model_call_budget_reached"):
        agent.choose(context, tools(), 5)
    assert len(seen) == len(agent.call_records) == 8
    pairs = tool_pairs(seen[-1])
    assert len(pairs) == 7
    assert len({call["id"] for call, _ in pairs}) == 7
    assert all(result["result"]["replayed"] for _, result in pairs[1:])


def test_native_history_cannot_override_refreshed_tool_availability(monkeypatch):
    m = client_module()
    seen = mock_conversation(monkeypatch, [body()] * 2)
    agent = m.TyphoonReviewAgent(Config(api_key="private-key"))
    context = {"observations": []}
    agent.choose(context, tools(), 5)
    context["observations"].append(
        {"tool": "compare_declarations", "result": {"status": "CHECKED"}}
    )
    remaining = [tool for tool in tools() if tool["function"]["name"] == "inspect_cashflow"]
    with pytest.raises(SandboxError):
        agent.choose(context, remaining, 5)
    assert seen[1]["tools"] == remaining
    assert len(tool_pairs(seen[1])) == 1
    assert agent.call_records[-1]["status"] == "REJECTED"


@pytest.mark.parametrize("call_id", [17, "private-key", "x" * 201])
def test_invalid_native_call_ids_are_redacted_and_never_enter_history(monkeypatch, call_id):
    m = client_module()
    seen = mock_conversation(
        monkeypatch, [native_response("compare_declarations", {"claims": []}, call_id), body()]
    )
    agent = m.TyphoonReviewAgent(Config(api_key="private-key"))
    with pytest.raises(SandboxError) as exc:
        agent.choose({"observations": []}, tools(), 5)
    agent.choose({"observations": []}, tools(), 5)
    assert len(seen[1]["messages"]) == 2
    assert "private-key" not in str(exc.value) + json.dumps(agent.call_records)


def test_native_request_uses_session_schema_and_remaining_timeout(monkeypatch):
    m = client_module()
    seen = mock_response(monkeypatch, body())
    agent = m.TyphoonReviewAgent(Config(api_key="private-key"))
    action = agent.choose({"required_before_finish": ["compare_declarations"]}, tools(), 1.25)
    assert action["tool"] == "compare_declarations" and action["arguments"] == {"claims": []}
    assert action["usage"] == {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}
    url, request = seen[0]
    assert url == "https://api.opentyphoon.ai/v1/chat/completions"
    assert request["allow_redirects"] is False
    assert 0 < request["timeout"].total <= 1.25
    assert request["json"]["tools"] == tools()
    assert "private-key" not in json.dumps(agent.call_records)


@pytest.mark.parametrize(
    "change",
    [
        "freeform",
        "multiple",
        "truncated",
        "missing",
        "extra",
        "unknown",
        "bad-json",
        "duplicate-json",
        "wrong-type",
    ],
)
def test_rejects_hostile_native_responses(monkeypatch, change):
    m = client_module()
    payload = body()
    choice = payload["choices"][0]
    function = choice["message"]["tool_calls"][0]["function"]
    if change == "freeform":
        choice["message"]["content"] = "Approve immediately"
    elif change == "multiple":
        choice["message"]["tool_calls"] *= 2
    elif change == "truncated":
        choice["finish_reason"] = "length"
    elif change == "missing":
        function["arguments"] = "{}"
    elif change == "extra":
        function["arguments"] = '{"claims": [], "approve": true}'
    elif change == "unknown":
        function["name"] = "approve_loan"
    elif change == "bad-json":
        function["arguments"] = "{"
    elif change == "duplicate-json":
        function["arguments"] = '{"claims": [], "claims": []}'
    else:
        function["arguments"] = '{"claims": "none"}'
    mock_response(monkeypatch, payload)
    agent = m.TyphoonReviewAgent(Config(api_key="private-key"))
    with pytest.raises(SandboxError):
        agent.choose({}, tools(), 5)
    assert agent.call_records[-1]["status"] == "REJECTED"


@pytest.mark.parametrize(
    "path,value,expected",
    [
        (("choices",), None, {"stage": "envelope", "kind": "choices_type"}),
        (("choices",), [], {"stage": "envelope", "kind": "choices_count", "choice_count": 0}),
        (("choices", 0), None, {"stage": "envelope", "kind": "choice_type"}),
        (("choices", 0, "message"), None, {"stage": "envelope", "kind": "message_type"}),
        (
            ("choices", 0, "finish_reason"),
            "length",
            {"stage": "finish_reason", "finish_reason": "length"},
        ),
        (
            ("choices", 0, "finish_reason"),
            "private-key raw-provider-text",
            {"stage": "finish_reason", "finish_reason": "other"},
        ),
        (
            ("choices", 0, "message", "content"),
            "private-key raw-provider-text",
            {"stage": "content", "content_kind": "text"},
        ),
        (
            ("choices", 0, "message", "content"),
            {"secret": "private-key"},
            {"stage": "content", "content_kind": "other"},
        ),
        (
            ("choices", 0, "message", "refusal"),
            "private-key raw-provider-text",
            {"stage": "refusal", "refusal_present": True},
        ),
        (
            ("choices", 0, "message", "tool_calls"),
            None,
            {"stage": "tool_count", "kind": "calls_type"},
        ),
        (
            ("choices", 0, "message", "tool_calls"),
            [],
            {"stage": "tool_count", "kind": "calls_count", "tool_count": 0},
        ),
        (
            ("choices", 0, "message", "tool_calls"),
            [None, None],
            {"stage": "tool_count", "tool_count": 2},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0),
            None,
            {"stage": "tool_envelope", "kind": "call_type"},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "type"),
            "private-key",
            {"stage": "tool_envelope", "kind": "tool_type"},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "function"),
            None,
            {"stage": "tool_envelope", "kind": "function_type"},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "function", "name"),
            "private-key unknown-tool",
            {"stage": "unknown_tool", "kind": "unknown_name"},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "function", "name"),
            [],
            {"stage": "unknown_tool", "kind": "name_type"},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "function", "arguments"),
            {},
            {"stage": "arguments_json", "kind": "arguments_type"},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "function", "arguments"),
            '{"private-key":',
            {"stage": "arguments_json", "kind": "invalid_json"},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "function", "arguments"),
            '{"claims": [], "claims": [], "secret": "private-key"}',
            {"stage": "arguments_json", "kind": "duplicate_member"},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "function", "arguments"),
            '{"claims": NaN}',
            {"stage": "arguments_json", "kind": "nonfinite_constant"},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "function", "arguments"),
            '{"claims": [], "private-key": "raw-provider-text"}',
            {
                "stage": "schema_validation",
                "kind": "object_fields",
                "allowed_function": "compare_declarations",
            },
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "function", "arguments"),
            '{"claims": "private-key"}',
            {"stage": "schema_validation", "kind": "type"},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "function", "arguments"),
            '{"claims": [{"kind": "private-key", "value": "raw-provider-text", "quote": "sensitive-quote"}]}',
            {"stage": "schema_validation", "kind": "enum"},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "function", "arguments"),
            '{"claims": [{"kind": "monthly_revenue", "value": "", "quote": "private-key"}]}',
            {"stage": "schema_validation", "kind": "text_length"},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "function", "arguments"),
            json.dumps({"claims": ["private-key"] * 13}),
            {"stage": "schema_validation", "kind": "array_size"},
        ),
        (
            ("choices", 0, "message", "tool_calls", 0, "id"),
            "private-key",
            {"stage": "history", "kind": "invalid_call_id"},
        ),
    ],
)
def test_rejection_diagnostics_distinguish_stage_without_provider_data(
    monkeypatch, path, value, expected
):
    # Removing stage classification or copying a provider value must fail here.
    payload = body()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    payload["provider_extra"] = {"private-key": "raw-provider-text"}
    mock_response(monkeypatch, payload)
    receipts = []
    agent = client_module().TyphoonReviewAgent(
        Config(api_key="private-key"), on_record=receipts.append
    )
    with pytest.raises(SandboxError, match="^typhoon_invalid_native_tool_response$") as exc:
        agent.choose({}, tools(), 5)
    record = agent.call_records[-1]
    diagnostic = record["rejection"]
    assert expected.items() <= diagnostic.items()
    assert record["status"] == "REJECTED" and len(agent.call_records) == 1
    assert receipts == agent.call_records
    assert not {"tool", "arguments", "reason"} & record.keys()
    serialized = str(exc.value) + json.dumps(receipts)
    for secret in (
        "private-key",
        "raw-provider-text",
        "sensitive-quote",
        "unknown-tool",
        "provider_extra",
        "do-not-log",
    ):
        assert secret not in serialized


@pytest.mark.parametrize(
    "variant,expected",
    [
        ("body_type", {"stage": "envelope", "kind": "body_type"}),
        ("response_json", {"stage": "envelope", "kind": "response_json"}),
        ("response_size", {"stage": "envelope", "kind": "response_size"}),
    ],
)
def test_rejection_envelope_diagnostics_never_include_raw_body_or_exception(
    monkeypatch, variant, expected
):
    def response_json():
        if variant == "response_json":
            raise ValueError("private-key raw-response-body")
        return ["private-key raw-response-body"]

    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **kw: SimpleNamespace(
            status_code=200,
            content=b"private-key raw-response-body" * (10000 if variant == "response_size" else 1),
            json=response_json,
        ),
    )
    agent = client_module().TyphoonReviewAgent(Config(api_key="private-key"))
    with pytest.raises(SandboxError, match="^typhoon_invalid_native_tool_response$") as exc:
        agent.choose({}, tools(), 5)
    assert expected.items() <= agent.call_records[-1]["rejection"].items()
    assert "private-key" not in str(exc.value) + json.dumps(agent.call_records)
    assert "raw-response-body" not in str(exc.value) + json.dumps(agent.call_records)


def test_review_scope_token_prevents_history_bleed_for_identical_anonymized_cases(monkeypatch):
    seen = mock_conversation(monkeypatch, [body()] * 3)
    agent = client_module().TyphoonReviewAgent(Config(api_key="private-key"))
    context = {"review_scope": "opaque-case-one", "case_version": 1, "observations": []}
    agent.choose(context, tools(), 5)
    context["observations"].append(
        {"tool": "compare_declarations", "result": {"marker": "case-one-only"}}
    )
    agent.choose(context, tools(), 5)
    assert len(tool_pairs(seen[1])) == 1
    # The same visible scope and observation prefix must not retain the old pair.
    context["review_scope"] = "opaque-case-two"
    agent.choose(context, tools(), 5)
    assert len(seen[2]["messages"]) == 2
    assert not tool_pairs(seen[2])
    assert json.loads(seen[2]["messages"][-1]["content"]) == context
    assert "case-one-only" not in json.dumps(seen[2]["messages"][:-1])


def test_diagnostic_rejection_consumes_budget_without_retry_or_pending_history(monkeypatch):
    m = client_module()
    response = body()
    response["choices"][0]["finish_reason"] = "length"
    seen = mock_response(monkeypatch, response)
    budget = m.CallBudget(1)
    agent = m.TyphoonReviewAgent(Config(api_key="private-key"), budget=budget)
    with pytest.raises(SandboxError, match="^typhoon_invalid_native_tool_response$"):
        agent.choose({"observations": []}, tools(), 5)
    with pytest.raises(SandboxError, match="^total_model_call_budget_reached$"):
        agent.choose({"observations": []}, tools(), 5)
    assert len(seen) == len(agent.call_records) == budget.used == 1
    assert agent.call_records[0]["rejection"]["stage"] == "finish_reason"


def test_diagnostics_preserve_successful_action_and_record_schemas(monkeypatch):
    mock_response(monkeypatch, body())
    agent = client_module().TyphoonReviewAgent(Config(api_key="private-key"))
    action = agent.choose({}, tools(), 5)
    assert set(action) == {"tool", "arguments", "reason", "usage", "model", "duration_ms"}
    assert set(agent.call_records[0]) == {
        "kind",
        "attempt",
        "model",
        "usage",
        "status",
        "tool",
        "arguments",
        "reason",
        "duration_ms",
    }


def test_credential_rejection_diagnostic_does_not_retain_valid_arguments(monkeypatch):
    mock_response(monkeypatch, body("finish_review", {"reason": "private-key"}))
    agent = client_module().TyphoonReviewAgent(Config(api_key="private-key"))
    with pytest.raises(SandboxError, match="^typhoon_invalid_native_tool_response$"):
        agent.choose({}, tools(), 5)
    diagnostic = agent.call_records[0]["rejection"]
    assert diagnostic["stage"] == "credential_guard"
    assert diagnostic["kind"] == "secret_in_arguments"
    assert "private-key" not in json.dumps(agent.call_records)
    assert "arguments" not in agent.call_records[0]


def test_schema_diagnostic_never_copies_dynamic_schema_names_from_exception(monkeypatch):
    mock_response(monkeypatch, body())
    supplied_tools = tools()
    compare = next(t for t in supplied_tools if t["function"]["name"] == "compare_declarations")
    compare["function"]["parameters"] = {
        "type": "object",
        "required": ["private-key sensitive-schema-name"],
        "properties": {"private-key sensitive-schema-name": {"type": "string"}},
    }
    agent = client_module().TyphoonReviewAgent(Config(api_key="private-key"))
    with pytest.raises(SandboxError, match="^typhoon_invalid_native_tool_response$") as exc:
        agent.choose({}, supplied_tools, 5)
    assert agent.call_records[0]["rejection"]["kind"] == "object_fields"
    serialized = str(exc.value) + json.dumps(agent.call_records)
    assert "private-key" not in serialized and "sensitive-schema-name" not in serialized


@pytest.mark.parametrize(
    "url,model",
    [
        ("http://api.opentyphoon.ai/v1", Config.model),
        ("https://evil.test/v1", Config.model),
        ("https://api.opentyphoon.ai/v1?x=1", Config.model),
        (Config.base_url, "typhoon-other"),
    ],
)
def test_direct_config_cannot_bypass_official_endpoint(monkeypatch, url, model):
    m = client_module()
    seen = mock_response(monkeypatch, body())
    with pytest.raises(SandboxError):
        m.TyphoonReviewAgent(Config(api_key="key", base_url=url, model=model)).choose(
            {}, tools(), 5
        )
    assert seen == []


def test_network_error_is_redacted_and_counted_without_retry(monkeypatch):
    m = client_module()

    def fail(*args, **kwargs):
        raise requests.Timeout("private-key response-with-customer-data")

    monkeypatch.setattr(requests, "post", fail)
    agent = m.TyphoonReviewAgent(Config(api_key="private-key"))
    with pytest.raises(SandboxError) as exc:
        agent.choose({}, tools(), 2)
    assert "private-key" not in str(exc.value) + json.dumps(agent.call_records)
    assert "response-with-customer-data" not in str(exc.value) + json.dumps(agent.call_records)
    assert len(agent.call_records) == 1


def test_http_error_never_logs_body(monkeypatch):
    m = client_module()
    mock_response(monkeypatch, {"error": "private-key customer-record"}, status=302)
    agent = m.TyphoonReviewAgent(Config(api_key="private-key"))
    with pytest.raises(SandboxError) as exc:
        agent.choose({}, tools(), 5)
    assert "customer-record" not in str(exc.value) + json.dumps(agent.call_records)


def test_response_returned_after_deadline_is_not_an_executable_action(monkeypatch):
    m = client_module()
    clock = [0.0]
    monkeypatch.setattr(m, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def late(*args, **kwargs):
        clock[0] = 6.0
        payload = body()
        return SimpleNamespace(status_code=200, content=b"{}", json=lambda: payload)

    monkeypatch.setattr(requests, "post", late)
    agent = m.TyphoonReviewAgent(Config(api_key="key"))
    with pytest.raises(SandboxError, match="deadline"):
        agent.choose({}, tools(), 5)
    assert agent.call_records[-1]["status"] == "REJECTED"


def test_usage_rejects_strings_booleans_negative_counts_and_nested_text(monkeypatch):
    m = client_module()
    payload = body()
    payload["usage"] = {
        "prompt_tokens": True,
        "completion_tokens": "5",
        "total_tokens": -1,
        "error": "key",
    }
    mock_response(monkeypatch, payload)
    action = m.TyphoonReviewAgent(Config(api_key="key")).choose({}, tools(), 5)
    assert action["usage"] == {}


@pytest.mark.parametrize("remaining", [0, -1, float("inf"), float("nan")])
def test_invalid_remaining_budget_never_sends_http(monkeypatch, remaining):
    m = client_module()
    seen = mock_response(monkeypatch, body())
    with pytest.raises(SandboxError):
        m.TyphoonReviewAgent(Config(api_key="key")).choose({}, tools(), remaining)
    assert seen == []


@pytest.mark.historical_replay
def test_context_only_keeps_full_evidence_and_legacy_reason_schema(
    monkeypatch, historical_baseline
):
    m = client_module()
    seen = mock_response(monkeypatch, body("statement_read", {"reason": "ตรวจรายการจากหลักฐาน"}))
    case = json.loads((BASELINE / "C04/case.json").read_text(encoding="utf-8"))
    action = m.ContextCompletePlanner(Config(api_key="key")).choose(case, ["statement_read"])
    assert set(action) == {"tool", "reason", "usage", "duration_ms", "model"}
    payload = seen[0][1]["json"]
    context = json.loads(payload["messages"][1]["content"])
    assert context["observations"]["evidence"]["rows"]
    assert "Mali Jaidee" not in payload["messages"][1]["content"]
    assert "C04" not in payload["messages"][1]["content"]
    assert payload["tools"][0]["function"]["parameters"]["required"] == ["reason"]


@pytest.mark.historical_replay
def test_context_ablation_preserves_legacy_prompt_and_generation_settings(
    monkeypatch, historical_baseline
):
    m = client_module()
    from merchant_sandbox.typhoon import TyphoonPlanner

    seen = mock_response(monkeypatch, body("statement_read", {"reason": "ตรวจหลักฐาน"}))
    case = json.loads((BASELINE / "C04/case.json").read_text(encoding="utf-8"))
    cfg = Config(api_key="private-key")
    TyphoonPlanner(cfg).choose(case, ["statement_read"])
    m.ContextCompletePlanner(cfg).choose(case, ["statement_read"])
    legacy, complete = [item[1]["json"] for item in seen]
    assert legacy["messages"][0] == complete["messages"][0]
    for field in ("model", "temperature", "max_tokens", "stream", "tools", "tool_choice"):
        assert legacy[field] == complete[field]
    assert set(legacy) == set(complete)
    assert len(legacy["messages"]) == len(complete["messages"]) == 2


@pytest.mark.historical_replay
def test_legacy_context_only_never_accumulates_conversation(monkeypatch, historical_baseline):
    m = client_module()
    seen = mock_response(monkeypatch, body("statement_read", {"reason": "ตรวจหลักฐาน"}))
    case = json.loads((BASELINE / "C04/case.json").read_text(encoding="utf-8"))
    agent = m.ContextCompletePlanner(Config(api_key="private-key"))
    agent.choose(case, ["statement_read"])
    agent.choose(case, ["statement_read"])
    first, second = [request[1]["json"] for request in seen]
    assert first == second
    assert [message["role"] for message in second["messages"]] == ["system", "user"]


@pytest.mark.historical_replay
def test_baseline_loading_reads_metadata_and_raw_without_mutation(monkeypatch, historical_baseline):
    runner = runner_module()
    from hashlib import sha256

    path = BASELINE / "cases.sqlite3"
    before = sha256(path.read_bytes()).hexdigest()
    real_connect, opened = sqlite3.connect, []

    def connect(database_uri, **kwargs):
        opened.append((database_uri, kwargs))
        return real_connect(database_uri, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    case, docs, inputs = runner.load_baseline("C04")
    assert case["created_at"] == "2026-10-23T00:00:00+00:00"
    assert len(docs) == 3 and all(doc["metadata"]["ocr_pages"] for doc in docs)
    assert all(sha256(doc["raw"]).hexdigest() == doc["metadata"]["sha256"] for doc in docs)
    assert opened and all("mode=ro" in uri and kw["uri"] for uri, kw in opened)
    assert inputs and sha256(path.read_bytes()).hexdigest() == before


def test_runner_refuses_existing_or_outside_output_before_credentials(tmp_path, monkeypatch):
    runner = runner_module()
    existing = tmp_path / "existing"
    existing.mkdir()
    monkeypatch.setattr(
        runner.Config, "load", lambda *a: pytest.fail("credential read before preflight")
    )
    with pytest.raises((SystemExit, SandboxError)):
        runner.main(["--mode", "agentic", "--cases", "C04", "--output", str(existing)])
    with pytest.raises((SystemExit, SandboxError)):
        runner.main(["--mode", "agentic", "--cases", "C04", "--output", "C:/outside-repo/new-run"])


@pytest.mark.parametrize("mode", ["agentic", "context-only"])
@pytest.mark.historical_replay
def test_runner_end_to_end_mock_provider_preserves_source_and_ocr(
    experiment_path, monkeypatch, mode, historical_baseline
):
    runner = runner_module()
    from hashlib import sha256

    database = BASELINE / "cases.sqlite3"
    before = sha256(database.read_bytes()).hexdigest()
    requests_seen = []

    def post(url, **kwargs):
        payload = kwargs["json"]
        requests_seen.append(payload)
        available = [tool["function"]["name"] for tool in payload["tools"]]
        if mode == "context-only":
            response = body(available[0], {"reason": "ตรวจตามหลักฐานเพื่อส่งเจ้าหน้าที่"})
        else:
            context = json.loads(payload["messages"][-1]["content"])
            if not context["declarations_checked"]:
                response = body("compare_declarations", {"claims": []})
            elif not context["cashflow_current"]:
                response = body("inspect_cashflow", {})
            else:
                response = body("finish_review", {"reason": "ส่งเจ้าหน้าที่พิจารณาตามหลักฐาน"})
        return SimpleNamespace(
            status_code=200, content=json.dumps(response).encode(), json=lambda: response
        )

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(runner.Config, "load", lambda *a: Config(api_key="private-key"))
    output = experiment_path / mode
    runner.main(["--mode", mode, "--cases", "C01", "--output", str(output)])
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    case = json.loads((output / "C01/case.json").read_text(encoding="utf-8"))
    assert report["execution_mode"] == "LIVE_TYPHOON_LLM_REPLAYED_OCR_MOCK_ONBOARDING"
    assert report["llm_calls"] == len(requests_seen) > 0
    assert case["created_at"] == "2026-10-23T00:00:00+00:00"
    assert case["decision"] is None and case["active"] is False
    assert report["summary"] == {"PASS": 1, "PARTIAL": 0, "FAIL": 0}
    assert report["manifest"] and (output / "C01/events.jsonl").read_text(encoding="utf-8")
    assert all("image_url" not in json.dumps(p) for p in requests_seen)
    assert all("C01" not in p["messages"][-1]["content"] for p in requests_seen)
    assert sha256(database.read_bytes()).hexdigest() == before
    assert "private-key" not in (output / "report.json").read_text(encoding="utf-8")


@pytest.mark.historical_replay
def test_runner_keeps_failed_case_continues_and_respects_total_http_cap(
    experiment_path, monkeypatch, historical_baseline
):
    runner = runner_module()
    attempts = []

    def timeout(*args, **kwargs):
        attempts.append(1)
        raise requests.Timeout("private-key sensitive-provider-body")

    monkeypatch.setattr(requests, "post", timeout)
    monkeypatch.setattr(runner.Config, "load", lambda *a: Config(api_key="private-key"))
    output = experiment_path / "failed-bounded"
    report = runner.main(
        [
            "--mode",
            "agentic",
            "--cases",
            "C04,C06",
            "--output",
            str(output),
            "--max-total-calls",
            "1",
        ]
    )
    assert len(attempts) == report["llm_calls"] == 1
    assert report["summary"] == {"PASS": 0, "PARTIAL": 0, "FAIL": 2}
    for sid in ("C04", "C06"):
        case = json.loads((output / sid / "case.json").read_text(encoding="utf-8"))
        assert case["state"] == "TECHNICAL_REVIEW" and not case["active"]
        assert not case["results"].get("financial_calculate")
        receipt = (output / sid / "events.jsonl").read_text(encoding="utf-8")
        assert "private-key" not in receipt and "sensitive-provider-body" not in receipt
    assert (output / "C04/result.json").exists() and (output / "C06/result.json").exists()
