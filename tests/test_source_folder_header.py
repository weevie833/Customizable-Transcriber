"""reviews/CODEX_REVIEW_8.md L-3 / HD-2 (maintainer chose folder name only):
the transcript header names the source folder without its full path. The
full path goes to the Progress Console instead. The off-peak path is
covered in tests/test_offpeak_batch.py."""

from customizable_transcriber import core


def test_real_time_transcript_header_has_folder_name_not_path(tmp_path, monkeypatch):
    image_folder = tmp_path / "private-account" / "Lappano Test Images"
    image_folder.mkdir(parents=True)
    (image_folder / "image_001.jpg").write_bytes(b"\xff\xd8\xff\xe0placeholder")
    monkeypatch.setattr(core, "make_client", lambda *args, **kwargs: core.LLMClient(provider="gemini"))
    monkeypatch.setattr(core, "transcribe_image_with_retry", lambda *args, **kwargs: "Entry text")
    logged: list[str] = []
    config = core.TranscriptionConfig(
        image_folder=image_folder,
        output_file=tmp_path / "out.md",
        prompt_file=tmp_path / "unused-prompt-file.txt",
        model="gemini-3.1-pro-preview",
        delay_seconds=0,
        system_prompt="sys",
    )
    core.run_batch(config, tmp_path, progress=logged.append)

    text = (tmp_path / "out.md").read_text(encoding="utf-8")
    assert "Source folder: Lappano Test Images\n" in text
    assert "private-account" not in text
    assert any(str(image_folder) in line for line in logged)

