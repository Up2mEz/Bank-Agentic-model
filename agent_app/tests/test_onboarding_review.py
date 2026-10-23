import json
import os
import socket
import subprocess
import sys
import time
import uuid
from copy import deepcopy
from pathlib import Path
from urllib.error import HTTPError

import pytest
import requests
from test_lending_documents import attach, statement

from merchant_sandbox.bank import BankOnboardingClient
from merchant_sandbox.core import BaselinePlanner, SandboxError, Store, default_input
from merchant_sandbox.lending import Documents, LendingController, app_input, customer_view
from merchant_sandbox.review import Reviews, staff_dossier
from merchant_sandbox.typhoon import Config


class Bank:
    def __init__(self, owner):
        self.snapshot = {
            "customer_id": owner,
            "version": 7,
            "phone": {"verified": True, "value": "0800000000"},
            "profile": {"date_of_birth": "1990-01-01", "first_name": "Mali", "last_name": "Jaidee"},
            "kyc": {"status": "APPROVED", "session_id": "original-kyc-session", "is_mock": True},
            "wallet": {"status": "ACTIVE", "account_id": str(uuid.uuid4())},
            "business": {"name": "shop", "ownership_confirmed": True},
            "kyb": {"status": "VERIFIED"},
            "is_mock": True,
        }
        self.calls = []

    def read(self, owner, *, reviewer=False):
        self.calls.append((owner, reviewer))
        assert owner == self.snapshot["customer_id"]
        return deepcopy(self.snapshot)

    def review(self, owner, kind, data):
        self.calls.append((owner, kind, deepcopy(data)))
        self.snapshot[kind]["status"] = data["decision"]
        self.snapshot["version"] += 1
        return deepcopy(self.snapshot)


@pytest.fixture
def ready(tmp_path, monkeypatch):
    store = Store(tmp_path / "cases.sqlite3")
    docs = Documents(store)
    data = default_input()
    data.pop("scenario")
    data["applicant_name"] = "Mali Jaidee"
    case = store.create(app_input(data), "create-ready-123", owner_id=str(uuid.uuid4()))
    case["created_at"] = "2026-10-22T00:00:00+00:00"
    store.save(case)
    case, _ = attach(docs, case, "identity")
    case, _ = attach(docs, case)

    class OCR:
        def __init__(self, *_):
            pass

        def extract_page(self, raw, mime, page):
            return {
                "page": page,
                "model": "offline-test",
                "text": statement()["ocr_pages"][0]["text"]
                if mime == "application/pdf"
                else "Full name: Mali Jaidee",
            }

    monkeypatch.setattr("merchant_sandbox.lending.TyphoonOCR", OCR)
    bank = Bank(case["owner_id"])
    controller = LendingController(store, docs, Config(), bank=bank)
    case = controller.run(case["id"], BaselinePlanner(), case["version"])
    return store, docs, bank, controller, case


def command(case, decision="APPROVED", key="decision-key-123"):
    return {
        "version": case["version"],
        "idempotency_key": key,
        "decision": decision,
        "reason": "ตรวจหลักฐานและกำลังชำระแล้ว",
        "onboarding_version": 7,
    }


def test_onboarding_tool_binds_stored_owner_and_packet(ready):
    store, docs, bank, controller, case = ready
    assert bank.calls == [(case["owner_id"], False)]
    assert case["results"]["onboarding_read"]["snapshot"]["version"] == 7
    assert case["packet"]["onboarding"]["snapshot"]["kyc"]["status"] == "APPROVED"
    assert case["packet"]["financial"]["proposed_limit_thb"] == "28400.00"
    assert case["state"] == "REVIEW_READY"
    assert "decision" not in controller.allowed(case)
    with pytest.raises(SandboxError):
        controller.execute(case, "decision")


def test_missing_config_is_never_verified(ready):
    store, docs, _, _, case = ready
    case = store.revise(case["id"], case["input"], case["version"])
    result = LendingController(store, docs, Config()).run(
        case["id"], BaselinePlanner(), case["version"]
    )
    assert result["results"]["onboarding_read"]["status"] == "UNAVAILABLE"
    assert result["state"] == "EXCEPTION_REVIEW"
    with pytest.raises(SandboxError):
        Reviews(store, docs, BankOnboardingClient()).decide(case["id"], command(result))


