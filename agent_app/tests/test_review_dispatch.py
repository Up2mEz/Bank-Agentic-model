"""Claim/CAS/receipt regressions against the real persisted offline service."""

import importlib
import importlib.util
import uuid
from copy import deepcopy

import pytest
from test_lending_documents import attach

from merchant_sandbox.bank import BankOnboardingClient
from merchant_sandbox.core import SandboxError, Store, default_input
from merchant_sandbox.lending import Documents
from merchant_sandbox.review import Reviews
from merchant_sandbox.review_gateway import ReviewGateway, sample_ocr
from merchant_sandbox.review_service import ReviewService


def dispatcher_module():
    assert importlib.util.find_spec("merchant_sandbox.review_dispatch"), (
        "Evidence dispatcher missing"
    )
    return importlib.import_module("merchant_sandbox.review_dispatch")


@pytest.fixture
def claimed(tmp_path):
    store = Store(tmp_path / "cases.sqlite3")
    docs = Documents(store)
    case = store.create(default_input(), "dispatch-create-001", owner_id=str(uuid.uuid4()))
    case, _ = attach(docs, case)
    doc = docs.list(case)[0]
    # Explicit synthetic fixture preparation; runtime must never assign this to real uploads.
    doc["ocr_pages"] = sample_ocr(doc)
    docs.save_ocr(doc)
    reviews = Reviews(store, docs, BankOnboardingClient())
    case, dispatched = reviews.accept_submit(
        case["id"], case["version"], idempotency_key="dispatch-submit-001"
    )
    assert dispatched
    return store, docs, reviews, case


def connect(monkeypatch, service, *, after_submit=None):
    gateway = ReviewGateway("http://127.0.0.1:1", "synthetic-test-credential-" + "x" * 32)
    calls = []

    def request(method, path, body=None):
        calls.append((method, path, deepcopy(body)))
        if method == "POST" and path == "/v1/reviews":
            job = service.submit(body)
            if after_submit:
                after_submit(job)
            return job
        assert method == "GET" and path.startswith("/v1/reviews/")
        service.process_next()
        return service.get(path.rsplit("/", 1)[1])

    monkeypatch.setattr(gateway, "request", request)
    return gateway, calls


def test_accepted_submit_replay_dispatches_once_and_evidence_cannot_approve(
    claimed, tmp_path, monkeypatch
):
    m = dispatcher_module()
    store, docs, reviews, case = claimed
    with ReviewService(tmp_path / "reviews.sqlite3") as service:
        gateway, calls = connect(monkeypatch, service)
        m.ReviewDispatcher(store, docs, gateway, mode="offline", poll_interval=0).run(case)
        completed = store.get(case["id"])
        assert completed["state"] == "EXCEPTION_REVIEW" and not completed["active"]
        assert completed.get("decision") is None
        packet = completed["packet"]
        assert packet["financial"] is None and packet["assessment"] is None
        assert packet["decision"] is None and packet["human_final_decision_required"] is True
        assert packet["recommendation"] == "EXCEPTION_REVIEW"
        assert packet["case_version"] == case["version"] and packet["snapshot"] == case["snapshot"]
        assert completed["results"]["evidence_review"]["status"] == "COMPLETED"
        assert completed["feedback"]
        replay, dispatch = reviews.accept_submit(
            case["id"], case["version"], idempotency_key="dispatch-submit-001"
        )
        assert not dispatch and replay == completed
        m.ReviewDispatcher(store, docs, gateway, mode="offline", poll_interval=0).run(case)
        assert len([c for c in calls if c[0] == "POST"]) == 1
        assert all(
            c[1] == "/v1/reviews/" + service.latest(case["id"])["id"]
            for c in calls
            if c[0] == "GET"
        )
        # Make the bank reachable: the unchanged financial completeness guard must reject evidence.
        from test_onboarding_review import Bank, command

        reviews.bank = Bank(case["owner_id"])
        with pytest.raises(SandboxError):
            reviews.decide(case["id"], command(completed))
        assert store.get(case["id"]).get("decision") is None


