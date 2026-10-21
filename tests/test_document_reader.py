import io

import pytest
from pypdf import PdfWriter

from conftest import EDGE, SAMPLES
from document_reader import DocumentError, extract_document, validate_upload


def read(path):
    return extract_document(path.read_bytes(), path.name)


def test_valid_pdf_extracts_text_and_pages():
    doc = read(SAMPLES / "document_a.pdf")
    assert doc.page_count == 1
    assert "20 days of paid annual leave" in doc.full_text
    assert doc.char_count > 200 and doc.word_count > 30
    assert "[Page 1]" in doc.full_text
    assert doc.unreadable_pages == []


def test_documents_stay_separate():
    a, b = read(SAMPLES / "document_a.pdf"), read(SAMPLES / "document_b.pdf")
    assert "24 days" in b.full_text and "24 days" not in a.full_text


def test_preview_is_short():
    doc = read(EDGE / "long_document.pdf")
    assert len(doc.preview(300)) <= 305


def test_wrong_file_type_rejected():
    with pytest.raises(DocumentError, match="not a PDF"):
        extract_document(b"hello", "notes.txt")


def test_empty_file_rejected():
    with pytest.raises(DocumentError, match="empty"):
        extract_document(b"", "empty.pdf")


def test_fake_pdf_rejected():
    with pytest.raises(DocumentError, match="not a valid PDF"):
        read(EDGE / "not_a_pdf.pdf")


def test_corrupted_pdf_rejected():
    data = (SAMPLES / "document_a.pdf").read_bytes()
    with pytest.raises(DocumentError):
        extract_document(data[: len(data) // 3], "broken.pdf")


def test_scanned_pdf_gives_helpful_message():
    with pytest.raises(DocumentError, match="No readable text.*scanned"):
        read(EDGE / "scanned_image_only.pdf")


def test_blank_pdf_rejected():
    with pytest.raises(DocumentError, match="No readable text"):
        read(EDGE / "empty_blank.pdf")


def test_password_protected_rejected():
    writer = PdfWriter()
    writer.append(str(SAMPLES / "document_a.pdf"))
    writer.encrypt("secret")
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(DocumentError, match="password"):
        extract_document(buf.getvalue(), "locked.pdf")


def test_oversized_file_rejected():
    with pytest.raises(DocumentError, match="larger than"):
        validate_upload("big.pdf", 25 * 1024 * 1024)


def test_partially_blank_pdf_reports_unreadable_pages():
    writer = PdfWriter()
    writer.append(str(SAMPLES / "document_a.pdf"))
    writer.add_blank_page(595, 842)
    buf = io.BytesIO()
    writer.write(buf)
    doc = extract_document(buf.getvalue(), "mixed.pdf")
    assert doc.page_count == 2 and doc.unreadable_pages == [2]