def test_human_decision_replay_cas_terminal_and_customer_projection(ready):
    store, docs, bank, controller, case = ready
    reviews = Reviews(store, docs, bank)
    stale = deepcopy(case)
    body = command(case)
    result = reviews.decide(case["id"], body)
    assert result["decision"]["amount_thb"] == "28400.00"
    assert result["decision"]["reviewer"] == "local-reviewer"
    assert result["decision"]["onboarding_version"] == 7
    assert result["state"] == "APPROVED"
    assert customer_view(result, docs)["decision"] == result["decision"]
    assert reviews.decide(case["id"], body)["decision"] == result["decision"]
    with pytest.raises(SandboxError):
        reviews.decide(case["id"], {**body, "reason": "changed"})
    with pytest.raises(SandboxError):
        store.save(stale)
    with pytest.raises(SandboxError):
        store.revise(case["id"], case["input"], case["version"])
    with pytest.raises(SandboxError):
        attach(docs, result, "business")
    with pytest.raises(SandboxError):
        controller.run(case["id"], BaselinePlanner(), case["version"])


@pytest.mark.parametrize(
    "field,value", [("kyc", "REVIEW"), ("wallet", "BLOCKED"), ("kyb", "PENDING_REVIEW")]
)
def test_approval_requires_verified_bank(ready, field, value):
    store, docs, bank, _, case = ready
    bank.snapshot[field]["status"] = value
    with pytest.raises(SandboxError):
        Reviews(store, docs, bank).decide(case["id"], command(case))
    assert store.get(case["id"]).get("decision") is None


@pytest.mark.parametrize("problem", ["incomplete", "identity", "bank_down"])
def test_decline_records_reason_without_approval_eligibility_or_fabricated_amount(ready, problem):
    store, docs, bank, _, case = ready
    if problem == "incomplete":
        case["packet"] = None
        case["results"] = {}
        case["input"]["debt_thb"] = None
        case["state"] = "WAIT_CUSTOMER"
    elif problem == "identity":
        case["results"]["evidence"]["status"] = "NEEDS_REVIEW"
        bank.snapshot["kyc"]["status"] = "DECLINED"
        bank.snapshot["profile"]["first_name"] = "Other"
        bank.snapshot["version"] = 8
    else:
        bank = BankOnboardingClient()
    store.save(case)
    result = Reviews(store, docs, bank).decide(case["id"], command(case, "DECLINED"))
    assert result["state"] == "DECLINED"
    assert result["decision"]["reason"]
    assert result["decision"]["amount_thb"] is None
    assert result["decision"]["onboarding_version"] == (8 if problem == "identity" else 7)
    with pytest.raises(SandboxError):
        store.revise(case["id"], case["input"], case["version"])


def test_decline_after_request_for_information_preserves_prior_decision(ready):
    store, docs, bank, _, case = ready
    reviews = Reviews(store, docs, bank)
    info = reviews.decide(case["id"], command(case, "NEEDS_INFORMATION"))
    declined = reviews.decide(case["id"], command(case, "DECLINED", key="decline-after-info-123"))
    assert declined["decision_history"][-1] == info["decision"]
    assert declined["state"] == "DECLINED"


@pytest.mark.parametrize(
    "change", ["debt", "evidence", "packet", "bank-version", "age", "calculation", "active"]
)
def test_incomplete_or_stale_inputs_cannot_approve(ready, change):
    store, docs, bank, _, case = ready
    if change == "debt":
        case["input"]["debt_thb"] = None
    elif change == "evidence":
        case["results"]["evidence"]["coverage"] = "PARTIAL"
    elif change == "packet":
        case["packet"]["case_version"] -= 1
    elif change == "bank-version":
        bank.snapshot["version"] += 1
    elif change == "age":
        bank.snapshot["profile"]["date_of_birth"] = "2010-01-01"
        case["results"]["onboarding_read"]["snapshot"]["profile"]["date_of_birth"] = "2010-01-01"
        case["packet"]["onboarding"] = deepcopy(case["results"]["onboarding_read"])
    elif change == "calculation":
        case["results"]["financial_calculate"]["proposed_limit_thb"] = "99999.00"
    else:
        case["active"] = True
    store.save(case)
    with pytest.raises(SandboxError):
        Reviews(store, docs, bank).decide(case["id"], command(case))


