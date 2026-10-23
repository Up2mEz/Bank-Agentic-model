"""Bounded case controller and computed tools; no approval or payment capability.

Fixtures are inputs, never precomputed lending decisions. The offline planner is
explicitly a rule-based baseline. A separate Typhoon adapter selects real tools.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import statistics
import time
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path

from .paths import ROOT

D = Decimal
FIXTURE = ROOT / "examples/merchant_sandbox/transactions.csv"
PARAMS = ROOT / "docs/merchant_lending/demo_parameters.json"
FINAL = {"APPROVED", "DECLINED"}
TERMINAL = {"WAIT_CUSTOMER", "REVIEW_READY", "EXCEPTION_REVIEW", "TECHNICAL_REVIEW"} | FINAL
SCENARIOS = {
    "complete": "ข้อมูลครบ · ประวัติร้านค้า 6 เดือน",
    "no_wallet": "ไม่มีประวัติ wallet · ใช้ statement แทน",
    "missing_months": "หลักฐานขาด 2 เดือน",
    "unknown_debt": "ยังไม่ทราบภาระหนี้เดิม",
    "low_capacity": "ภาระหนี้สูง · เงินเหลือไม่พอ",
    "identity_conflict": "เจ้าของบัญชีไม่ตรงกับผู้สมัคร",
    "timeout_once": "แหล่งข้อมูลขัดข้อง 1 ครั้ง แล้วกู้คืนได้",
    "provider_down": "แหล่งข้อมูลขัดข้องต่อเนื่อง",
}
DESCRIPTIONS = {
    "onboarding_read": "อ่านสถานะ KYC กระเป๋า และ KYB จากธนาคารตามเจ้าของเคสที่ระบบบันทึกไว้ ไม่มีสิทธิ์แก้ไขหรือตัดสิน",
    "document_extract": "อ่านเอกสารที่ผู้สมัครส่งด้วย Typhoon OCR เก็บข้อความและหน้าอ้างอิง ไม่ยืนยันเอกสารแท้",
    "intake_check": "ตรวจข้อมูลสมัครร้านค้า คำขอ และ consent ก่อนอ่านหลักฐาน",
    "identity_verify": "ตรวจหลักฐานตัวตนตามแหล่งข้อมูลเคส ส่งข้อขัดแย้งและ KYC ที่ยังไม่ยืนยันให้เจ้าหน้าที่",
    "wallet_read": "อ่านประวัติร้านค้าจำลองจาก CSV และตรวจความครอบคลุม",
    "statement_read": "อ่านและตรวจความครบถ้วนของ statement ตามแหล่งข้อมูลเคส ตรวจยอดคงเหลือและรายการคลุมเครือ",
    "financial_calculate": "คำนวณ cash flow, stress capacity และ repayment schedule ด้วย Decimal",
    "policy_evaluate": "ตรวจ demo scorecard และเสนอผลด้วยกฎที่ตรึง version",
    "customer_request_information": "แจ้งข้อมูลที่ขาดเฉพาะกรณีและพักรอลูกค้า",
    "review_build_packet": "สร้างแฟ้มอ้างอิงหลักฐานให้คนตรวจ ไม่มีอำนาจอนุมัติ",
    "service_escalate": "พักเคสเพื่อแก้ปัญหาเทคนิค ไม่ปฏิเสธสินเชื่อ",
}


class SandboxError(ValueError):
    pass


class MutationError(SandboxError):
    def __init__(self, message, *, code="stale_version", status=409):
        super().__init__(message)
        self.code, self.status = code, status


def archive_analysis(case):
    """Preserve the superseded evidence/calculation/decision before accepting supplements."""
    if case.get("results") or case.get("packet") or case.get("decision"):
        case.setdefault("history", []).append(
            deepcopy(
                {
                    k: case.get(k)
                    for k in (
                        "version",
                        "snapshot",
                        "input",
                        "input_hash",
                        "document_ids",
                        "results",
                        "packet",
                        "decision",
                        "policy_snapshot",
                    )
                }
            )
        )
    case["decision"] = None


def now() -> str:
    return datetime.now(UTC).isoformat()


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def money(value) -> str:
    return str(D(value).quantize(D("0.01"), rounding=ROUND_HALF_UP))


def amount(value, *, optional=False) -> Decimal | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,9}(\.\d{1,2})?", value):
        raise SandboxError("จำนวนเงินต้องเป็นข้อความเลขบวกหรือศูนย์ หน่วยบาท ทศนิยมไม่เกิน 2 ตำแหน่ง")
    return D(value)


def default_input(scenario="complete") -> dict:
    if scenario not in SCENARIOS:
        raise SandboxError("ไม่รู้จัก scenario")
    return {
        "scenario": scenario,
        "applicant_name": "มะลิ ใจดี (จำลอง)",
        "email": "mali@example.test",
        "phone": "0800000000",
        "shop_name": "ครัวมะลิ · ร้านตัวอย่าง",
        "business_type": "อาหารตามสั่ง",
        "business_location": "ตลาดทดสอบ กรุงเทพฯ",
        "consent": True,
        "requested_thb": "30000.00",
        "purpose": "ซื้อวัตถุดิบและเพิ่มสินค้าคงคลัง",
        "living_cost_thb": "15000.00",
        "debt_thb": None
        if scenario == "unknown_debt"
        else ("16000.00" if scenario == "low_capacity" else "10000.00"),
        "message": "ช่วยตรวจว่าข้อมูลสมัครครบไหม และเตรียมคำขอสินเชื่อให้เจ้าหน้าที่ตรวจ",
    }


def validate_input(data: dict) -> dict:
    if not isinstance(data, dict) or set(data) != set(default_input()):
        raise SandboxError("โครงสร้างข้อมูลใบสมัครไม่ตรงกับ sandbox contract")
    if data["scenario"] not in SCENARIOS or type(data["consent"]) is not bool:
        raise SandboxError("scenario หรือ consent ไม่ถูกต้อง")
    for key in (
        "applicant_name",
        "email",
        "phone",
        "shop_name",
        "business_type",
        "business_location",
        "purpose",
        "message",
    ):
        if not isinstance(data[key], str) or len(data[key]) > 1200:
            raise SandboxError(f"ช่อง {key} ต้องเป็นข้อความไม่เกิน 1,200 ตัวอักษร")
    if amount(data["requested_thb"]) <= 0:
        raise SandboxError("จำนวนเงินที่ขอต้องมากกว่าศูนย์")
    amount(data["living_cost_thb"], optional=True)
    amount(data["debt_thb"], optional=True)
    return deepcopy(data)


class Store:
    """SQLite compare-and-swap prevents simultaneous owners and stale revisions."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, input_hash TEXT NOT NULL, case_id TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS mutation_receipts (scope TEXT NOT NULL, key TEXT NOT NULL, payload_hash TEXT NOT NULL, PRIMARY KEY(scope,key))"
            )

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    @staticmethod
    def _scope(case, action):
        return f"{case.get('owner_id', 'lab')}:{case['id']}:{action}"

    def replay(self, case, action, payload, key, *, db=None):
        if key is None:
            return None
        if not isinstance(key, str) or not 8 <= len(key) <= 100:
            raise SandboxError("ต้องมี idempotency key 8–100 ตัวอักษร")
        if db is None:
            with self.connect() as conn:
                return self.replay(case, action, payload, key, db=conn)
        old = db.execute(
            "SELECT payload_hash FROM mutation_receipts WHERE scope=? AND key=?",
            (self._scope(case, action), key),
        ).fetchone()
        if old:
            if old[0] != digest(payload):
                raise MutationError(
                    "key เดิมใช้กับข้อมูลต่างกัน", code="idempotency_key_reused", status=422
                )
            row = db.execute("SELECT payload FROM cases WHERE id=?", (case["id"],)).fetchone()
            return json.loads(row[0])
        return None

    def receipt(self, db, case, action, payload, key):
        if key is not None:
            db.execute(
                "INSERT INTO mutation_receipts VALUES (?,?,?)",
                (self._scope(case, action), key, digest(payload)),
            )

    def replay_create(self, data, key, *, owner_id):
        """Resolve an accepted create only; never allocate a case or write a receipt."""
        data = validate_input(data)
        owner_id = str(uuid.UUID(owner_id))
        if not isinstance(key, str) or not 8 <= len(key) <= 100:
            raise SandboxError("ต้องมี idempotency key 8–100 ตัวอักษร")
        with self.connect() as db:
            row = db.execute(
                "SELECT r.input_hash,c.payload FROM requests r JOIN cases c ON c.id=r.case_id WHERE r.key=?",
                ("customer:" + owner_id + ":" + key,),
            ).fetchone()
        if row is None:
            return None
        case = json.loads(row[1])
        if case.get("owner_id") != owner_id or case.get("source") != "merchant_app":
            return None
        if row[0] != digest(data):
            raise MutationError("key เดิมใช้กับข้อมูลต่างกัน", code="idempotency_key_reused", status=422)
        return case

    def create(self, data: dict, key: str, *, owner_id: str | None = None) -> dict:
        data = validate_input(data)
        if not isinstance(key, str) or not 8 <= len(key) <= 100:
            raise SandboxError("ต้องมี idempotency key 8–100 ตัวอักษร")
        if owner_id is not None:
            owner_id = str(uuid.UUID(owner_id))
            key = "customer:" + owner_id + ":" + key
        case_id = "CASE-" + uuid.uuid4().hex[:12]
        case = {
            "id": case_id,
            "revision": 0,
            "version": 1,
            "state": "DRAFT",
            "created_at": now(),
            "input": data,
            "input_hash": digest(data),
            "policy_snapshot": json.loads(PARAMS.read_text(encoding="utf-8")),
            "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            "snapshot": case_id + ":v1",
            "results": {},
            "trace": [],
            "packet": None,
            "feedback": [],
            "registration": None,
            "attempts": {},
            "llm_calls": 0,
            "is_mock": True,
            "active": False,
        }
        if owner_id:
            case.update(
                owner_id=owner_id,
                source="merchant_app",
                is_mock=False,
                fixture_sha256=None,
                document_ids=[],
            )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT input_hash,case_id FROM requests WHERE key=?", (key,)
            ).fetchone()
            if old:
                if old[0] != digest(data):
                    raise MutationError(
                        "idempotency key เดิมใช้กับข้อมูลต่างกัน",
                        code="idempotency_key_reused",
                        status=422,
                    )
                return self.get(old[1])
            db.execute(
                "INSERT INTO cases VALUES (?,?,?)",
                (case_id, 0, json.dumps(case, ensure_ascii=False)),
            )
            db.execute("INSERT INTO requests VALUES (?,?,?)", (key, digest(data), case_id))
        return case

    def get(self, case_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise SandboxError("ไม่พบเคส")
        return json.loads(row[0])

    def list(self) -> list[dict]:
        with self.connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute("SELECT payload FROM cases ORDER BY rowid DESC LIMIT 50")
            ]

    def save(self, case: dict):
        old_revision = case["revision"]
        saved = deepcopy(case)
        saved["revision"] += 1
        with self.connect() as db:
            result = db.execute(
                "UPDATE cases SET revision=?,payload=? WHERE id=? AND revision=?",
                (
                    saved["revision"],
                    json.dumps(saved, ensure_ascii=False),
                    case["id"],
                    old_revision,
                ),
            )
            if result.rowcount != 1:
                raise SandboxError("เคสเปลี่ยนแล้ว กรุณาโหลดสถานะล่าสุด")
        case["revision"] = saved["revision"]

    def revise(self, case_id: str, data: dict, version: int, *, idempotency_key=None) -> dict:
        case = self.get(case_id)
        payload = {"input": data, "version": version}
        replay = self.replay(case, "revise", payload, idempotency_key)
        if replay is not None:
            return replay
        if (
            case["state"] in FINAL
            or case["active"]
            or type(version) is not int
            or version != case["version"]
        ):
            raise MutationError("เคสตัดสินแล้ว กำลังทำงาน หรือ version เก่า กรุณาโหลดใหม่")
        data = validate_input(data)
        archive_analysis(case)
        case["input"] = validate_input(data)
        case["input_hash"] = digest(data)
        case["policy_snapshot"] = json.loads(PARAMS.read_text(encoding="utf-8"))
        case["fixture_sha256"] = (
            None
            if case.get("source") == "merchant_app"
            else hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        )
        case["version"] += 1
        case["snapshot"] = f"{case_id}:v{case['version']}"
        case.update(
            state="DRAFT",
            results={},
            packet=None,
            feedback=[],
            attempts={},
            llm_calls=0,
            registration=None,
        )
        case["trace"].append(
            {
                "at": now(),
                "kind": "revision",
                "version": case["version"],
                "reason": "ข้อมูลใหม่: ยกเลิกผลคำนวณและแฟ้มรุ่นก่อน",
            }
        )
        old_revision = case["revision"]
        case["revision"] += 1
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = self.replay(case, "revise", payload, idempotency_key, db=db)
            if replay is not None:
                return replay
            changed = db.execute(
                "UPDATE cases SET revision=?,payload=? WHERE id=? AND revision=?",
                (case["revision"], json.dumps(case, ensure_ascii=False), case_id, old_revision),
            )
            if changed.rowcount != 1:
                raise MutationError("เคสเปลี่ยนแล้ว กรุณาโหลดใหม่")
            self.receipt(db, case, "revise", payload, idempotency_key)
        return case

    def recover(self):
        # Called only by the single local server after acquiring its process lock.
        with self.connect() as db:
            cases = [json.loads(row[0]) for row in db.execute("SELECT payload FROM cases")]
        for case in cases:
            if case["active"]:
                case.update(active=False, state="TECHNICAL_REVIEW")
                case["feedback"] = ["เซิร์ฟเวอร์หยุดระหว่างทำงาน กดรันต่อเพื่อใช้ checkpoint ล่าสุด"]
                self.save(case)


