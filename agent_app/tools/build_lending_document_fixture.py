"""Build an explicitly synthetic statement with an independent arithmetic oracle."""

import json
from decimal import Decimal
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "examples/merchant_sandbox/documents"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    font = Path("C:/Windows/Fonts/LeelawUI.ttf")
    pdfmetrics.registerFont(TTFont("Thai", str(font)))
    style = ParagraphStyle("body", fontName="Thai", fontSize=10, leading=16)
    heading = ParagraphStyle("heading", parent=style, fontSize=17, leading=25)
    rows = [
        ["Date / วันที่", "Description / รายการ", "Debit / ถอน", "Credit / ฝาก", "Balance / คงเหลือ"]
    ]
    balance = Decimal("100000")
    oracle = []
    for month in range(4, 10):
        for day, description, debit, credit in [
            (2, "ยอดขาย SALES", "0", "200000"),
            (5, "วัตถุดิบ COST OF GOODS", "100000", "0"),
            (7, "ค่าเช่า RENT", "45000", "0"),
            (10, "โอนตนเอง OWN TRANSFER", "0", "10000"),
            (11, "โอนตนเอง OWN TRANSFER", "10000", "0"),
        ]:
            balance += Decimal(credit) - Decimal(debit)
            row = [
                f"2026-{month:02}-{day:02}",
                description,
                f"{Decimal(debit):,.2f}",
                f"{Decimal(credit):,.2f}",
                f"{balance:,.2f}",
            ]
            rows.append(row)
            oracle.append(row)
    story = [
        Paragraph("รายการเดินบัญชีสังเคราะห์ / SYNTHETIC STATEMENT", heading),
        Paragraph("TEST DOCUMENT ONLY - NOT ISSUED BY A BANK", style),
        Spacer(1, 8),
        Paragraph("Account holder: Mali Jaidee", style),
        Paragraph("Account: TEST-0001", style),
        Paragraph("Period: 2026-04-01 to 2026-09-30", style),
        Paragraph("Opening balance: 100,000.00 THB", style),
        Spacer(1, 10),
    ]
    table = Table(rows, colWidths=[73, 177, 75, 75, 85], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Thai"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEADING", (0, 0), (-1, -1), 11),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#bccbc4")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0ede7")),
            ]
        )
    )
    story += [table, Spacer(1, 10), Paragraph(f"Closing balance: {balance:,.2f} THB", style)]
    path = OUT / "synthetic-statement.pdf"
    SimpleDocTemplate(
        str(path), pagesize=A4, rightMargin=40, leftMargin=40, topMargin=26, bottomMargin=26
    ).build(story)
    with pdfium.PdfDocument(path) as pdf:
        for i, page in enumerate(pdf):
            bitmap = page.render(scale=2)
            bitmap.to_pil().save(OUT / f"synthetic-statement-page-{i + 1}.png")
            bitmap.close()
            page.close()
    im = Image.new("RGB", (1200, 550), "white")
    draw = ImageDraw.Draw(im)
    large = ImageFont.truetype(str(font), 35)
    small = ImageFont.truetype(str(font), 27)
    draw.text((50, 50), "SYNTHETIC IDENTITY DOCUMENT", font=large, fill="#164d3d")
    draw.text((50, 130), "NOT A VALID ID / เอกสารทดสอบเท่านั้น", font=small, fill="#a34c2c")
    draw.text((50, 230), "Full name: Mali Jaidee", font=large, fill="black")
    draw.text((50, 310), "Reference: DEMO-ONLY-001", font=small, fill="black")
    draw.text((50, 390), "For local OCR integration testing only", font=small, fill="black")
    im.save(OUT / "synthetic-identity.png")
    (OUT / "oracle.json").write_text(
        json.dumps(
            {
                "rows": oracle,
                "opening": "100000.00",
                "closing": str(balance),
                "expected_capacity": "5000.00",
                "expected_limit": "28400.00",
                "is_synthetic": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"pdf": str(path), "rows": len(oracle), "closing": str(balance)}))


if __name__ == "__main__":
    main()
