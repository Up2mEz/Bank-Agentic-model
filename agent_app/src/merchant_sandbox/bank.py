"""Server-owned, bounded onboarding adapter. No destinations or owners from an LLM."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .core import SandboxError


class BankError(SandboxError):
    def __init__(self, message, *, status=503, code="bank_unavailable"):
        super().__init__(message)
        self.status, self.code = status, code


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_snapshot(data, owner):
    """Allowlist the documented fields; never propagate OTP, raw ID or provider secrets."""
    try:
        if (
            str(uuid.UUID(data["customer_id"])) != owner
            or type(data["version"]) is not int
            or data["version"] < 0
        ):
            raise ValueError
        statuses = {
            "kyc": {
                "NOT_STARTED",
                "APPROVED",
                "RESUBMISSION_REQUESTED",
                "REVIEW",
                "DECLINED",
                "EXPIRED",
            },
            "wallet": {"NOT_OPEN", "ACTIVE", "BLOCKED", "CLOSED"},
            "kyb": {"NOT_SUBMITTED", "PENDING_REVIEW", "VERIFIED", "NEEDS_INFORMATION"},
        }
        if any(data[k]["status"] not in allowed for k, allowed in statuses.items()):
            raise ValueError
        if type(data["phone"]["verified"]) is not bool:
            raise ValueError
        fields = {
            "phone": "value verified",
            "profile": "first_name last_name date_of_birth nationality document_number_masked document_expiry current_address occupation source_of_funds wallet_purpose privacy_accepted",
            "kyc": "session_id status attempt is_mock reason provider reviewed_at reviewer",
            "wallet": "status account_id",
            "business": "name category location started_on ownership_confirmed evidence_note",
            "kyb": "status reason reviewed_at reviewer",
        }
        out = {"customer_id": owner, "version": data["version"], "is_mock": data.get("is_mock")}
        for name, keys in fields.items():
            value = data.get(name)
            out[name] = None if value is None else {k: value[k] for k in keys.split() if k in value}
            if value is not None and not isinstance(value, dict):
                raise ValueError
            if value and any(isinstance(v, (dict, list)) for v in out[name].values()):
                raise ValueError
        audit = data.get("audit", [])
        if not isinstance(audit, list) or any(not isinstance(row, dict) for row in audit):
            raise ValueError
        out["audit"] = [
            {
                k: row[k]
                for k in ("action", "reviewer", "reason", "at")
                if k in row and isinstance(row[k], str)
            }
            for row in audit[-100:]
        ]
        return out
    except (KeyError, TypeError, ValueError, AttributeError):
        raise BankError(
            "ข้อมูล onboarding จากธนาคารไม่ตรงกับเจ้าของหรือ contract", code="invalid_bank_snapshot"
        ) from None


class BankOnboardingClient:
    def __init__(
        self,
        base_url="",
        agent_key_file: Path | None = None,
        reviewer_key_file: Path | None = None,
        *,
        timeout=10,
    ):
        self.base_url = base_url.rstrip("/")
        if self.base_url:
            url = urlsplit(self.base_url)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})
                or url.username
                or url.password
                or url.path
                or url.query
                or url.fragment
            ):
                raise SandboxError("bank URL ต้องเป็น HTTPS หรือ HTTP loopback ไม่มี path/credentials")
            _ = url.port  # Validate malformed ports at configuration time.
        if not 0 < timeout <= 30:
            raise SandboxError("bank timeout ต้องอยู่ในช่วง 0–30 วินาที")
        self.timeout = timeout
        self._agent_key = self._key(agent_key_file)
        self._reviewer_key = self._key(reviewer_key_file)
        self._opener = build_opener(ProxyHandler({}), NoRedirect())

    @staticmethod
    def _key(path):
        value = Path(path).read_text(encoding="utf-8-sig").strip() if path else ""
        if value and (len(value) > 4096 or any(c.isspace() for c in value)):
            raise SandboxError("รูปแบบ bank key file ไม่ถูกต้อง")
        return value

    @property
    def configured(self):
        return bool(self.base_url and self._agent_key)

    @property
    def reviewer_configured(self):
        return bool(self.base_url and self._reviewer_key)

    def _request(self, owner, *, reviewer=False, kind=None, data=None):
        try:
            owner = str(uuid.UUID(owner))
        except (ValueError, TypeError, AttributeError):
            raise BankError("เคสไม่มีเจ้าของบัญชีที่ถูกต้อง", code="invalid_owner") from None
        key = self._reviewer_key if reviewer else self._agent_key
        if not self.base_url or not key:
            raise BankError("ยังไม่ได้ตั้งค่าการเชื่อม onboarding ธนาคาร", code="bank_not_configured")
        path = (
            f"/v1/review/onboarding/{owner}"
            if reviewer
            else f"/v1/agent/customers/{owner}/onboarding"
        )
        if kind:
            path += f"/{kind}-decision"
        raw = None if data is None else json.dumps(data, ensure_ascii=False).encode()
        req = Request(
            self.base_url + path,
            data=raw,
            headers={
                "X-API-Key": key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="GET" if raw is None else "POST",
        )
        try:
            with self._opener.open(req, timeout=self.timeout) as response:
                body = response.read(256_001)
                if response.status != 200 or len(body) > 256_000:
                    raise ValueError
            return safe_snapshot(json.loads(body), owner)
        except HTTPError as exc:
            # Only allowlisted machine codes cross the adapter, never arbitrary upstream messages.
            code = "bank_request_failed"
            try:
                error = json.loads(exc.read(16_000)).get("error", {})
                candidate = error.get("code") if isinstance(error, dict) else None
                if candidate in {
                    "idempotency_key_reused",
                    "stale_version",
                    "invalid_request",
                    "not_found",
                }:
                    code = candidate
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            raise BankError(
                f"ธนาคารตอบ HTTP {exc.code}; โหลดสถานะล่าสุดหรือลองใหม่",
                status=exc.code if exc.code in {400, 404, 409, 422} else 503,
                code=code,
            ) from None
        except (URLError, OSError, ValueError, TypeError):
            raise BankError("อ่าน onboarding ไม่สำเร็จ กรุณาตรวจบริการธนาคารและลองใหม่") from None

    def read(self, owner, *, reviewer=False):
        return self._request(owner, reviewer=reviewer)

    def review(self, owner, kind, data):
        validate_review(kind, data)
        return self._request(owner, reviewer=True, kind=kind, data=data)


def validate_review(kind, data):
    choices = {
        "kyc": {"APPROVED", "DECLINED", "RESUBMISSION_REQUESTED"},
        "kyb": {"VERIFIED", "NEEDS_INFORMATION"},
    }
    if (
        kind not in choices
        or not isinstance(data, dict)
        or set(data) != {"version", "idempotency_key", "decision", "reason"}
        or type(data["version"]) is not int
        or data["version"] < 0
        or not isinstance(data["idempotency_key"], str)
        or not 8 <= len(data["idempotency_key"]) <= 100
        or data["decision"] not in choices[kind]
        or not isinstance(data["reason"], str)
        or not 1 <= len(data["reason"].strip()) <= 1200
    ):
        raise SandboxError("คำขอตรวจ KYC/KYB ต้องมี version, key, ผลตรวจ และเหตุผลตาม contract")
