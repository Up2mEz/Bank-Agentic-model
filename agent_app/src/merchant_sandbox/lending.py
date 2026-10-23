"""Authenticated gateway intake and evidence workflow for the merchant app.

The gateway establishes account ownership; neither OCR nor a demo score establishes
KYC, authenticity, or lending authority. Uploaded cases never read CSV fixtures.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid

from .bank import BankOnboardingClient
from .core import (
    FINAL,
    TERMINAL,
    Controller,
    MutationError,
    SandboxError,
    archive_analysis,
    digest,
    input_gaps,
    now,
    require_resolved_evidence_review,
    validate_input,
)
from .ocr import TyphoonOCR, inspect_document
from .statements import normal_name, verify_statements

MAX_CASE_PAGES = 8


def app_input(data):
    if not isinstance(data, dict) or "scenario" in data:
        raise SandboxError("ข้อมูลจากแอปต้องไม่มี scenario จำลอง")
    return validate_input({**data, "scenario": "complete"})


class Documents:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, case_id TEXT NOT NULL, raw BLOB NOT NULL, metadata TEXT NOT NULL)"
            )

    def get(self, doc_id, *, raw=False):
        with self.store.connect() as db:
            row = db.execute("SELECT raw,metadata FROM documents WHERE id=?", (doc_id,)).fetchone()
        if row is None:
            raise SandboxError("ไม่พบเอกสาร")
        return (row[0], json.loads(row[1])) if raw else json.loads(row[1])

    def list(self, case):
        return [self.get(x) for x in case.get("document_ids", [])]

    def save_ocr(self, doc):
        with self.store.connect() as db:
            db.execute(
                "UPDATE documents SET metadata=? WHERE id=?",
                (json.dumps(doc, ensure_ascii=False), doc["id"]),
            )

    def change(self, case, version, *, data=None, remove=None, idempotency_key=None):
        action = "document_upload" if data is not None else "document_remove"
        payload = {"version": version, "document": data, "remove": remove}
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM cases WHERE id=?", (case["id"],)).fetchone()
            case = json.loads(row[0])
            replay = self.store.replay(case, action, payload, idempotency_key, db=db)
            if replay is not None:
                return replay
            require_resolved_evidence_review(case)
            result = self._change(case, version, data=data, remove=remove, db=db)
            self.store.receipt(db, result, action, payload, idempotency_key)
            return result

    def _change(self, case, version, *, data=None, remove=None, db):
        if case["state"] in FINAL:
            raise MutationError("เคสมีคำตัดสินสุดท้ายแล้ว")
        if case["active"]:
            raise SandboxError("Agent กำลังทำงาน รอผลก่อนเปลี่ยนเอกสาร")
        case.setdefault("document_ids", [])
        docs = self.list(case)
        document = None
        raw = None
        if data is not None:
            if set(data) != {"kind", "filename", "mime_type", "content_base64"} or data[
                "kind"
            ] not in {"identity", "statement", "business"}:
                raise SandboxError("ประเภทหรือโครงสร้างเอกสารไม่ถูกต้อง")
            if not isinstance(data["filename"], str) or not 1 <= len(data["filename"]) <= 180:
                raise SandboxError("ชื่อไฟล์ยาวเกินขอบเขต")
            try:
                raw = base64.b64decode(data["content_base64"], validate=True)
            except (ValueError, TypeError):
                raise SandboxError("ข้อมูลไฟล์ base64 ไม่ถูกต้อง") from None
            pages = inspect_document(raw, data["mime_type"])
            sha = hashlib.sha256(raw).hexdigest()
            # Retransmitting a lost response is safe even with the previous version.
            if any(x["sha256"] == sha and x["kind"] == data["kind"] for x in docs):
                return case
            if len(docs) >= 8 or pages + sum(x["pages"] for x in docs) > MAX_CASE_PAGES:
                raise SandboxError("เอกสารรวมต้องไม่เกิน 8 ไฟล์/8 หน้า ต่อคำขอ")
            document = {
                "id": "DOC-" + uuid.uuid4().hex[:16],
                "case_id": case["id"],
                "kind": data["kind"],
                "filename": data["filename"],
                "mime_type": data["mime_type"],
                "sha256": sha,
                "size": len(raw),
                "pages": pages,
                "ocr_pages": [],
                "ocr_attempts": 0,
                "uploaded_at": now(),
            }
        elif remove not in case["document_ids"]:
            return case
        if type(version) is not int or version != case["version"]:
            raise SandboxError("version เก่า กรุณาโหลดคำขอล่าสุด")
        old_revision = case["revision"]
        archive_analysis(case)
        if document:
            case["document_ids"].append(document["id"])
        else:
            case["document_ids"].remove(remove)
        case.update(
            version=case["version"] + 1,
            revision=old_revision + 1,
            state="DRAFT",
            results={},
            packet=None,
            feedback=[],
            attempts={},
            llm_calls=0,
        )
        case["snapshot"] = f"{case['id']}:v{case['version']}"
        case["trace"].append(
            {
                "at": now(),
                "kind": "document_revision",
                "version": case["version"],
                "reason": "เพิ่มเอกสาร" if document else "ถอนเอกสารจากรุ่นปัจจุบัน",
                "document_id": document["id"] if document else remove,
            }
        )
        changed = db.execute(
            "UPDATE cases SET revision=?,payload=? WHERE id=? AND revision=?",
            (case["revision"], json.dumps(case, ensure_ascii=False), case["id"], old_revision),
        )
        if changed.rowcount != 1:
            raise MutationError("คำขอเปลี่ยนแล้ว กรุณาโหลดใหม่")
        if document:
            db.execute(
                "INSERT INTO documents VALUES (?,?,?,?)",
                (document["id"], case["id"], raw, json.dumps(document, ensure_ascii=False)),
            )
        return case


def customer_view(case, documents):
    """The app receives its own application, progress and feedback, not officer traces."""
    out = {
        k: case[k] for k in ("id", "version", "state", "created_at", "input", "feedback", "active")
    }
    out["input"] = {k: v for k, v in out["input"].items() if k != "scenario"}
    out["documents"] = [
        {k: d[k] for k in ("id", "kind", "filename", "mime_type", "sha256", "pages")}
        | {"ocr_completed_pages": len(d["ocr_pages"])}
        for d in documents.list(case)
    ]
    out["decision"] = case.get("decision")
    snapshot = case.get("results", {}).get("onboarding_read", {}).get("snapshot") or {}
    out["kyc_status"] = snapshot.get("kyc", {}).get("status", "PENDING_OFFICER_REVIEW")
    return out


class LendingController(Controller):
    def __init__(self, store, documents, config, *, bank=None):
        super().__init__(store)
        self.documents, self.config = documents, config
        self.bank = bank or BankOnboardingClient()

    def allowed(self, case):
        if case.get("source") != "merchant_app":
            return super().allowed(case)
        r, data = case["results"], case["input"]
        if "intake_check" not in r:
            return ["intake_check"]
        if r["intake_check"]["gaps"]:
            return ["customer_request_information"]
        if "onboarding_read" not in r:
            return ["onboarding_read"]
        if "document_extract" not in r:
            return ["document_extract"]
        pending = [x for x in ("identity_verify", "statement_read") if x not in r]
        if pending:
            return pending
        if r["evidence"]["status"] != "OK" or r["identity_verify"]["status"] == "CONFLICT":
            return ["review_build_packet"]
        if (
            r["evidence"]["coverage"] != "COMPLETE"
            or data["debt_thb"] is None
            or data["living_cost_thb"] is None
        ):
            return ["customer_request_information"]
        if "financial_calculate" not in r:
            return ["financial_calculate"]
        if "policy_evaluate" not in r:
            return ["policy_evaluate"]
        return ["review_build_packet"]

    def execute(self, case, tool):
        if case.get("source") != "merchant_app" or tool in {
            "financial_calculate",
            "policy_evaluate",
        }:
            return super().execute(case, tool)
        if tool not in self.allowed(case) or case["state"] in TERMINAL:
            raise SandboxError("เครื่องมืออยู่นอกขั้นตอนที่อนุญาต")
        r, data = case["results"], case["input"]
        case["attempts"][tool] = case["attempts"].get(tool, 0) + 1
        docs = self.documents.list(case)
        if tool == "onboarding_read":
            try:
                snapshot = self.bank.read(case["owner_id"])
                result = {
                    "status": "OK",
                    "snapshot": snapshot,
                    "onboarding_version": snapshot["version"],
                    "read_at": now(),
                    "case_version": case["version"],
                    "provenance": "merchant_go_onboarding",
                }
            except SandboxError as exc:
                result = {
                    "status": "UNAVAILABLE",
                    "snapshot": None,
                    "read_at": now(),
                    "case_version": case["version"],
                    "reason": str(exc),
                    "credit_implication": "NONE",
                }
        elif tool == "intake_check":
            gaps = [
                x.replace("จำลอง", "").replace(
                    "การใช้ข้อมูลสังเคราะห์สำหรับทดลอง", "ส่งเอกสารให้ Typhoon OCR"
                )
                for x in input_gaps(data)
            ]
            kinds = {d["kind"] for d in docs}
            if "identity" not in kinds:
                gaps.append("แนบเอกสารยืนยันตัวตนสำหรับเจ้าหน้าที่ตรวจ KYC")
            if "statement" not in kinds:
                gaps.append("แนบ statement ย้อนหลัง 6 เดือนที่ปิดครบแล้ว")
            result = {"status": "NEEDS_INPUT" if gaps else "OK", "gaps": gaps}
            case["registration"] = {
                "customer_id": case["owner_id"],
                "status": "REGISTERED_ACCOUNT",
                "provider": "merchant_go_backend",
                "real_authentication": True,
                "identity_verified": False,
            }
        elif tool == "document_extract":
            started = time.monotonic()
            reader = TyphoonOCR(self.config)
            for doc in docs:
                raw, _ = self.documents.get(doc["id"], raw=True)
                for page in range(1, doc["pages"] + 1):
                    if any(p["page"] == page for p in doc["ocr_pages"]):
                        continue
                    if time.monotonic() - started > 400:
                        raise SandboxError("ถึงเวลารอบ OCR แล้ว กดตรวจต่อเพื่อใช้หน้าที่อ่านสำเร็จไว้")
                    doc["ocr_attempts"] += 1
                    self.documents.save_ocr(doc)
                    result = reader.extract_page(raw, doc["mime_type"], page)
                    doc["ocr_pages"].append(result)
                    self.documents.save_ocr(doc)
            result = {
                "status": "OK",
                "model": self.config.ocr_model,
                "document_count": len(docs),
                "pages": sum(d["pages"] for d in docs),
                "authenticity_verified": False,
            }
        elif tool == "identity_verify":
            names = []
            for doc in docs:
                if doc["kind"] == "identity":
                    for page in doc["ocr_pages"]:
                        plain = re.sub(r"<[^>]*>", " ", page["text"]).replace("**", "")
                        match = re.search(
                            r"(?:Full name|ชื่อ-นามสกุล)\s*[:：]\s*([^\n]+)", plain, re.I
                        )
                        if match:
                            names.append(match[1].strip())
            conflict = any(normal_name(n) != normal_name(data["applicant_name"]) for n in names)
            result = {
                "status": "CONFLICT" if conflict else "PENDING_REVIEW",
                "provider": "typhoon-ocr",
                "method": "OCR_DOCUMENT_ONLY",
                "real_identity_verified": False,
                "extracted_names": names,
                "evidence_refs": [d["id"] for d in docs if d["kind"] == "identity"],
            }
        elif tool == "statement_read":
            result = verify_statements(docs, case)
            r["evidence"] = result
        elif tool == "customer_request_information":
            gaps = list(r["intake_check"]["gaps"])
            missing = r.get("evidence", {}).get("missing_months", [])
            if missing:
                gaps.append("เพิ่ม statement ของเดือน " + ", ".join(missing))
            if data["debt_thb"] is None:
                gaps.append("ระบุยอดผ่อนหนี้เดิมต่อเดือน หากไม่มีหนี้ให้ยืนยัน 0")
            if data["living_cost_thb"] is None:
                gaps.append("ระบุค่าครองชีพจำเป็นต่อเดือน โดยไม่รวมซ้ำกับค่าใช้จ่ายร้าน")
            case.update(state="WAIT_CUSTOMER", feedback=gaps)
            result = {"status": "NEEDS_INPUT", "gaps": gaps}
        else:
            onboarding = r.get("onboarding_read", {})
            bank = onboarding.get("snapshot") or {}
            bank_ready = (
                bank.get("kyc", {}).get("status") == "APPROVED"
                and bank.get("wallet", {}).get("status") == "ACTIVE"
                and bank.get("kyb", {}).get("status") == "VERIFIED"
                and bank.get("phone", {}).get("verified") is True
            )
            conflict = (
                r["identity_verify"]["status"] == "CONFLICT" or r["evidence"]["status"] != "OK"
            )
            recommendation = r.get("policy_evaluate", {}).get("recommendation", "EXCEPTION_REVIEW")
            review_reason = (
                "พบข้อขัดแย้งในเอกสาร ต้องตรวจสอบ"
                if conflict
                else "ยังอ่านสถานะธนาคารไม่ได้ กรุณาตรวจการเชื่อมต่อ"
                if onboarding.get("status") != "OK"
                else "รอตรวจ KYC กระเป๋า หรือ KYB ให้ครบ"
                if not bank_ready
                else "เตรียมแฟ้มครบแล้ว รอเจ้าหน้าที่พิจารณา"
            )
            ready = bank_ready and not conflict and r.get("financial_calculate") is not None
            case["packet"] = {
                "case_id": case["id"],
                "case_version": case["version"],
                "snapshot": case["snapshot"],
                "input_hash": case["input_hash"],
                "recommendation": recommendation if ready else "EXCEPTION_REVIEW",
                "review_reason": review_reason,
                "onboarding": onboarding,
                "evidence": {
                    "status": r["evidence"]["status"],
                    "coverage": r["evidence"]["coverage"],
                    "source_sha256": r["evidence"]["source_sha256"],
                    "evidence_refs": r["evidence"]["evidence_refs"],
                    "document_ownership_checked": all(d["case_id"] == case["id"] for d in docs),
                },
                "identity": r["identity_verify"],
                "financial": r.get("financial_calculate"),
                "assessment": r.get("policy_evaluate", {}),
                "document_issues": r["evidence"]["issues"],
                "decision": None,
                "human_final_decision_required": True,
                "is_mock": False,
                "policy_sha256": digest(case["policy_snapshot"]),
                "policy_version": case["policy_snapshot"]["policy_version"],
            }
            case.update(
                state="REVIEW_READY"
                if ready and recommendation != "EXCEPTION_REVIEW"
                else "EXCEPTION_REVIEW",
                feedback=[review_reason + " ยังไม่มีคำตัดสินสินเชื่อ"],
            )
            result = {
                "status": "OK",
                "recommendation": case["packet"]["recommendation"],
                "decision": None,
            }
        r[tool] = result
        return result
