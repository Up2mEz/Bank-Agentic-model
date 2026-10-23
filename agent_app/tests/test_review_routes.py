"""Local manual intake must use actual uploaded/versioned evidence."""

import base64
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
import requests
from test_onboarding_review import http_server as http_server

from merchant_sandbox.core import ROOT, Store, default_input


def test_case_api_exposes_service_capabilities_without_provider_secrets(http_server):
    base, config, _, _ = http_server
    response = requests.get(base + "/healthz", timeout=3)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "component": "case-api"}
    capability = config["capabilities"]["agent_review"]
    assert capability["configured"] is False
    assert capability["available"] is False
    assert "token" not in str(capability).lower()


def test_manual_sample_attachment_replays_exactly_and_never_uses_a_credit_oracle(http_server):
    base, config, _, _ = http_server
    headers = {"X-Review-Nonce": config["review_nonce"]}
    case = requests.post(
        base + "/api/cases",
        json={"input": default_input(), "idempotency_key": "manual-test-create"},
        headers=headers,
        timeout=3,
    ).json()
    endpoint = base + "/api/cases/" + case["id"] + "/sample-documents"
    body = {"version": case["version"], "idempotency_key": "manual-sample-documents"}
    first = requests.post(endpoint, json=body, headers=headers, timeout=3)
    assert first.status_code == 200, first.text
    again = requests.post(endpoint, json=body, headers=headers, timeout=3)
    assert again.status_code == 200
    assert first.json() == again.json()
    assert first.json()["version"] == case["version"] + 1
    assert len(first.json()["documents"]) == 1
    doc = first.json()["documents"][0]
    assert doc["kind"] == "statement" and "synthetic" in doc["filename"]
    assert not first.json()["results"]
    assert first.json()["packet"] is None


def test_local_document_route_does_not_mutate_android_case(http_server):
    base, config, _, store = http_server
    case = store.create(default_input(), "android-source-case", owner_id=str(uuid.uuid4()))
    before = store.get(case["id"])
    response = requests.post(
        base + "/api/cases/" + case["id"] + "/sample-documents",
        json={"version": 1, "idempotency_key": "android-source-unchanged"},
        headers={"X-Review-Nonce": config["review_nonce"]},
        timeout=3,
    )
    assert response.status_code == 403
    assert store.get(case["id"]) == before


def test_staff_submit_without_service_is_visible_and_does_not_claim_case_complete(http_server):
    base, config, _, store = http_server
    case = store.create(default_input(), "manual-no-service-case")
    response = requests.post(
        base + "/api/cases/" + case["id"] + "/evidence-review",
        json={"version": 1, "mode": "offline", "idempotency_key": "manual-no-service-review"},
        headers={"X-Review-Nonce": config["review_nonce"]},
        timeout=3,
    )
    assert response.status_code in {400, 503}
    assert "service" in response.json()["error"].lower()
    assert store.get(case["id"])["state"] == "DRAFT"


@pytest.fixture(params=["offline", "default-typhoon"])
def evidence_http(request, tmp_path):
    """Only synthetic loopback listeners and per-test databases, closed on exit."""
    from merchant_sandbox.review_api import create_http_server
    from merchant_sandbox.review_pipeline import ReviewPipeline
    from merchant_sandbox.review_service import ReviewService

    entered, release = threading.Event(), threading.Event()
    accepted = []

    def runner(payload):
        accepted.append(payload)
        entered.set()
        if not release.wait(8):
            raise RuntimeError("test gate timeout")
        if payload["mode"] == "typhoon":
            raise RuntimeError("synthetic failure; no provider execution")
        return ReviewPipeline()(payload)

    token = "synthetic-http-service-" + "x" * 40
    with ReviewService(tmp_path / "reviews.sqlite3", runner=runner) as service:
        listener = create_http_server(service, ("127.0.0.1", 0), token=token)
        serving = threading.Thread(target=listener.serve_forever, daemon=True)
        serving.start()
        service.start_worker()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            **os.environ,
            "AGENT_SERVICE_TOKEN": token,
            "LENDING_SERVICE_TOKEN": token,
            "TYPHOON_API_KEY": "",
            "AGENT_SERVICE_URL": "",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        }
        command = [
            sys.executable,
            "-m",
            "merchant_sandbox.server",
            "--port",
            str(port),
            "--db",
            str(tmp_path / "cases.sqlite3"),
            "--agent-service-url",
            f"http://127.0.0.1:{listener.server_port}",
        ]
        if request.param == "offline":
            command += ["--agent-review-mode", "offline"]
        proc = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try:
                    response = requests.get(base + "/healthz", timeout=0.2)
                    response.raise_for_status()
                    break
                except requests.RequestException:
                    if proc.poll() is not None:
                        raise AssertionError(proc.communicate()[1].decode()) from None
                    time.sleep(0.05)
            else:
                raise AssertionError("case HTTP listener did not start")
            yield (
                base,
                token,
                Store(tmp_path / "cases.sqlite3"),
                service,
                accepted,
                entered,
                release,
                request.param,
            )
        finally:
            release.set()
            proc.terminate()
            proc.communicate(timeout=10)
            listener.shutdown()
            listener.server_close()
            serving.join(timeout=3)


