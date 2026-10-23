"""Case API boundaries for the independently deployed evidence service."""

import base64
import hashlib
from copy import deepcopy

import pytest

from merchant_sandbox.core import ROOT, SandboxError, Store, default_input, digest
from merchant_sandbox.lending import Documents


def test_lab_document_upload_can_be_replayed_without_creating_a_new_revision(tmp_path):
    store = Store(tmp_path / "cases.sqlite3")
    docs = Documents(store)
    case = store.create(default_input(), "create-document-case")
    raw = (ROOT / "examples/merchant_sandbox/documents/synthetic-statement.pdf").read_bytes()
    body = {
        "kind": "statement",
        "filename": "statement.pdf",
        "mime_type": "application/pdf",
        "content_base64": base64.b64encode(raw).decode(),
    }
    uploaded = docs.change(case, 1, data=body, idempotency_key="upload-document-case")
    replay = docs.change(case, 1, data=body, idempotency_key="upload-document-case")
    assert uploaded == replay
    assert uploaded["version"] == 2
    assert len(docs.list(uploaded)) == 1


@pytest.fixture
def gateway():
    from merchant_sandbox.review_gateway import ReviewGateway

    return ReviewGateway("http://127.0.0.1:8781", "x" * 40)


def snapshot():
    case = {
        "id": "CASE-test",
        "version": 2,
        "state": "DRAFT",
        "active": False,
        "input": {"consent": True},
        "results": {},
        "trace": [],
        "decision": None,
    }
    documents = [
        {
            "id": "DOC-test",
            "case_id": case["id"],
            "kind": "statement",
            "sha256": "a" * 64,
            "ocr_pages": [{"page": 1, "text": "recorded OCR"}],
        }
    ]
    return case, documents


def test_gateway_forwards_only_internal_snapshot_and_retains_exact_job_key(gateway, monkeypatch):
    case, docs = snapshot()
    before = deepcopy((case, docs))
    calls = []
    job = {
        "id": "JOB-test",
        "case_id": case["id"],
        "case_version": 2,
        "snapshot_hash": digest({"case": case, "documents": docs}),
        "status": "QUEUED",
        "mode": "offline",
    }
    monkeypatch.setattr(
        gateway,
        "request",
        lambda method, path, body=None: calls.append((method, path, body)) or job,
    )
    assert gateway.submit(case, docs, 2, "offline", "review-exact-key") == job
    assert calls == [
        (
            "POST",
            "/v1/reviews",
            {
                "case": case,
                "documents": docs,
                "mode": "offline",
                "idempotency_key": "review-exact-key",
            },
        )
    ]
    assert (case, docs) == before


@pytest.mark.parametrize(
    "change", ["consent", "active", "final", "decision", "processing", "version", "no_statement"]
)
def test_gateway_rejects_ineligible_case_before_contacting_service(gateway, monkeypatch, change):
    case, docs = snapshot()
    version = 2
    if change == "consent":
        case["input"]["consent"] = False
    elif change == "active":
        case["active"] = True
    elif change == "final":
        case["state"] = "APPROVED"
    elif change == "decision":
        case["decision"] = {"status": "APPROVED"}
    elif change == "processing":
        case["state"] = "PROCESSING"
    elif change == "version":
        version = 1
    else:
        docs = []
    monkeypatch.setattr(gateway, "request", lambda *a, **k: pytest.fail("ineligible snapshot sent"))
    with pytest.raises(SandboxError):
        gateway.submit(case, docs, version, "offline", "review-exact-key")


def test_job_from_another_case_is_never_displayed(gateway, monkeypatch):
    case, docs = snapshot()
    monkeypatch.setattr(
        gateway,
        "request",
        lambda *a: {
            "id": "JOB-other",
            "case_id": "CASE-other",
            "case_version": 2,
            "snapshot_hash": "bad",
        },
    )
    with pytest.raises(SandboxError):
        gateway.latest(case, docs)


def test_modified_snapshot_marks_old_report_stale(gateway, monkeypatch):
    case, docs = snapshot()
    original_hash = digest({"case": case, "documents": docs})
    job = {
        "id": "JOB-test",
        "case_id": case["id"],
        "case_version": 2,
        "snapshot_hash": original_hash,
        "mode": "offline",
        "status": "QUEUED",
        "result": None,
    }
    monkeypatch.setattr(gateway, "request", lambda *a: deepcopy(job))
    assert gateway.latest(case, docs)["stale"] is False
    case["version"] = 3
    assert gateway.latest(case, docs)["stale"] is True


