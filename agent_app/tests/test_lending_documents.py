import base64
import json
import uuid
from copy import deepcopy
from pathlib import Path

import pytest

from merchant_sandbox.core import BaselinePlanner, SandboxError, Store, default_input
from merchant_sandbox.lending import Documents, LendingController, app_input, customer_view
from merchant_sandbox.ocr import MAX_FILE_BYTES, inspect_document
from merchant_sandbox.statements import parse_statement, verify_statements
from merchant_sandbox.typhoon import Config

FIXTURES = Path(__file__).resolve().parents[2] / "examples/merchant_sandbox/documents"


def statement():
    oracle = json.loads((FIXTURES / "oracle.json").read_text(encoding="utf8"))
    rows = [["Date", "Description", "Debit", "Credit", "Balance"], *oracle["rows"]]
    text = "Account holder: Mali Jaidee\nAccount: TEST-0001\nPeriod: 2026-04-01 to 2026-09-30\nOpening balance: 100,000.00 THB\n"
    text += (
        "<table>"
        + "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
        + "</table>\nClosing balance: 430,000.00 THB"
    )
    return {
        "id": "DOC-test",
        "kind": "statement",
        "sha256": "test-hash",
        "ocr_pages": [{"page": 1, "text": text}],
    }


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "cases.db")
    docs = Documents(store)
    data = default_input()
    data.pop("scenario")
    data["applicant_name"] = "Mali Jaidee"
    case = store.create(app_input(data), "create-123456", owner_id=str(uuid.uuid4()))
    case["created_at"] = "2026-10-22T00:00:00+00:00"
    store.save(case)
    return store, docs, case


def attach(docs, case, kind="statement"):
    name, mime = (
        ("synthetic-statement.pdf", "application/pdf")
        if kind == "statement"
        else ("synthetic-identity.png", "image/png")
    )
    data = {
        "kind": kind,
        "filename": name,
        "mime_type": mime,
        "content_base64": base64.b64encode((FIXTURES / name).read_bytes()).decode(),
    }
    return docs.change(case, case["version"], data=data), data


def test_real_ownership_is_atomic_and_idempotency_is_scoped(setup):
    store, docs, case = setup
    assert case["source"] == "merchant_app" and not case["is_mock"]
    assert case["fixture_sha256"] is None
    assert (
        store.create(case["input"], "create-123456", owner_id=case["owner_id"])["id"] == case["id"]
    )
    assert (
        store.create(case["input"], "create-123456", owner_id=str(uuid.uuid4()))["id"] != case["id"]
    )
    assert "owner_id" not in customer_view(case, docs)
    assert "scenario" not in customer_view(case, docs)["input"]


def test_document_replay_stale_revision_and_removal_invalidate_packet(setup):
    store, docs, case = setup
    old = deepcopy(case)
    case, payload = attach(docs, case)
    assert (
        docs.change(store.get(case["id"]), old["version"], data=payload)["version"]
        == case["version"]
    )
    payload["kind"] = "identity"
    with pytest.raises(SandboxError, match="version"):
        docs.change(store.get(case["id"]), old["version"], data=payload)
    case.update(packet={"decision": None}, results={"stale": 1})
    store.save(case)
    document_id = case["document_ids"][0]
    removed = docs.change(case, case["version"], remove=document_id)
    assert removed["document_ids"] == [] and removed["packet"] is None and removed["results"] == {}
    assert docs.get(document_id)["sha256"]  # Original remains in audit history.


@pytest.mark.parametrize(
    "raw,mime",
    [
        (b"not pdf", "application/pdf"),
        (b"<script>attack</script>", "image/png"),
        (b"x" * (MAX_FILE_BYTES + 1), "image/jpeg"),
        (b"x", "text/html"),
    ],
    ids=["invalid_pdf", "disguised_script", "oversize_image", "unsupported_mime"],
)
def test_invalid_uploads_rejected(raw, mime):
    with pytest.raises(SandboxError):
        inspect_document(raw, mime)


