"""Regression test for reviews/CODEX_REVIEW.md finding M-6: Test Mode's DOCX output
used to omit record_type/model/profile_label metadata that the normal
Transcribe path always writes into the header box (see write_docx()'s own
call sites in app.py, and header_box_element()'s docstring on the invariant
this preserves). Exercises run_test_job() directly -- the function under
test -- with the AI provider stubbed out, and reads the real DOCX produced
to confirm all three previously-missing fields are present."""

from __future__ import annotations

import zipfile
from xml.etree import ElementTree

import app as ctapp
import run_support

_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _document_text(docx_path) -> str:
    with zipfile.ZipFile(docx_path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    return "".join(t.text or "" for t in root.iter(f"{_NS}t"))


def test_test_mode_docx_includes_model_profile_and_record_type(
    sandboxed_user_data, tmp_path, monkeypatch
):
    profile = ctapp.save_custom_profile(
        "Metadata Test Profile",
        "role",
        "reference",
        "format",
        native_language="Latin",
        translation_languages=["English"],
        record_type="battesimi",
    )

    source_folder = tmp_path / "source"
    source_folder.mkdir()
    (source_folder / "page_001.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(run_support, "load_source_folder", lambda: source_folder)
    monkeypatch.setattr(
        run_support, "validate_api_key_with_retry", lambda *args, **kwargs: None
    )

    def fake_run_batch(config, project_dir, progress=None, cancel_requested=None):
        config.output_file.parent.mkdir(parents=True, exist_ok=True)
        config.output_file.write_text("Some transcription text.", encoding="utf-8")
        return []

    monkeypatch.setattr(run_support, "run_batch", fake_run_batch)

    model = "gemini-3.1-pro-preview"
    markdown_file = tmp_path / "run.md"
    output_file = tmp_path / "run.docx"
    run_specs = [("batch-a", "Batch · Model A", model, "fake-api-key", markdown_file, output_file)]

    form = ctapp.FormData(
        {
            "profile_id": [profile["id"]],
            "profile_action": ["use"],
            "order": ["oldest"],
            "file_type": ["jpeg"],
        }
    )

    ctapp.run_test_job(form, run_specs)

    assert output_file.exists()
    text = _document_text(output_file)
    assert f"AI model: {model}" in text
    assert f"Prompt profile: {profile['label']}" in text
    assert "Record type:" in text