def test_more_info_and_supplement_preserve_history(ready):
    store, docs, bank, controller, case = ready
    reviews = Reviews(store, docs, bank)
    result = reviews.decide(case["id"], command(case, "NEEDS_INFORMATION"))
    assert result["state"] == "WAIT_CUSTOMER"
    assert customer_view(result, docs)["decision"]["reason"]
    revised = store.revise(case["id"], case["input"], case["version"])
    assert revised.get("decision") is None and revised["packet"] is None
    assert revised["history"][-1]["decision"]["status"] == "NEEDS_INFORMATION"
    assert (
        revised["history"][-1]["results"]["financial_calculate"]["proposed_limit_thb"] == "28400.00"
    )
    assert customer_view(revised, docs)["decision"] is None
    assert (
        controller.run(case["id"], BaselinePlanner(), revised["version"])["state"] == "REVIEW_READY"
    )


def test_business_document_never_satisfies_identity_or_statement(ready):
    store, docs, bank, _, case = ready
    empty = store.create(case["input"], "empty-business-123", owner_id=case["owner_id"])
    empty, _ = attach(docs, empty, "business")
    result = LendingController(store, docs, Config(), bank=bank).run(
        empty["id"], BaselinePlanner(), empty["version"]
    )
    assert result["state"] == "WAIT_CUSTOMER"
    assert len(result["results"]["intake_check"]["gaps"]) == 2


def test_review_uses_stored_owner_preserves_analysis_and_refreshes_bank_version(ready):
    store, docs, bank, _, case = ready
    body = {
        "version": 7,
        "idempotency_key": "kyb-review-123",
        "decision": "NEEDS_INFORMATION",
        "reason": "ขอเอกสารเพิ่ม",
    }
    reviews = Reviews(store, docs, bank)
    result = reviews.onboarding_decision(case["id"], "kyb", body)
    assert bank.calls[-1] == (case["owner_id"], "kyb", body)
    assert result["version"] == case["version"]
    assert result["packet"] == case["packet"]
    assert result["latest_onboarding"]["version"] == 8
    with pytest.raises(SandboxError):
        reviews.onboarding_decision(case["id"], "kyb", {**body, "customer_id": str(uuid.uuid4())})


def test_decision_detects_case_changed_during_bank_read(ready):
    store, docs, bank, _, case = ready
    original = bank.read

    def read(owner, *, reviewer=False):
        result = original(owner, reviewer=reviewer)
        store.revise(case["id"], case["input"], case["version"])
        return result

    bank.read = read
    with pytest.raises(SandboxError):
        Reviews(store, docs, bank).decide(case["id"], command(case))
    assert store.get(case["id"]).get("decision") is None


def test_staff_dossier_has_references_no_raw_bytes(ready):
    _, docs, _, _, case = ready
    dossier = staff_dossier(case, docs)
    assert dossier["owner_id"] == case["owner_id"]
    assert dossier["packet"]["financial"]
    assert dossier["documents"][0]["sha256"]
    assert "ocr_pages" not in dossier["documents"][0]
    json.dumps(dossier)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:secret@example.com",
        "http://127.0.0.1/a",
        "https://bank.test/?key=x",
    ],
)
def test_bank_url_rejects_unsafe_destinations(url):
    with pytest.raises(SandboxError):
        BankOnboardingClient(url)


def test_optional_mutation_receipts_replay_before_version_and_terminal(ready):
    store, docs, bank, _, case = ready
    body = deepcopy(case["input"])
    revised = store.revise(case["id"], body, case["version"], idempotency_key="revise-key-123")
    assert (
        store.revise(case["id"], body, case["version"], idempotency_key="revise-key-123")["version"]
        == revised["version"]
    )
    with pytest.raises(SandboxError) as changed:
        store.revise(
            case["id"],
            {**body, "message": "changed"},
            case["version"],
            idempotency_key="revise-key-123",
        )
    assert changed.value.code == "idempotency_key_reused"
    _, payload = attach(docs, revised, "business")
    current = store.get(case["id"])
    docs.change(current, current["version"], data=payload, idempotency_key="document-key-123")
    replay = docs.change(
        store.get(case["id"]), current["version"], data=payload, idempotency_key="document-key-123"
    )
    assert replay["document_ids"] == store.get(case["id"])["document_ids"]
    with pytest.raises(SandboxError) as changed:
        docs.change(
            replay,
            current["version"],
            data={**payload, "filename": "changed.png"},
            idempotency_key="document-key-123",
        )
    assert changed.value.code == "idempotency_key_reused"


