"""Conservative statement table parser; ambiguities become review gaps, not income."""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser

from .core import digest, money

D = Decimal
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?"
DATE = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})"


def normal_name(value):
    return re.sub(r"[^\w]", "", value.casefold(), flags=re.UNICODE)


def parse_date(value):
    if "/" in value:
        day, month, year = map(int, value.split("/"))
    else:
        year, month, day = map(int, value.split("-"))
    if year > 2400:
        year -= 543
    return date(year, month, day)


def parse_amount(value):
    value = value.strip().replace("฿", "").replace("THB", "").strip()
    if value in {"", "-", "—"}:
        return D(0)
    if not re.fullmatch(NUMBER, value):
        raise ValueError("invalid amount")
    result = D(value.replace(",", ""))
    if result > D("999999999.99"):
        raise ValueError("amount out of range")
    return result


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.rows, self.row, self.cell = [], [], [], None
        self.unsupported = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.rows = []
        elif tag == "tr":
            self.row = []
        elif tag in {"td", "th"}:
            if any(k in {"colspan", "rowspan"} and v != "1" for k, v in attrs):
                self.unsupported = True
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join(self.cell).strip())
            self.cell = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
        elif tag == "table":
            self.tables.append(self.rows)


def get_tables(text):
    parser = Tables()
    parser.feed(text)
    if parser.unsupported:
        raise ValueError("merged cells require review")
    if parser.tables:
        return parser.tables
    rows, tables = [], []
    for line in text.splitlines() + [""]:
        if line.strip().startswith("|"):
            cells = [x.strip() for x in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r"[:\-\s]+", x or "-") for x in cells):
                rows.append(cells)
        elif rows:
            tables.append(rows)
            rows = []
    return tables


def category(description, debit, credit):
    text = description.casefold()
    if any(x in text for x in ("own transfer", "โอนตนเอง", "โอนบัญชีตนเอง")):
        return "OWN_TRANSFER"
    if credit and any(x in text for x in ("loan proceeds", "เงินกู้รับ")):
        return "LOAN_PROCEEDS"
    if credit and any(x in text for x in ("sales", "ยอดขาย")):
        return "R"
    if debit and any(x in text for x in ("cost of goods", "วัตถุดิบ", "ต้นทุนสินค้า")):
        return "V"
    if debit and any(x in text for x in ("rent", "payroll", "ค่าเช่า", "เงินเดือนพนักงาน")):
        return "F"
    if debit and any(x in text for x in ("loan repayment", "ชำระหนี้")):
        return "D"
    return "UNRESOLVED"


def expected_months(as_of):
    current = date.fromisoformat(as_of[:10]).replace(day=1)
    out = []
    for _ in range(6):
        current = date(current.year - (current.month == 1), (current.month - 2) % 12 + 1, 1)
        out.append(current.strftime("%Y-%m"))
    return sorted(out)


def parse_statement(doc):
    text = "\n".join(page["text"] for page in doc["ocr_pages"])
    plain = re.sub(r"<[^>]*>", " ", text).replace("**", "")
    name = re.search(r"(?:Account holder|ชื่อบัญชี)\s*[:：]\s*([^\n]+)", plain, re.I)
    account = re.search(r"(?:Account|เลขที่บัญชี)\s*[:：]\s*([^\n]+)", plain, re.I)
    period = re.search(
        r"(?:Period|ช่วงรายการ)\s*[:：]\s*(" + DATE + r")\s*(?:to|ถึง|[-–])\s*(" + DATE + r")",
        plain,
        re.I,
    )
    opening = re.search(r"(?:Opening balance|ยอดยกมา)\s*[:：]\s*(" + NUMBER + ")", plain, re.I)
    closing = re.search(
        r"(?:Closing balance|ยอดคงเหลือสุดท้าย)\s*[:：]\s*(" + NUMBER + ")", plain, re.I
    )
    if not all((name, account, period, opening, closing)):
        raise ValueError("ต้องมีชื่อ/เลขบัญชี ช่วงรายการ ยอดยกมา และยอดคงเหลือสุดท้าย")
    start, end = parse_date(period[1]), parse_date(period[2])
    if start > end or (end - start).days > 370:
        raise ValueError("ช่วงรายการไม่ถูกต้อง")
    balance, rows, last_date = parse_amount(opening[1]), [], start
    for page in doc["ocr_pages"]:
        for table_no, table in enumerate(get_tables(page["text"]), 1):
            if not table:
                continue
            header = " ".join(table[0]).casefold()
            if not all(
                any(x in header for x in group)
                for group in [
                    ("date", "วันที่"),
                    ("debit", "ถอน"),
                    ("credit", "ฝาก"),
                    ("balance", "คงเหลือ"),
                ]
            ):
                raise ValueError("ตารางไม่ใช่รูปแบบ วันที่/รายการ/ถอน/ฝาก/คงเหลือ ที่รองรับ")
            # Check each column, not only whether all labels occur somewhere.
            if len(table[0]) != 5 or not all(
                any(label in table[0][i].casefold() for label in labels)
                for i, labels in enumerate(
                    [
                        ("date", "วันที่"),
                        ("description", "รายการ"),
                        ("debit", "ถอน"),
                        ("credit", "ฝาก"),
                        ("balance", "คงเหลือ"),
                    ]
                )
            ):
                raise ValueError("ลำดับคอลัมน์ไม่รองรับ ต้องให้เจ้าหน้าที่ตรวจ")
            for row_no, cells in enumerate(table[1:], 2):
                if len(cells) != 5:
                    raise ValueError("จำนวนช่องในแถวไม่ครบ")
                if cells[4].strip() in {"", "-", "—"}:
                    raise ValueError("ยอดคงเหลือในแถวอ่านไม่ได้ ต้องตรวจเอกสาร")
                when = parse_date(cells[0].strip())
                debit, credit, observed = map(parse_amount, cells[2:])
                if not start <= when <= end or when < last_date or (debit > 0) == (credit > 0):
                    raise ValueError("วันที่/ยอดถอนฝากในแถวไม่ถูกต้อง")
                balance += credit - debit
                if balance != observed:
                    raise ValueError(f"ยอดคงเหลือไม่ตรงที่หน้า {page['page']} แถว {row_no}")
                ref = f"{doc['id']}:page-{page['page']}:table-{table_no}:row-{row_no}"
                rows.append(
                    {
                        "date": when.isoformat(),
                        "description": cells[1],
                        "debit": money(debit),
                        "credit": money(credit),
                        "balance": money(observed),
                        "category": category(cells[1], debit, credit),
                        "ref": ref,
                        "page": page["page"],
                        "row": row_no,
                        "bbox": None,
                    }
                )
                last_date = when
    if not rows or balance != parse_amount(closing[1]):
        raise ValueError("ไม่มีรายการหรือยอดปิดบัญชีไม่ตรง")
    return {
        "account_holder": name[1].strip(),
        "account": account[1].strip(),
        "start": start,
        "end": end,
        "rows": rows,
    }


