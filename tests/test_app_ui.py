"""UI tests using Streamlit's AppTest (no browser, no real API)."""
import json

from streamlit.testing.v1 import AppTest

import comparison
from comparison import LLMServiceError
from test_comparison import FakeLLM, good_payload
from conftest import ROOT, SAMPLES, EDGE


def make_app(llm):
    class _Client:
        model = "fake"
        def __init__(self, *a, **k): pass
        def __call__(self, s, u, json_mode=True): return llm(s, u, json_mode)
    comparison.GeminiClient = _Client  # app imports compare_documents which looks this up
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    return at


def test_app_loads_with_required_ui():
    at = make_app(FakeLLM(good_payload())).run()
    assert not at.exception
    assert at.title[0].value == "AI Document Comparison Assistant"
    assert [b.label for b in at.button] == ["Compare Documents", "Reset"]


def test_missing_files_message():
    at = make_app(FakeLLM(good_payload())).run()
    at.button[0].click().run()
    assert any("both" in e.value for e in at.error)


def upload(at, a_path, b_path):
    for widget, path in zip(at.file_uploader, (a_path, b_path)):
        widget.upload(path.name, path.read_bytes(), "application/pdf")
    return at


def test_full_flow_results_tabs_and_download():
    at = make_app(FakeLLM(good_payload())).run()
    upload(at, SAMPLES / "document_a.pdf", SAMPLES / "document_b.pdf").run()
    at.button[0].click().run()
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs] == [
        "Summary A", "Summary B", "Similarities", "Differences",
        "Key Details", "Overall Conclusion", "Limitations"]
    assert any("Comparison complete" in s.value for s in at.success)
    assert at.metric  # extracted page/char counts shown (FR-04)


def test_scanned_pdf_blocks_comparison_with_message():
    at = make_app(FakeLLM(good_payload())).run()
    upload(at, EDGE / "scanned_image_only.pdf", SAMPLES / "document_b.pdf").run()
    at.button[0].click().run()
    assert any("No readable text" in e.value for e in at.error)
    assert not at.tabs  # no misleading comparison


def test_api_failure_shows_error_and_retry_works():
    llm = FakeLLM(LLMServiceError("down"))
    at = make_app(llm).run()
    upload(at, SAMPLES / "document_a.pdf", SAMPLES / "document_b.pdf").run()
    at.button[0].click().run()
    assert any("down" in e.value for e in at.error)
    assert any(b.label == "Retry comparison" for b in at.button)
    llm.replies = [good_payload()]  # service recovers
    next(b for b in at.button if b.label == "Retry comparison").click().run()
    assert any("Comparison complete" in s.value for s in at.success)


def test_reset_clears_everything():
    at = make_app(FakeLLM(good_payload())).run()
    upload(at, SAMPLES / "document_a.pdf", SAMPLES / "document_b.pdf").run()
    at.button[0].click().run()
    next(b for b in at.button if b.label == "Reset").click().run()
    assert at.session_state["result"] is None and at.session_state["docs"] is None
    assert at.session_state["uploader_key"] == 1
    assert not at.tabs
