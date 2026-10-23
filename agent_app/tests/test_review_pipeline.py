"""Real evidence/report pipeline; external transports replaced only in Typhoon tests."""

import base64
import importlib
import importlib.util
import io
from copy import deepcopy
from hashlib import sha256

import pytest
from PIL import Image
from test_review_service import payload


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    import requests

    monkeypatch.setattr(
        requests.sessions.Session,
        "request",
        lambda *a, **k: pytest.fail("provider/network call forbidden"),
    )


def pipeline_module():
    assert importlib.util.find_spec("merchant_sandbox.review_pipeline"), "Review pipeline missing"
    return importlib.import_module("merchant_sandbox.review_pipeline")


def test_offline_uses_supplied_ocr_and_real_four_part_report_without_config(monkeypatch):
    m = pipeline_module()
    from merchant_sandbox.typhoon import Config

    monkeypatch.setattr(
        Config, "load", lambda *a, **k: pytest.fail("offline must not read credentials")
    )
    body = payload()
    original = deepcopy(body)
    result = m.ReviewPipeline()(body)
    assert body == original
    assert result["decision"] is None and result["human_final_decision_required"] is True
    assert result["review_state"] == "OFFLINE_EVIDENCE_ONLY"
    assert set(result["report"]["sections"]) == {
        "supported_sales",
        "non_sales_inflows",
        "identifiable_obligations",
        "follow_up",
    }
    assert result["report"]["sections"]["supported_sales"]["credit_total_thb"] == "0.00"
    assert result["usage"]["provider_calls"] == 0
    assert result["execution_mode"] == "OFFLINE_SUPPLIED_OCR"
    assert "recommendation" not in result
    assert result["limitations"]["financial_semantics"] == "UNRESOLVED_EXISTING_MODEL_SEMANTICS"


def test_offline_missing_ocr_never_falls_back(monkeypatch):
    m = pipeline_module()
    body = payload()
    body["documents"][0]["ocr_pages"] = []
    monkeypatch.setattr(m, "TyphoonOCR", lambda *a: pytest.fail("no offline OCR"))
    with pytest.raises(ValueError, match="OCR"):
        m.ReviewPipeline()(body)


def test_native_mode_uses_real_session_and_bounded_runner_without_promoting_policy(monkeypatch):
    m = pipeline_module()
    from merchant_sandbox.typhoon import Config

    captured = []

    class NativeDouble:
        mode = "typhoon"

        def __init__(self, config, **kwargs):
            self.call_records = []
            captured.append(kwargs)

        def choose(self, context, tools, timeout_seconds):
            names = {t["function"]["name"] for t in tools}
            tool = (
                "compare_declarations"
                if "compare_declarations" in names
                else "inspect_cashflow"
                if "inspect_cashflow" in names
                else "finish_review"
            )
            args = (
                {"claims": []}
                if tool == "compare_declarations"
                else {"reason": "Hand off evidence"}
                if tool == "finish_review"
                else {}
            )
            self.call_records.append({"usage": {"total_tokens": 7}, "http_status": 200})
            return {"tool": tool, "arguments": args, "usage": {"total_tokens": 7}}

    monkeypatch.setattr(m, "TyphoonReviewAgent", NativeDouble)
    monkeypatch.setattr(m, "TyphoonOCR", lambda *a: pytest.fail("supplied OCR must be reused"))
    body = payload()
    body["mode"] = "typhoon"
    out = m.ReviewPipeline(config=Config(api_key="synthetic-key"))(body)
    assert captured[0]["max_calls"] == 8
    assert 0 < out["usage"]["provider_calls"] <= 8
    assert any(e.get("tool") == "compare_declarations" for e in out["trace"])
    action = next(
        e for e in out["trace"] if e.get("kind") == "agent_action" and e.get("status") == "ACCEPTED"
    )
    assert isinstance(action["arguments"], dict) and isinstance(action["reason"], str)
    observation = next(e for e in out["trace"] if e.get("actor") == "evidence_tool")
    assert isinstance(observation["result"], dict)
    assert out["execution_mode"] == "TYPHOON_NATIVE"
    assert out["decision"] is None and "packet" not in out and "recommendation" not in out
    assert out["report"]["decision"] is None


def test_content_goes_to_ocr_with_exact_bytes_and_usage_is_counted(monkeypatch):
    m = pipeline_module()
    from merchant_sandbox.core import SandboxError
    from merchant_sandbox.typhoon import Config

    body = payload()
    text = body["documents"][0]["ocr_pages"][0]["text"]
    stream = io.BytesIO()
    Image.new("RGB", (2, 2)).save(stream, format="PNG")
    raw = stream.getvalue()
    doc = body["documents"][0]
    doc.update(
        mime_type="image/png",
        size=len(raw),
        sha256=sha256(raw).hexdigest(),
        content_base64=base64.b64encode(raw).decode(),
        ocr_pages=[],
    )
    body["mode"] = "typhoon"

    class OCR:
        def __init__(self, config):
            pass

        def extract_page(self, data, mime, page):
            assert data == raw and mime == "image/png" and page == 1
            return {"page": 1, "text": text, "usage": {"total_tokens": 11}}

    class StopAgent:
        mode = "typhoon"

        def __init__(self, *a, **k):
            self.call_records = []

        def choose(self, *args):
            raise SandboxError("synthetic transport stop")

    monkeypatch.setattr(m, "TyphoonOCR", OCR)
    monkeypatch.setattr(m, "TyphoonReviewAgent", StopAgent)
    out = m.ReviewPipeline(config=Config(api_key="synthetic-key"))(body)
    assert out["usage"]["ocr_calls"] == 1 and out["usage"]["total_tokens"] == 11
    assert out["review_state"] == "TECHNICAL_REVIEW"
    assert "content_base64" not in str(out)
    assert body["documents"][0]["ocr_pages"] == []


