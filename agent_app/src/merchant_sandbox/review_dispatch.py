"""Bounded bridge from an accepted Android submit to evidence-only review.

No startup scanning or retries: Store.recover retains its existing behavior.
Persist the deterministic key before transport, then retain the exact job for
manual receipt recovery. Every write uses the worker's own CAS revision; loading
a newer case and saving the old result onto it is deliberately forbidden.
"""

from __future__ import annotations

import time
from copy import deepcopy

from .core import FINAL, MutationError, SandboxError, digest
from .review_gateway import analysis_snapshot, review_documents


def claim_key(case, mode):
    """Stable for this accepted claim, including submissions without a caller key."""
    return "android-review-" + digest(
        {"case": analysis_snapshot(case), "claim_revision": case["revision"], "mode": mode}
    )


class _ClaimLost(Exception):
    pass


class ReviewDispatcher:
    def __init__(
        self,
        store,
        documents,
        gateway,
        *,
        mode="typhoon",
        max_seconds=600,
        max_polls=1200,
        poll_interval=0.5,
    ):
        if (
            mode not in {"offline", "typhoon"}
            or type(max_polls) is not int
            or not 1 <= max_polls <= 1200
            or not 0 < max_seconds <= 600
            or not 0 <= poll_interval <= 5
        ):
            raise ValueError("invalid evidence dispatch bounds")
        self.store, self.documents, self.gateway = store, documents, gateway
        self.mode, self.max_seconds = mode, max_seconds
        self.max_polls, self.poll_interval = max_polls, poll_interval

    def _save(self, case):
        try:
            self.store.save(case)
        except SandboxError:
            raise _ClaimLost from None

    def _owns(self, case):
        current = self.store.get(case["id"])
        if (
            current["version"] != case["version"]
            or current["revision"] != case["revision"]
            or current["state"] != "PROCESSING"
            or current["active"] is not True
        ):
            raise _ClaimLost

    def _recovery_binding(self, case, record):
        command = record.get("command")
        decision = case.get("decision")
        if isinstance(decision, dict):
            decision = decision.get("status", decision.get("decision"))
        if (
            not isinstance(command, dict)
            or set(command) != {"case", "documents", "mode", "idempotency_key"}
            or record.get("case_version") != case["version"]
            or record.get("mode") != self.mode
            or command.get("mode") != record.get("mode")
            or command.get("idempotency_key") != record.get("idempotency_key")
            or command.get("case") != analysis_snapshot(case)
            or command.get("documents") != review_documents(self.documents, case)
            or not case.get("owner_id")
            or case.get("source") != "merchant_app"
            or not case["input"].get("consent")
            or case["state"] in FINAL
            or decision not in (None, "NEEDS_INFORMATION")
        ):
            raise MutationError(
                "Original command binding changed; recovery stopped",
                code="evidence_recovery_mismatch",
            )

    def accept_recovery(self, case_id, data):
        """Explicit operator action; the only replay is the original service body/key."""
        if not isinstance(data, dict) or set(data) != {
            "version",
            "revision",
            "mode",
            "idempotency_key",
        }:
            raise SandboxError("Recovery requires version, revision, original mode and key")
        case = self.store.get(case_id)
        record = (case.get("results") or {}).get("evidence_review") or {}
        self._recovery_binding(case, record)
        if record.get("recovery_request") == data:
            return case, False
        if (
            case["active"]
            or case["state"] != "TECHNICAL_REVIEW"
            or type(data["version"]) is not int
            or data["version"] != case["version"]
            or type(data["revision"]) is not int
            or data["revision"] != case["revision"]
            or data["mode"] != record["mode"]
            or data["idempotency_key"] != record["idempotency_key"]
        ):
            raise MutationError(
                "Recovery ownership/revision changed; reload the original receipt",
                code="evidence_recovery_mismatch",
            )
        record["recovery_request"] = deepcopy(data)
        case.update(active=True, state="PROCESSING")
        # CAS covers document/owner/consent/version races after binding validation.
        self.store.save(case)
        return case, True

    def run(self, claimed, *, recovery=False):
        case = deepcopy(claimed)
        if case.get("active") is not True or case.get("state") != "PROCESSING":
            return None
        record = (
            deepcopy(case["results"]["evidence_review"])
            if recovery
            else {
                "idempotency_key": claim_key(case, self.mode),
                "claim_revision": case["revision"],
                "case_version": case["version"],
                "mode": self.mode,
                "job_id": None,
                "status": "SUBMITTING",
            }
        )
        try:
            self._owns(case)
            documents = review_documents(self.documents, case)
            if recovery:
                self._recovery_binding(case, record)
            else:
                record["command"] = {
                    "case": analysis_snapshot(case),
                    "documents": deepcopy(documents),
                    "mode": self.mode,
                    "idempotency_key": record["idempotency_key"],
                }
            # Own checkpoint, no legacy approval data in an evidence-only run.
            case.update(results={"evidence_review": record}, packet=None)
            self._save(case)
            self._owns(case)
            job = self.gateway.replay_claimed(
                case,
                record["command"],
                claimed_revision=case["revision"],
            )
            if record.get("job_id") and job["id"] != record["job_id"]:
                raise SandboxError("Original job pointer mismatch; recovery stopped")
            record.update(
                job_id=job["id"], status=job["status"], snapshot_hash=job["snapshot_hash"]
            )
            self._save(case)
            deadline = time.monotonic() + self.max_seconds
            for _ in range(self.max_polls):
                if job["status"] in {"COMPLETED", "FAILED", "INTERRUPTED"}:
                    break
                if time.monotonic() >= deadline:
                    break
                self._owns(case)
                if self.poll_interval:
                    time.sleep(min(self.poll_interval, max(0, deadline - time.monotonic())))
                job = self.gateway.get(job["id"], case, documents, mode=self.mode)
            self._owns(case)
            record.update(
                status=job["status"], job_id=job["id"], snapshot_hash=job["snapshot_hash"]
            )
            result = job.get("result")
            if job["status"] != "COMPLETED":
                record["dispatch_state"] = (
                    "POLL_LIMIT" if job["status"] in {"QUEUED", "RUNNING"} else job["status"]
                )
                return self._technical(case)
            record["review_state"] = result["review_state"]
            record["result"] = deepcopy(result)
            if result["review_state"] == "TECHNICAL_REVIEW":
                return self._technical(case)
            case["packet"] = {
                "case_id": case["id"],
                "case_version": case["version"],
                "snapshot": case["snapshot"],
                "input_hash": case["input_hash"],
                "policy_sha256": digest(case["policy_snapshot"]),
                "policy_version": case["policy_snapshot"].get("policy_version"),
                "recommendation": "EXCEPTION_REVIEW",
                "financial": None,
                "assessment": None,
                "decision": None,
                "human_final_decision_required": True,
                "is_mock": case["is_mock"],
                "scope": "EVIDENCE_ASSISTANT_ONLY",
                "evidence_review": {
                    k: deepcopy(v)
                    for k, v in record.items()
                    if k not in {"result", "command", "recovery_request"}
                },
                "report": deepcopy(result["report"]),
            }
            case.update(
                active=False,
                state="EXCEPTION_REVIEW",
                feedback=["ผลตรวจหลักฐานพร้อมให้เจ้าหน้าที่ตรวจทาน ยังไม่มีผลประเมินกำลังชำระหรือคำตัดสินสินเชื่อ"],
            )
            self._save(case)
            return case
        except _ClaimLost:
            # No fresh revision is borrowed to save a late answer or error.
            return None
        except (SandboxError, OSError, ValueError, TypeError):
            record["dispatch_state"] = "TRANSPORT_OR_VALIDATION_UNCERTAIN"
            try:
                return self._technical(case)
            except _ClaimLost:
                return None

    def _technical(self, case):
        case.update(
            active=False,
            state="TECHNICAL_REVIEW",
            packet=None,
            feedback=[
                "งานตรวจหลักฐานยังไม่สำเร็จ ตรวจสถานะงานและ receipt เดิมด้วย key เดิมก่อนส่งคำสั่งซ้ำ ไม่มีคำตัดสินสินเชื่อ"
            ],
        )
        self._save(case)
        return case
