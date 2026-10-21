"""Generate sample PDFs for manual testing.

Run from the project root:   python sample_documents/generate_samples.py

Creates (in this folder):
  document_a.pdf / document_b.pdf   - policy v1 vs v2 with different dates/numbers
  identical_a.pdf / identical_b.pdf - same content (must produce NO invented differences)
and (in edge_cases/):
  scanned_image_only.pdf, empty_blank.pdf, long_document.pdf,
  not_a_pdf.pdf (text renamed to .pdf), wrong_type.txt
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

HERE = Path(__file__).parent
EDGE = HERE / "edge_cases"
EDGE.mkdir(exist_ok=True)
styles = getSampleStyleSheet()


def make_pdf(path: Path, title: str, paragraphs: list[str]) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=A4, title=title)
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    for text in paragraphs:
        story += [Paragraph(text, styles["BodyText"]), Spacer(1, 8)]
    doc.build(story)


POLICY_V1 = [
    "<b>Purpose.</b> This policy explains how employees request annual leave at Northwind Training Institute.",
    "<b>Effective date:</b> 1 January 2025.",
    "<b>Entitlement.</b> Full-time employees receive 20 days of paid annual leave per year.",
    "<b>Notice period.</b> Leave requests must be submitted at least 14 days in advance to the HR Manager, Priya Nair.",
    "<b>Carry-over.</b> Up to 5 unused days may be carried over to the next calendar year.",
    "<b>Approval.</b> Requests are approved by the line manager and confirmed by HR.",
    "<b>Sick leave.</b> A medical certificate is required for absences longer than 3 consecutive days.",
]
POLICY_V2 = [
    "<b>Purpose.</b> This policy explains how employees request annual leave at Northwind Training Institute.",
    "<b>Effective date:</b> 1 July 2026.",
    "<b>Entitlement.</b> Full-time employees receive 24 days of paid annual leave per year.",
    "<b>Notice period.</b> Leave requests must be submitted at least 7 days in advance to the HR Manager, Daniel Ortiz.",
    "<b>Carry-over.</b> Up to 5 unused days may be carried over to the next calendar year.",
    "<b>Approval.</b> Requests are approved by the line manager and confirmed by HR.",
    "<b>Sick leave.</b> A medical certificate is required for absences longer than 2 consecutive days.",
    "<b>Remote work.</b> Employees may work remotely up to 2 days per week with manager approval.",
]

make_pdf(HERE / "document_a.pdf", "Annual Leave Policy - Version 1", POLICY_V1)
make_pdf(HERE / "document_b.pdf", "Annual Leave Policy - Version 2", POLICY_V2)
make_pdf(HERE / "identical_a.pdf", "Annual Leave Policy", POLICY_V1)
make_pdf(HERE / "identical_b.pdf", "Annual Leave Policy", POLICY_V1)

# --- Edge cases --------------------------------------------------------------
# 1. Scanned / image-only PDF: text drawn into a bitmap, so there is no text layer.
try:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(POLICY_V1):
        draw.text((80, 100 + i * 60), line.replace("<b>", "").replace("</b>", ""), fill="black")
    img_path = EDGE / "_scan.png"
    img.save(img_path)
    c = canvas.Canvas(str(EDGE / "scanned_image_only.pdf"), pagesize=A4)
    c.drawImage(str(img_path), 0, 0, width=A4[0], height=A4[1])
    c.save()
    img_path.unlink()
except ImportError:
    print("Pillow is not installed - skipped scanned_image_only.pdf")

# 2. Blank PDF (one page, no content).
c = canvas.Canvas(str(EDGE / "empty_blank.pdf"), pagesize=A4)
c.showPage()
c.save()

# 3. Long document (~180 pages) to exercise condensing / the too-long message.
long_doc = SimpleDocTemplate(str(EDGE / "long_document.pdf"), pagesize=A4)
story = []
for n in range(1, 181):
    story.append(Paragraph(f"Section {n}", styles["Heading1"]))
    for k in range(1, 9):
        story.append(
            Paragraph(
                (f"Clause {n}.{k}: The participant must complete module {n} by deadline {k} "
                 f"and pay a fee of ${n * 10 + k}. ") * 6,
                styles["BodyText"],
            )
        )
    story.append(PageBreak())
long_doc.build(story)

# 4. Fake PDF (text file renamed) and a wrong file type.
(EDGE / "not_a_pdf.pdf").write_text("This is just plain text pretending to be a PDF.")
(EDGE / "wrong_type.txt").write_text("A plain text file - the app must reject it.")

print("Sample documents created in", HERE)
