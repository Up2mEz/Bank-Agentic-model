"""Focused final review regressions; real local stores, no listeners or providers."""

import json
import uuid
from copy import deepcopy
from io import BytesIO

import pytest
from test_onboarding_review import command
from test_onboarding_review import ready as ready

from merchant_sandbox import server
from merchant_sandbox.core import BaselinePlanner, MutationError, Store
from merchant_sandbox.review import Reviews


@pytest.mark.parametrize(
    "original,current",
    [
        ("original-kyc-session", "new-kyc-session"),
        (None, "new-kyc-session"),
        ("original-kyc-session", None),
        ("", ""),
    ],
)
def test_approval_rejects_changed_or_missing_kyc_binding(ready, original, current):
    store, docs, bank, _, case = ready
    case["results"]["onboarding_read"]["snapshot"]["kyc"]["session_id"] = original
    case["packet"]["onboarding"] = deepcopy(case["results"]["onboarding_read"])
    store.save(case)
    bank.snapshot["kyc"]["session_id"] = current
    bank.snapshot["version"] = 9
    with pytest.raises(MutationError):
        Reviews(store, docs, bank).decide(case["id"], {**command(case), "onboarding_version": 9})
    assert store.get(case["id"]).get("decision") is None


def test_new_analysis_binds_new_session_and_can_be_approved(ready):
    store, docs, bank, controller, case = ready
    bank.snapshot["kyc"]["session_id"] = "new-kyc-session"
    bank.snapshot["version"] = 9
    revised = store.revise(case["id"], case["input"], case["version"])
    analyzed = controller.run(case["id"], BaselinePlanner(), revised["version"])
    result = Reviews(store, docs, bank).decide(
        case["id"], {**command(analyzed), "onboarding_version": 9}
    )
    assert result["decision"]["amount_thb"] == "28400.00"
    assert (
        result["history"][-1]["results"]["onboarding_read"]["snapshot"]["kyc"]["session_id"]
        == "original-kyc-session"
    )


def test_create_receipt_resolution_is_owner_bound_and_read_only(ready):
    store, docs, bank, _, case = ready
    # Original create key from the shared fixture. Latest projection can differ.
    case["state"] = "TECHNICAL_REVIEW"
    store.save(case)
    recovered = Store(store.path).replay_create(
        case["input"], "create-ready-123", owner_id=case["owner_id"]
    )
    assert recovered["id"] == case["id"] and recovered["state"] == "TECHNICAL_REVIEW"
    with pytest.raises(MutationError) as mismatch:
        store.replay_create(
            {**case["input"], "message": "different"}, "create-ready-123", owner_id=case["owner_id"]
        )
    assert (mismatch.value.status, mismatch.value.code) == (422, "idempotency_key_reused")
    assert store.replay_create(case["input"], "new-create-123", owner_id=case["owner_id"]) is None
    assert (
        store.replay_create(case["input"], "create-ready-123", owner_id=str(uuid.uuid4())) is None
    )
    assert len(store.list()) == 1


def test_submit_receipt_resolution_has_no_dispatch_or_mutation(ready):
    store, docs, bank, _, case = ready
    revised = store.revise(case["id"], case["input"], case["version"])
    reviews = Reviews(store, docs, bank)
    claimed, dispatch = reviews.accept_submit(
        case["id"], revised["version"], idempotency_key="accepted-submit-123"
    )
    assert dispatch
    store.recover()
    before = store.get(case["id"])
    assert (
        store.replay(before, "submit", {"version": revised["version"]}, "accepted-submit-123")[
            "state"
        ]
        == "TECHNICAL_REVIEW"
    )
    with pytest.raises(MutationError) as mismatch:
        store.replay(before, "submit", {"version": 999}, "accepted-submit-123")
    assert mismatch.value.status == 422
    assert store.replay(before, "submit", {"version": revised["version"]}, "new-submit-123") is None
    assert (
        store.replay(before, "decision", {"version": revised["version"]}, "accepted-submit-123")
        is None
    )
    assert store.get(case["id"]) == before


def test_internal_replay_routes_auth_owner_mismatch_and_no_worker(ready, tmp_path, monkeypatch):
    store, docs, bank, _, case = ready
    captured = {}

    class NoListener:
        def __init__(self, address, handler):
            captured["handler"] = handler

        def serve_forever(self):
            pass

        def server_close(self):
            pass

    token_file = tmp_path / "bridge.key"
    token_file.write_text("s" * 40)
    monkeypatch.setattr(server, "ThreadingHTTPServer", NoListener)
    monkeypatch.setattr(
        "sys.argv", ["server", "--db", str(store.path), "--bridge-token-file", str(token_file)]
    )
    server.main()  # Captures the real handler; never constructs a socket/listener.

    def call(path, data, *, owner=case["owner_id"], token="s" * 40):
        h = object.__new__(captured["handler"])
        raw = json.dumps(data).encode()
        h.path = path
        h.headers = {
            "Host": "127.0.0.1:8765",
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
            "Authorization": "Bearer " + token,
            "X-Customer-ID": owner,
        }
        h.rfile = BytesIO(raw)
        response = []
        h.send = lambda status, body, *args: response.append((status, body))
        h.do_POST()
        return response[0]

    data = deepcopy(case["input"])
    data.pop("scenario")
    body = {"input": data, "idempotency_key": "create-ready-123"}
    base = "/internal/lending/cases"
    before = store.get(case["id"])
    status, result = call(base + "/replay", body)
    assert status == 200 and result["id"] == case["id"]
    assert "owner_id" not in result and "trace" not in result
    assert call(base + "/replay", body, token="invalid")[0] == 401
    assert call(base + "/replay", body, owner=str(uuid.uuid4()))[0] == 404
    assert call(base + "/replay", {**body, "idempotency_key": "unseen-key-123"})[0] == 404
    status, mismatch = call(base + "/replay", {**body, "input": {**data, "message": "different"}})
    assert status == 422 and mismatch["code"] == "idempotency_key_reused"
    # Submit uses its original receipt; a read-only resolution cannot launch a thread.
    revised = store.revise(case["id"], case["input"], case["version"])
    reviews = Reviews(store, docs, bank)
    reviews.accept_submit(case["id"], revised["version"], idempotency_key="submit-route-123")
    store.recover()
    submit_path = base + "/" + case["id"] + "/submit/replay"
    submit = {"version": revised["version"], "idempotency_key": "submit-route-123"}

    def forbidden(*args, **kwargs):
        raise AssertionError("replay tried to mutate or dispatch")

    monkeypatch.setattr(server.threading, "Thread", forbidden)
    monkeypatch.setattr(Reviews, "accept_submit", forbidden)
    monkeypatch.setattr(Store, "create", forbidden)
    before = store.get(case["id"])
    status, result = call(submit_path, submit)
    assert status == 200 and result["state"] == "TECHNICAL_REVIEW"
    assert call(submit_path, submit, owner=str(uuid.uuid4()))[0] == 404
    assert call(submit_path, {**submit, "version": 999})[0] == 422
    assert call(submit_path, {**submit, "idempotency_key": "new-submit-123"})[0] == 404
    assert call(base + "/" + case["id"] + "/revise/replay", submit)[0] == 404
    assert store.get(case["id"]) == before
