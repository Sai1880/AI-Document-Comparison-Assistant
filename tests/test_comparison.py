import json

import pytest

import comparison as cmp
from comparison import (
    NOT_FOUND, ComparisonError, ConfigurationError, DocumentTooLongError,
    GeminiClient, LLMServiceError, ResponseValidationError, compare_documents,
    parse_json_response, validate_result,
)
from document_reader import ExtractedDocument, PageText, extract_document
from conftest import EDGE, SAMPLES


def load(name):
    p = SAMPLES / name
    return extract_document(p.read_bytes(), p.name)


def good_payload(**over):
    data = {
        "summary_a": "Policy v1 grants 20 days of leave.",
        "summary_b": "Policy v2 grants 24 days of leave and adds remote work.",
        "similarities": [{
            "point": "Carry-over of 5 days",
            "evidence_a": "Up to 5 unused days may be carried over",
            "evidence_b": "Up to 5 unused days may be carried over",
            "page_a": "1", "page_b": "1"}],
        "differences": [{
            "topic": "Annual leave entitlement", "type": "changed",
            "document_a": "20 days", "document_b": "24 days",
            "evidence_a": "receive 20 days of paid annual leave",
            "evidence_b": "receive 24 days of paid annual leave",
            "page_a": "1", "page_b": "1"}],
        "key_details": [
            {"field": "Annual leave", "document_a": "20 days", "document_b": "24 days", "status": "different"},
            {"field": "Remote work", "document_a": NOT_FOUND, "document_b": "2 days per week", "status": "only_in_b"}],
        "conclusion": "Version 2 increases leave and adds remote work.",
        "limitations": "",
    }
    data.update(over)
    return data


class FakeLLM:
    """Returns queued replies; an Exception instance in the queue is raised."""
    model = "fake"

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, system, user, json_mode=True):
        self.calls.append((system, user, json_mode))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)


nosleep = lambda s: None


def run(llm, a="document_a.pdf", b="document_b.pdf"):
    return compare_documents(load(a), load(b), llm=llm, sleep=nosleep)


# ---- happy path / prompt ----------------------------------------------------
def test_two_valid_pdfs_produce_full_result():
    r = run(FakeLLM(good_payload()))
    assert r["summary_a"] and r["summary_b"] and r["conclusion"]
    assert r["differences"][0]["document_b"] == "24 days"
    assert r["meta"]["file_name_a"] == "document_a.pdf"
    assert r["limitations"][-1] == cmp.DISCLAIMER


def test_prompt_keeps_documents_separate_and_has_rules():
    llm = FakeLLM(good_payload())
    run(llm)
    system, user, _ = llm.calls[0]
    assert "=== DOCUMENT A (file: document_a.pdf) ===" in user
    assert "=== DOCUMENT B (file: document_b.pdf) ===" in user
    assert user.index("20 days") < user.index("=== DOCUMENT B") < user.index("24 days")
    for phrase in (NOT_FOUND, "ONLY", "never invent", "legally"):
        assert phrase.lower() in system.lower()


# ---- parsing / validation -----------------------------------------------------
def test_code_fenced_json_is_accepted():
    raw = "```json\n" + json.dumps(good_payload()) + "\n```"
    assert run(FakeLLM(raw))["conclusion"]


def test_json_with_chatter_is_accepted():
    raw = "Here you go:\n" + json.dumps(good_payload()) + "\nHope that helps!"
    assert run(FakeLLM(raw))["conclusion"]


def test_malformed_then_valid_retries_once():
    llm = FakeLLM("{not json", good_payload())
    assert run(llm)["conclusion"]
    assert len(llm.calls) == 2 and "rejected" in llm.calls[1][1]


def test_malformed_twice_gives_safe_error():
    with pytest.raises(ResponseValidationError, match="unexpected format"):
        run(FakeLLM("garbage"))


def test_missing_keys_rejected():
    bad = good_payload()
    del bad["differences"]
    with pytest.raises(ResponseValidationError, match="differences"):
        validate_result(bad)


def test_wrong_types_rejected():
    with pytest.raises(ResponseValidationError, match="must be a list"):
        validate_result(good_payload(similarities="none"))
    with pytest.raises(ResponseValidationError, match="not an object"):
        validate_result(good_payload(differences=["x"]))


def test_missing_item_fields_filled_with_not_found():
    r = validate_result(good_payload(differences=[{"topic": "T"}]))
    assert r["differences"][0]["document_a"] == NOT_FOUND
    assert r["differences"][0]["type"] == "changed"


def test_status_is_derived_when_invalid():
    r = validate_result(good_payload(key_details=[
        {"field": "x", "document_a": "1", "document_b": "2", "status": "???"},
        {"field": "y", "document_a": NOT_FOUND, "document_b": "2", "status": ""}]))
    assert [k["status"] for k in r["key_details"]] == ["different", "only_in_b"]


def test_parse_json_rejects_non_object():
    with pytest.raises(ResponseValidationError):
        parse_json_response("[1, 2]")
    with pytest.raises(ResponseValidationError):
        parse_json_response("")


# ---- accuracy safeguards ------------------------------------------------------
def test_identical_documents_do_not_invent_differences():
    payload = good_payload(differences=[], key_details=[])
    r = run(FakeLLM(payload), "identical_a.pdf", "identical_b.pdf")
    assert r["differences"] == []