def input_gaps(data: dict) -> list[str]:
    labels = {
        "applicant_name": "ชื่อผู้สมัคร",
        "shop_name": "ชื่อร้าน",
        "business_type": "ประเภทธุรกิจ",
        "business_location": "สถานที่/ช่องทางขาย",
        "purpose": "วัตถุประสงค์การขอสินเชื่อ",
    }
    gaps = [f"กรุณาระบุ{label}" for key, label in labels.items() if not data[key].strip()]
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", data["email"]):
        gaps.append("กรุณาตรวจอีเมลสำหรับบัญชีจำลอง")
    if not re.fullmatch(r"0\d{9}", data["phone"]):
        gaps.append("กรุณากรอกเบอร์โทรศัพท์จำลอง 10 หลัก")
    if not data["consent"]:
        gaps.append("กรุณายืนยันการใช้ข้อมูลสังเคราะห์สำหรับทดลองก่อนอ่านหลักฐาน")
    return gaps


def read_evidence(scenario: str, source: str) -> dict:
    raw = FIXTURE.read_bytes()
    months: dict[str, dict] = {}
    seen, excluded, refs = set(), [], []
    with FIXTURE.open(encoding="utf-8", newline="") as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):
            month = row["date"][:7]
            if scenario == "missing_months" and month in {"2026-06", "2026-08"}:
                continue
            ref = f"{source}:transactions.csv:row-{line}"
            if row["id"] in seen:
                excluded.append({"ref": ref, "reason": "DUPLICATE_SOURCE_ID"})
                continue
            seen.add(row["id"])
            if row["kind"] in {"OWN_TRANSFER", "LOAN_PROCEEDS"}:
                excluded.append({"ref": ref, "reason": row["kind"]})
                continue
            if row["kind"] not in {"R", "O", "V", "F"}:
                raise SandboxError("พบประเภทธุรกรรมที่ fixture parser ไม่รองรับ")
            values = months.setdefault(
                month, {"R": D(0), "O": D(0), "V": D(0), "F": D(0), "refs": []}
            )
            values[row["kind"]] += amount(row["amount_thb"])
            values["refs"].append(ref)
            refs.append(ref)
    expected = [f"2026-{m:02}" for m in range(4, 10)]
    return {
        "status": "OK",
        "source": source,
        "coverage": "COMPLETE" if sorted(months) == expected else "PARTIAL",
        "missing_months": sorted(set(expected) - set(months)),
        "expected_months": expected,
        "months": [
            {"month": month, **{k: money(v) if k != "refs" else v for k, v in values.items()}}
            for month, values in sorted(months.items())
        ],
        "excluded": excluded,
        "evidence_refs": refs,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "provenance": "SYNTHETIC_CSV_NOT_REAL_BANK_EXPORT",
        "as_of": "2026-10-22",
        "is_mock": True,
    }


