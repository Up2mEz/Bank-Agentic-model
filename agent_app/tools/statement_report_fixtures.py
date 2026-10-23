"""Offline fixture factory for the additional S01..S05 statement probes.

build_cases() returns separate case/documents/corroboration/expected keys. Only
case and documents enter ReviewSession. Literal expected values are loaded from
the NEW oracle, never computed by this builder or inserted in model context.
No files are written, no database/network/config/credential access is performed.
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent_app/src"))
sys.path.insert(0, str(ROOT / "agent_app/tools"))

from run_lending_scenario_audit import MockBank, make_document  # noqa: E402

from merchant_sandbox.core import default_input  # noqa: E402

SPEC = ROOT / "examples/merchant_sandbox/statement_review_additional_v1.json"


def build_cases() -> dict:
    """Build fresh synthetic ReviewSession-compatible snapshots without I/O writes.

    Reuse the heldout H01 case shape and existing mock onboarding/make_document
    helpers. No saved run, old fixture or old evaluator is changed. Normalized
    OCR text is the artifact: hashes explicitly do NOT identify a source PDF.
    Corroboration stays None pending the report owner's versioned contract.
    """
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    policy = json.loads(
        (ROOT / "docs/merchant_lending/demo_parameters.json").read_text(encoding="utf-8")
    )
    built = {}
    for sid, scenario in spec["cases"].items():
        data = default_input()
        data.update(
            applicant_name="Mali Jaidee",
            message="ตรวจเอกสารเพื่อเสนอให้เจ้าหน้าที่",
            living_cost_thb="15000.00",
            debt_thb=scenario.get("debt_thb", "10000.00"),
            requested_thb="30000.00",
        )
        bank = MockBank("synthetic-owner").read("synthetic-owner")
        # MockBank's wallet ID is normally random; use a stable mock identity.
        bank["wallet"]["account_id"] = "00000000-0000-4000-8000-000000000001"
        case = {
            "id": f"CASE-{sid}",
            "version": 1,
            "snapshot": f"CASE-{sid}:v1",
            "created_at": spec["as_of"],
            "input": data,
            "state": "DRAFT",
            "active": False,
            "decision": None,
            "trace": [],
            "is_mock": True,
            "policy_snapshot": deepcopy(policy),
            "results": {
                "onboarding_read": {"status": "OK", "snapshot": bank},
                "identity_verify": {"status": "PENDING_REVIEW", "real_identity_verified": False},
            },
        }
        rows = []
        for month, sale in zip(
            spec["months"], scenario.get("sales", spec["base"]["sales"]), strict=True
        ):
            # No zero/zero pseudo-transaction: the full September statement and
            # its real debits establish coverage in the zero-income S03 month.
            if sale:
                rows.append((f"{month}-02", "shop sales", 0, sale))
            rows.extend(
                [
                    (f"{month}-10", "cost of goods", spec["base"]["goods"], 0),
                    (f"{month}-15", "rent", spec["base"]["rent"], 0),
                ]
            )
            rows.extend(
                (f"{month}-{day}", memo, debit, credit)
                for day, memo, debit, credit in scenario.get("monthly_extra_rows", [])
            )
        rows.extend(scenario.get("extra_rows", []))
        documents = []
        layouts = scenario.get(
            "documents",
            [
                {
                    "id": f"DOC-{sid}-A",
                    "start": "2026-04-01",
                    "end": "2026-09-30",
                    "holder": "Mali Jaidee",
                    "account": "OWN-A",
                }
            ],
        )
        for layout in layouts:
            selected = [r for r in rows if layout["start"] <= r[0] <= layout["end"]]
            printed = make_document(
                selected,
                account=layout["account"],
                start=layout["start"],
                end=layout["end"],
                nonce=sid,
            )
            text = printed["text"].replace(
                "Account holder: Mali Jaidee", "Account holder: " + layout["holder"], 1
            )
            documents.append(
                {
                    "id": layout["id"],
                    "case_id": case["id"],
                    "kind": "statement",
                    "sha256": sha256(text.encode("utf-8")).hexdigest(),
                    "pages": 1,
                    "ocr_pages": [{"page": 1, "text": text}],
                    "fixture_provenance": {
                        "mode": "SYNTHETIC_NORMALIZED_OCR_TEXT_NO_PROVIDER_CALL",
                        "sha256_basis": "UTF8_OCR_TEXT_NOT_SOURCE_PDF",
                        "real_document_authenticity_verified": False,
                    },
                }
            )
        built[sid] = {
            "case": case,
            "documents": documents,
            "corroboration": None,
            "expected": deepcopy(scenario["expected"]),
        }
    return built