def test_only_exact_bundled_sample_gets_explicit_recorded_ocr():
    from merchant_sandbox.review_gateway import sample_ocr

    path = ROOT / "examples/merchant_sandbox/documents/synthetic-statement.pdf"
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    doc = {"kind": "statement", "sha256": sha}
    pages = sample_ocr(doc)
    assert len(pages) == 1 and "Mali Jaidee" in pages[0]["text"]
    assert pages[0]["provenance"] == "BUNDLED_SYNTHETIC_RECORDED_OCR"
    assert "expected_capacity" not in pages[0]["text"]
    assert sample_ocr({"kind": "statement", "sha256": "0" * 64}) is None


def test_snapshot_embeds_raw_uploaded_document_only_when_ocr_is_absent():
    from merchant_sandbox.review_gateway import review_documents

    raw = b"a real stored document payload"
    doc = {
        "id": "DOC-uploaded",
        "kind": "statement",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "ocr_pages": [],
    }

    class FakeDocuments:
        def list(self, case):
            return [deepcopy(doc)]

        def get(self, ident, *, raw=False):
            assert ident == doc["id"] and raw is True
            return b"a real stored document payload", deepcopy(doc)

    result = review_documents(FakeDocuments(), {"id": "CASE-test"})
    assert base64.b64decode(result[0]["content_base64"]) == raw
    assert result[0]["ocr_pages"] == []
    assert "content_base64" not in doc


def test_analysis_snapshot_retains_inputs_but_excludes_operational_state():
    from merchant_sandbox.review_gateway import analysis_snapshot

    case, _ = snapshot()
    case.update(
        snapshot="CASE-test:v2",
        input_hash="input-hash",
        created_at="2026-10-24",
        policy_snapshot={"policy_version": "test"},
        fixture_sha256=None,
        owner_id="owner-test",
        source="merchant_app",
        document_ids=["DOC-test"],
        is_mock=False,
    )
    expected = deepcopy(case)
    case.update(
        state="PROCESSING",
        active=True,
        revision=9,
        feedback=["changed"],
        results={"financial_calculate": {"proposed_limit_thb": "100"}},
        packet={"recommendation": "RECOMMEND_APPROVE"},
        attempts={"a": 1},
        decision={"status": "NEEDS_INFORMATION"},
        trace=[{"kind": "run"}],
    )
    before = deepcopy(case)
    assert analysis_snapshot(case) == expected
    assert case == before
    copy = analysis_snapshot(case)
    copy["input"]["consent"] = False
    assert case["input"]["consent"] is True


@pytest.mark.parametrize(
    "field", ["state", "active", "revision", "feedback", "results", "packet", "trace", "decision"]
)
def test_lifecycle_changes_do_not_stale_job(gateway, monkeypatch, field):
    case, docs = snapshot()
    job = {
        "id": "JOB-test",
        "case_id": case["id"],
        "case_version": 2,
        "snapshot_hash": digest({"case": case, "documents": docs}),
        "mode": "offline",
        "status": "QUEUED",
        "result": None,
    }
    monkeypatch.setattr(gateway, "request", lambda *a: deepcopy(job))
    case[field] = {"changed": True}
    assert gateway.latest(case, docs)["stale"] is False


@pytest.mark.parametrize(
    "field",
    ["version", "input", "policy_snapshot", "document_ids", "owner_id", "source", "snapshot"],
)
def test_changed_analysis_inputs_stale_job(gateway, monkeypatch, field):
    case, docs = snapshot()
    job = {
        "id": "JOB-test",
        "case_id": case["id"],
        "case_version": 2,
        "snapshot_hash": digest({"case": case, "documents": docs}),
        "mode": "offline",
        "status": "QUEUED",
        "result": None,
    }
    monkeypatch.setattr(gateway, "request", lambda *a: deepcopy(job))
    case[field] = 3 if field == "version" else "changed"
    assert gateway.latest(case, docs)["stale"] is True


def test_document_content_change_stales_job(gateway, monkeypatch):
    case, docs = snapshot()
    job = {
        "id": "JOB-test",
        "case_id": case["id"],
        "case_version": 2,
        "snapshot_hash": digest({"case": case, "documents": docs}),
        "mode": "offline",
        "status": "QUEUED",
    }
    monkeypatch.setattr(gateway, "request", lambda *a: deepcopy(job))
    docs[0]["sha256"] = "b" * 64
    assert gateway.latest(case, docs)["stale"] is True


