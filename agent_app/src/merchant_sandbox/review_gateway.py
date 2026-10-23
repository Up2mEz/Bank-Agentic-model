"""Versioned Case API snapshots sent to the isolated evidence-review service."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from .core import FINAL, ROOT, MutationError, SandboxError, digest, require_resolved_evidence_review

SAMPLES = ROOT / "examples/merchant_sandbox/documents"


def analysis_snapshot(case):
    """Copy immutable analysis inputs, never the case's operational state.

    One envelope is used for POST and stale checks. Lifecycle, revision, feedback,
    decisions and prior results must not change its fingerprint. Eligibility is
    checked against the original case BEFORE normalizing this analysis envelope.
    """
    snapshot = {
        k: deepcopy(case[k])
        for k in (
            "id",
            "version",
            "snapshot",
            "created_at",
            "input",
            "input_hash",
            "policy_snapshot",
            "fixture_sha256",
            "source",
            "owner_id",
            "document_ids",
            "is_mock",
        )
        if k in case
    }
    snapshot.update(state="DRAFT", active=False, results={}, trace=[], decision=None)
    return snapshot


def sample_ocr(document):
    """Recorded synthetic text is permitted only for the exact bundled PDF."""
    if document.get("kind") != "statement":
        return None
    recorded = SAMPLES / "synthetic-statement.ocr.json"
    if not recorded.is_file():
        return None
    data = json.loads(recorded.read_text(encoding="utf-8"))
    expected = data["source_sha256"]
    if document.get("sha256") != expected:
        return None
    if hashlib.sha256((SAMPLES / "synthetic-statement.pdf").read_bytes()).hexdigest() != expected:
        raise SandboxError("ไฟล์ตัวอย่างเปลี่ยน ไม่ใช้ OCR ที่บันทึกไว้")
    return deepcopy(data["ocr_pages"])


def review_documents(documents, case):
    """Read only documents selected in the Case API snapshot, never file paths."""
    selected = deepcopy(documents.list(case))
    for item in selected:
        if not item.get("ocr_pages") and case.get("is_mock"):
            item["ocr_pages"] = sample_ocr(item) or []
            if item["ocr_pages"]:
                item["synthetic"] = True
        if not item.get("ocr_pages"):
            raw, stored = documents.get(item["id"], raw=True)
            if (
                stored["sha256"] != item["sha256"]
                or hashlib.sha256(raw).hexdigest() != item["sha256"]
            ):
                raise SandboxError("เนื้อหาเอกสารไม่ตรงกับ snapshot")
            item["content_base64"] = base64.b64encode(raw).decode("ascii")
    return selected


class ReviewGateway:
    def __init__(self, base_url="", token=""):
        self.base_url, self._token = base_url.rstrip("/"), token
        if self.base_url:
            parsed = urlparse(self.base_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or len(token) < 32
            ):
                raise ValueError("Agent service ต้องใช้ URL และ service token อย่างน้อย 32 ตัวอักษร")

    @classmethod
    def load(cls, base_url, token_file=None):
        import os

        token = (
            Path(token_file).read_text(encoding="utf-8").strip()
            if token_file
            else os.environ.get("AGENT_SERVICE_TOKEN", "")
        )
        return cls(base_url or os.environ.get("AGENT_SERVICE_URL", ""), token)

    @property
    def configured(self):
        return bool(self.base_url and self._token)

    def request(self, method, path, body=None):
        if not self.configured:
            raise SandboxError("ยังไม่ได้เชื่อม Agent service")
        try:
            response = requests.request(
                method,
                self.base_url + path,
                headers={"Authorization": "Bearer " + self._token},
                json=body,
                timeout=(3, 8),
                allow_redirects=False,
            )
        except requests.RequestException:
            raise SandboxError("ติดต่อ Agent service ไม่ได้ กรุณาตรวจสถานะบริการแล้วลองคำสั่งเดิม") from None
        if method == "GET" and response.status_code == 404:
            return None
        if response.status_code not in {200, 201, 202}:
            raise MutationError(
                f"Agent service HTTP {response.status_code}; ยังไม่มีผลตรวจที่ใช้ได้",
                code="agent_service_rejected",
                status=409 if response.status_code in {409, 422} else 503,
            )
        try:
            if len(response.content) > 8_000_000:
                raise ValueError
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, TypeError):
            raise SandboxError("Agent service ส่งผลไม่ครบ กรุณาตรวจผลคำสั่งเดิม") from None

    def capabilities(self):
        result = {
            "configured": self.configured,
            "available": False,
            "modes": [],
            "typhoon_configured": False,
        }
        if self.configured:
            try:
                ready = self.request("GET", "/readyz") or {}
                result.update(
                    available=bool(ready.get("ready")),
                    modes=ready.get("modes", []),
                    typhoon_configured=bool(ready.get("typhoon_configured")),
                )
            except SandboxError:
                pass
        return result

    @staticmethod
    def _check_job(job, case, documents, *, current=False):
        if (
            not isinstance(job, dict)
            or not isinstance(job.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job["id"])
            or job.get("case_id") != case["id"]
            or type(job.get("case_version")) is not int
            or job["case_version"] < 1
            or not isinstance(job.get("snapshot_hash"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", job["snapshot_hash"])
            or not isinstance(job.get("status"), str)
            or job["status"] not in {"QUEUED", "RUNNING", "COMPLETED", "FAILED", "INTERRUPTED"}
            or not isinstance(job.get("mode"), str)
            or job["mode"] not in {"offline", "typhoon"}
        ):
            raise SandboxError("ผล Agent service ไม่ตรงกับเจ้าของเคส")
        stale = job["case_version"] != case["version"] or job["snapshot_hash"] != digest(
            {"case": analysis_snapshot(case), "documents": documents}
        )
        if current and stale:
            raise SandboxError("Agent service รับ snapshot คนละรุ่น กรุณาตรวจผลเดิม")
        result = job.get("result")
        if (job["status"] == "COMPLETED" and result is None) or (
            result is not None
            and (
                not isinstance(result, dict)
                or result.get("decision", True) is not None
                or result.get("human_final_decision_required") is not True
                or not isinstance(result.get("report"), dict)
                or result["report"].get("decision", True) is not None
                or not isinstance(result.get("trace"), list)
                or not isinstance(result.get("usage"), dict)
                or not isinstance(result.get("review_state"), str)
                or not result["review_state"]
            )
        ):
            raise SandboxError("ผลตรวจต้องส่งต่อให้เจ้าหน้าที่ตัดสินใจ")
        return {**job, "stale": stale}

    def _submit(self, case, documents, version, mode, key, *, claimed_revision=None):
        claimed = claimed_revision is not None
        decision = case.get("decision")
        if isinstance(decision, dict):
            decision = decision.get("status", decision.get("decision"))
        if (
            type(version) is not int
            or version != case["version"]
            or not case["input"].get("consent")
            or (not claimed and (case.get("active") or case["state"] == "PROCESSING"))
            or (
                claimed
                and (
                    type(claimed_revision) is not int
                    or case.get("revision") != claimed_revision
                    or case.get("active") is not True
                    or case["state"] != "PROCESSING"
                )
            )
            or case["state"] in FINAL
            or decision not in (None, "NEEDS_INFORMATION")
            or not any(d.get("kind") == "statement" for d in documents)
            or not isinstance(mode, str)
            or mode not in {"offline", "typhoon"}
            or not isinstance(key, str)
            or not 8 <= len(key) <= 100
        ):
            raise SandboxError("ตรวจ consent รุ่นคำขอ และ statement ก่อนเริ่ม Agent service")
        job = self.request(
            "POST",
            "/v1/reviews",
            {
                "case": analysis_snapshot(case),
                "documents": documents,
                "mode": mode,
                "idempotency_key": key,
            },
        )
        self._check_job(job, case, documents, current=True)
        if job["mode"] != mode:
            raise SandboxError("Agent service ส่งโหมดไม่ตรงกับคำสั่งเดิม")
        return job

    def submit(self, case, documents, version, mode, key):
        require_resolved_evidence_review(case)
        return self._submit(case, documents, version, mode, key)

    def replay_claimed(self, case, command, *, claimed_revision):
        """Replay the persisted body verbatim after validating the owned binding."""
        if command.get("case") != analysis_snapshot(case):
            raise SandboxError("snapshot คำสั่งเดิมไม่ตรงกับเคส หยุดการกู้คืน")
        # _submit constructs exactly this canonical body and enforces consent,
        # final human decision and the active worker's CAS ownership.
        return self._submit(
            case,
            command["documents"],
            case["version"],
            command["mode"],
            command["idempotency_key"],
            claimed_revision=claimed_revision,
        )

    def submit_claimed(self, case, documents, version, mode, key, *, claimed_revision):
        """Trusted worker entry for an already receipted PROCESSING claim only."""
        return self._submit(case, documents, version, mode, key, claimed_revision=claimed_revision)

    def get(self, job_id, case, documents, *, mode):
        """Poll the accepted job, never whichever job happens to be latest."""
        if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            raise SandboxError("รหัสงาน Agent service ไม่ถูกต้อง")
        job = self.request("GET", "/v1/reviews/" + quote(job_id, safe=""))
        checked = self._check_job(job, case, documents, current=True)
        if checked["id"] != job_id or checked["mode"] != mode:
            raise SandboxError("Agent service ส่งงานไม่ตรงกับคำสั่งเดิม")
        return checked

    def latest(self, case, documents):
        job = self.request("GET", "/v1/cases/" + quote(case["id"], safe="") + "/review")
        if job is None:
            return {
                "status": "NOT_STARTED",
                "case_id": case["id"],
                "case_version": case["version"],
                "stale": False,
                "result": None,
            }
        return self._check_job(job, case, documents)