def test_actual_android_internal_submit_reaches_one_persisted_evidence_job(evidence_http):
    base, token, store, service, accepted, entered, release, mode = evidence_http
    owner = str(uuid.uuid4())
    headers = {"Authorization": "Bearer " + token, "X-Customer-ID": owner}
    data = default_input()
    data.pop("scenario")
    intake = {"input": data, "idempotency_key": "android-http-create"}
    endpoint = base + "/internal/lending/cases"
    created = requests.post(endpoint, json=intake, headers=headers, timeout=3)
    assert created.status_code == 201, created.text
    case = created.json()
    endpoint += "/" + case["id"]
    raw = (ROOT / "examples/merchant_sandbox/documents/synthetic-statement.pdf").read_bytes()
    upload = {
        "version": case["version"],
        "idempotency_key": "android-http-document",
        "document": {
            "kind": "statement",
            "filename": "synthetic-statement.pdf",
            "mime_type": "application/pdf",
            "content_base64": base64.b64encode(raw).decode(),
        },
    }
    attached = requests.post(endpoint + "/documents", json=upload, headers=headers, timeout=3)
    assert attached.status_code == 200, attached.text
    assert (
        requests.post(endpoint + "/documents", json=upload, headers=headers, timeout=3).json()
        == attached.json()
    )
    case = store.get(case["id"])
    # is_mock is false for Android. Offline OCR is explicit test setup, never runtime injection.
    from merchant_sandbox.lending import Documents
    from merchant_sandbox.review_gateway import sample_ocr

    docs = Documents(store)
    doc = docs.list(case)[0]
    doc["ocr_pages"] = sample_ocr(doc)
    docs.save_ocr(doc)
    command = {"version": case["version"], "idempotency_key": "android-http-submit"}
    submitted = requests.post(endpoint + "/submit", json=command, headers=headers, timeout=3)
    assert submitted.status_code == 202, submitted.text
    try:
        assert entered.wait(3), "Android submit did not reach ReviewService"
        assert store.get(case["id"])["active"] is True
        again = requests.post(endpoint + "/submit", json=command, headers=headers, timeout=3)
        assert again.status_code == 202
        replay = requests.post(
            endpoint + "/submit/replay", json=command, headers=headers, timeout=3
        )
        assert replay.status_code == 200
        assert len(accepted) == 1
        assert accepted[0]["case"]["owner_id"] == owner
        assert accepted[0]["case"]["state"] == "DRAFT" and not accepted[0]["case"]["active"]
        assert accepted[0]["mode"] == ("offline" if mode == "offline" else "typhoon")
    finally:
        release.set()
    for _ in range(100):
        current = store.get(case["id"])
        if not current["active"]:
            break
        time.sleep(0.05)
    assert not current["active"]
    assert current["state"] == ("EXCEPTION_REVIEW" if mode == "offline" else "TECHNICAL_REVIEW")
    assert current.get("decision") is None
    job = service.latest(case["id"])
    assert current["results"]["evidence_review"]["job_id"] == job["id"]
    assert "financial_calculate" not in current["results"]
    if current["packet"]:
        assert current["packet"]["financial"] is None and current["packet"]["assessment"] is None
    assert (
        requests.post(
            endpoint + "/submit/replay", json=command, headers=headers, timeout=3
        ).status_code
        == 200
    )
    wrong_owner = {**headers, "X-Customer-ID": str(uuid.uuid4())}
    assert (
        requests.post(
            endpoint + "/submit/replay", json=command, headers=wrong_owner, timeout=3
        ).status_code
        == 404
    )
    assert (
        requests.post(
            endpoint + "/submit/replay",
            json={**command, "version": 999},
            headers=headers,
            timeout=3,
        ).status_code
        == 422
    )
    assert len(accepted) == 1
    # Staff/browser stale checking reads the same canonical snapshot after lifecycle writes.
    visible = requests.get(base + "/api/cases/" + case["id"] + "/evidence-review", timeout=3)
    assert visible.status_code == 200 and visible.json()["id"] == job["id"]
    assert visible.json()["stale"] is False


