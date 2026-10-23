"""Bounded, single-process evidence-review queue; owns no case or lending state.

One service instance owns each SQLite file. Construction recovers interrupted
jobs, but never starts a worker or calls a provider. Retention is fail-closed:
when full, reject new jobs rather than discard exact idempotency receipts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from copy import deepcopy
from pathlib import Path

from .core import FINAL, SandboxError, digest, now, validate_input
from .ocr import MAX_FILE_BYTES, MIMES, inspect_document

MAX_PAYLOAD_BYTES = 48 * 1024 * 1024
MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_OCR_TEXT = 200_000


class ReviewError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


class ReviewExecutionFailure(Exception):
    """Pipeline failure carrying only normalized provider call/token counts."""

    def __init__(self, usage, *, trace=None):
        super().__init__("REVIEW_EXECUTION_FAILED")
        self.usage = normalize_usage(usage)
        self.trace = deepcopy(trace or [])


def normalize_usage(value):
    """Never persist arbitrary runner/provider fields on the failure path."""
    if not isinstance(value, dict):
        return {}
    out = {
        k: value[k]
        for k in ("provider_calls", "ocr_calls", "agent_calls")
        if type(value.get(k)) is int and value[k] >= 0
    }
    records = []
    for record in value.get("records", []) if isinstance(value.get("records"), list) else []:
        if not isinstance(record, dict) or record.get("kind") not in {"ocr", "agent"}:
            continue
        usage = record.get("usage") or {}
        records.append(
            {
                "kind": record["kind"],
                "usage": {
                    k: usage[k]
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if isinstance(usage, dict) and type(usage.get(k)) is int and usage[k] >= 0
                },
            }
        )
    out["records"] = records
    totals = [r["usage"].get("total_tokens") for r in records]
    if records:
        out["total_tokens"] = sum(totals) if all(type(t) is int for t in totals) else None
    else:
        total = value.get("total_tokens")
        out["total_tokens"] = (
            total
            if type(total) is int and total >= 0
            else 0
            if out.get("provider_calls") == 0
            else None
        )
    return out


def _require(condition, code):
    if not condition:
        raise ReviewError(code)


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value)


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise ReviewError("INVALID_JSON") from None


def validate_payload(payload: dict, *, max_payload_bytes: int = MAX_PAYLOAD_BYTES) -> dict:
    """Validate and copy the exact snapshot, without normalization or OCR mutation.

    Required envelope: case/documents/mode/idempotency_key only. Case is a raw
    Store snapshot (id/version/snapshot/input/state/active/created_at/policy_snapshot,
    results and trace); optional input_hash and document_ids must agree when sent.
    Documents use Documents.list metadata plus optional content_base64. Every doc
    needs id/case_id/kind/filename/mime_type/sha256/size/pages/ocr_pages. OCR may be
    partial only in typhoon mode with the exact original bytes supplied.
    """
    encoded = _json(payload)
    if len(encoded.encode("utf-8")) > max_payload_bytes:
        raise ReviewError("PAYLOAD_TOO_LARGE", 413)
    _require(
        isinstance(payload, dict)
        and set(payload)
        == {
            "case",
            "documents",
            "mode",
            "idempotency_key",
        },
        "INVALID_ENVELOPE",
    )
    _require(payload["mode"] in ("offline", "typhoon"), "INVALID_MODE")
    key = payload["idempotency_key"]
    _require(isinstance(key, str) and 8 <= len(key) <= 100 and bool(key.strip()), "INVALID_KEY")
    case, docs = payload["case"], payload["documents"]
    _require(isinstance(case, dict), "INVALID_CASE")
    _require(_identifier(case.get("id")), "INVALID_CASE_ID")
    version = case.get("version")
    _require(type(version) is int and 1 <= version <= 2**53 - 1, "INVALID_VERSION")
    _require(case.get("snapshot") == f"{case['id']}:v{version}", "SNAPSHOT_VERSION_MISMATCH")
    _require(
        isinstance(case.get("state"), str)
        and case["state"] not in FINAL
        and case["state"] != "PROCESSING"
        and case.get("active") is False,
        "CASE_UNAVAILABLE",
    )
    decision = case.get("decision")
    if isinstance(decision, dict):
        decision = decision.get("status", decision.get("decision", "UNKNOWN"))
    _require(decision in (None, "NEEDS_INFORMATION"), "CASE_FINAL")
    try:
        validate_input(case.get("input"))
    except (SandboxError, TypeError, KeyError):
        raise ReviewError("INVALID_CASE_INPUT") from None
    _require(case["input"]["consent"] is True, "CONSENT_REQUIRED")
    if "input_hash" in case:
        _require(case["input_hash"] == digest(case["input"]), "INPUT_HASH_MISMATCH")
    _require(
        isinstance(case.get("created_at"), str) and 1 <= len(case["created_at"]) <= 80,
        "INVALID_CASE_TIMESTAMP",
    )
    _require(
        isinstance(case.get("policy_snapshot"), dict) and bool(case["policy_snapshot"]),
        "POLICY_SNAPSHOT_REQUIRED",
    )
    _require(
        isinstance(case.get("results"), dict) and isinstance(case.get("trace"), list),
        "INVALID_CASE_OBSERVATIONS",
    )
    _require(isinstance(docs, list) and 1 <= len(docs) <= 8, "INVALID_DOCUMENT_COUNT")
    ids, total_pages = [], 0
    for doc in docs:
        _require(isinstance(doc, dict), "INVALID_DOCUMENT")
        _require(_identifier(doc.get("id")) and doc["id"] not in ids, "INVALID_DOCUMENT_ID")
        ids.append(doc["id"])
        _require(doc.get("case_id") == case["id"], "DOCUMENT_SCOPE_MISMATCH")
        if "case_version" in doc:
            _require(
                type(doc["case_version"]) is int and doc["case_version"] == version,
                "DOCUMENT_VERSION_MISMATCH",
            )
        _require(doc.get("kind") in ("identity", "statement", "business"), "INVALID_DOCUMENT_KIND")
        _require(
            isinstance(doc.get("filename"), str) and 1 <= len(doc["filename"]) <= 180,
            "INVALID_FILENAME",
        )
        _require(doc.get("mime_type") in tuple(MIMES), "INVALID_MIME")
        _require(
            isinstance(doc.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", doc["sha256"]),
            "INVALID_DOCUMENT_HASH",
        )
        _require(
            type(doc.get("size")) is int and 1 <= doc["size"] <= MAX_FILE_BYTES,
            "INVALID_DOCUMENT_SIZE",
        )
        _require(type(doc.get("pages")) is int and 1 <= doc["pages"] <= 8, "INVALID_PAGE_COUNT")
        total_pages += doc["pages"]
        _require(total_pages <= 8, "CASE_PAGE_LIMIT")
        ocr = doc.get("ocr_pages")
        _require(isinstance(ocr, list) and len(ocr) <= doc["pages"], "INVALID_OCR")
        seen = set()
        for page in ocr:
            _require(isinstance(page, dict), "INVALID_OCR")
            n = page.get("page")
            _require(
                type(n) is int and 1 <= n <= doc["pages"] and n not in seen, "INVALID_OCR_PAGE"
            )
            _require(
                isinstance(page.get("text"), str)
                and 1 <= len(page["text"]) <= MAX_OCR_TEXT
                and bool(page["text"].strip()),
                "INVALID_OCR_TEXT",
            )
            seen.add(n)
        if payload["mode"] == "offline":
            _require(len(seen) == doc["pages"], "OFFLINE_OCR_REQUIRED")
        if "content_base64" in doc:
            content = doc["content_base64"]
            _require(
                isinstance(content, str) and len(content) <= 4 * ((MAX_FILE_BYTES + 2) // 3),
                "INVALID_CONTENT",
            )
            try:
                raw = base64.b64decode(content, validate=True)
            except (ValueError, TypeError):
                raise ReviewError("INVALID_BASE64") from None
            _require(
                len(raw) == doc["size"] and 0 < len(raw) <= MAX_FILE_BYTES, "CONTENT_SIZE_MISMATCH"
            )
            _require(hashlib.sha256(raw).hexdigest() == doc["sha256"], "CONTENT_HASH_MISMATCH")
            try:
                pages = inspect_document(raw, doc["mime_type"])
            except SandboxError:
                raise ReviewError("INVALID_DOCUMENT_CONTENT") from None
            _require(pages == doc["pages"], "CONTENT_PAGE_MISMATCH")
        elif len(seen) != doc["pages"]:
            raise ReviewError("OCR_CONTENT_REQUIRED")
    if "document_ids" in case:
        _require(case["document_ids"] == ids, "DOCUMENT_MANIFEST_MISMATCH")
    return deepcopy(payload)


class ReviewService:
    """Explicit lifecycle. Runner signature: runner(accepted_payload) -> result dict."""

    def __init__(
        self,
        path: str | Path,
        *,
        runner=None,
        max_jobs=128,
        max_queued=16,
        max_payload_bytes=MAX_PAYLOAD_BYTES,
        max_result_bytes=MAX_RESULT_BYTES,
    ):
        for bound in (max_jobs, max_queued, max_payload_bytes, max_result_bytes):
            if type(bound) is not int or bound < 1:
                raise ValueError("positive service bounds required")
        if runner is None:
            from .review_pipeline import ReviewPipeline

            runner = ReviewPipeline()
        self.runner = runner
        self.max_jobs, self.max_queued = max_jobs, max_queued
        self.max_payload_bytes, self.max_result_bytes = max_payload_bytes, max_result_bytes
        self._lock, self._execution = threading.RLock(), threading.Lock()
        self._wake, self._stop = threading.Event(), threading.Event()
        self._worker = None
        self._closed = False
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS review_jobs (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
                case_id TEXT NOT NULL, case_version INTEGER NOT NULL, snapshot_hash TEXT NOT NULL,
                mode TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, result TEXT, error TEXT)""")
            self._db.execute("CREATE INDEX IF NOT EXISTS review_case ON review_jobs(case_id,seq)")
            self._db.execute(
                "UPDATE review_jobs SET status='INTERRUPTED',stage='INTERRUPTED',"
                "updated_at=?,error=? WHERE status='RUNNING'",
                (now(), _json({"code": "PROCESS_INTERRUPTED"})),
            )

    @staticmethod
    def _job(row):
        return {
            k: json.loads(row[k]) if k in ("result", "error") and row[k] is not None else row[k]
            for k in (
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
            )
        }

    def submit(self, payload: dict) -> dict:
        accepted = validate_payload(payload, max_payload_bytes=self.max_payload_bytes)
        snapshot = {"case": accepted["case"], "documents": accepted["documents"]}
        fingerprint = digest({**snapshot, "mode": accepted["mode"]})
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            old = self._db.execute(
                "SELECT * FROM review_jobs WHERE key=?", (accepted["idempotency_key"],)
            ).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ReviewError("IDEMPOTENCY_CONFLICT", 409)
                return self._job(old)
            total, queued = self._db.execute(
                "SELECT COUNT(*),COALESCE(SUM(status IN ('QUEUED','RUNNING')),0) FROM review_jobs"
            ).fetchone()
            if total >= self.max_jobs or queued >= self.max_queued:
                raise ReviewError("QUEUE_CAPACITY", 503)
            ident, timestamp = "REV-" + uuid.uuid4().hex, now()
            self._db.execute(
                """INSERT INTO review_jobs
                (id,key,fingerprint,payload,case_id,case_version,snapshot_hash,mode,status,stage,
                 created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,'QUEUED','QUEUED',?,?)""",
                (
                    ident,
                    accepted["idempotency_key"],
                    fingerprint,
                    _json(accepted),
                    accepted["case"]["id"],
                    accepted["case"]["version"],
                    digest(snapshot),
                    accepted["mode"],
                    timestamp,
                    timestamp,
                ),
            )
        self._wake.set()
        return self.get(ident)

    def get(self, job_id: str) -> dict:
        with self._lock:
            row = self._db.execute("SELECT * FROM review_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise ReviewError("JOB_NOT_FOUND", 404)
            return self._job(row)

    def latest(self, case_id: str) -> dict:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM review_jobs WHERE case_id=? ORDER BY seq DESC LIMIT 1", (case_id,)
            ).fetchone()
            if row is None:
                raise ReviewError("JOB_NOT_FOUND", 404)
            return self._job(row)

    def process_next(self) -> bool:
        """Claim and commit before calling runner; never retry RUNNING/FAILED jobs."""
        if not self._execution.acquire(blocking=False):
            return False
        try:
            with self._lock, self._db:
                self._db.execute("BEGIN IMMEDIATE")
                row = self._db.execute(
                    "SELECT * FROM review_jobs WHERE status='QUEUED' ORDER BY seq LIMIT 1"
                ).fetchone()
                if row is None:
                    return False
                self._db.execute(
                    "UPDATE review_jobs SET status='RUNNING',stage='REVIEW',updated_at=? WHERE id=?",
                    (now(), row["id"]),
                )
            result = None
            try:
                result = self.runner(json.loads(row["payload"]))
                _require(
                    isinstance(result, dict)
                    and isinstance(result.get("report"), dict)
                    and isinstance(result.get("trace"), list)
                    and isinstance(result.get("usage"), dict)
                    and isinstance(result.get("review_state"), str)
                    and result.get("decision", True) is None
                    and result.get("human_final_decision_required") is True
                    and result["report"].get("decision", True) is None,
                    "INVALID_RUNNER_RESULT",
                )
                encoded = _json(result)
                _require(len(encoded.encode("utf-8")) <= self.max_result_bytes, "RESULT_TOO_LARGE")
                status, error = "COMPLETED", None
            except Exception as exc:
                # Exceptions may contain credentials, applicant data or provider bodies.
                failure = {"code": "REVIEW_EXECUTION_FAILED"}
                if isinstance(exc, ReviewExecutionFailure):
                    failure["usage"] = exc.usage
                    if exc.trace:
                        failure["trace"] = exc.trace
                elif isinstance(result, dict) and isinstance(result.get("usage"), dict):
                    failure["usage"] = normalize_usage(result["usage"])
                status, encoded, error = "FAILED", None, _json(failure)
            with self._lock, self._db:
                self._db.execute(
                    "UPDATE review_jobs SET status=?,stage=?,updated_at=?,result=?,error=? WHERE id=?",
                    (status, status, now(), encoded, error, row["id"]),
                )
            return True
        finally:
            self._execution.release()

    def start_worker(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("service closed")
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop.clear()
            self._worker = threading.Thread(target=self._work, name="evidence-review", daemon=True)
            self._worker.start()

    def _work(self):
        while not self._stop.is_set():
            self._wake.clear()
            if not self.process_next():
                self._wake.wait(0.5)

    def stop_worker(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._worker is not None:
            self._worker.join()

    def close(self) -> None:
        self.stop_worker()
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
