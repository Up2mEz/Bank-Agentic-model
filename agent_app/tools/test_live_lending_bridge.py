"""Opt-in local end-to-end probe using only visibly synthetic documents.

Starts no servers. Calls the authenticated Go API and the configured live OCR/LLM.
Writes a redacted receipt and asserts independent fixture values. No keys logged.
"""

from __future__ import annotations

import base64
import json
import sys
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent_app/src"))
from merchant_sandbox.core import default_input  # noqa: E402


def main():
    base = "http://127.0.0.1:18080/v1"
    out = ROOT / "outputs/merchant_sandbox/android-ocr-20261022"
    email = f"mali.{uuid.uuid4().hex[:8]}@example.test"
    session = requests.Session()
    registration = session.post(
        base + "/auth/register",
        json={
            "first_name": "Mali",
            "last_name": "Jaidee",
            "email": email,
            "phone": "0800000000",
            "password": "Synthetic-Lending-Test-927!",
        },
        timeout=15,
    )
    registration.raise_for_status()
    token = registration.json()
    session.headers["Authorization"] = "Bearer " + token["access_token"]
    # A local-only login handoff for the Android runtime probe, not committed.
    (out / "test-login.json").write_text(
        json.dumps({"email": email, "password": "Synthetic-Lending-Test-927!"}), encoding="utf8"
    )
    data = default_input()
    data.pop("scenario")
    data.update(
        applicant_name="Mali Jaidee", email=email, shop_name="Mali OCR · SYNTHETIC integration"
    )
    create = {"input": data, "idempotency_key": str(uuid.uuid4())}
    response = session.post(base + "/lending/cases", json=create, timeout=15)
    response.raise_for_status()
    case = response.json()
    again = session.post(base + "/lending/cases", json=create, timeout=15)
    assert again.json()["id"] == case["id"]
    path = base + "/lending/cases/" + case["id"]
    assert requests.get(path, timeout=5).status_code == 401
    for kind, filename, mime in [
        ("identity", "synthetic-identity.png", "image/png"),
        ("statement", "synthetic-statement.pdf", "application/pdf"),
    ]:
        raw = (ROOT / "examples/merchant_sandbox/documents" / filename).read_bytes()
        payload = {
            "version": case["version"],
            "document": {
                "kind": kind,
                "filename": filename,
                "mime_type": mime,
                "content_base64": base64.b64encode(raw).decode(),
            },
        }
        response = session.post(path + "/documents", json=payload, timeout=20)
        response.raise_for_status()
        case = response.json()
        repeat = session.post(path + "/documents", json=payload, timeout=20)
        assert repeat.json()["version"] == case["version"]
    # A second authenticated customer cannot read the first one's application.
    other = requests.post(
        base + "/auth/register",
        json={
            "first_name": "Other",
            "last_name": "Test",
            "email": f"other.{uuid.uuid4().hex[:8]}@example.test",
            "phone": "0800000001",
            "password": "Synthetic-Lending-Test-928!",
        },
        timeout=15,
    ).json()
    denied = requests.get(
        path,
        headers={
            "Authorization": "Bearer " + other["access_token"],
            "X-Customer-ID": token["customer_id"],
        },
        timeout=10,
    )
    assert denied.status_code == 404
    response = session.post(path + "/submit", json={"version": case["version"]}, timeout=15)
    response.raise_for_status()
    assert response.status_code == 202
    print(
        json.dumps(
            {
                "case_id": case["id"],
                "submitted": True,
                "duplicate_create_and_upload": "PASS",
                "cross_owner": denied.status_code,
            }
        ),
        flush=True,
    )
    deadline = time.monotonic() + 700
    while time.monotonic() < deadline:
        case = session.get(path, timeout=15).json()
        if not case["active"] and case["state"] not in {"DRAFT", "PROCESSING"}:
            break
        time.sleep(3)
    staff = requests.get("http://127.0.0.1:8767/api/cases/" + case["id"], timeout=15).json()
    (out / "live-bridge-receipt.json").write_text(
        json.dumps(
            {
                "case": staff,
                "duplicate_create_and_upload": "PASS",
                "cross_owner": 404,
                "unauthenticated": 401,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf8",
    )
    print(
        json.dumps(
            {
                "case_id": case["id"],
                "state": case["state"],
                "feedback": case["feedback"],
                "llm_calls": staff["llm_calls"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    assert case["state"] == "EXCEPTION_REVIEW", case["feedback"]
    evidence = staff["results"]["evidence"]
    assert evidence["status"] == "OK", evidence["issues"]
    assert len(evidence["rows"]) == 30
    oracle = json.loads(
        (ROOT / "examples/merchant_sandbox/documents/oracle.json").read_text(encoding="utf8")
    )
    for observed, expected in zip(evidence["rows"], oracle["rows"], strict=True):
        for field, index in (("date", 0), ("debit", 2), ("credit", 3), ("balance", 4)):
            assert observed[field] == expected[index].replace(",", ""), (field, observed, expected)
    assert staff["packet"]["financial"]["capacity_thb"] == "5000.00"
    assert staff["packet"]["financial"]["proposed_limit_thb"] == "28400.00"
    assert staff["packet"]["decision"] is None
    assert not staff["packet"]["identity"]["real_identity_verified"]
    assert all(p["model"] == "typhoon-ocr" for d in staff["documents"] for p in d["ocr_pages"])
    print(
        "PASS: real Go authentication -> document upload -> live Typhoon OCR/agent -> officer packet",
        flush=True,
    )


if __name__ == "__main__":
    main()