def test_fabricated_quote_is_flagged_unverified():
    payload = good_payload()
    payload["differences"][0]["evidence_b"] = "employees receive 30 days of leave"
    r = run(FakeLLM(payload))
    assert r["differences"][0]["evidence_b_verified"] is False
    assert r["differences"][0]["evidence_a_verified"] is True
    assert r["evidence_warnings"]
    assert any("unverified" in l for l in r["limitations"])


def test_not_found_and_empty_evidence_are_not_checked():
    payload = good_payload()
    payload["differences"][0]["evidence_a"] = NOT_FOUND
    payload["differences"][0]["evidence_b"] = ""
    r = run(FakeLLM(payload))
    assert r["differences"][0]["evidence_a_verified"] is None
    assert r["differences"][0]["evidence_b_verified"] is None


def test_quote_with_ellipsis_and_page_marker_verifies():
    assert cmp.excerpt_in_text("Up to 5 unused days … next calendar year", load("document_a.pdf").full_text) is True


def test_legal_claim_wording_is_flagged():
    r = run(FakeLLM(good_payload(conclusion="Version 2 is legally compliant.")))
    assert any("legal" in l.lower() and "judgement" in l for l in r["limitations"])


def test_unreadable_pages_listed_in_limitations():
    a = load("document_a.pdf")
    a.unreadable_pages = [2]
    r = compare_documents(a, load("document_b.pdf"), llm=FakeLLM(good_payload()), sleep=nosleep)
    assert any("page(s) 2" in l for l in r["limitations"])


# ---- API failures -------------------------------------------------------------
def test_transient_failure_is_retried_then_succeeds():
    llm = FakeLLM(LLMServiceError("rate limited"), good_payload())
    assert run(llm)["conclusion"] and len(llm.calls) == 2


def test_persistent_api_failure_raises_retryable_error():
    with pytest.raises(LLMServiceError) as exc:
        run(FakeLLM(LLMServiceError("down")))
    assert exc.value.retryable is True


def test_configuration_error_is_not_retried():
    llm = FakeLLM(ConfigurationError("bad key"))
    with pytest.raises(ConfigurationError):
        run(llm)
    assert len(llm.calls) == 1


def test_missing_api_key_message(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        GeminiClient()


class _Err(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


@pytest.mark.parametrize("exc,expected_type,fragment", [
    (_Err("API key not valid", 400), ConfigurationError, "API key"),
    (_Err("forbidden", 403), ConfigurationError, "API key"),
    (_Err("not found", 404), ConfigurationError, "model"),
    (_Err("quota", 429), LLMServiceError, "rate-limited"),
    (_Err("oops", 503), LLMServiceError, "unavailable"),
    (_Err("input token count exceeds the maximum", 400), DocumentTooLongError, "too long"),
    (type("ReadTimeout", (Exception,), {})("read timed out"), LLMServiceError, "timed out"),
    (_Err("weird"), LLMServiceError, "error"),
])
def test_error_mapping(exc, expected_type, fragment):
    mapped = GeminiClient._map_error(exc)
    assert isinstance(mapped, expected_type) and fragment in str(mapped)


# ---- long documents -----------------------------------------------------------
def make_long_doc():
    return ExtractedDocument("long.pdf", [PageText(i, f"Clause {i}: pay ${i * 10}. " * 40) for i in range(1, 30)])


def test_long_document_is_condensed_in_chunks(monkeypatch):
    monkeypatch.setattr(cmp, "MAX_CHARS_PER_DOC", 5_000)
    monkeypatch.setattr(cmp, "CHUNK_CHARS", 3_000)
    monkeypatch.setattr(cmp, "MAX_CHUNKS_PER_DOC", 200)
    long = make_long_doc()
    n_chunks = len(cmp.split_into_chunks(long))
    assert n_chunks > 1
    # first n_chunks calls are the condensing step (plain text), the last is the comparison
    llm = FakeLLM(*(["condensed notes"] * n_chunks + [good_payload()]))
    r = compare_documents(long, load("document_b.pdf"), llm=llm, sleep=nosleep)
    assert len(llm.calls) == n_chunks + 1
    assert all(c[2] is False for c in llm.calls[:n_chunks])
    assert any("condensed" in l for l in r["limitations"])


def test_too_long_document_gives_clear_message(monkeypatch):
    monkeypatch.setattr(cmp, "MAX_CHARS_PER_DOC", 1_000)
    monkeypatch.setattr(cmp, "CHUNK_CHARS", 500)
    monkeypatch.setattr(cmp, "MAX_CHUNKS_PER_DOC", 2)
    with pytest.raises(DocumentTooLongError, match="too long"):
        compare_documents(make_long_doc(), load("document_b.pdf"), llm=FakeLLM(good_payload()), sleep=nosleep)


def test_real_long_pdf_splits_into_page_based_chunks():
    doc = extract_document((EDGE / "long_document.pdf").read_bytes(), "long.pdf")
    chunks = cmp.split_into_chunks(doc)
    assert all(len(c) <= cmp.CHUNK_CHARS for c in chunks)
    assert chunks[0].startswith("[Page 1]")