def verify_statements(documents, case):
    expected = expected_months(case["created_at"])
    months = {m: {"R": D(0), "O": D(0), "V": D(0), "F": D(0), "refs": []} for m in expected}
    covered, all_rows, seen, excluded, issues, holders = set(), [], set(), [], [], []
    account_coverage = {}
    debt_payments = {m: D(0) for m in expected}
    for doc in documents:
        if doc["kind"] != "statement":
            continue
        try:
            parsed = parse_statement(doc)
        except (ValueError, TypeError, KeyError) as exc:
            issues.append({"document_id": doc["id"], "reason": str(exc)[:250]})
            continue
        holders.append(parsed["account_holder"])
        account_months = account_coverage.setdefault(parsed["account"], set())
        if normal_name(parsed["account_holder"]) != normal_name(case["input"]["applicant_name"]):
            issues.append({"document_id": doc["id"], "reason": "ชื่อบัญชีไม่ตรงกับชื่อที่ผู้สมัครแจ้ง"})
        for month in expected:
            year, number = map(int, month.split("-"))
            if parsed["start"] <= date(year, number, 1) and parsed["end"] >= date(
                year, number, monthrange(year, number)[1]
            ):
                covered.add(month)
                account_months.add(month)
        for row in parsed["rows"]:
            signature = (
                normal_name(parsed["account_holder"]),
                parsed["account"],
                row["date"],
                row["description"],
                row["debit"],
                row["credit"],
                row["balance"],
            )
            if signature in seen:
                excluded.append({"ref": row["ref"], "reason": "DUPLICATE_TRANSACTION"})
                continue
            seen.add(signature)
            all_rows.append(row)
            month, kind = row["date"][:7], row["category"]
            if month not in months:
                excluded.append({"ref": row["ref"], "reason": "OUTSIDE_WINDOW"})
            elif kind in {"OWN_TRANSFER", "LOAN_PROCEEDS"}:
                excluded.append({"ref": row["ref"], "reason": kind})
            elif kind == "D":
                debt_payments[month] += D(row["debit"])
                excluded.append({"ref": row["ref"], "reason": "DEBT_PAID_COUNTED_IN_DECLARED_D"})
            elif kind == "UNRESOLVED":
                issues.append(
                    {"ref": row["ref"], "reason": "ประเภทรายการไม่ชัดเจน ต้องตรวจโดยเจ้าหน้าที่"}
                )
            else:
                months[month][kind] += D(row["credit"] if kind in {"R", "O"} else row["debit"])
                months[month]["refs"].append(row["ref"])
    declared = case["input"]["debt_thb"]
    if declared is not None and max(debt_payments.values()) > D(declared):
        issues.append({"reason": "ยอดชำระหนี้ในเอกสารสูงกว่าภาระหนี้ที่แจ้ง ต้องทบทวนข้อมูล"})
    missing = sorted(set(expected) - covered)
    if len(account_coverage) > 1:
        for covered_months in account_coverage.values():
            if set(expected) - covered_months:
                issues.append(
                    {"reason": "แนบหลายบัญชีแต่บางบัญชีมีช่วงเดือนไม่ครบ ต้องตรวจความครอบคลุมแยกบัญชี"}
                )
    return {
        "status": "NEEDS_REVIEW" if issues else "OK",
        "source": "typhoon_ocr_statement",
        "coverage": "COMPLETE" if not missing else "PARTIAL",
        "expected_months": expected,
        "missing_months": missing,
        "months": [
            {"month": m, **{k: money(v) if k != "refs" else v for k, v in values.items()}}
            for m, values in months.items()
        ],
        "excluded": excluded,
        "rows": all_rows,
        "issues": issues,
        "account_holders": holders,
        "evidence_refs": [x["ref"] for x in all_rows],
        "source_sha256": digest([d["sha256"] for d in documents if d["kind"] == "statement"]),
        "provenance": "UPLOADED_DOCUMENT_TYPHOON_OCR_UNVERIFIED_AUTHENTICITY",
        "is_mock": False,
    }
