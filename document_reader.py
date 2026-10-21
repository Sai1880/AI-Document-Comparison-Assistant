"""PDF validation and text extraction.

This module knows nothing about Streamlit or the LLM. It turns an uploaded
file into an ``ExtractedDocument`` (text kept per page, so page numbers survive)
or raises a ``DocumentError`` with a message that is safe to show to the user.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import BinaryIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

# --- Limits -----------------------------------------------------------------
MAX_FILE_SIZE_MB = 20
# A PDF whose whole text is shorter than this is treated as "no readable text"
# (typical for scanned / image-only PDFs that only contain stray characters).
MIN_TOTAL_CHARS = 50
# A single page with fewer characters than this is reported as unreadable.
MIN_PAGE_CHARS = 5


class DocumentError(Exception):
    """A problem with an uploaded document. The message is user-friendly."""


@dataclass
class PageText:
    number: int  # 1-based page number
    text: str


@dataclass
class ExtractedDocument:
    name: str
    pages: list[PageText] = field(default_factory=list)
    unreadable_pages: list[int] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def char_count(self) -> int:
        return sum(len(p.text) for p in self.pages)

    @property
    def word_count(self) -> int:
        return sum(len(p.text.split()) for p in self.pages)

    @property
    def full_text(self) -> str:
        """All text with ``[Page n]`` markers so the LLM can cite pages."""
        return "\n\n".join(
            f"[Page {p.number}]\n{p.text}" for p in self.pages if p.text
        )

    def preview(self, max_chars: int = 600) -> str:
        """Short preview of the first readable text."""
        flat = re.sub(r"\s+", " ", " ".join(p.text for p in self.pages)).strip()
        return flat if len(flat) <= max_chars else flat[:max_chars].rstrip() + " …"


# --- Helpers ----------------------------------------------------------------
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(raw: str) -> str:
    """Normalise whitespace and strip control characters from extracted text."""
    text = _CONTROL_CHARS.sub("", raw or "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def validate_upload(file_name: str, size_bytes: int) -> None:
    """Cheap checks done before any parsing. Raises DocumentError."""
    if not file_name or not file_name.lower().endswith(".pdf"):
        raise DocumentError(
            f"“{file_name or 'Unnamed file'}” is not a PDF. "
            "Only .pdf files are supported."
        )
    if size_bytes <= 0:
        raise DocumentError(f"“{file_name}” is empty (0 bytes).")
    if size_bytes > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise DocumentError(
            f"“{file_name}” is larger than {MAX_FILE_SIZE_MB} MB. "
            "Please upload a smaller file."
        )


def extract_document(data: bytes | BinaryIO, file_name: str) -> ExtractedDocument:
    """Validate a PDF and extract its text page by page.

    Raises DocumentError for: wrong type, empty file, corrupted PDF, password
    protected PDF, and PDFs without readable text (e.g. scans).
    """
    raw = data if isinstance(data, (bytes, bytearray)) else data.read()
    validate_upload(file_name, len(raw))

    # Real PDFs start with %PDF (allow a little leading junk, as the spec does).
    if b"%PDF" not in raw[:1024]:
        raise DocumentError(
            f"“{file_name}” has a .pdf extension but is not a valid PDF file."
        )

    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            # Many PDFs are "encrypted" with an empty user password.
            if not reader.decrypt(""):
                raise DocumentError(
                    f"“{file_name}” is password-protected. Remove the password "
                    "and upload it again."
                )
        pages_obj = list(reader.pages)
    except DocumentError:
        raise
    except (PdfReadError, ValueError, KeyError, OSError, TypeError) as exc:
        raise DocumentError(
            f"“{file_name}” could not be opened. It may be corrupted. ({exc})"
        ) from exc
    except Exception as exc:  # pypdf can raise a wide range of errors
        raise DocumentError(
            f"“{file_name}” could not be read as a PDF ({type(exc).__name__})."
        ) from exc

    if not pages_obj:
        raise DocumentError(f"“{file_name}” contains no pages.")

    doc = ExtractedDocument(name=file_name)
    for index, page in enumerate(pages_obj, start=1):
        try:
            text = clean_text(page.extract_text() or "")
        except Exception:
            text = ""  # one broken page should not kill the whole document
        if len(text) < MIN_PAGE_CHARS:
            doc.unreadable_pages.append(index)
            text = ""
        doc.pages.append(PageText(number=index, text=text))

    if doc.char_count < MIN_TOTAL_CHARS:
        raise DocumentError(
            f"No readable text was found in “{file_name}”. It may be a scanned "
            "or image-only PDF. OCR is not supported in this version — please "
            "upload a text-based PDF."
        )
    return doc