def test_typhoon_failure_never_becomes_offline_success(monkeypatch):
    m = pipeline_module()
    from merchant_sandbox.core import SandboxError
    from merchant_sandbox.typhoon import Config

    body = payload()
    body["mode"] = "typhoon"
    with pytest.raises(SandboxError, match="configuration"):
        m.ReviewPipeline(config=Config())(body)


def test_failed_ocr_attempt_retains_counts_without_exception_or_provider_text(
    monkeypatch, tmp_path
):
    m = pipeline_module()
    from reportlab.pdfgen.canvas import Canvas

    from merchant_sandbox.core import SandboxError
    from merchant_sandbox.review_service import ReviewService
    from merchant_sandbox.typhoon import Config

    body = payload()
    stream = io.BytesIO()
    canvas = Canvas(stream)
    canvas.drawString(20, 20, "Synthetic page one")
    canvas.showPage()
    canvas.drawString(20, 20, "Synthetic page two")
    canvas.save()
    raw = stream.getvalue()
    body["documents"][0].update(
        mime_type="application/pdf",
        pages=2,
        size=len(raw),
        sha256=sha256(raw).hexdigest(),
        content_base64=base64.b64encode(raw).decode(),
        ocr_pages=[],
    )
    body["mode"] = "typhoon"

    class FailedOCR:
        def __init__(self, config):
            pass

        def extract_page(self, *args):
            if args[-1] == 1:
                return {"page": 1, "text": "synthetic page", "usage": {"total_tokens": 11}}
            raise SandboxError("provider-secret-body")

    monkeypatch.setattr(m, "TyphoonOCR", FailedOCR)
    with ReviewService(
        tmp_path / "failure.sqlite3", runner=m.ReviewPipeline(config=Config(api_key="test"))
    ) as service:
        job = service.submit(body)
        service.process_next()
        failed = service.get(job["id"])
    assert failed["status"] == "FAILED" and failed["result"] is None
    assert failed["error"]["usage"]["ocr_calls"] == 2
    assert failed["error"]["usage"]["records"][0]["usage"]["total_tokens"] == 11
    assert failed["error"]["usage"]["total_tokens"] is None
    assert "provider-secret-body" not in str(failed)


@pytest.mark.parametrize("stage", ["session", "context", "native", "report"])
def test_all_downstream_failures_retain_successful_paid_ocr_usage(monkeypatch, tmp_path, stage):
    m = pipeline_module()
    from merchant_sandbox.review_service import ReviewService
    from merchant_sandbox.typhoon import Config

    body = payload()
    text = body["documents"][0]["ocr_pages"][0]["text"]
    stream = io.BytesIO()
    Image.new("RGB", (2, 2)).save(stream, format="PNG")
    raw = stream.getvalue()
    body["documents"][0].update(
        mime_type="image/png",
        size=len(raw),
        sha256=sha256(raw).hexdigest(),
        content_base64=base64.b64encode(raw).decode(),
        ocr_pages=[],
    )
    body["mode"] = "typhoon"

    class OCR:
        def __init__(self, config):
            pass

        def extract_page(self, *args):
            return {"page": 1, "text": text, "usage": {"total_tokens": 11}}

    def fail(*args, **kwargs):
        raise ValueError("private-provider-text")

    monkeypatch.setattr(m, "TyphoonOCR", OCR)
    target = {
        "session": "ReviewSession",
        "context": "statement_context",
        "native": "run_review",
        "report": "build_staff_report",
    }[stage]
    if stage == "report":
        monkeypatch.setattr(
            m, "run_review", lambda *a, **k: {"trace": [], "state": "TECHNICAL_REVIEW"}
        )
    monkeypatch.setattr(m, target, fail)
    with ReviewService(
        tmp_path / "jobs", runner=m.ReviewPipeline(config=Config(api_key="synthetic"))
    ) as service:
        job = service.submit(body)
        service.process_next()
        failed = service.get(job["id"])
    assert failed["status"] == "FAILED"
    assert failed["error"]["usage"]["ocr_calls"] == 1
    assert failed["error"]["usage"]["total_tokens"] == 11
    assert "private-provider-text" not in str(failed)


def test_two_native_rejections_both_have_sanitized_attempt_receipts(monkeypatch):
    m = pipeline_module()
    from merchant_sandbox.typhoon import Config

    class Response:
        status_code = 200
        content = b"synthetic"

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "PRIVATE rejected response", "tool_calls": []},
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            }

    monkeypatch.setattr("requests.post", lambda *a, **k: Response())
    body = payload()
    body["mode"] = "typhoon"
    out = m.ReviewPipeline(config=Config(api_key="synthetic-secret"))(body)
    attempts = [e for e in out["trace"] if e.get("kind") == "llm_attempt"]
    assert len(attempts) == out["usage"]["agent_calls"] == 2
    assert [e["attempt"] for e in attempts] == [1, 2]
    assert all(e["rejection"]["stage"] == "finish_reason" for e in attempts)
    assert all(e["rejection"]["tool_count"] == 0 and e["http_status"] == 200 for e in attempts)
    assert attempts[-1]["usage"]["total_tokens"] == 7
    assert "PRIVATE" not in str(out) and "synthetic-secret" not in str(out)
