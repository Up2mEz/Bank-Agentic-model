"""Offline public trace and bounded context contract for the four-part experiment."""

import importlib.util
from copy import deepcopy

import pytest


def module():
    assert importlib.util.find_spec("merchant_sandbox.statement_experiment"), (
        "Experiment trace wrapper missing"
    )
    from merchant_sandbox import statement_experiment

    return statement_experiment


class FakeAgent:
    mode = "typhoon"

    def __init__(self):
        self.call_records = []
        self.received = []

    def choose(self, context, tools, timeout_seconds):
        self.received.append(deepcopy((context, tools)))
        self.call_records.append(
            {
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                "status": "ACCEPTED",
            }
        )
        return {
            "tool": "compare_declarations",
            "arguments": {
                "claims": [
                    {
                        "kind": "business_account",
                        "value": "ACC-1 and OWN-B",
                        "quote": "two accounts ACC-1 and OWN-B",
                    }
                ]
            },
            "reason": "native tool choice",
            "model": "offline",
        }


def test_choice_arguments_survive_controller_rejection_without_mutating_context():
    m = module()
    inner = FakeAgent()
    agent = m.TracedAgent(inner, max_total_tokens=50000)
    context = {
        "message_untrusted": "two accounts ACC-1 and OWN-B",
        "observations": [],
        "progress": {"model_calls_used": 0},
    }
    original = deepcopy(context)
    choice = agent.choose(context, [], 10)
    # The real controller can reject this choice later; the returned fields must remain auditable.
    choice["arguments"]["claims"].clear()
    assert agent.choices[0]["arguments"]["claims"][0]["value"] == "ACC-1 and OWN-B"
    assert context == original
    assert inner.received[0][0]["review_contract"]["raw_material_classification_required"] is False
    assert agent.call_records == inner.call_records


def test_trace_context_uses_caller_whitelist_and_has_no_evaluation_oracle():
    m = module()
    inner = FakeAgent()
    agent = m.TracedAgent(inner, max_total_tokens=50000)
    with pytest.raises(ValueError, match="evaluation"):
        agent.choose({"expected": {"answer": "secret-test-oracle"}}, [], 10)
    assert not inner.received and not agent.contexts


def test_unknown_transport_spend_blocks_following_request():
    m = module()
    from merchant_sandbox.core import SandboxError

    inner = FakeAgent()
    agent = m.TracedAgent(inner, max_total_tokens=50000)
    inner.call_records.append({"usage": None, "status": "REJECTED"})
    with pytest.raises(SandboxError, match="usage_unknown"):
        agent.choose({}, [], 10)
    assert not inner.received


def test_token_reservation_stops_before_http_not_after_spending():
    m = module()
    from merchant_sandbox.core import SandboxError

    inner = FakeAgent()
    agent = m.TracedAgent(inner, max_total_tokens=100)
    with pytest.raises(SandboxError, match="token_budget"):
        agent.choose({"observations": []}, [], 10)
    assert not inner.received


def test_claim_schema_clarifies_one_account_without_changing_allowed_fields():
    m = module()
    from merchant_sandbox.agentic_review import TOOL_SPECS

    schema = deepcopy(TOOL_SPECS["compare_declarations"][1])
    tools = [
        {
            "type": "function",
            "function": {
                "name": "compare_declarations",
                "description": "extract",
                "parameters": schema,
            },
        }
    ]
    original = deepcopy(tools)
    inner = FakeAgent()
    agent = m.TracedAgent(inner, max_total_tokens=50000)
    agent.choose({}, tools, 10)
    sent = inner.received[0][1][0]["function"]["parameters"]
    assert tools == original
    value = sent["properties"]["claims"]["items"]["properties"]["value"]
    assert "ONE account" in value["description"]
    assert sent["required"] == schema["required"]


def test_document_context_exposes_period_and_continuity_without_names_or_oracle():
    m = module()
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "agent_app/tools/statement_report_fixtures.py"
    spec = importlib.util.spec_from_file_location("report_fixture_probe", path)
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    fixture = fixtures.build_cases()["S01"]
    facts = m.statement_context(fixture["case"], fixture["documents"])
    assert facts["documents"][1]["holder_matches_applicant"] is False
    assert facts["documents"][1]["period_end"] == "2026-09-29"
    assert facts["continuity_checks"][0]["difference_thb"] == "-165000.00"
    assert facts["continuity_checks"][0]["matches"] is False
    import json

    exported = json.dumps(facts)
    assert "Mali Jaidee" not in exported and "Other Person" not in exported
    assert "expected" not in facts and facts["authenticity"] == "UNVERIFIED"


def test_supplied_document_facts_are_copied_into_actual_model_context():
    m = module()
    facts = {"authenticity": "UNVERIFIED", "documents": [{"document_id": "A"}]}
    inner = FakeAgent()
    agent = m.TracedAgent(inner, max_total_tokens=50000, evidence_context=facts)
    facts["documents"].clear()
    agent.choose({}, [], 10)
    assert inner.received[0][0]["statement_document_facts"]["documents"] == [{"document_id": "A"}]
