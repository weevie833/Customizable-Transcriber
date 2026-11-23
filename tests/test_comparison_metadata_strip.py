"""reviews/CODEX_REVIEW_8.md M-6: a run scored against its own downloaded DOCX
scores zero whichever entry point supplied each side."""

from __future__ import annotations

from http_utils import extract_docx_text
from run_support import write_docx
from test_mode.comparison import score_transcription, strip_app_metadata

MD = """# Transcription Output

Source folder: /Users/someone/Register

--- START OF RECORD: a_001.jpg ---

Date: 1 Jan 1800 [1 January 1800]

Latin Transcription: Ego baptizavi infantem Petrum.

English Translation: I baptized Peter.

--- START OF RECORD: a_002.jpg ---

Latin Transcription: Ego baptizavi infantem Paulum.
"""


def test_docx_and_markdown_of_same_run_score_zero(tmp_path):
    docx = tmp_path / "run.docx"
    write_docx(docx, MD, native_language="Latin", translation_languages=["English"],
               record_type="battesimi", model="gemini-3.1-pro-preview", profile_label="Profile")
    docx_text = extract_docx_text(docx.read_bytes())
    assert score_transcription(docx_text, MD)["cer"] == 0
    assert score_transcription(MD, docx_text)["cer"] == 0
    assert score_transcription(docx_text, docx_text)["cer"] == 0


def test_register_text_after_first_record_is_never_stripped():
    text = "--- START OF RECORD: a_001.jpg ---\n\nRecord type: written by the scribe\n"
    assert "Record type: written by the scribe" in strip_app_metadata(text)
