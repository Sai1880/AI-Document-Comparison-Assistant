"""AI Document Comparison Assistant - Streamlit interface.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

from comparison import (
    DISCLAIMER,
    NOT_FOUND,
    ComparisonError,
    ConfigurationError,
    compare_documents,
)
from document_reader import DocumentError, ExtractedDocument, extract_document
from report_generator import STATUS_LABELS, TYPE_LABELS, build_docx_report

load_dotenv()

st.set_page_config(page_title="AI Document Comparison Assistant", page_icon="📄", layout="wide")


# --- Session state -------------------------------------------------------------
def init_state() -> None:
    defaults = {
        "uploader_key": 0,   # changing this key resets both file uploaders
        "docs": None,        # (ExtractedDocument, ExtractedDocument)
        "result": None,      # validated comparison dict
        "error": None,       # (message, retryable)
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def reset_all() -> None:
    """Callback for the Reset button (FR-12)."""
    st.session_state.docs = None
    st.session_state.result = None
    st.session_state.error = None
    st.session_state.uploader_key += 1


# --- Actions ---------------------------------------------------------------------
def extract_both(file_a, file_b) -> tuple[ExtractedDocument, ExtractedDocument] | None:
    """Validate and extract both PDFs. Shows every problem found, returns None on failure."""
    docs: list[ExtractedDocument] = []
    failed = False
    for label, uploaded in (("Document A", file_a), ("Document B", file_b)):
        try:
            docs.append(extract_document(uploaded.getvalue(), uploaded.name))
        except DocumentError as exc:
            st.error(f"**{label}:** {exc}")
            failed = True
    return None if failed else (docs[0], docs[1])


def run_comparison() -> None:
    """Run the LLM comparison on the documents stored in session state."""
    doc_a, doc_b = st.session_state.docs
    st.session_state.result = None
    st.session_state.error = None
    progress_slot = st.empty()
    try:
        with st.spinner("Comparing documents - this can take up to a minute…"):
            st.session_state.result = compare_documents(
                doc_a, doc_b, progress=lambda msg: progress_slot.caption(msg)
            )
    except ConfigurationError as exc:
        st.session_state.error = (str(exc), False)
    except ComparisonError as exc:
        st.session_state.error = (str(exc), exc.retryable)
    except Exception as exc:  # last-resort guard: never show a stack trace
        st.session_state.error = (f"Unexpected error: {type(exc).__name__}. Please try again.", True)
    finally:
        progress_slot.empty()


# --- Rendering -------------------------------------------------------------------
def render_previews(doc_a: ExtractedDocument, doc_b: ExtractedDocument) -> None:
    """FR-04: confirm the files were read."""
    st.subheader("Extracted content check")
    for col, label, doc in zip(st.columns(2), ("Document A", "Document B"), (doc_a, doc_b)):
        with col:
            st.markdown(f"**{label}:** {doc.name}")
            m1, m2, m3 = st.columns(3)
            m1.metric("Pages", doc.page_count)
            m2.metric("Characters", f"{doc.char_count:,}")
            m3.metric("Words", f"{doc.word_count:,}")
            if doc.unreadable_pages:
                st.warning("No readable text on page(s): " + ", ".join(map(str, doc.unreadable_pages)))
            with st.expander("Text preview"):
                st.write(doc.preview())


def evidence_line(text: str, page: str, verified: bool | None, label: str) -> None:
    if not text:
        return
    suffix = f" (p. {page})" if page else ""
    flag = "  ⚠️ *unverified - not found verbatim in the PDF*" if verified is False else ""
    st.markdown(f"> **{label}:** “{text}”{suffix}{flag}")


def render_result(result: dict) -> None:
    meta = result["meta"]
    st.success("Comparison complete.")
    tabs = st.tabs(
        ["Summary A", "Summary B", "Similarities", "Differences", "Key Details", "Overall Conclusion", "Limitations"]
    )

    with tabs[0]:
        st.markdown(f"**File:** {meta['file_name_a']}")
        st.write(result["summary_a"])
    with tabs[1]:
        st.markdown(f"**File:** {meta['file_name_b']}")
        st.write(result["summary_b"])

    with tabs[2]:
        if not result["similarities"]:
            st.info("No similarities were identified from the provided text.")
        for i, s in enumerate(result["similarities"], start=1):
            st.markdown(f"**{i}. {s['point']}**")
            evidence_line(s["evidence_a"], s["page_a"], s.get("evidence_a_verified"), "Document A")
            evidence_line(s["evidence_b"], s["page_b"], s.get("evidence_b_verified"), "Document B")

    with tabs[3]:
        if not result["differences"]:
            st.info("No differences were identified from the provided text.")
        for i, d in enumerate(result["differences"], start=1):
            st.markdown(f"**{i}. {d['topic']}**  ·  `{TYPE_LABELS.get(d['type'], d['type'])}`")
            c1, c2 = st.columns(2)
            c1.markdown(f"**Document A:** {d['document_a']}")
            c2.markdown(f"**Document B:** {d['document_b']}")
            evidence_line(d["evidence_a"], d["page_a"], d.get("evidence_a_verified"), "A")
            evidence_line(d["evidence_b"], d["page_b"], d.get("evidence_b_verified"), "B")
            st.divider()

    with tabs[4]:
        if not result["key_details"]:
            st.info(f"{NOT_FOUND} (no comparable key details were identified).")
        else:
            st.table(
                [
                    {
                        "Detail": k["field"],
                        "Document A": k["document_a"],
                        "Document B": k["document_b"],
                        "Status": STATUS_LABELS.get(k["status"], k["status"]),
                    }
                    for k in result["key_details"]
                ]
            )

    with tabs[5]:
        st.write(result["conclusion"])
    with tabs[6]:
        for item in result["limitations"]:
            st.markdown(f"- {item}")

    try:
        st.download_button(
            "Download Comparison Report",
            data=build_docx_report(result),
            file_name="document_comparison_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
        )
    except Exception as exc:
        st.error(f"The report could not be generated ({type(exc).__name__}). The results above are still valid.")


# --- Page ------------------------------------------------------------------------
def main() -> None:
    init_state()

    st.title("AI Document Comparison Assistant")
    st.write(
        "Upload two **text-based PDF** documents - for example an old and a new course "
        "syllabus, two versions of a policy, two project requirement documents, product "
        "descriptions or instruction manuals - and get summaries, similarities, differences "
        "and a comparison of key details such as dates, amounts and requirements."
    )
    st.caption(DISCLAIMER)

    key = st.session_state.uploader_key
    col_a, col_b = st.columns(2)
    with col_a:
        file_a = st.file_uploader("Document A", type=["pdf"], key=f"doc_a_{key}")
        if file_a:
            st.caption(f"Selected: {file_a.name}")
    with col_b:
        file_b = st.file_uploader("Document B", type=["pdf"], key=f"doc_b_{key}")
        if file_b:
            st.caption(f"Selected: {file_b.name}")

    btn1, btn2, _ = st.columns([1, 1, 4])
    compare_clicked = btn1.button("Compare Documents", type="primary")
    btn2.button("Reset", on_click=reset_all, help="Clear everything and start a new comparison")

    if compare_clicked:
        st.session_state.result = None
        st.session_state.error = None
        if not file_a or not file_b:
            st.session_state.docs = None
            st.error("Please upload **both** Document A and Document B before comparing.")
        else:
            docs = extract_both(file_a, file_b)
            st.session_state.docs = docs
            if docs:
                run_comparison()

    if st.session_state.docs:
        render_previews(*st.session_state.docs)

    if st.session_state.error:
        message, retryable = st.session_state.error
        st.error(message)
        if retryable and st.session_state.docs:
            if st.button("Retry comparison"):
                run_comparison()
                st.rerun()

    if st.session_state.result:
        render_result(st.session_state.result)


main()
