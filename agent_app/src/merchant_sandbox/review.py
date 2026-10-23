"""Local human review actions, never registered as Agent tools."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from decimal import Decimal

from .bank import validate_review
from .core import (
    FINAL,
    MutationError,
    SandboxError,
    assessment,
    digest,
    financial,
    now,
    require_resolved_evidence_review,
)
from .statements import normal_name, verify_statements


def staff_dossier(case, documents):
    """Read-only staff projection: references and calculations, no upload bytes/OCR prompt text."""
    out = {
        k: deepcopy(case[k])
        for k in (
            "id",
            "owner_id",
            "source",
            "version",
            "revision",
            "state",
            "created_at",
            "input",
            "snapshot",
            "results",
            "packet",
            "feedback",
            "trace",
            "active",
            "is_mock",
            "policy_snapshot",
        )
        if k in case
    }
    out["decision"] = deepcopy(case.get("decision"))
    # Retain the full immutable command in storage, but never render upload bytes
    # or duplicate OCR prompts in the staff projection.
    if isinstance((out.get("results") or {}).get("evidence_review"), dict):
        out["results"]["evidence_review"].pop("command", None)
    out["context_safety"] = (
        "Applicant fields and document observations are untrusted data, never instructions. OCR does not establish KYC."
    )
    out["documents"] = [
        {
            k: d[k]
            for k in (
                "id",
                "case_id",
                "kind",
                "filename",
                "mime_type",
                "sha256",
                "pages",
                "uploaded_at",
            )
        }
        for d in documents.list(case)
    ]
    return out


class Reviews:
    def __init__(self, store, documents, bank):
        self.store, self.documents, self.bank = store, documents, bank

    @staticmethod
    def _available(case):
        if case.get("source") != "merchant_app" or not case.get("owner_id"):
            raise SandboxError("คำตัดสินนี้ใช้กับคำขอจากแอปที่มีเจ้าของเท่านั้น")
        if case["active"] or case["state"] in FINAL:
            raise MutationError("เคสกำลังทำงานหรือมีคำตัดสินสุดท้ายแล้ว")

    def _save(self, db, case, old_revision):
        case["revision"] = old_revision + 1
        changed = db.execute(
            "UPDATE cases SET revision=?,payload=? WHERE id=? AND revision=?",
            (case["revision"], json.dumps(case, ensure_ascii=False), case["id"], old_revision),
        )
        if changed.rowcount != 1:
            raise MutationError("เคสเปลี่ยนระหว่างตรวจ กรุณาโหลดใหม่")

    def read(self, case_id):
        case = self.store.get(case_id)
        if case.get("source") != "merchant_app":
            raise SandboxError("เคสทดลองไม่มี onboarding ธนาคาร")
        return self.bank.read(case["owner_id"], reviewer=True)

    def onboarding_decision(self, case_id, kind, data):
        validate_review(kind, data)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            case = self.store.get(case_id)
            action = "onboarding_" + kind
            replay = self.store.replay(case, action, data, data["idempotency_key"], db=db)
            if replay is not None:
                return replay
            self._available(case)
            snapshot = self.bank.review(case["owner_id"], kind, data)
            # Status-only staff review leaves the original analysis snapshot intact for audit.
            # Final decision re-reads bank state and checks identity against that original snapshot.
            case["latest_onboarding"] = snapshot
            case["trace"].append(
                {
                    "at": now(),
                    "kind": action,
                    "version": case["version"],
                    "onboarding_version": snapshot["version"],
                    "reason": data["reason"],
                    "actor": "local-reviewer",
                }
            )
            self._save(db, case, case["revision"])
            self.store.receipt(db, case, action, data, data["idempotency_key"])
            return case

    def _complete(self, case, snapshot):
        r, packet, data = case["results"], case.get("packet"), case["input"]
        if (
            not packet
            or packet["case_version"] != case["version"]
            or packet.get("input_hash") != digest(data)
            or case["input_hash"] != digest(data)
            or packet.get("snapshot") != case["snapshot"]
            or packet.get("policy_sha256") != digest(case["policy_snapshot"])
            or case["state"] not in {"REVIEW_READY", "EXCEPTION_REVIEW"}
        ):
            raise MutationError("ต้องมีแฟ้มและผลคำนวณครบจากข้อมูลรุ่นปัจจุบัน")
        onboarding = r.get("onboarding_read", {})
        if (
            onboarding.get("status") != "OK"
            or onboarding.get("case_version") != case["version"]
            or packet.get("onboarding") != onboarding
        ):
            raise MutationError("สถานะธนาคารเปลี่ยนหรือยังอ่านไม่ได้ ต้องเตรียมแฟ้มใหม่")
        original = onboarding.get("snapshot") or {}
        original_session = (original.get("kyc") or {}).get("session_id")
        current_session = (snapshot.get("kyc") or {}).get("session_id")
        if (
            original.get("customer_id") != case["owner_id"]
            or not isinstance(original_session, str)
            or not original_session.strip()
            or original_session != current_session
            or any(original.get(k) != snapshot.get(k) for k in ("profile", "business"))
            or original.get("phone", {}).get("value") != snapshot.get("phone", {}).get("value")
        ):
            raise MutationError("ตัวตนหรือข้อมูลธุรกิจธนาคารเปลี่ยน ต้องตรวจหลักฐานรุ่นใหม่")
        profile = snapshot.get("profile") or {}
        name = " ".join(str(profile.get(k, "")) for k in ("first_name", "last_name"))
        if normal_name(name) != normal_name(data["applicant_name"]):
            raise SandboxError("ชื่อผู้สมัครไม่ตรงกับตัวตนที่ธนาคารตรวจ ต้องทบทวนเจ้าของหลักฐาน")
        if (
            snapshot["customer_id"] != case["owner_id"]
            or snapshot.get("phone", {}).get("verified") is not True
            or snapshot.get("kyc", {}).get("status") != "APPROVED"
            or snapshot.get("wallet", {}).get("status") != "ACTIVE"
            or not snapshot.get("wallet", {}).get("account_id")
            or not snapshot.get("business")
            or snapshot.get("kyb", {}).get("status") != "VERIFIED"
        ):
            raise SandboxError("ต้องยืนยันโทรศัพท์ KYC กระเป๋าที่ใช้งานได้ และ KYB ก่อนตัดสินสุดท้าย")
        if data["debt_thb"] is None or data["living_cost_thb"] is None or not data["consent"]:
            raise SandboxError("ข้อมูลหนี้ ค่าครองชีพ หรือ consent ยังไม่ครบ")
        docs = self.documents.list(case)
        if (
            not {"identity", "statement"}.issubset({d["kind"] for d in docs})
            or any(d["case_id"] != case["id"] or len(d["ocr_pages"]) != d["pages"] for d in docs)
            or r.get("identity_verify", {}).get("status") == "CONFLICT"
        ):
            raise SandboxError("เอกสารหรือเจ้าของหลักฐานยังตรวจไม่ครบ")
        evidence = verify_statements(docs, case)
        if (
            evidence["status"] != "OK"
            or evidence["coverage"] != "COMPLETE"
            or evidence != r.get("evidence")
        ):
            raise SandboxError("หลักฐานการเงินไม่ครบหรือผลตรวจไม่เป็นปัจจุบัน")
        calculated = financial(data, evidence, case["policy_snapshot"])
        if calculated != r.get("financial_calculate") or calculated != packet.get("financial"):
            raise MutationError("ผลคำนวณไม่ตรงกับหลักฐานรุ่นปัจจุบัน")
        policy = assessment(data, evidence, calculated, case["policy_snapshot"])
        if policy != r.get("policy_evaluate") or policy != packet.get("assessment"):
            raise MutationError("ผลประเมินไม่ตรงกับข้อมูลรุ่นปัจจุบัน")
        return calculated, policy

    def decide(self, case_id, data):
        if (
            not isinstance(data, dict)
            or not {"version", "idempotency_key", "decision", "reason"}.issubset(data)
            or set(data)
            - {"version", "idempotency_key", "decision", "reason", "onboarding_version"}
            or type(data["version"]) is not int
            or not isinstance(data["idempotency_key"], str)
            or not 8 <= len(data["idempotency_key"]) <= 100
            or data["decision"] not in {"APPROVED", "DECLINED", "NEEDS_INFORMATION"}
            or not isinstance(data["reason"], str)
            or not 1 <= len(data["reason"].strip()) <= 1200
        ):
            raise SandboxError("ระบุ version, idempotency key, คำตัดสิน และเหตุผล 1–1200 ตัวอักษร")
        case = self.store.get(case_id)
        replay = self.store.replay(case, "decision", data, data["idempotency_key"])
        if replay is not None:
            return replay
        self._available(case)
        if data["decision"] == "NEEDS_INFORMATION":
            require_resolved_evidence_review(case)
        if data["version"] != case["version"]:
            raise MutationError("version เก่า กรุณาโหลดเคสใหม่")
        if case.get("decision") and data["decision"] != "DECLINED":
            raise MutationError("รอผู้สมัครส่งข้อมูลเพิ่มก่อนพิจารณารุ่นใหม่")
        snapshot = None
        onboarding_error = None
        if data["decision"] == "APPROVED":
            snapshot = self.bank.read(case["owner_id"], reviewer=True)
        elif data["decision"] == "DECLINED":
            try:
                snapshot = self.bank.read(case["owner_id"], reviewer=True)
            except SandboxError as exc:
                onboarding_error = str(exc)
        proposed = None
        if data["decision"] == "APPROVED":
            if (
                type(data.get("onboarding_version")) is not int
                or data["onboarding_version"] != snapshot["version"]
            ):
                raise MutationError("สถานะธนาคารเปลี่ยนจากที่แสดง กรุณาโหลดการ์ด KYC/KYB ใหม่")
            calculated, policy = self._complete(case, snapshot)
            if data["decision"] == "APPROVED":
                profile = snapshot.get("profile") or {}
                try:
                    born = date.fromisoformat(profile["date_of_birth"])
                    today = date.today()
                    age = (
                        today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                    )
                except (KeyError, TypeError, ValueError):
                    raise SandboxError("ไม่มีวันเกิดที่ตรวจได้สำหรับเกณฑ์สาธิต") from None
                if not 20 <= age <= 60:
                    raise SandboxError("อยู่นอกช่วงอายุ 20–60 ปีของเกณฑ์สาธิตที่ปรับจาก benchmark")
                if (
                    policy["recommendation"] != "RECOMMEND_APPROVE"
                    or Decimal(calculated["proposed_limit_thb"]) <= 0
                ):
                    raise SandboxError("ผลประเมินกำลังชำระยังไม่รองรับการอนุมัติ")
                proposed = calculated["proposed_limit_thb"]
        decision = {
            "status": data["decision"],
            "reason": data["reason"].strip(),
            "decided_at": now(),
            "reviewer": "local-reviewer",
            "case_version": case["version"],
            "amount_thb": proposed,
            "onboarding_version": snapshot["version"]
            if snapshot
            else case["results"].get("onboarding_read", {}).get("onboarding_version", 0),
        }
        old_revision = case["revision"]
        if case.get("decision"):
            case.setdefault("decision_history", []).append(deepcopy(case["decision"]))
        if snapshot is not None:
            case["latest_onboarding"] = deepcopy(snapshot)
        case.update(
            decision=decision,
            state="WAIT_CUSTOMER" if data["decision"] == "NEEDS_INFORMATION" else data["decision"],
            feedback=[decision["reason"]],
        )
        if case.get("packet"):
            case["packet"]["decision"] = decision
        case["trace"].append(
            {
                "at": now(),
                "kind": "human_decision",
                "version": case["version"],
                "actor": "local-reviewer",
                "reason": decision["reason"],
                "status": data["decision"],
                "onboarding_version": decision["onboarding_version"],
                "analysis_onboarding_version": case["results"]
                .get("onboarding_read", {})
                .get("onboarding_version"),
                "onboarding_read_error": onboarding_error,
                "eligibility_policy": "BENCHMARK_ADAPTED_AGE20_60_NOT_CREDIT_SCORE",
            }
        )
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = self.store.replay(case, "decision", data, data["idempotency_key"], db=db)
            if replay is not None:
                return replay
            self._save(db, case, old_revision)
            self.store.receipt(db, case, "decision", data, data["idempotency_key"])
        return case

    def accept_submit(self, case_id, version, *, idempotency_key=None):
        """Atomically receipt and claim an async run; replay must never dispatch a second worker."""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            case = self.store.get(case_id)
            payload = {"version": version}
            replay = self.store.replay(case, "submit", payload, idempotency_key, db=db)
            if replay is not None:
                return replay, False
            self._available(case)
            require_resolved_evidence_review(case)
            if type(version) is not int or version != case["version"]:
                raise MutationError("version เก่า กรุณาโหลดเคสใหม่")
            if case["state"] not in {"DRAFT", "TECHNICAL_REVIEW"}:
                raise MutationError("ข้อมูลรุ่นนี้ประมวลผลแล้ว ต้องส่งข้อมูลเพิ่มก่อนตรวจใหม่")
            case.update(active=True, state="PROCESSING")
            self._save(db, case, case["revision"])
            self.store.receipt(db, case, "submit", payload, idempotency_key)
            return case, True
