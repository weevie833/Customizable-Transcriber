"""Regression test for part of reviews/CODEX_REVIEW.md finding M-1: the batch
Transcribe/Test Mode source-file path trusted a file's extension alone
(source_files() filters by suffix) and never checked its actual content
before sending it to an AI provider -- unlike the single-upload paths
(Prompt Builder Preflight, XLS Conversion), which already sniff real
magic bytes via sniff_file_type(). transcribe_image() now does the same
content check for the batch path: a file whose real bytes don't match a
supported JPEG/PNG signature is rejected with a clear error (which
run_batch()'s existing per-image try/except turns into one failed image,
not a fatal batch abort) instead of being forwarded to the provider
mislabeled by whatever its extension happened to claim.

Note: this closes only the content-sniffing part of M-1. The file-size
ceiling and symlink/path-containment checks the same finding also
recommends are not addressed here -- see reviews/CLAUDE_RESPONSE.md for why those
remain a human decision (an appropriate size limit depends on how large a
real archival scan legitimately gets for this app's users)."""

from __future__ import annotations

import types

import pytest

from customizable_transcriber import core


class _FakeGeminiClient:
    def __init__(self):
        self.captured_mime_type = None

    @property
    def models(self):
        outer = self

        class _Models:
            def generate_content(self, model, contents, config):
                outer.captured_mime_type = contents[0].inline_data.mime_type
                return types.SimpleNamespace(text="fake transcription", candidates=[])

        return _Models()


def test_mislabeled_file_is_rejected_before_reaching_the_provider(tmp_path):
    # A plain text file wearing a .jpg extension -- exactly the mislabeled/
    # renamed-file scenario the extension-only batch filter can't catch.
    fake_image = tmp_path / "not_really_a_jpeg.jpg"
    fake_image.write_bytes(b"this is not an image at all")

    client = core.LLMClient(provider="gemini", gemini=_FakeGeminiClient())
    with pytest.raises(RuntimeError, match="does not look like a JPEG or PNG"):
        core.transcribe_image(client, fake_image, "system prompt", "gemini-2.5-pro")

    # The provider must never have been called with the mislabeled content.
    assert client.gemini.captured_mime_type is None


def test_real_jpeg_content_is_sent_with_the_correct_mime_type_regardless_of_extension(tmp_path):
    # Real JPEG magic bytes, but a .png extension -- confirms the content
    # sniff (not the extension) decides the MIME type sent to the provider,
    # matching sniff_file_type()'s existing single-upload behavior.
    real_jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 16
    mislabeled = tmp_path / "actually_a_jpeg.png"
    mislabeled.write_bytes(real_jpeg_bytes)

    client = core.LLMClient(provider="gemini", gemini=_FakeGeminiClient())
    text = core.transcribe_image(client, mislabeled, "system prompt", "gemini-2.5-pro")

    assert text == "fake transcription"
    assert client.gemini.captured_mime_type == "image/jpeg"