@pytest.mark.parametrize("failure", ["FAILED", "INTERRUPTED", "TECHNICAL_REVIEW"])
def test_failure_and_native_technical_state_are_visible_not_success(
    claimed, tmp_path, monkeypatch, failure
):
    m = dispatcher_module()
    store, docs, _, case = claimed

    def runner(payload):
        if failure == "FAILED":
            raise RuntimeError("private provider response must not reach feedback")
        return {
            "report": {"decision": None},
            "trace": [],
            "usage": {},
            "review_state": "TECHNICAL_REVIEW",
            "decision": None,
            "human_final_decision_required": True,
        }

    with ReviewService(tmp_path / "reviews.sqlite3", runner=runner) as service:
        gateway, _ = connect(monkeypatch, service)
        if failure == "INTERRUPTED":
            original = gateway.request

            def interrupted(method, path, body=None):
                job = original(method, path, body)
                return {**job, "status": "INTERRUPTED", "result": None} if method == "GET" else job

            monkeypatch.setattr(gateway, "request", interrupted)
        m.ReviewDispatcher(store, docs, gateway, mode="offline", poll_interval=0).run(case)
    current = store.get(case["id"])
    assert current["state"] == "TECHNICAL_REVIEW" and not current["active"]
    assert current.get("decision") is None and current["feedback"]
    assert current["packet"] is None or current["packet"]["financial"] is None
    assert "private provider" not in str(current)


@pytest.mark.parametrize("conflict", ["version", "human", "before_submit"])
def test_claim_cas_never_overwrites_newer_input_or_human_result(
    claimed, tmp_path, monkeypatch, conflict
):
    m = dispatcher_module()
    store, docs, _, case = claimed
    newer = None

    def change(_job=None):
        nonlocal newer
        newer = store.get(case["id"])
        newer["active"] = False
        if conflict == "human":
            newer.update(state="DECLINED", decision={"status": "DECLINED", "reason": "human"})
        else:
            newer["version"] += 1
            newer["input"]["message"] = "new input must survive"
        store.save(newer)

    with ReviewService(tmp_path / "reviews.sqlite3") as service:
        gateway, calls = connect(monkeypatch, service, after_submit=change)
        if conflict == "before_submit":
            change()
        m.ReviewDispatcher(store, docs, gateway, mode="offline", poll_interval=0).run(case)
        assert store.get(case["id"]) == newer
        if conflict == "before_submit":
            assert calls == []


def test_uncertain_transport_preserves_exact_key_receipt_and_no_restart_retry(
    claimed, tmp_path, monkeypatch
):
    m = dispatcher_module()
    store, docs, reviews, case = claimed
    with ReviewService(tmp_path / "reviews.sqlite3") as service:

        def lose_response(job):
            raise SandboxError("transport uncertain")

        gateway, calls = connect(monkeypatch, service, after_submit=lose_response)
        key = m.claim_key(case, "offline")
        assert key == m.claim_key(deepcopy(case), "offline")
        m.ReviewDispatcher(store, docs, gateway, mode="offline", poll_interval=0).run(case)
        current = store.get(case["id"])
        assert current["state"] == "TECHNICAL_REVIEW"
        assert current["results"]["evidence_review"]["idempotency_key"] == key
        assert "key ใหม่" not in str(current["feedback"])
        assert calls[0][2]["idempotency_key"] == key
        accepted = service.latest(case["id"])
        assert service.submit(calls[0][2])["id"] == accepted["id"]
        store.recover()
        replay, dispatch = reviews.accept_submit(
            case["id"], case["version"], idempotency_key="dispatch-submit-001"
        )
        assert not dispatch and replay["results"]["evidence_review"]["idempotency_key"] == key
        assert len(calls) == 1


def test_poll_bound_keeps_exact_job_for_manual_recovery(claimed, tmp_path, monkeypatch):
    m = dispatcher_module()
    store, docs, _, case = claimed
    with ReviewService(tmp_path / "reviews.sqlite3") as service:
        gateway, calls = connect(monkeypatch, service)
        original = gateway.request

        def queued(method, path, body=None):
            return (
                service.get(path.rsplit("/", 1)[1])
                if method == "GET"
                else original(method, path, body)
            )

        monkeypatch.setattr(gateway, "request", queued)
        m.ReviewDispatcher(store, docs, gateway, mode="offline", poll_interval=0, max_polls=2).run(
            case
        )
        current = store.get(case["id"])
        assert current["state"] == "TECHNICAL_REVIEW"
        assert current["results"]["evidence_review"]["job_id"] == service.latest(case["id"])["id"]
        assert len(calls) == 1


