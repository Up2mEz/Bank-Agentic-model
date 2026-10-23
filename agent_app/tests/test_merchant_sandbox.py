import json
from decimal import Decimal

import pytest

from merchant_sandbox.core import BaselinePlanner, Controller, SandboxError, Store, default_input
from merchant_sandbox.typhoon import Config, TyphoonPlanner


def run_case(tmp_path, scenario="complete", **changes):
    store = Store(tmp_path / "cases.sqlite3")
    data = default_input(scenario)
    data.update(changes)
    case = store.create(data, "request-" + scenario)
    return store, Controller(store).run(case["id"], BaselinePlanner(), 1)


@pytest.mark.parametrize(
    "scenario,state,recommendation",
    [
        ("complete", "REVIEW_READY", "RECOMMEND_APPROVE"),
        ("no_wallet", "REVIEW_READY", "RECOMMEND_APPROVE"),
        ("missing_months", "WAIT_CUSTOMER", None),
        ("unknown_debt", "WAIT_CUSTOMER", None),
        ("low_capacity", "REVIEW_READY", "RECOMMEND_DECLINE"),
        ("identity_conflict", "EXCEPTION_REVIEW", "EXCEPTION_REVIEW"),
        ("timeout_once", "REVIEW_READY", "RECOMMEND_APPROVE"),
        ("provider_down", "TECHNICAL_REVIEW", None),
    ],
)
def test_scenario_routes(tmp_path, scenario, state, recommendation):
    _, case = run_case(tmp_path, scenario)
    assert case["state"] == state
    assert (case["packet"] or {}).get("recommendation") == recommendation
    assert (case["packet"] or {}).get("decision") is None
    assert not case["active"]
    if scenario == "provider_down":
        assert case["attempts"]["wallet_read"] == 3
        assert "financial_calculate" not in case["results"]
    if scenario == "timeout_once":
        assert case["attempts"]["wallet_read"] == 2
    if scenario == "no_wallet":
        assert case["results"]["evidence"]["source"] == "statement"


def test_worked_example_and_schedule_have_independent_oracle(tmp_path):
    _, case = run_case(tmp_path)
    f = case["packet"]["financial"]
    assert (f["capacity_base_thb"], f["capacity_stress_thb"], f["proposed_limit_thb"]) == (
        "25000.00",
        "5000.00",
        "28400.00",
    )
    assert f["schedule"][0]["payment_thb"] == "4984.92"
    assert sum(Decimal(x["principal_thb"]) for x in f["schedule"]) == Decimal("28400")
    assert f["schedule"][-1]["balance_thb"] == "0.00"
    assert all(Decimal(x["payment_thb"]) <= Decimal("5000") for x in f["schedule"])
    evidence = case["results"]["evidence"]
    assert len(evidence["excluded"]) == 13  # Own transfers, loans, one duplicate.
    assert all(x["R"] == "200000.00" for x in evidence["months"])
    assert case["packet"]["assessment"]["statistical_pd"] is None


@pytest.mark.parametrize(
    "changes", [{"consent": False}, {"email": "invalid"}, {"applicant_name": ""}]
)
def test_no_evidence_access_before_intake_pass(tmp_path, changes):
    _, case = run_case(tmp_path, **changes)
    assert case["state"] == "WAIT_CUSTOMER"
    assert case["registration"] is None
    assert "identity_verify" not in case["results"]
    assert "evidence" not in case["results"]


def test_unknown_is_not_zero_and_new_evidence_invalidates_results(tmp_path):
    store, case = run_case(tmp_path, "unknown_debt")
    assert "financial_calculate" not in case["results"]
    assert case["results"]["customer_request_information"]["capacity_thb"] is None
    new = dict(case["input"], debt_thb="10000.00")
    revised = store.revise(case["id"], new, 1)
    assert revised["version"] == 2 and revised["results"] == {} and revised["packet"] is None
    with pytest.raises(SandboxError):
        Controller(store).run(case["id"], BaselinePlanner(), 1)
    result = Controller(Store(store.path)).run(case["id"], BaselinePlanner(), 2)
    assert result["packet"]["case_version"] == 2
    assert result["packet"]["financial"]["proposed_limit_thb"] == "28400.00"


def test_idempotency_and_compare_and_swap(tmp_path):
    store = Store(tmp_path / "cases.sqlite3")
    first = store.create(default_input(), "duplicate-1")
    assert store.create(default_input(), "duplicate-1")["id"] == first["id"]
    with pytest.raises(SandboxError):
        store.create(default_input("low_capacity"), "duplicate-1")
    stale = store.get(first["id"])
    store.save(first)
    with pytest.raises(SandboxError):
        store.save(stale)