@pytest.mark.parametrize(
    "change", ["id", "status", "mode", "hash", "result", "decision", "report_decision"]
)
def test_malformed_job_is_rejected(gateway, monkeypatch, change):
    case, docs = snapshot()
    job = {
        "id": "JOB-test",
        "case_id": case["id"],
        "case_version": 2,
        "snapshot_hash": digest({"case": case, "documents": docs}),
        "mode": "offline",
        "status": "COMPLETED",
        "result": {
            "report": {"decision": None},
            "trace": [],
            "usage": {},
            "review_state": "OFFLINE_EVIDENCE_ONLY",
            "decision": None,
            "human_final_decision_required": True,
        },
    }
    if change in {"id", "status", "mode"}:
        job[change] = []
    elif change == "hash":
        job["snapshot_hash"] = "invalid"
    elif change == "result":
        job["result"] = ["bad"]
    elif change == "decision":
        job["result"]["decision"] = "APPROVED"
    else:
        job["result"]["report"]["decision"] = "APPROVED"
    monkeypatch.setattr(gateway, "request", lambda *a: deepcopy(job))
    with pytest.raises(SandboxError):
        gateway.latest(case, docs)


def test_trusted_claim_requires_exact_processing_version_and_revision(gateway, monkeypatch):
    case, docs = snapshot()
    canonical = deepcopy(case)
    case.update(state="PROCESSING", active=True, revision=7)
    job = {
        "id": "JOB-test",
        "case_id": case["id"],
        "case_version": 2,
        "snapshot_hash": digest({"case": canonical, "documents": docs}),
        "status": "QUEUED",
        "mode": "offline",
    }
    bodies = []
    monkeypatch.setattr(gateway, "request", lambda m, p, b: bodies.append(b) or deepcopy(job))
    gateway.submit_claimed(case, docs, 2, "offline", "claimed-exact-key", claimed_revision=7)
    assert bodies[0]["case"] == canonical
    assert bodies[0]["idempotency_key"] == "claimed-exact-key"
    for version, revision in [(1, 7), (2, 6)]:
        with pytest.raises(SandboxError):
            gateway.submit_claimed(
                case, docs, version, "offline", "claimed-exact-key", claimed_revision=revision
            )
    case["state"] = "DRAFT"
    with pytest.raises(SandboxError):
        gateway.submit_claimed(case, docs, 2, "offline", "claimed-exact-key", claimed_revision=7)
    assert len(bodies) == 1


@pytest.mark.parametrize("change", ["job_id", "mode", "snapshot", "version", "missing"])
def test_exact_poll_rejects_other_job_or_snapshot(gateway, monkeypatch, change):
    case, docs = snapshot()
    job = {
        "id": "JOB-test",
        "case_id": case["id"],
        "case_version": 2,
        "snapshot_hash": digest({"case": case, "documents": docs}),
        "mode": "offline",
        "status": "QUEUED",
    }
    if change == "job_id":
        job["id"] = "JOB-other"
    elif change == "mode":
        job["mode"] = "typhoon"
    elif change == "snapshot":
        job["snapshot_hash"] = "b" * 64
    elif change == "version":
        job["case_version"] = 3
    else:
        job = None
    calls = []
    monkeypatch.setattr(gateway, "request", lambda method, path: calls.append(path) or job)
    with pytest.raises(SandboxError):
        gateway.get("JOB-test", case, docs, mode="offline")
    assert calls == ["/v1/reviews/JOB-test"]


def test_real_upload_never_gets_bundled_ocr_without_mock_boundary():
    from merchant_sandbox.review_gateway import review_documents

    raw = (ROOT / "examples/merchant_sandbox/documents/synthetic-statement.pdf").read_bytes()
    doc = {
        "id": "DOC-real-upload",
        "kind": "statement",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "ocr_pages": [],
    }

    class Uploaded:
        def list(self, case):
            return [deepcopy(doc)]

        def get(self, ident, *, raw=False):
            return (raw_bytes, doc)

    raw_bytes = raw
    actual = review_documents(Uploaded(), {"is_mock": False})[0]
    assert actual["ocr_pages"] == [] and "synthetic" not in actual
    assert base64.b64decode(actual["content_base64"]) == raw
    synthetic = review_documents(Uploaded(), {"is_mock": True})[0]
    assert synthetic["ocr_pages"] and synthetic["synthetic"] is True
    assert "content_base64" not in synthetic