def test_final_store_cas_race_preserves_human_result(claimed, tmp_path, monkeypatch):
    m = dispatcher_module()
    store, docs, _, case = claimed
    original_save = store.save
    human = None

    def race_at_final_save(candidate):
        nonlocal human
        if candidate["state"] == "EXCEPTION_REVIEW":
            human = store.get(case["id"])
            human.update(
                active=False,
                state="DECLINED",
                decision={"status": "DECLINED", "reason": "human race winner"},
            )
            original_save(human)
        return original_save(candidate)

    monkeypatch.setattr(store, "save", race_at_final_save)
    with ReviewService(tmp_path / "reviews.sqlite3") as service:
        gateway, _ = connect(monkeypatch, service)
        m.ReviewDispatcher(store, docs, gateway, mode="offline", poll_interval=0).run(case)
    assert human is not None
    assert store.get(case["id"]) == human


@pytest.mark.parametrize("loss", ["submit", "poll", "bound"])
def test_unresolved_receipt_blocks_fresh_submit_and_explicit_recovery_replays_exact_body(
    claimed, tmp_path, monkeypatch, loss
):
    m = dispatcher_module()
    store, docs, reviews, case = claimed
    with ReviewService(tmp_path / "reviews.sqlite3") as service:
        gateway, calls = connect(monkeypatch, service)
        original = gateway.request

        def uncertain(method, path, body=None):
            if method == "GET":
                if loss == "poll":
                    raise SandboxError("synthetic lost poll")
                return service.get(path.rsplit("/", 1)[1])
            job = original(method, path, body)
            if loss == "submit":
                raise SandboxError("synthetic committed then lost response")
            return job

        monkeypatch.setattr(gateway, "request", uncertain)
        dispatcher = m.ReviewDispatcher(
            store, docs, gateway, mode="offline", poll_interval=0, max_polls=1
        )
        dispatcher.run(case)
        prior = store.get(case["id"])
        with pytest.raises(SandboxError):
            reviews.accept_submit(
                case["id"], case["version"], idempotency_key="fresh-android-submit"
            )
        assert store.get(case["id"]) == prior
        replay, dispatch = reviews.accept_submit(
            case["id"], case["version"], idempotency_key="dispatch-submit-001"
        )
        assert replay == prior and not dispatch
        record = prior["results"]["evidence_review"]
        assert record["command"] == calls[0][2]
        monkeypatch.setattr(gateway, "request", original)
        command = {
            "version": prior["version"],
            "revision": prior["revision"],
            "mode": record["mode"],
            "idempotency_key": record["idempotency_key"],
        }
        claimed_recovery, dispatch = dispatcher.accept_recovery(case["id"], command)
        assert dispatch
        dispatcher.run(claimed_recovery, recovery=True)
        done = store.get(case["id"])
        assert done["state"] == "EXCEPTION_REVIEW" and not done["active"]
        assert done["results"]["evidence_review"]["command"] == record["command"]
        assert [c[2] for c in calls if c[0] == "POST"] == [record["command"], record["command"]]
        assert service.latest(case["id"])["id"] == done["results"]["evidence_review"]["job_id"]
        assert done["packet"]["financial"] is None and done["packet"]["decision"] is None


@pytest.mark.parametrize("mutation", ["revise", "upload", "remove"])
def test_unresolved_command_survives_direct_domain_mutations(claimed, mutation):
    store, docs, _, case = claimed
    case.update(
        active=False,
        state="TECHNICAL_REVIEW",
        results={
            "evidence_review": {
                "status": "SUBMITTING",
                "idempotency_key": "original-service-key",
                "case_version": case["version"],
            }
        },
    )
    store.save(case)
    before = deepcopy(case)
    with pytest.raises(SandboxError, match="งานเดิม"):
        if mutation == "revise":
            store.revise(
                case["id"],
                {**case["input"], "message": "new declaration"},
                case["version"],
                idempotency_key="fresh-revise",
            )
        elif mutation == "remove":
            docs.change(
                case,
                case["version"],
                remove=case["document_ids"][0],
                idempotency_key="fresh-remove",
            )
        else:
            attach(docs, case, kind="identity")
    assert store.get(case["id"]) == before