def test_actual_browser_submit_uses_the_same_persisted_service(evidence_http):
    base, _, store, service, accepted, entered, release, _ = evidence_http
    config = requests.get(base + "/api/config", timeout=3).json()
    headers = {"X-Review-Nonce": config["review_nonce"]}
    case = requests.post(
        base + "/api/cases",
        headers=headers,
        timeout=3,
        json={"input": default_input(), "idempotency_key": "browser-shared-create"},
    ).json()
    endpoint = base + "/api/cases/" + case["id"]
    case = requests.post(
        endpoint + "/sample-documents",
        headers=headers,
        timeout=3,
        json={"version": case["version"], "idempotency_key": "browser-shared-docs"},
    ).json()
    body = {
        "version": case["version"],
        "mode": "offline",
        "idempotency_key": "browser-shared-review",
    }
    first = requests.post(endpoint + "/evidence-review", headers=headers, json=body, timeout=3)
    assert first.status_code == 202, first.text
    try:
        assert entered.wait(3)
        again = requests.post(endpoint + "/evidence-review", headers=headers, json=body, timeout=3)
        assert again.status_code == 202 and again.json()["id"] == first.json()["id"]
        assert len(accepted) == 1
        assert accepted[0]["case"]["document_ids"] == case["document_ids"]
        assert accepted[0]["case"]["results"] == {} and accepted[0]["case"]["decision"] is None
    finally:
        release.set()
    for _ in range(100):
        job = service.get(first.json()["id"])
        if job["status"] == "COMPLETED":
            break
        time.sleep(0.05)
    assert job["status"] == "COMPLETED"
    visible = requests.get(endpoint + "/evidence-review", timeout=3).json()
    assert visible["id"] == job["id"] and visible["stale"] is False
    assert job["result"]["decision"] is None
    assert store.get(case["id"]).get("decision") is None


def test_staff_explicit_android_recovery_reconciles_exact_job_and_replays_case_receipt(
    evidence_http,
):
    from test_lending_documents import attach

    from merchant_sandbox.lending import Documents
    from merchant_sandbox.review_gateway import sample_ocr

    base, token, store, service, accepted, entered, release, mode = evidence_http
    owner = str(uuid.uuid4())
    case = store.create(default_input(), "recover-android-create", owner_id=owner)
    docs = Documents(store)
    case, _ = attach(docs, case)
    doc = docs.list(case)[0]
    doc["ocr_pages"] = sample_ocr(doc)
    docs.save_ocr(doc)
    endpoint = base + "/internal/lending/cases/" + case["id"] + "/submit"
    headers = {"Authorization": "Bearer " + token, "X-Customer-ID": owner}
    submitted = requests.post(
        endpoint,
        json={"version": case["version"], "idempotency_key": "recover-original-submit"},
        headers=headers,
        timeout=3,
    )
    assert submitted.status_code == 202
    assert entered.wait(3)
    for _ in range(100):
        current = store.get(case["id"])
        if current["results"]["evidence_review"].get("job_id"):
            break
        time.sleep(0.02)
    # Simulate a bounded poll timeout while the exact accepted service job lives.
    current.update(active=False, state="TECHNICAL_REVIEW")
    current["results"]["evidence_review"]["dispatch_state"] = "POLL_LIMIT"
    store.save(current)
    record = current["results"]["evidence_review"]
    assert record["command"] == accepted[0]
    fresh = requests.post(
        endpoint,
        json={"version": case["version"], "idempotency_key": "recover-forbidden-fresh"},
        headers=headers,
        timeout=3,
    )
    assert fresh.status_code == 409
    config = requests.get(base + "/api/config", timeout=3).json()
    staff_headers = {"X-Review-Nonce": config["review_nonce"]}
    path = base + "/api/cases/" + case["id"] + "/evidence-review/recover"
    command = {
        "version": current["version"],
        "revision": current["revision"],
        "mode": record["mode"],
        "idempotency_key": record["idempotency_key"],
    }
    assert requests.post(path, json=command, timeout=3).status_code == 403
    wrong = {**command, "mode": "typhoon" if command["mode"] == "offline" else "offline"}
    assert requests.post(path, json=wrong, headers=staff_headers, timeout=3).status_code == 409
    recovered = requests.post(path, json=command, headers=staff_headers, timeout=3)
    assert recovered.status_code == 202, recovered.text
    assert "command" not in recovered.json()["results"]["evidence_review"]
    release.set()
    for _ in range(100):
        done = store.get(case["id"])
        if not done["active"]:
            break
        time.sleep(0.05)
    assert done["state"] == ("EXCEPTION_REVIEW" if mode == "offline" else "TECHNICAL_REVIEW")
    assert done["results"]["evidence_review"]["job_id"] == record["job_id"]
    assert len(accepted) == 1
    replay = requests.post(path, json=command, headers=staff_headers, timeout=3)
    assert replay.status_code == 202 and store.get(case["id"]) == done
    assert service.latest(case["id"])["id"] == record["job_id"]