def financial(data: dict, evidence: dict, params: dict) -> dict:
    with localcontext() as ctx:
        ctx.prec = 40
        values = {
            k: statistics.median(D(row[k]) for row in evidence["months"])
            for k in ("R", "O", "V", "F")
        }
        r, o, v, f = (values[k] for k in ("R", "O", "V", "F"))
        h, debt = amount(data["living_cost_thb"]), amount(data["debt_thb"])
        reserve = D(params["affordability"]["reserve_thb"])
        stress = D(params["affordability"]["revenue_stress_fraction"])
        base = r + o - v - f - h - debt - reserve
        stressed = (1 - stress) * (r - v) + o - f - h - debt - reserve
        capacity = max(D(0), min(base, stressed))
        cfg = params["limit_fixture"]
        n = cfg["repayment_intervals"]
        rate = D(cfg["annual_nominal_simple_rate"]) / 365 * cfg["days_per_interval"]
        factor = D(n) if rate == 0 else (1 - (1 + rate) ** -n) / rate
        maximum = min(
            capacity * factor,
            amount(data["requested_thb"]),
            *(
                D(cfg[k])
                for k in ("product_cap_thb", "policy_cap_thb", "remaining_exposure_headroom_thb")
            ),
        )
        step = D(cfg["amount_step_thb"])
        proposed = (maximum / step).to_integral_value(rounding=ROUND_FLOOR) * step
        # Check actual rounded final installment, lowering the proposal if needed.
        while True:
            scheduled = D(money(proposed / factor))
            balance, schedule = proposed, []
            for installment in range(1, n + 1):
                interest = D(money(balance * rate))
                paid = min(balance + interest, scheduled) if installment < n else balance + interest
                principal = paid - interest
                balance -= principal
                schedule.append(
                    {
                        "installment": installment,
                        "day": installment * cfg["days_per_interval"],
                        "payment_thb": money(paid),
                        "interest_thb": money(interest),
                        "principal_thb": money(principal),
                        "balance_thb": money(balance),
                    }
                )
            if max(D(row["payment_thb"]) for row in schedule) <= capacity and balance == 0:
                break
            proposed = max(D(0), proposed - step)
        return {
            "status": "OK",
            "values_thb": {
                k: money(x) for k, x in {**values, "H": h, "D": debt, "B": reserve}.items()
            },
            "capacity_base_thb": money(base),
            "capacity_stress_thb": money(stressed),
            "capacity_thb": money(capacity),
            "limit_capacity_thb": money(capacity * factor),
            "proposed_limit_thb": money(proposed),
            "schedule": schedule,
            "terms": deepcopy(cfg),
            "policy_version": params["policy_version"],
            "confidence": "PROVISIONAL",
            "assumptions": [
                "ข้อมูลธุรกรรมสังเคราะห์ 6 เดือน ไม่ใช่ข้อมูลรายได้จริง"
                if evidence.get("is_mock", True)
                else "ข้อมูลจาก OCR เอกสารที่แนบ ยังต้องตรวจความแท้และการจัดหมวดโดยเจ้าหน้าที่",
                "ค่าครองชีพและหนี้เป็นคำแจ้ง ไม่ได้ตรวจบูโร",
                "ต้นทุนผันแปรลดตามยอดขายใน stress fixture",
                "6 งวด งวดละ 30 วัน เบิกเต็มครั้งเดียว ไม่เบิกซ้ำ",
                "DEMO_PARAMETER ไม่ใช่นโยบายสินเชื่อที่ผ่าน validation",
            ],
            "evidence_refs": evidence["evidence_refs"],
        }