@pytest.mark.parametrize(
    "change", ["version", "owner", "consent", "document", "mode", "revision", "human"]
)
def test_recovery_binding_mismatch_stops_before_transport(claimed, tmp_path, monkeypatch, change):
    m = dispatcher_module()
    store, docs, _, case = claimed
    with ReviewService(tmp_path / "reviews.sqlite3") as service:

        def lose(_):
            raise SandboxError("lost accepted response")

        gateway, calls = connect(monkeypatch, service, after_submit=lose)
        dispatcher = m.ReviewDispatcher(store, docs, gateway, mode="offline", poll_interval=0)
        dispatcher.run(case)
        current = store.get(case["id"])
        record = current["results"]["evidence_review"]
        command = {
            "version": current["version"],
            "revision": current["revision"],
            "mode": "offline",
            "idempotency_key": record["idempotency_key"],
        }
        if change == "mode":
            command["mode"] = "typhoon"
        elif change == "revision":
            current["feedback"] = ["another operator changed the case"]
        elif change == "version":
            current["version"] += 1
        elif change == "owner":
            current["owner_id"] = str(uuid.uuid4())
        elif change == "consent":
            current["input"]["consent"] = False
        elif change == "human":
            current.update(
                state="DECLINED", decision={"status": "DECLINED", "reason": "human final"}
            )
        else:
            doc = docs.list(current)[0]
            doc["ocr_pages"][0]["text"] += " changed"
            docs.save_ocr(doc)
        store.save(current)
        before = store.get(case["id"])
        if change != "revision":
            command["revision"] = before["revision"]
        if change == "version":
            command["version"] = before["version"]
        with pytest.raises(SandboxError):
            dispatcher.accept_recovery(case["id"], command)
        assert store.get(case["id"]) == before
        assert len(calls) == 1


def test_failed_known_job_can_be_retried_explicitly_with_original_submit_replay_preserved(
    claimed, tmp_path, monkeypatch
):
    m = dispatcher_module()
    store, docs, reviews, case = claimed
    with ReviewService(
        tmp_path / "jobs", runner=lambda _: (_ for _ in ()).throw(ValueError("safe stub"))
    ) as service:
        gateway, calls = connect(monkeypatch, service)
        dispatcher = m.ReviewDispatcher(store, docs, gateway, mode="offline", poll_interval=0)
        dispatcher.run(case)
        failed = store.get(case["id"])
        assert failed["results"]["evidence_review"]["status"] == "FAILED"
        next_case, dispatch = reviews.accept_submit(
            case["id"], case["version"], idempotency_key="explicit-known-failure-retry"
        )
        assert dispatch
        dispatcher.run(next_case)
        assert len([c for c in calls if c[0] == "POST"]) == 2
        assert calls[0][2]["idempotency_key"] != calls[2][2]["idempotency_key"]
        replay, dispatch = reviews.accept_submit(
            case["id"], case["version"], idempotency_key="dispatch-submit-001"
        )
        assert not dispatch and replay == store.get(case["id"])