def test_staff_kyb_then_approval_uses_displayed_version_without_rerunning(ready):
    store, docs, bank, _, case = ready
    bank.snapshot["kyb"]["status"] = "PENDING_REVIEW"
    case["results"]["onboarding_read"]["snapshot"]["kyb"]["status"] = "PENDING_REVIEW"
    case["packet"]["onboarding"] = deepcopy(case["results"]["onboarding_read"])
    store.save(case)
    reviews = Reviews(store, docs, bank)
    result = reviews.onboarding_decision(
        case["id"],
        "kyb",
        {
            "version": 7,
            "idempotency_key": "kyb-final-123",
            "decision": "VERIFIED",
            "reason": "เอกสารครบ",
        },
    )
    assert result["packet"]["onboarding"]["snapshot"]["version"] == 7
    with pytest.raises(SandboxError):
        reviews.decide(case["id"], command(case))
    approved = reviews.decide(case["id"], {**command(case), "onboarding_version": 8})
    assert approved["decision"]["status"] == "APPROVED"


def test_changed_bank_identity_cannot_be_approved_even_with_latest_version(ready):
    store, docs, bank, _, case = ready
    bank.snapshot["profile"]["first_name"] = "Other"
    bank.snapshot["version"] = 8
    with pytest.raises(SandboxError):
        Reviews(store, docs, bank).decide(case["id"], {**command(case), "onboarding_version": 8})


def test_submit_receipt_claims_once_and_survives_recovery(ready):
    store, docs, bank, controller, case = ready
    case = store.revise(case["id"], case["input"], case["version"])
    reviews = Reviews(store, docs, bank)
    claimed, dispatch = reviews.accept_submit(
        case["id"], case["version"], idempotency_key="submit-once-123"
    )
    assert dispatch and claimed["active"]
    again, dispatch = reviews.accept_submit(
        case["id"], case["version"], idempotency_key="submit-once-123"
    )
    assert not dispatch and again["active"]
    result = controller.run(
        case["id"], BaselinePlanner(), case["version"], _claimed_revision=claimed["revision"]
    )
    assert result["state"] == "REVIEW_READY" and not result["active"]
    assert not reviews.accept_submit(
        case["id"], case["version"], idempotency_key="submit-once-123"
    )[1]
    with pytest.raises(SandboxError) as changed:
        reviews.accept_submit(case["id"], case["version"] + 1, idempotency_key="submit-once-123")
    assert changed.value.status == 422
    case = store.revise(case["id"], case["input"], case["version"])
    reviews.accept_submit(case["id"], case["version"], idempotency_key="submit-crash-123")
    store.recover()
    assert store.get(case["id"])["state"] == "TECHNICAL_REVIEW"
    assert not reviews.accept_submit(
        case["id"], case["version"], idempotency_key="submit-crash-123"
    )[1]
    assert reviews.accept_submit(case["id"], case["version"], idempotency_key="submit-retry-123")[1]


def test_bank_client_exact_roles_paths_safe_snapshot_and_bounded_failures(tmp_path):
    owner = str(uuid.uuid4())
    a, r = tmp_path / "agent.key", tmp_path / "reviewer.key"
    a.write_text("agent-test-secret", encoding="utf8")
    r.write_text("reviewer-test-secret", encoding="utf8")
    bank = BankOnboardingClient("http://127.0.0.1:18082", a, r)
    snapshot = Bank(owner).snapshot
    snapshot["profile"]["document_number"] = "raw-secret"
    snapshot["kyc"]["provider_secret"] = "secret"
    snapshot["otp"] = "123456"
    calls = []

    class Reply:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, limit):
            assert limit == 256001
            return json.dumps(snapshot).encode()

    class Transport:
        def open(self, req, timeout):
            calls.append((req, timeout))
            return Reply()

    bank._opener = Transport()
    safe = bank.read(owner)
    assert calls[-1][0].full_url == f"http://127.0.0.1:18082/v1/agent/customers/{owner}/onboarding"
    assert calls[-1][0].get_header("X-api-key") == "agent-test-secret"
    assert "raw-secret" not in json.dumps(safe) and "provider_secret" not in json.dumps(safe)
    bank.read(owner, reviewer=True)
    assert calls[-1][0].full_url.endswith(f"/v1/review/onboarding/{owner}")
    assert calls[-1][0].get_header("X-api-key") == "reviewer-test-secret"
    body = {
        "version": 7,
        "idempotency_key": "bank-review-123",
        "decision": "VERIFIED",
        "reason": "ครบ",
    }
    bank.review(owner, "kyb", body)
    assert calls[-1][0].get_method() == "POST"
    assert json.loads(calls[-1][0].data) == body
    snapshot["customer_id"] = str(uuid.uuid4())
    with pytest.raises(SandboxError):
        bank.read(owner)

    class Redirect:
        def open(self, req, timeout):
            raise HTTPError(req.full_url, 302, "redirect", {}, None)

    bank._opener = Redirect()
    with pytest.raises(SandboxError):
        bank.read(owner)


