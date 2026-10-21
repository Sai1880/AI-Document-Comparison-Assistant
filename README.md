# AI Document Comparison Assistant

A Streamlit web app that compares two PDF documents with a Large Language Model (Gemini).
It extracts the text, validates the inputs, produces a summary of each document, lists
similarities, differences and key details (dates, amounts, names, requirements), and exports
a DOCX report.

> **Scope:** informational comparison only. It does **not** give legal advice and never states
> that a document is legally safe, compliant, or equivalent.

## Features (mapped to the brief)

| Requirement | Where |
|---|---|
| FR-01 Upload two PDFs, show names | `app.py` (two uploaders, "Selected: …") |
| FR-02 Validate files (type, empty, no readable text, corrupted, password, size) | `document_reader.py` |
| FR-03 Extract text per document, keep page numbers | `ExtractedDocument.pages`, `[Page n]` markers |
| FR-04 Preview / character + page count | `render_previews()` |
| FR-05 – FR-08 Summaries, similarities, differences, key details | `comparison.py` (prompt + JSON schema) |
| FR-09 Labelled tabs | `render_result()` |
| FR-10 Download DOCX report | `report_generator.py` |
| FR-11 Error handling (API, timeout, long docs, missing input) | `comparison.py` error classes + `app.py` |
| FR-12 Reset and compare again | `reset_all()` (changes uploader keys) |

Extras beyond the brief: evidence verification (quotes are checked against the PDF text and
flagged "unverified"), automatic retry for transient API errors, one repair retry for malformed
JSON, chunk-and-condense strategy for long documents, prompt-injection resistance.

## Project structure

```
ai-document-comparison-assistant/
├── app.py                 # Streamlit UI and session state
├── document_reader.py     # PDF validation + text extraction (pypdf)
├── comparison.py          # Prompts, Gemini client, JSON parsing/validation, long-doc handling
├── report_generator.py    # DOCX report (python-docx)
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── docs/
│   ├── TEST_PLAN.md       # Manual + automated test matrix
│   └── VIVA_NOTES.md      # Explanations and likely viva questions
├── sample_documents/
│   ├── generate_samples.py
│   ├── document_a.pdf / document_b.pdf      # policy v1 vs v2 (different dates/numbers)
│   ├── identical_a.pdf / identical_b.pdf    # must produce no invented differences
│   └── edge_cases/                          # scanned, blank, long, fake PDF, .txt
└── tests/                 # 54 pytest tests (no real API calls needed)
```

## Setup

```bash
git clone <your-repo-url> && cd ai-document-comparison-assistant
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Edit `.env` and set `GEMINI_API_KEY` (free key: https://aistudio.google.com/apikey).
Optionally set `GEMINI_MODEL` (default `gemini-2.5-flash`).

## Run

```bash
streamlit run app.py
```

Try it with `sample_documents/document_a.pdf` (Document A) and `document_b.pdf` (Document B).
Regenerate samples any time: `python sample_documents/generate_samples.py`.

## Run the tests

```bash
python -m pytest -q
```

The tests use a fake LLM, so they need no API key or internet.

## How it works

1. **Validate** - extension, size, empty file, `%PDF` header, corruption, password protection.
2. **Extract** - `pypdf` reads each page; text is cleaned and kept per page. Pages with
   (almost) no text are listed as unreadable. If the *whole* file has no readable text
   (scanned PDF) the app stops with a clear message (OCR is a possible enhancement).
3. **Fit the input limit** - up to 100,000 characters per document are sent directly. Longer
   documents are split on page boundaries (60,000-char chunks), each chunk is condensed by the
   LLM (keeping dates, numbers, names and page markers), then the condensed notes are compared.
   Beyond 10 chunks (~600k characters) the app refuses with a clear message.
4. **Compare** - one LLM call with a strict system prompt and clearly delimited
   `DOCUMENT A` / `DOCUMENT B` blocks. Temperature is 0.1 and JSON output is requested.
5. **Validate the response** - code fences stripped, JSON parsed, schema enforced, types coerced,
   missing item fields set to "Not found in the provided text". Invalid output triggers one
   repair retry, then a safe error.
6. **Verify evidence** - every quoted excerpt is searched in the original extracted text; misses
   are marked unverified in the UI and report, and counted in Limitations.
7. **Display and export** - seven tabs on screen; the same sections in the DOCX.

## Response JSON schema

```json
{
  "summary_a": "", "summary_b": "",
  "similarities": [{"point": "", "evidence_a": "", "evidence_b": "", "page_a": "", "page_b": ""}],
  "differences":  [{"topic": "", "type": "added|removed|changed|conflict",
                    "document_a": "", "document_b": "",
                    "evidence_a": "", "evidence_b": "", "page_a": "", "page_b": ""}],
  "key_details":  [{"field": "", "document_a": "", "document_b": "",
                    "status": "same|different|only_in_a|only_in_b"}],
  "conclusion": "", "limitations": ""
}
```

## Error handling summary

| Situation | Behaviour |
|---|---|
| A file missing | "Please upload both Document A and Document B" |
| Not a PDF / fake PDF / empty / corrupted / password-protected / too big | Specific message naming the file and which document slot |
| Scanned or blank PDF | "No readable text… may be scanned. OCR not supported" - no comparison |
| Some pages unreadable | Comparison proceeds; pages listed under Limitations |
| Missing or invalid API key, wrong model | Configuration message pointing to `.env` |
| Rate limit / 5xx / network / timeout | Auto-retry (2s, 5s), then error + **Retry comparison** button |
| Malformed model output | One repair retry, then safe error + Retry |
| Document too long | Condensed in chunks, or a clear "too long" message |
| Unexpected exception | Generic message, no stack trace shown |

## Limitations

- No OCR: scanned/image-only PDFs are rejected. Tables and multi-column layouts can come out
  in a jumbled reading order from `pypdf`.
- LLMs can still misread or omit things. Quote verification catches fabricated *quotes*, not
  every wrong *interpretation*; always check important points in the originals.
- Condensing very long documents may lose fine detail (flagged in Limitations).
- Content is sent to the Gemini API: do not upload confidential documents unless your
  organisation approves it.
- Not a legal decision-maker.

## Ideas for enhancement

OCR (e.g. `pytesseract`/`pdf2image`) for scans, side-by-side highlighted diff view,
PDF report option (ReportLab), support for DOCX/TXT inputs, caching results by file hash,
a provider switch (OpenAI/Anthropic) behind the same `(system, user) -> str` interface.

## Git workflow suggestion

```bash
git init && git add . && git commit -m "Initial project structure"
# commit per milestone: reader, comparison, report, UI, tests, README
git branch -M main
git remote add origin <your-repo-url> && git push -u origin main
```
Check `git status` shows **no `.env`** before pushing.