def test_parser_checks_all_rows_and_excludes_transfers(setup):
    _, _, case = setup
    evidence = verify_statements([statement()], case)
    assert evidence["status"] == "OK" and evidence["coverage"] == "COMPLETE"
    assert len(evidence["rows"]) == 30 and len(evidence["excluded"]) == 12
    assert all(
        (m["R"], m["V"], m["F"]) == ("200000.00", "100000.00", "45000.00")
        for m in evidence["months"]
    )
    assert all(row["ref"].startswith("DOC-test:page-1:table-1:row-") for row in evidence["rows"])


@pytest.mark.parametrize(
    "old,new",
    [
        ("300,000.00", "300,001.00"),
        ("Mali Jaidee", "Other Person"),
        ("ยอดขาย SALES", "UNKNOWN CASH IN"),
        (
            "<td>Date</td><td>Description</td><td>Debit</td><td>Credit</td>",
            "<td>Date</td><td>Description</td><td>Credit</td><td>Debit</td>",
        ),
        ("<td>300,000.00</td>", "<td></td>"),
    ],
)
def test_ambiguous_or_conflicting_statement_never_becomes_computable(setup, old, new):
    _, _, case = setup
    doc = statement()
    doc["ocr_pages"][0]["text"] = doc["ocr_pages"][0]["text"].replace(old, new)
    evidence = verify_statements([doc], case)
    assert evidence["status"] == "NEEDS_REVIEW"


def test_duplicate_documents_do_not_double_income_but_other_accounts_are_distinct(setup):
    _, _, case = setup
    original, duplicate = statement(), statement()
    duplicate["id"] = "DOC-duplicate"
    evidence = verify_statements([original, duplicate], case)
    assert evidence["months"][0]["R"] == "200000.00"
    duplicate["ocr_pages"][0]["text"] = duplicate["ocr_pages"][0]["text"].replace(
        "TEST-0001", "TEST-0002"
    )
    assert verify_statements([original, duplicate], case)["months"][0]["R"] == "400000.00"


def test_merged_cells_fail_closed():
    doc = statement()
    doc["ocr_pages"][0]["text"] = doc["ocr_pages"][0]["text"].replace("<td>", '<td colspan="2">', 1)
    with pytest.raises(ValueError):
        parse_statement(doc)


def test_app_workflow_uses_uploaded_ocr_and_preserves_human_kyc_gate(setup, monkeypatch):
    store, docs, case = setup
    case, _ = attach(docs, case, "identity")
    case, _ = attach(docs, case)
    calls = []

    class FakeOCR:
        def __init__(self, config):
            pass

        def extract_page(self, raw, mime, page):
            calls.append(mime)
            return {
                "text": statement()["ocr_pages"][0]["text"]
                if mime == "application/pdf"
                else "Full name: Mali Jaidee",
                "page": page,
                "model": "test-ocr",
            }

    monkeypatch.setattr("merchant_sandbox.lending.TyphoonOCR", FakeOCR)
    cfg = Config(api_key="test")
    controller = LendingController(store, docs, cfg)
    result = controller.run(case["id"], BaselinePlanner(), case["version"])
    assert calls == ["image/png", "application/pdf"]
    assert result["state"] == "EXCEPTION_REVIEW" and result["packet"]["decision"] is None
    assert result["packet"]["financial"]["capacity_thb"] == "5000.00"
    assert result["packet"]["financial"]["proposed_limit_thb"] == "28400.00"
    assert "OCR" in result["packet"]["financial"]["assumptions"][0]
    assert not result["packet"]["identity"]["real_identity_verified"]
    assert "wallet_read" not in result["results"]
    revised = store.revise(case["id"], result["input"], case["version"])
    controller.run(case["id"], BaselinePlanner(), revised["version"])
    assert len(calls) == 2  # OCR checkpoint reused on a profile-only revision.


def test_no_consent_or_no_documents_never_calls_provider(setup, monkeypatch):
    store, docs, case = setup

    class ForbiddenPlanner:
        mode = "typhoon"

        def choose(self, *_):
            raise AssertionError("external provider called without consent")

    case["input"]["consent"] = False
    store.save(case)
    result = LendingController(store, docs, Config(api_key="test")).run(
        case["id"], ForbiddenPlanner(), case["version"]
    )
    assert result["state"] == "WAIT_CUSTOMER"
    assert result["llm_calls"] == 0 and not result["packet"]