def assessment(data: dict, evidence: dict, calculation: dict, params: dict) -> dict:
    rows, cfg = evidence["months"], params["assessment"]
    revenue = [D(x["R"]) for x in rows]
    residual = [
        D(x["R"])
        + D(x["O"])
        - D(x["V"])
        - D(x["F"])
        - D(data["living_cost_thb"])
        - D(data["debt_thb"])
        for x in rows
    ]
    mean, median = statistics.mean(revenue), statistics.median(revenue)
    cv = None if mean == 0 else (sum((x - mean) ** 2 for x in revenue) / len(revenue)).sqrt() / mean
    trend = None if median == 0 else statistics.median(revenue[-3:]) / median
    rules = [
        {
            "id": "S1",
            "pass": sum(x > 0 for x in residual) >= cfg["positive_residual_months_min"],
            "observed": sum(x > 0 for x in residual),
        },
        {
            "id": "S2",
            "pass": statistics.median(residual) > 0,
            "observed": money(statistics.median(residual)),
        },
        {
            "id": "S3",
            "pass": cv is not None and cv <= D(cfg["population_revenue_cv_max"]),
            "observed": str(cv) if cv is not None else "FAIL_ZERO_REVENUE",
        },
        {
            "id": "S4",
            "pass": trend is not None
            and trend >= D(cfg["recent3_to_full6_revenue_median_ratio_min"]),
            "observed": str(trend) if trend is not None else "FAIL_ZERO_REVENUE",
        },
    ]
    score = sum(x["pass"] for x in rules) * cfg["points_per_rule"]
    recommendation = "RECOMMEND_APPROVE"
    if D(calculation["capacity_thb"]) <= 0:
        recommendation = "RECOMMEND_DECLINE"
    elif score < cfg["exception_review_below_score"]:
        recommendation = "EXCEPTION_REVIEW"
    return {
        "status": "OK",
        "recommendation": recommendation,
        "demo_policy_score": score,
        "rules": rules,
        "statistical_pd": None,
        "statistical_pd_reason": "NO_VALIDATED_MERCHANT_MODEL",
        "human_final_decision_required": True,
    }