def test_final_guard_information_request_waits_for_exact_recovery_then_allows_supplements(
    claimed, monkeypatch
):
    from merchant_sandbox.core import digest

    m = dispatcher_module()
    store, docs, reviews, case = claimed
    gateway = ReviewGateway("http://127.0.0.1:1", "synthetic-test-token-" + "x" * 32)
    commands, jobs = [], {}

    def request(method, path, body=None):
        assert method == "POST" and path == "/v1/reviews"
        commands.append(deepcopy(body))
        key = body["idempotency_key"]
        jobs.setdefault(
            key,
            {
                "id": "original-synthetic-job",
                "case_id": case["id"],
                "case_version": case["version"],
                "mode": "offline",
                "status": "COMPLETED",
                "snapshot_hash": digest({"case": body["case"], "documents": body["documents"]}),
                "result": {
                    "report": {"decision": None},
                    "trace": [],
                    "usage": {},
                    "review_state": "OFFLINE_EVIDENCE_ONLY",
                    "decision": None,
                    "human_final_decision_required": True,
                },
            },
        )
        if len(commands) == 1:
            raise SandboxError("synthetic accepted command response loss")
        return deepcopy(jobs[key])

    monkeypatch.setattr(gateway, "request", request)
    dispatcher = m.ReviewDispatcher(store, docs, gateway, mode="offline", poll_interval=0)
    dispatcher.run(case)
    uncertain = store.get(case["id"])
    assert uncertain["state"] == "TECHNICAL_REVIEW"
    decision = {
        "version": case["version"],
        "idempotency_key": "final-guard-information",
        "decision": "NEEDS_INFORMATION",
        "reason": "Please supply missing evidence",
    }
    with pytest.raises(SandboxError) as rejected:
        reviews.decide(case["id"], decision)
    assert rejected.value.code == "evidence_dispatch_unresolved"
    assert store.get(case["id"]) == uncertain
    record = uncertain["results"]["evidence_review"]
    claim, dispatch = dispatcher.accept_recovery(
        case["id"],
        {
            "version": uncertain["version"],
            "revision": uncertain["revision"],
            "mode": record["mode"],
            "idempotency_key": record["idempotency_key"],
        },
    )
    assert dispatch
    dispatcher.run(claim, recovery=True)
    recovered = store.get(case["id"])
    assert recovered["results"]["evidence_review"]["job_id"] == "original-synthetic-job"
    assert commands == [record["command"], record["command"]] and len(jobs) == 1
    requested = reviews.decide(case["id"], decision)
    assert (
        requested["state"] == "WAIT_CUSTOMER"
        and requested["decision"]["reason"] == decision["reason"]
    )
    assert reviews.decide(case["id"], decision) == requested
    supplemented, _ = attach(docs, requested, kind="identity")
    assert supplemented["version"] == requested["version"] + 1
    revised = store.revise(
        case["id"],
        {**supplemented["input"], "message": "Additional evidence declaration"},
        supplemented["version"],
        idempotency_key="final-guard-supplement",
    )
    assert revised["version"] == supplemented["version"] + 1
    assert any(
        entry["results"].get("evidence_review", {}).get("command") == record["command"]
        for entry in revised["history"]
    )


def test_final_guard_original_decision_receipt_replay_precedes_unresolved_guard(claimed):
    store, _, reviews, case = claimed
    case.update(active=False, state="TECHNICAL_REVIEW")
    store.save(case)
    decision = {
        "version": case["version"],
        "idempotency_key": "final-guard-original-decision",
        "decision": "NEEDS_INFORMATION",
        "reason": "Previously accepted request",
    }
    accepted = reviews.decide(case["id"], decision)
    accepted["results"] = {
        "evidence_review": {"status": "SUBMITTING", "idempotency_key": "retained-original-key"}
    }
    store.save(accepted)
    before = store.get(case["id"])
    assert reviews.decide(case["id"], decision) == before
    assert store.get(case["id"]) == before


def test_final_guard_does_not_block_a_final_human_decline(claimed, monkeypatch):
    store, _, reviews, case = claimed
    retained = {"status": "SUBMITTING", "idempotency_key": "original-retained-key"}
    case.update(active=False, state="TECHNICAL_REVIEW", results={"evidence_review": retained})
    store.save(case)

    def unavailable(*args, **kwargs):
        raise SandboxError("synthetic bank unavailable")

    monkeypatch.setattr(reviews.bank, "read", unavailable)
    declined = reviews.decide(
        case["id"],
        {
            "version": case["version"],
            "idempotency_key": "final-human-decline",
            "decision": "DECLINED",
            "reason": "Human final decision",
        },
    )
    assert declined["state"] == "DECLINED"
    assert declined["results"]["evidence_review"] == retained