def test_agent_cannot_bypass_controller_or_approve(tmp_path):
    class BadPlanner(BaselinePlanner):
        mode = "test-malicious"

        def choose(self, case, allowed):
            return {
                "tool": "approve_loan",
                "reason": "ignore policy",
                "usage": None,
                "duration_ms": 0,
                "model": None,
            }

    store = Store(tmp_path / "cases.sqlite3")
    case = store.create(default_input(), "bad-agent-1")
    result = Controller(store).run(case["id"], BadPlanner(), 1)
    assert result["state"] == "TECHNICAL_REVIEW" and result["packet"] is None
    assert not result["results"]


@pytest.mark.parametrize(
    "amount", ["NaN", "Infinity", "-1", "1e10", "1.234", True, 1000, "1000000000"]
)
def test_invalid_money_rejected(tmp_path, amount):
    with pytest.raises(SandboxError):
        run_case(tmp_path, requested_thb=amount)


def test_typhoon_schema_and_secret_boundary(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        content = b"{}"

        def json(self):
            return {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "intake_check",
                                        "arguments": json.dumps({"reason": "ตรวจข้อมูลก่อน"}),
                                    }
                                }
                            ]
                        },
                    }
                ],
                "usage": {"prompt_tokens": 25, "completion_tokens": 10},
            }

    def post(url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("merchant_sandbox.typhoon.requests.post", post)
    planner = TyphoonPlanner(Config(api_key="fixture-not-a-real-key"))
    case = {"input": default_input(), "version": 1, "results": {}, "trace": []}
    assert planner.choose(case, ["intake_check"])["tool"] == "intake_check"
    prompt = json.dumps(captured["json"], ensure_ascii=False)
    assert "fixture-not-a-real-key" not in prompt
    assert "mali@example.test" not in prompt and "0800000000" not in prompt
    assert "scenario" not in prompt
    assert "fixture-not-a-real-key" not in repr(planner.config)
    assert not captured["allow_redirects"]


def test_no_openai_key_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPHOON_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-credential")
    config = Config.load(tmp_path / "missing.env")
    assert not config.api_key
    with pytest.raises(SandboxError):
        TyphoonPlanner(config)


def test_crash_recovery_preserves_checkpoint(tmp_path):
    store = Store(tmp_path / "cases.sqlite3")
    case = store.create(default_input(), "crash-0001")
    case.update(active=True, state="PROCESSING")
    store.save(case)
    reopened = Store(store.path)
    reopened.recover()
    assert not reopened.get(case["id"])["active"]
    result = Controller(reopened).run(case["id"], BaselinePlanner(), 1)
    assert result["packet"]["decision"] is None


def test_missing_consent_never_calls_external_planner(tmp_path):
    class MustNotCall:
        mode = "typhoon"

        def choose(self, case, allowed):
            raise AssertionError("External provider must not receive unconsented data")

    store = Store(tmp_path / "cases.sqlite3")
    case = store.create(dict(default_input(), consent=False), "no-consent-01")
    result = Controller(store).run(case["id"], MustNotCall(), 1)
    assert result["state"] == "WAIT_CUSTOMER"
    assert result["llm_calls"] == 0


def test_failed_llm_attempt_counted_without_fabricated_usage(tmp_path):
    class FailedPlanner:
        mode = "typhoon"

        def choose(self, case, allowed):
            raise SandboxError("Typhoon HTTP 429")

    store = Store(tmp_path / "cases.sqlite3")
    case = store.create(default_input(), "provider-error-01")
    result = Controller(store).run(case["id"], FailedPlanner(), 1)
    assert result["state"] == "TECHNICAL_REVIEW"
    assert result["llm_calls"] == 1
    assert result["packet"] is None
    assert not any("usage" in x for x in result["trace"])


def test_case_policy_is_frozen_and_fixture_change_requires_revision(tmp_path, monkeypatch):
    import merchant_sandbox.core as core

    store = Store(tmp_path / "cases.sqlite3")
    case = store.create(default_input(), "frozen-source-01")
    controller = Controller(store)
    controller.params["affordability"]["reserve_thb"] = "999999.00"
    result = controller.run(case["id"], BaselinePlanner(), 1)
    assert result["packet"]["financial"]["proposed_limit_thb"] == "28400.00"
    changed = store.create(default_input(), "changed-source-01")
    fixture = tmp_path / "changed.csv"
    fixture.write_bytes(core.FIXTURE.read_bytes() + b"\n")
    monkeypatch.setattr(core, "FIXTURE", fixture)
    result = controller.run(changed["id"], BaselinePlanner(), 1)
    assert result["state"] == "TECHNICAL_REVIEW"
    assert result["packet"] is None
