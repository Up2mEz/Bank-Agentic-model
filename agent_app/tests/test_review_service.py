"""Persisted review jobs against synthetic snapshots and injected offline runners."""

import base64
import importlib
import importlib.util
import io
import json
import threading
from copy import deepcopy
from hashlib import sha256

import pytest
from PIL import Image

from merchant_sandbox.core import PARAMS, default_input, digest


def service_module():
    assert importlib.util.find_spec("merchant_sandbox.review_service"), "Review service missing"
    return importlib.import_module("merchant_sandbox.review_service")


def payload():
    data = default_input()
    data.update(applicant_name="Mali Jaidee", message="Please review the supplied documents")
    case = {
        "id": "CASE-service",
        "version": 2,
        "snapshot": "CASE-service:v2",
        "created_at": "2026-10-24T00:00:00+00:00",
        "state": "DRAFT",
        "active": False,
        "input": data,
        "input_hash": digest(data),
        "document_ids": ["DOC-service"],
        "policy_snapshot": json.loads(PARAMS.read_text(encoding="utf-8")),
        "results": {},
        "trace": [],
        "is_mock": True,
    }
    text = (
        "Account holder: Mali Jaidee\nAccount: TEST-A\n"
        "Period: 2026-04-01 to 2026-09-30\nOpening balance: 1000.00\n"
        "| Date | Description | Debit | Credit | Balance |\n"
        "|---|---|---|---|---|\n"
        "| 2026-04-01 | Unverified receipt | 0 | 100 | 1100 |\n"
        "Closing balance: 1100.00"
    )
    doc = {
        "id": "DOC-service",
        "case_id": case["id"],
        "kind": "statement",
        "filename": "synthetic.pdf",
        "mime_type": "application/pdf",
        "size": 123,
        "pages": 1,
        "sha256": sha256(b"synthetic-original").hexdigest(),
        "ocr_pages": [{"page": 1, "text": text, "model": "synthetic-replay"}],
    }
    return {
        "case": case,
        "documents": [doc],
        "mode": "offline",
        "idempotency_key": "review-key-0001",
    }


def result():
    return {
        "report": {"sections": {}, "decision": None},
        "trace": [],
        "usage": {},
        "review_state": "OFFLINE_EVIDENCE_ONLY",
        "decision": None,
        "human_final_decision_required": True,
    }


def test_snapshot_fingerprint_and_idempotent_replay_survive_restart(tmp_path):
    m = service_module()
    path = tmp_path / "jobs.sqlite"
    body = payload()
    with m.ReviewService(path, runner=lambda p: result()) as service:
        job = service.submit(body)
        assert set(job) == {
            "id",
            "case_id",
            "case_version",
            "snapshot_hash",
            "mode",
            "status",
            "stage",
            "created_at",
            "updated_at",
            "result",
            "error",
        }
        assert job["snapshot_hash"] == digest(
            {"case": body["case"], "documents": body["documents"]}
        )
        reordered = json.loads(json.dumps(body, sort_keys=True))
        assert service.submit(reordered)["id"] == job["id"]
        service.process_next()
        assert service.get(job["id"])["status"] == "COMPLETED"
    with m.ReviewService(path, runner=lambda p: pytest.fail("replay must not execute")) as service:
        assert service.submit(body)["id"] == job["id"]
        assert not service.process_next()
        assert service.latest("CASE-service")["id"] == job["id"]


def test_key_conflicts_include_mode_but_snapshot_hash_excludes_it(tmp_path):
    m = service_module()
    with m.ReviewService(tmp_path / "jobs", runner=lambda p: result()) as service:
        body = payload()
        first = service.submit(body)
        body["mode"] = "typhoon"
        with pytest.raises(m.ReviewError) as exc:
            service.submit(body)
        assert exc.value.status == 409
        body["idempotency_key"] = "review-key-0002"
        second = service.submit(body)
        assert first["snapshot_hash"] == second["snapshot_hash"]
        assert first["id"] != second["id"]
        assert service.latest("CASE-service")["id"] == second["id"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(mode="unknown"),
        lambda p: p.update(extra=True),
        lambda p: p.update(idempotency_key="short"),
        lambda p: p["case"].update(version=True),
        lambda p: p["case"].update(version=0),
        lambda p: p["case"].update(snapshot="CASE-service:v1"),
        lambda p: p["case"].update(input_hash="a" * 64),
        lambda p: p["case"].update(active=True),
        lambda p: p["case"].update(state="APPROVED"),
        lambda p: p["case"].update(decision="DECLINED"),
        lambda p: p["case"].update(decision={"status": "APPROVED", "reason": "human final"}),
        lambda p: p["case"]["input"].update(consent=False),
        lambda p: p["case"].update(document_ids=["DOC-missing"]),
        lambda p: p["documents"][0].update(case_id="CASE-other"),
        lambda p: p["documents"][0].update(sha256="bad"),
        lambda p: p["documents"][0].update(pages=True),
        lambda p: p["documents"][0].update(pages=9),
        lambda p: p["documents"][0].update(ocr_pages=[]),
        lambda p: p["documents"][0]["ocr_pages"][0].update(page=2),
        lambda p: p["documents"][0]["ocr_pages"][0].update(text=""),
        lambda p: p["documents"][0].update(content_base64=base64.b64encode(b"wrong").decode()),
        lambda p: p["documents"].append(deepcopy(p["documents"][0])),
        lambda p: p.update(documents=[]),
    ],
)
def test_invalid_snapshot_never_enters_queue(tmp_path, mutation):
    m = service_module()
    with m.ReviewService(
        tmp_path / "jobs", runner=lambda p: pytest.fail("invalid enqueue")
    ) as service:
        body = payload()
        mutation(body)
        with pytest.raises(m.ReviewError) as exc:
            service.submit(body)
        assert exc.value.status == 400
        assert not service.process_next()