class Controller:
    def __init__(self, store: Store):
        self.store = store
        self.params = json.loads(PARAMS.read_text(encoding="utf-8"))

    def allowed(self, case: dict) -> list[str]:
        r, data = case["results"], case["input"]
        if "intake_check" not in r:
            return ["intake_check"]
        if r["intake_check"]["gaps"]:
            return ["customer_request_information"]
        if r.get("identity_verify", {}).get("status") == "CONFLICT":
            return ["review_build_packet"]
        evidence = r.get("evidence")
        pending = []
        if "identity_verify" not in r:
            pending.append("identity_verify")
        if not evidence:
            if case["attempts"].get("wallet_read", 0) >= 3:
                return ["service_escalate"]
            pending.append(
                "statement_read"
                if r.get("wallet_read", {}).get("status") == "NO_HISTORY"
                else "wallet_read"
            )
        if pending:
            return pending
        if (
            evidence["coverage"] != "COMPLETE"
            or data["debt_thb"] is None
            or data["living_cost_thb"] is None
        ):
            return ["customer_request_information"]
        if "financial_calculate" not in r:
            return ["financial_calculate"]
        if "policy_evaluate" not in r:
            return ["policy_evaluate"]
        return ["review_build_packet"]

    def execute(self, case: dict, tool: str) -> dict:
        if tool not in self.allowed(case) or case["state"] in TERMINAL:
            raise SandboxError("เครื่องมือนี้ไม่มีสิทธิ์ทำงานในขั้นตอนปัจจุบัน")
        data, r = case["input"], case["results"]
        policy = case["policy_snapshot"]
        case["attempts"][tool] = case["attempts"].get(tool, 0) + 1
        if tool == "intake_check":
            gaps = input_gaps(data)
            result = {"status": "NEEDS_INPUT" if gaps else "OK", "gaps": gaps}
            if not gaps:
                case["registration"] = {
                    "customer_id": "MOCK-" + case["id"],
                    "status": "SIMULATED_REGISTERED",
                    "provider": "local_fixture",
                    "real_authentication": False,
                }
        elif tool == "identity_verify":
            result = {
                "status": "CONFLICT" if data["scenario"] == "identity_conflict" else "OK",
                "provider": "mock",
                "method": "SYNTHETIC_FIXTURE",
                "real_identity_verified": False,
                "evidence_refs": [case["snapshot"] + ":identity-fixture"],
            }
        elif tool in {"wallet_read", "statement_read"}:
            if hashlib.sha256(FIXTURE.read_bytes()).hexdigest() != case["fixture_sha256"]:
                raise SandboxError("ไฟล์หลักฐานเปลี่ยนหลังสร้าง snapshot ต้องบันทึก revision ใหม่")
            if tool == "wallet_read" and data["scenario"] == "no_wallet":
                result = {
                    "status": "NO_HISTORY",
                    "alternative": "statement_read",
                    "credit_implication": "NONE",
                }
            elif tool == "wallet_read" and (
                data["scenario"] == "provider_down"
                or data["scenario"] == "timeout_once"
                and case["attempts"][tool] == 1
            ):
                result = {
                    "status": "RETRYABLE_ERROR",
                    "error_code": "SIMULATED_TIMEOUT",
                    "credit_implication": "NONE",
                }
            else:
                result = read_evidence(
                    data["scenario"],
                    "statement" if tool == "statement_read" else "merchant_history",
                )
                r["evidence"] = result
        elif tool == "financial_calculate":
            result = financial(data, r["evidence"], policy)
        elif tool == "policy_evaluate":
            result = assessment(data, r["evidence"], r["financial_calculate"], policy)
        elif tool == "customer_request_information":
            gaps = list(r["intake_check"]["gaps"])
            if not gaps:
                if r["evidence"]["missing_months"]:
                    gaps.append(
                        "เพิ่ม statement หรือรายงานขายของเดือน "
                        + ", ".join(r["evidence"]["missing_months"])
                    )
                if data["debt_thb"] is None:
                    gaps.append("ระบุยอดผ่อนหนี้เดิมต่อเดือน รวม supplier/BNPL ที่มี หากไม่มีหนี้ให้ยืนยัน 0")
                if data["living_cost_thb"] is None:
                    gaps.append("ระบุค่าใช้จ่ายจำเป็นส่วนตัวต่อเดือน โดยไม่รวมซ้ำกับค่าใช้จ่ายร้าน")
            case.update(state="WAIT_CUSTOMER", feedback=gaps)
            result = {
                "status": "NEEDS_INPUT",
                "gaps": gaps,
                "capacity_thb": None,
                "proposed_limit_thb": None,
            }
        elif tool == "service_escalate":
            case.update(
                state="TECHNICAL_REVIEW",
                feedback=[
                    "ระบบข้อมูลจำลองขัดข้องครบจำนวน retry แล้ว รอแก้บริการหรือส่งหลักฐานใหม่ ไม่ใช่ผลปฏิเสธสินเชื่อ"
                ],
            )
            result = {"status": "RETRYABLE_ERROR", "credit_recommendation": None}
        else:
            conflict = r["identity_verify"]["status"] == "CONFLICT"
            policy = r.get("policy_evaluate", {}) if not conflict else {}
            case["packet"] = {
                "case_id": case["id"],
                "case_version": case["version"],
                "snapshot": case["snapshot"],
                "input_hash": case["input_hash"],
                "recommendation": "EXCEPTION_REVIEW" if conflict else policy["recommendation"],
                "identity": r["identity_verify"],
                "financial": None if conflict else r["financial_calculate"],
                "assessment": policy,
                "decision": None,
                "human_final_decision_required": True,
                "is_mock": True,
                "policy_sha256": digest(case["policy_snapshot"]),
                "policy_version": case["policy_snapshot"]["policy_version"],
            }
            case["state"] = (
                "EXCEPTION_REVIEW"
                if case["packet"]["recommendation"] == "EXCEPTION_REVIEW"
                else "REVIEW_READY"
            )
            case["feedback"] = [
                "เจ้าของบัญชีไม่ตรงกับผู้สมัคร ต้องให้เจ้าหน้าที่ตรวจหลักฐานความสัมพันธ์"
                if conflict
                else "เตรียมแฟ้มแล้ว รอเจ้าหน้าที่ตรวจและตัดสิน ยังไม่อนุมัติหรือเปิดวงเงิน"
            ]
            result = {
                "status": "OK",
                "recommendation": case["packet"]["recommendation"],
                "decision": None,
            }
        r[tool] = result
        return result

    def run(self, case_id: str, planner, expected_version: int, *, _claimed_revision=None) -> dict:
        case = self.store.get(case_id)
        if case["state"] in FINAL:
            raise SandboxError("เคสมีคำตัดสินสุดท้ายแล้ว")
        claimed = (
            _claimed_revision is not None
            and case["revision"] == _claimed_revision
            and case["active"]
        )
        if (
            expected_version != case["version"]
            or (case["active"] and not claimed)
            or (_claimed_revision is not None and not claimed)
        ):
            raise SandboxError("เคสกำลังทำงานหรือ version เก่า")
        if case["state"] in TERMINAL and case["state"] != "TECHNICAL_REVIEW":
            return case
        if not case["input"]["consent"]:
            planner = BaselinePlanner()  # Enforce consent locally, before any provider request.
        case.update(active=True, state="PROCESSING", mode=planner.mode, feedback=[])
        self.store.save(case)  # CAS claims this run before any LLM request.
        started, turns = time.monotonic(), 0
        budget = case["policy_snapshot"]["runtime_proposal"]
        try:
            while (
                turns < budget["max_llm_turns_per_active_run"]
                and time.monotonic() - started < budget["max_active_run_seconds"]
            ):
                allowed = self.allowed(case)
                turns += 1
                if planner.mode == "typhoon":
                    case["llm_calls"] += 1
                    self.store.save(case)  # Count attempted calls, including errors/crashes.
                choice = planner.choose(case, allowed)
                if not isinstance(choice, dict) or set(choice) != {
                    "tool",
                    "reason",
                    "usage",
                    "duration_ms",
                    "model",
                }:
                    raise SandboxError("รูปแบบ action จาก planner ไม่ถูกต้อง")
                tool, reason = choice["tool"], choice["reason"]
                if (
                    tool not in allowed
                    or not isinstance(reason, str)
                    or not 1 <= len(reason) <= 1000
                ):
                    raise SandboxError("โมเดลเลือกเครื่องมือนอกสิทธิ์หรือ reason ไม่ถูกต้อง")
                tick = time.monotonic()
                result = self.execute(case, tool)
                event = {
                    "at": now(),
                    "kind": "tool",
                    "version": case["version"],
                    "snapshot": case["snapshot"],
                    "tool": tool,
                    "reason": reason,
                    "actor": planner.mode,
                    "model": choice["model"],
                    "status": result["status"],
                    "execution_mode": "BANK_ONBOARDING_READ"
                    if tool == "onboarding_read"
                    else "LIVE_PROVIDER"
                    if tool == "document_extract"
                    else "SIMULATED_PROVIDER"
                    if case["is_mock"]
                    and (
                        tool in {"identity_verify", "intake_check"}
                        or result["status"] in {"NO_HISTORY", "RETRYABLE_ERROR"}
                    )
                    else "COMPUTED",
                    "duration_ms": round((time.monotonic() - tick) * 1000),
                    "llm_duration_ms": choice["duration_ms"],
                    "usage": choice["usage"],
                    "result": deepcopy(result),
                }
                case["trace"].append(event)
                self.store.save(case)
                if case["state"] in TERMINAL:
                    break
            else:
                raise SandboxError("ถึงขอบเขตจำนวนรอบหรือเวลาของการทดลอง")
        except (SandboxError, OSError) as exc:
            case.update(state="TECHNICAL_REVIEW", feedback=[str(exc)])
            case["trace"].append(
                {
                    "at": now(),
                    "kind": "error",
                    "version": case["version"],
                    "reason": str(exc),
                    "credit_recommendation": None,
                }
            )
        finally:
            case["active"] = False
            case["active_duration_ms"] = round((time.monotonic() - started) * 1000)
            self.store.save(case)
        return case


class BaselinePlanner:
    mode = "baseline"

    def choose(self, case, allowed):
        tool = allowed[0]
        return {
            "tool": tool,
            "reason": DESCRIPTIONS[tool],
            "usage": None,
            "duration_ms": 0,
            "model": None,
        }
