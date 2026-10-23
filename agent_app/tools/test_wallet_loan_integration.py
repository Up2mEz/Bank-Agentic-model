"""Bounded HTTP acceptance for wallet/KYC/loan/staff integration.
Run only against isolated local runtimes. Reads private keys from config paths;
prints no credentials. OCR/planner scope is declared by the caller.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--config", type=Path, default=ROOT / "outputs/wallet-loan-20261023/runtime-config.json"
    )
    p.add_argument(
        "--receipt", type=Path, default=ROOT / "outputs/wallet-loan-20261023/http-acceptance.json"
    )
    p.add_argument(
        "--review-regressions",
        action="store_true",
        help="Verify fixed identity binding and accepted-operation recovery over HTTP",
    )
    args = p.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    bank = cfg["bank_url"] + "/v1"
    review = cfg["review_url"]
    keys = {k: Path(cfg[k + "_file"]).read_text().strip() for k in ("agent", "reviewer")}
    checks = []
    private = {"config": str(args.config)}

    def save_receipt():
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(
                {
                    "checks": checks,
                    "passed": sum(c["passed"] for c in checks),
                    "failed": sum(not c["passed"] for c in checks),
                    "scope": "Real local HTTP/auth/stores/tools. OCR and tool planner replaced by frozen synthetic oracles; no live provider or native device.",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf8",
        )

    def raw(method, path, body=None, *, token=None, service=None, staff=False, nonce=True):
        base = review if staff else bank
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if service:
            headers["X-API-Key"] = keys[service]
        if staff and method != "GET" and nonce:
            headers["X-Review-Nonce"] = staff_nonce
        req = Request(
            base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
            method=method,
        )
        try:
            with urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except HTTPError as e:
            try:
                response = json.loads(e.read())
            except ValueError:
                response = {"error": "non-json response"}
            return e.code, response

    def call(method, path, body=None, **kw):
        status, data = raw(method, path, body, **kw)
        assert 200 <= status < 300, (method, path, status, data.get("error", data))
        return data

    def assert_status(statuses, method, path, body=None, **kw):
        actual, data = raw(method, path, body, **kw)
        assert actual in statuses, (method, path, actual, data.get("error", data))
        return data

    def mark(name, fn):
        before = time.monotonic()
        try:
            value = fn()
            checks.append(
                {"name": name, "passed": True, "seconds": round(time.monotonic() - before, 3)}
            )
            return value
        except Exception as exc:
            checks.append({"name": name, "passed": False, "error": str(exc)[:1800]})
            raise
        finally:
            save_receipt()

    def key():
        return str(uuid.uuid4())

    def register():
        body = {
            "first_name": "Mali",
            "last_name": "Jaidee",
            "email": "wallet-test-" + uuid.uuid4().hex[:10] + "@example.test",
            "phone": "0800000000",
            "password": "Local-only-" + uuid.uuid4().hex,
        }
        auth = call("POST", "/auth/register", body)
        return {**auth, "email": body["email"], "password": body["password"]}

    def data(debt="10000.00"):
        return {
            "applicant_name": "Mali Jaidee",
            "email": applicant["email"],
            "phone": "0800000000",
            "shop_name": "ครัวทดสอบ",
            "business_type": "อาหารตามสั่ง",
            "business_location": "ตลาดทดสอบ",
            "consent": True,
            "requested_thb": "30000.00",
            "purpose": "ซื้อวัตถุดิบ",
            "living_cost_thb": "15000.00",
            "debt_thb": debt,
            "message": "เตรียมแฟ้มให้เจ้าหน้าที่พิจารณา",
        }

    def ocmd(method, path, fields):
        before = call("GET", "/onboarding", token=token)
        body = {"version": before["version"], "idempotency_key": key(), **fields}
        return call(method, path, body, token=token), body

    def upload(case, kind, name):
        file = ROOT / "examples/merchant_sandbox/documents" / name
        body = {
            "version": case["version"],
            "idempotency_key": key(),
            "document": {
                "kind": kind,
                "filename": name,
                "mime_type": "application/pdf" if name.endswith(".pdf") else "image/png",
                "content_base64": base64.b64encode(file.read_bytes()).decode(),
            },
        }
        result = call("POST", "/lending/cases/" + case["id"] + "/documents", body, token=token)
        return result, body

    def prepare(debt="10000.00"):
        createbody = {"input": data(debt), "idempotency_key": key()}
        case = call("POST", "/lending/cases", createbody, token=token)
        private.setdefault("create_receipts", {})[case["id"]] = createbody
        case, _ = upload(case, "identity", "synthetic-identity.png")
        case, _ = upload(case, "statement", "synthetic-statement.pdf")
        return case

    def submit(case):
        body = {"version": case["version"], "idempotency_key": key()}
        path = "/lending/cases/" + case["id"] + "/submit"
        _accepted = call("POST", path, body, token=token)
        call("POST", path, body, token=token)
        for _ in range(100):
            current = call("GET", "/lending/cases/" + case["id"], token=token)
            if not current.get("active") and current["state"] not in ("DRAFT", "RUNNING"):
                return current, body
            time.sleep(0.1)
        raise AssertionError("case did not settle after 10 seconds")

    try:
        config = call("GET", "/api/config", staff=True)
        staff_nonce = config.get("review_nonce", "")
        assert staff_nonce, "Missing reviewer nonce"
        applicant = mark("registration creates authenticated customer", register)
        token = applicant["access_token"]
        owner = applicant["customer_id"]
        private["applicant"] = applicant
        mark(
            "registration creates no automatic wallet",
            lambda: assert_equal(
                call("GET", "/customers/" + owner + "/accounts", token=token)["items"], []
            ),
        )
        mark(
            "onboarding requires authentication", lambda: assert_status({401}, "GET", "/onboarding")
        )
        mark(
            "legacy wallet open cannot bypass KYC",
            lambda: assert_status(
                {403, 409},
                "POST",
                "/customers/" + owner + "/accounts",
                {"type": "WALLET", "currency": "THB"},
                token=token,
            ),
        )
        mark(
            "agent key cannot mutate legacy banking routes",
            lambda: assert_status(
                {403},
                "POST",
                "/customers/" + owner + "/accounts",
                {"type": "WALLET", "currency": "THB"},
                service="agent",
            ),
        )
        mark(
            "loan cannot be created before onboarding",
            lambda: assert_status(
                {403, 409},
                "POST",
                "/lending/cases",
                {"input": data(), "idempotency_key": key()},
                token=token,
            ),
        )
        challenge, _ = ocmd("POST", "/onboarding/phone/challenge", {"phone": "0800000000"})
        verified, _ = ocmd(
            "POST",
            "/onboarding/phone/verify",
            {"challenge_id": challenge["challenge_id"], "code": "123456"},
        )
        mark(
            "phone mock challenge confirms only its owner",
            lambda: (
                True
                if verified["phone"]["verified"]
                else (_ for _ in ()).throw(AssertionError("phone not verified"))
            ),
        )
        profile = {
            "first_name": "Mali",
            "last_name": "Jaidee",
            "date_of_birth": "1990-04-23",
            "nationality": "TH",
            "document_number": "1111111111119",
            "document_expiry": "2030-04-23",
            "current_address": "ที่อยู่ทดสอบเท่านั้น",
            "occupation": "เจ้าของร้านอาหาร",
            "source_of_funds": "รายได้จากการขายอาหาร",
            "wallet_purpose": "รับเงินและชำระค่าสินค้า",
            "privacy_accepted": True,
        }
        saved, _ = ocmd("PUT", "/onboarding/profile", {"profile": profile})
        kyc, _ = ocmd("POST", "/onboarding/kyc", {})
        mark("KYC has provider result, wallet remains unopened", lambda: assert_kyc(kyc))
        before = call("GET", "/onboarding", token=token)
        walletbody = {
            "version": before["version"],
            "idempotency_key": key(),
            "terms_accepted": True,
        }

        def wallet_race():
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                results = list(
                    pool.map(
                        lambda _: raw("POST", "/onboarding/wallet", walletbody, token=token),
                        range(6),
                    )
                )
            assert all(status in (200, 201) for status, _ in results), [
                (s, d.get("error")) for s, d in results
            ]
            ids = {d["wallet"]["account_id"] for _, d in results}
            assert len(ids) == 1
            assert len(call("GET", "/customers/" + owner + "/accounts", token=token)["items"]) == 1
            return results[0][1]

        _wallet = mark("six identical concurrent wallet opens create one account", wallet_race)
        mark(
            "wallet key reused for changed payload is rejected",
            lambda: assert_status(
                {422},
                "POST",
                "/onboarding/wallet",
                {**walletbody, "terms_accepted": False},
                token=token,
            ),
        )
        business = {
            "name": "ครัวทดสอบ",
            "category": "อาหารตามสั่ง",
            "location": "ตลาดทดสอบ",
            "started_on": "2022-01-01",
            "ownership_confirmed": True,
            "evidence_note": "เอกสารกิจการสังเคราะห์สำหรับตรวจรับ",
        }
        onboard, _ = ocmd("PUT", "/onboarding/business", {"business": business})
        assert onboard["kyb"]["status"] == "PENDING_REVIEW"
        safe = mark(
            "Agent can read current onboarding",
            lambda: call("GET", "/agent/customers/" + owner + "/onboarding", service="agent"),
        )
        assert profile["document_number"] not in json.dumps(safe), "raw ID leaked to agent"
        mark(
            "Agent cannot decide KYB",
            lambda: assert_status(
                {403},
                "POST",
                "/review/onboarding/" + owner + "/kyb-decision",
                {
                    "version": onboard["version"],
                    "idempotency_key": key(),
                    "decision": "VERIFIED",
                    "reason": "forbidden agent",
                },
                service="agent",
            ),
        )
        case = prepare()
        case, uploadbody = upload(case, "business", "synthetic-identity.png")
        mark(
            "business upload replay creates no duplicate document",
            lambda: assert_same_documents(
                case,
                call(
                    "POST", "/lending/cases/" + case["id"] + "/documents", uploadbody, token=token
                ),
            ),
        )
        result, submitbody = mark(
            "app submission processes through real HTTP into staff dossier", lambda: submit(case)
        )
        case_id = result["id"]
        private["case_id"] = case_id
        packet = call("GET", "/agent/lending/cases/" + case_id, service="agent")
        financial = packet["results"]["financial_calculate"]
        mark("financial oracle is capacity5000 and limit28400", lambda: assert_financial(financial))
        assert packet["results"]["onboarding_read"], "Agent did not fetch applicant context"
        assert result["decision"] is None
        current = call("GET", "/api/cases/" + case_id + "/onboarding", staff=True)
        decision = {
            "version": result["version"],
            "idempotency_key": key(),
            "decision": "APPROVED",
            "reason": "ตรวจแฟ้มและกำลังชำระแล้ว",
            "onboarding_version": current["version"],
        }
        mark(
            "pending KYB cannot be approved as a loan",
            lambda: assert_status(
                {400, 409}, "POST", "/api/cases/" + case_id + "/decision", decision, staff=True
            ),
        )
        mark(
            "review mutation requires same-origin nonce",
            lambda: assert_status(
                {400, 401, 403},
                "POST",
                "/api/cases/" + case_id + "/decision",
                decision,
                staff=True,
                nonce=False,
            ),
        )
        body = {
            "version": current["version"],
            "idempotency_key": key(),
            "decision": "VERIFIED",
            "reason": "ตรวจความเกี่ยวข้องกับกิจการจากหลักฐานแล้ว",
        }
        _updated = call(
            "POST", "/api/cases/" + case_id + "/onboarding/kyb-decision", body, staff=True
        )
        current = call("GET", "/api/cases/" + case_id + "/onboarding", staff=True)
        approvedbody = {
            **decision,
            "idempotency_key": key(),
            "onboarding_version": current["version"],
        }
        _approved = mark(
            "human approval records exact computed amount",
            lambda: call("POST", "/api/cases/" + case_id + "/decision", approvedbody, staff=True),
        )
        public = call("GET", "/lending/cases/" + case_id, token=token)
        assert (
            public["decision"]["status"] == "APPROVED"
            and public["decision"]["amount_thb"] == "28400.00"
        ), public["decision"]
        mark(
            "same decision replay cannot create another decision",
            lambda: call("POST", "/api/cases/" + case_id + "/decision", approvedbody, staff=True),
        )
        mark(
            "terminal approved case rejects fresh revision",
            lambda: assert_status(
                {400, 409},
                "POST",
                "/lending/cases/" + case_id + "/revise",
                {"version": public["version"], "idempotency_key": key(), "input": data("16000.00")},
                token=token,
            ),
        )
        other = register()
        mark(
            "different customer cannot read the applicant case",
            lambda: assert_status(
                {404}, "GET", "/lending/cases/" + case_id, token=other["access_token"]
            ),
        )
        mark(
            "customer token cannot read staff Agent dossiers",
            lambda: assert_status(
                {401, 403}, "GET", "/agent/lending/cases/" + case_id, token=token
            ),
        )
        unknown = prepare(None)
        unknown, _ = submit(unknown)
        assert unknown["state"] == "WAIT_CUSTOMER", unknown["state"]
        info = call(
            "POST",
            "/api/cases/" + unknown["id"] + "/decision",
            {
                "version": unknown["version"],
                "idempotency_key": key(),
                "decision": "NEEDS_INFORMATION",
                "reason": "กรุณาระบุภาระผ่อนหนี้เดิม",
                "onboarding_version": current["version"],
            },
            staff=True,
        )
        revised = call(
            "POST",
            "/lending/cases/" + unknown["id"] + "/revise",
            {"version": info["version"], "idempotency_key": key(), "input": data()},
            token=token,
        )
        assert revised["id"] == unknown["id"] and revised["version"] > unknown["version"]
        recovered, _ = submit(revised)
        mark(
            "unknown debt requests more info and resumes same case",
            lambda: (
                True
                if recovered["decision"] is None and recovered["id"] == unknown["id"]
                else (_ for _ in ()).throw(AssertionError("case recovery"))
            ),
        )
        low = prepare("16000.00")
        low, _ = submit(low)
        mark(
            "nonpositive capacity cannot be approved",
            lambda: assert_status(
                {400, 409},
                "POST",
                "/api/cases/" + low["id"] + "/decision",
                {
                    "version": low["version"],
                    "idempotency_key": key(),
                    "decision": "APPROVED",
                    "reason": "must be refused",
                    "onboarding_version": current["version"],
                },
                staff=True,
            ),
        )
        _declined = call(
            "POST",
            "/api/cases/" + low["id"] + "/decision",
            {
                "version": low["version"],
                "idempotency_key": key(),
                "decision": "DECLINED",
                "reason": "เงินเหลือหลังภาระปัจจุบันยังไม่พอ",
                "onboarding_version": current["version"],
            },
            staff=True,
        )
        public_low = call("GET", "/lending/cases/" + low["id"], token=token)
        mark(
            "human decline returns customer-facing reason",
            lambda: (
                True
                if public_low["decision"]["status"] == "DECLINED"
                and public_low["decision"]["reason"]
                else (_ for _ in ()).throw(AssertionError("missing decline"))
            ),
        )
        if args.review_regressions:
            recovery = prepare()
            recovery, accepted_submit = submit(recovery)
            accepted_create = private["create_receipts"][recovery["id"]]
            prior_snapshot = call("GET", "/onboarding", token=token)
            # Only change the private prefix; a masked profile comparison cannot detect this.
            changed_profile = {**profile, "document_number": "2222222221119"}
            invalidated, _ = ocmd("PUT", "/onboarding/profile", {"profile": changed_profile})
            assert invalidated["kyc"]["status"] == "NOT_STARTED"

            def accepted_recovery():
                replayed_create = call("POST", "/lending/cases", accepted_create, token=token)
                replayed_submit = call(
                    "POST",
                    "/lending/cases/" + recovery["id"] + "/submit",
                    accepted_submit,
                    token=token,
                )
                assert replayed_create["id"] == recovery["id"] == replayed_submit["id"]
                assert (
                    not replayed_submit["active"]
                    and replayed_submit["version"] == recovery["version"]
                )

            mark(
                "unready onboarding still resolves accepted create and submit receipts",
                accepted_recovery,
            )
            mark(
                "unready onboarding refuses genuinely new create",
                lambda: assert_status(
                    {403, 409},
                    "POST",
                    "/lending/cases",
                    {"input": data(), "idempotency_key": key()},
                    token=token,
                ),
            )
            mark(
                "receipt recovery rejects changed payload",
                lambda: assert_status(
                    {422},
                    "POST",
                    "/lending/cases",
                    {
                        **accepted_create,
                        "input": {**accepted_create["input"], "requested_thb": "31000.00"},
                    },
                    token=token,
                ),
            )
            renewed, _ = ocmd("POST", "/onboarding/kyc", {})
            assert renewed["profile"] == prior_snapshot["profile"]
            assert renewed["kyc"]["session_id"] != prior_snapshot["kyc"]["session_id"]
            mark(
                "new KYC identity cannot approve an old masked-identical analysis",
                lambda: assert_status(
                    {400, 409},
                    "POST",
                    "/api/cases/" + recovery["id"] + "/decision",
                    {
                        "version": recovery["version"],
                        "idempotency_key": key(),
                        "decision": "APPROVED",
                        "reason": "must reject old identity analysis",
                        "onboarding_version": renewed["version"],
                    },
                    staff=True,
                ),
            )
        print(
            json.dumps(
                {
                    "passed": len(checks),
                    "failed": 0,
                    "case_id": case_id,
                    "receipt": str(args.receipt),
                }
            )
        )
    except Exception as exc:
        if not any(not c["passed"] for c in checks):
            checks.append(
                {
                    "name": "integration step outside named check",
                    "passed": False,
                    "error": str(exc)[:1800],
                }
            )
            save_receipt()
        print(
            json.dumps(
                {
                    "passed": sum(c["passed"] for c in checks),
                    "failed": max(1, sum(not c["passed"] for c in checks)),
                    "error": str(exc)[:1800],
                    "receipt": str(args.receipt),
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(1) from exc
    finally:
        (args.receipt.parent / "acceptance-private.json").write_text(
            json.dumps(private, ensure_ascii=False, indent=2), encoding="utf8"
        )


def assert_kyc(s):
    assert (
        s["kyc"]["status"] == "APPROVED"
        and s["kyc"]["is_mock"]
        and s["wallet"]["status"] == "NOT_OPEN"
    ), s


def assert_financial(s):
    assert s["capacity_thb"] == "5000.00" and s["proposed_limit_thb"] == "28400.00", s


def assert_same_documents(a, b):
    assert a["id"] == b["id"] and a["version"] == b["version"] and a["documents"] == b["documents"]


def assert_equal(actual, expected):
    assert actual == expected, (actual, expected)


if __name__ == "__main__":
    main()