def test_payload_and_result_bounds_keep_durable_replays(tmp_path):
    m = service_module()
    with m.ReviewService(tmp_path / "small", runner=lambda p: result(), max_payload_bytes=100) as s:
        with pytest.raises(m.ReviewError) as exc:
            s.submit(payload())
        assert exc.value.status == 413
    with m.ReviewService(tmp_path / "jobs", runner=lambda p: result(), max_jobs=1) as s:
        first = s.submit(payload())
        assert s.submit(payload())["id"] == first["id"]
        s.process_next()
        other = payload()
        other["idempotency_key"] = "review-key-other"
        with pytest.raises(m.ReviewError) as exc:
            s.submit(other)
        assert exc.value.status == 503
        assert s.get(first["id"])["status"] == "COMPLETED"


def test_queue_bound_and_concurrent_same_key_only_execute_once(tmp_path):
    m = service_module()
    calls, jobs = [], []
    with m.ReviewService(
        tmp_path / "jobs", runner=lambda p: calls.append(p) or result(), max_queued=1
    ) as s:
        threads = [
            threading.Thread(target=lambda: jobs.append(s.submit(payload())["id"]))
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(jobs) == 8 and len(set(jobs)) == 1
        other = payload()
        other["idempotency_key"] = "review-key-other"
        with pytest.raises(m.ReviewError) as exc:
            s.submit(other)
        assert exc.value.status == 503
        s.process_next()
        assert len(calls) == 1


def test_running_is_interrupted_on_restart_queued_resumes_without_paid_retry(tmp_path):
    m = service_module()
    path = tmp_path / "jobs"
    with m.ReviewService(path, runner=lambda p: result()) as s:
        first = s.submit(payload())
        # A killed process leaves a committed RUNNING receipt before the runner.
        with s._db:
            s._db.execute(
                "UPDATE review_jobs SET status='RUNNING',stage='REVIEW' WHERE id=?", (first["id"],)
            )
        other = payload()
        other["idempotency_key"] = "review-key-other"
        second = s.submit(other)
    with m.ReviewService(path, runner=lambda p: result()) as s:
        interrupted = s.get(first["id"])
        assert interrupted["status"] == "INTERRUPTED"
        assert interrupted["error"]["code"] == "PROCESS_INTERRUPTED"
        assert s.submit(payload())["id"] == first["id"]
        s.process_next()
        assert s.get(second["id"])["status"] == "COMPLETED"
        assert s.get(first["id"])["status"] == "INTERRUPTED"
        assert not s.process_next()


def test_failure_is_safe_persisted_and_never_retried(tmp_path):
    m = service_module()

    def failing(p):
        raise RuntimeError("secret-value raw provider body")

    with m.ReviewService(tmp_path / "jobs", runner=failing) as s:
        job = s.submit(payload())
        s.process_next()
        failed = s.get(job["id"])
        assert failed["status"] == "FAILED" and failed["result"] is None
        assert "secret-value" not in json.dumps(failed)
        assert s.submit(payload())["status"] == "FAILED"
        assert not s.process_next()


def test_no_implicit_worker_and_worker_is_single_and_stoppable(tmp_path):
    m = service_module()
    ran = threading.Event()
    with m.ReviewService(tmp_path / "jobs", runner=lambda p: ran.set() or result()) as s:
        job = s.submit(payload())
        assert not ran.is_set() and s.get(job["id"])["status"] == "QUEUED"
        s.start_worker()
        s.start_worker()
        assert ran.wait(3)
        s.stop_worker()
        assert s.get(job["id"])["status"] == "COMPLETED"


def test_snapshot_stored_before_processing_and_runner_cannot_mutate_receipt(tmp_path):
    m = service_module()
    body = payload()
    expected = digest({"case": body["case"], "documents": body["documents"]})

    def mutate(p):
        p["case"]["version"] = 77
        p["documents"].clear()
        return result()

    with m.ReviewService(tmp_path / "jobs", runner=mutate) as s:
        job = s.submit(body)
        s.process_next()
        assert s.get(job["id"])["snapshot_hash"] == expected
        assert s.submit(body)["id"] == job["id"]


@pytest.mark.parametrize(
    "bad_result", [None, {**result(), "decision": "APPROVED"}, {**result(), "trace": "bad"}]
)
def test_invalid_runner_output_is_failed(tmp_path, bad_result):
    m = service_module()
    with m.ReviewService(tmp_path / "jobs", runner=lambda p: bad_result) as s:
        job = s.submit(payload())
        s.process_next()
        assert s.get(job["id"])["status"] == "FAILED"


def test_snapshot_fingerprint_includes_original_bytes_before_runner_strips_them(tmp_path):
    m = service_module()
    body = payload()
    stream = io.BytesIO()
    Image.new("RGB", (2, 2)).save(stream, format="PNG")
    raw = stream.getvalue()
    doc = body["documents"][0]
    doc.update(
        content_base64=base64.b64encode(raw).decode(),
        sha256=sha256(raw).hexdigest(),
        size=len(raw),
        mime_type="image/png",
        ocr_pages=[],
    )
    body["mode"] = "typhoon"
    expected = digest({"case": body["case"], "documents": body["documents"]})

    def strip_content(p):
        p["documents"][0].pop("content_base64")
        return result()

    with m.ReviewService(tmp_path / "jobs", runner=strip_content) as s:
        job = s.submit(body)
        assert job["snapshot_hash"] == expected
        s.process_next()
        assert s.submit(body)["snapshot_hash"] == expected
        with s._lock:
            stored = json.loads(s._db.execute("SELECT payload FROM review_jobs").fetchone()[0])
        assert stored["documents"][0]["content_base64"] == base64.b64encode(raw).decode()


def test_result_byte_limit_fails_without_storing_unbounded_output(tmp_path):
    m = service_module()
    large = result()
    large["trace"] = [{"text": "x" * 1024}]
    with m.ReviewService(tmp_path / "jobs", runner=lambda p: large, max_result_bytes=512) as s:
        job = s.submit(payload())
        s.process_next()
        failed = s.get(job["id"])
        assert failed["status"] == "FAILED" and failed["result"] is None


@pytest.mark.parametrize("failure", ["size", "validation"])
def test_runner_result_rejection_preserves_only_normalized_known_usage(tmp_path, failure):
    m = service_module()
    out = result()
    out["usage"] = {
        "provider_calls": 2,
        "ocr_calls": 1,
        "agent_calls": 1,
        "secret": "private-provider-body",
        "records": [
            {"kind": "ocr", "usage": {"total_tokens": 11, "raw": "private-provider-body"}},
            {"kind": "agent", "usage": {}},
        ],
    }
    if failure == "size":
        out["trace"] = [{"private": "x" * 1024}]
    else:
        out["decision"] = "INVALID"
    with m.ReviewService(tmp_path / "jobs", runner=lambda _: out, max_result_bytes=512) as service:
        job = service.submit(payload())
        service.process_next()
        failed = service.get(job["id"])
    usage = failed["error"]["usage"]
    assert failed["status"] == "FAILED" and usage["provider_calls"] == 2
    assert usage["records"][0]["usage"]["total_tokens"] == 11
    assert usage["total_tokens"] is None
    assert "private-provider-body" not in str(failed)


def test_default_service_runner_completes_offline_without_loading_provider(tmp_path, monkeypatch):
    m = service_module()
    from merchant_sandbox.typhoon import Config

    monkeypatch.setattr(Config, "load", lambda *a, **k: pytest.fail("provider credentials read"))
    with m.ReviewService(tmp_path / "jobs") as s:
        job = s.submit(payload())
        s.process_next()
        done = s.get(job["id"])
        assert done["status"] == "COMPLETED"
        assert done["result"]["model_execution"] == "NOT_RUN_OFFLINE_SUPPLIED_OCR"


def test_parallel_consumers_cannot_execute_two_jobs_at_once(tmp_path):
    m = service_module()
    started, release = threading.Event(), threading.Event()
    calls = []

    def blocked(p):
        calls.append(p)
        started.set()
        assert release.wait(3)
        return result()

    with m.ReviewService(tmp_path / "jobs", runner=blocked) as s:
        first = s.submit(payload())
        other = payload()
        other["idempotency_key"] = "review-key-other"
        second = s.submit(other)
        worker = threading.Thread(target=s.process_next)
        worker.start()
        try:
            assert started.wait(3)
            assert s.get(first["id"])["status"] == "RUNNING"
            assert s.process_next() is False
            assert s.get(second["id"])["status"] == "QUEUED"
        finally:
            release.set()
            worker.join()
        assert len(calls) == 1