@pytest.fixture
def http_server(tmp_path):
    """Own ephemeral server/store only; never touches the shared runtime or any real provider."""
    root = Path(__file__).resolve().parents[2]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token_file = tmp_path / "bridge.key"
    token_file.write_text("offline-bridge-" + "x" * 40, encoding="utf8")
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "merchant_sandbox.server",
            "--port",
            str(port),
            "--db",
            str(tmp_path / "http.sqlite3"),
            "--bridge-token-file",
            str(token_file),
        ],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                response = requests.get(base + "/api/config", timeout=0.2)
                response.raise_for_status()
                break
            except requests.RequestException:
                if proc.poll() is not None:
                    raise AssertionError(proc.communicate()[1].decode()) from None
                time.sleep(0.05)
        else:
            raise AssertionError("ephemeral server did not start")
        yield base, response.json(), token_file.read_text(), Store(tmp_path / "http.sqlite3")
    finally:
        proc.terminate()
        proc.communicate(timeout=10)


def test_http_nonce_agent_auth_isolation_receipt_codes_and_lab_guard(http_server):
    base, config, token, store = http_server
    assert config["review_nonce"]
    body = {"input": default_input(), "idempotency_key": "lab-create-123"}
    assert requests.post(base + "/api/cases", json=body, timeout=2).status_code == 403
    headers = {"X-Review-Nonce": config["review_nonce"]}
    assert (
        requests.post(
            base + "/api/cases",
            json=body,
            headers={**headers, "Origin": "http://evil.test"},
            timeout=2,
        ).status_code
        == 400
    )
    assert (
        requests.post(base + "/api/cases", json=body, headers=headers, timeout=2).status_code == 201
    )
    owner = str(uuid.uuid4())
    case = store.create(default_input(), "http-customer-123", owner_id=owner)
    auth = {"Authorization": "Bearer " + token}
    assert requests.get(base + "/internal/agent/cases", timeout=2).status_code == 401
    listing = requests.get(base + "/internal/agent/cases", headers=auth, timeout=2)
    assert listing.status_code == 200 and listing.json()["items"][0]["owner_id"] == owner
    assert (
        requests.get(
            base + f"/internal/agent/cases/{case['id']}", headers=auth, timeout=2
        ).status_code
        == 200
    )
    assert (
        requests.post(base + "/internal/agent/cases", json={}, headers=auth, timeout=2).status_code
        == 405
    )
    customer = {**auth, "X-Customer-ID": owner}
    path = base + f"/internal/lending/cases/{case['id']}/revise"
    command = {
        "version": case["version"],
        "input": {k: v for k, v in case["input"].items() if k != "scenario"},
        "idempotency_key": "http-revise-123",
    }
    first = requests.post(path, json=command, headers=customer, timeout=2)
    assert first.status_code == 200
    assert (
        requests.post(path, json=command, headers=customer, timeout=2).json()["version"]
        == first.json()["version"]
    )
    conflict = requests.post(path, json={**command, "version": 999}, headers=customer, timeout=2)
    assert conflict.status_code == 422 and conflict.json()["code"] == "idempotency_key_reused"
    other = {**auth, "X-Customer-ID": str(uuid.uuid4())}
    assert (
        requests.get(
            base + f"/internal/lending/cases/{case['id']}", headers=other, timeout=2
        ).status_code
        == 404
    )
    latest = store.get(case["id"])
    latest["state"] = "APPROVED"
    store.save(latest)
    lab_bypass = requests.post(
        base + f"/api/cases/{case['id']}/revise",
        json={"input": latest["input"], "version": latest["version"]},
        headers=headers,
        timeout=2,
    )
    assert lab_bypass.status_code == 409
    # Accepted replay still returns the latest safe projection after the case became final.
    assert (
        requests.post(path, json=command, headers=customer, timeout=2).json()["state"] == "APPROVED"
    )
