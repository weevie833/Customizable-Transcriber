"""Page zoom (customizable_transcriber/page_zoom.py): gutter detection,
page crops, the Gemini request shape with and without zoom, the off-peak
batch request shape, the free Preflight advice, Test Mode's per-slot
setting, and the profile default saved by Prompt Builder."""

from __future__ import annotations

import io
import types

import pytest
from PIL import Image, ImageDraw

import app as ctapp
import batch_transcription as bt
import run_support
from customizable_transcriber import core, page_zoom
from profiles_store import profile_zoom_pages


def _spread(width=3200, height=2400, gutter=0.48, gutter_width=0.01) -> Image.Image:
    """Two light pages with lines of dark 'text' and a narrow dark gutter."""
    image = Image.new("L", (width, height), 215)
    draw = ImageDraw.Draw(image)
    for y in range(int(height * 0.1), int(height * 0.9), 60):
        draw.rectangle((int(width * 0.05), y, int(width * 0.44), y + 12), fill=120)
        draw.rectangle((int(width * 0.53), y, int(width * 0.95), y + 12), fill=120)
    x = int(width * gutter)
    draw.rectangle((x - int(width * gutter_width / 2), 0, x + int(width * gutter_width / 2), height), fill=60)
    return image


def _jpeg_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def test_gutter_is_found_on_a_two_page_spread():
    info = page_zoom.analyze_spread(_spread(gutter=0.48))
    assert info.gutter_x is not None
    assert abs(info.gutter_x / info.width - 0.48) < 0.01


def test_no_gutter_on_a_blank_or_broadly_stained_photo():
    assert page_zoom.analyze_spread(Image.new("L", (3000, 2000), 200)).gutter_x is None
    stained = Image.new("L", (3000, 2000), 210)
    ImageDraw.Draw(stained).rectangle((1200, 0, 1800, 2000), fill=150)  # broad, not a narrow line
    assert page_zoom.analyze_spread(stained).gutter_x is None


def test_page_crops_overlap_the_gutter():
    image = _spread(width=3200, gutter=0.5)
    left, right = page_zoom.page_crops(_jpeg_bytes(image))
    pad = round(page_zoom.CROP_OVERLAP * 3200)
    left_width = Image.open(io.BytesIO(left)).width
    right_width = Image.open(io.BytesIO(right)).width
    assert abs(left_width - (1600 + pad)) <= 10
    assert abs(right_width - (1600 + pad)) <= 10


def test_page_crops_returns_none_without_a_gutter():
    assert page_zoom.page_crops(_jpeg_bytes(Image.new("L", (3000, 2000), 200))) is None


class _CapturingGemini:
    def __init__(self):
        self.contents = None

    @property
    def models(self):
        outer = self

        class _Models:
            def generate_content(self, model, contents, config):
                outer.contents = contents
                return types.SimpleNamespace(text="fake transcription", candidates=[])

        return _Models()


def _image_parts(contents):
    return [part for part in contents if hasattr(part, "inline_data")]


def test_zoom_sends_full_photo_plus_both_page_crops(tmp_path):
    path = tmp_path / "spread.jpg"
    path.write_bytes(_jpeg_bytes(_spread()))
    client = core.LLMClient(provider="gemini", gemini=_CapturingGemini())

    core.transcribe_image(client, path, "system prompt", "gemini-3.1-pro-preview", zoom_pages=True)

    assert len(_image_parts(client.gemini.contents)) == 3
    assert client.gemini.contents[-1].endswith(page_zoom.PAGE_ZOOM_INSTRUCTION)


def test_without_zoom_only_the_full_photo_is_sent(tmp_path):
    path = tmp_path / "spread.jpg"
    path.write_bytes(_jpeg_bytes(_spread()))
    client = core.LLMClient(provider="gemini", gemini=_CapturingGemini())

    core.transcribe_image(client, path, "system prompt", "gemini-3.1-pro-preview")

    assert len(_image_parts(client.gemini.contents)) == 1
    assert client.gemini.contents[-1] == core.USER_INSTRUCTION


def test_zoom_falls_back_to_the_full_photo_when_no_gutter_is_found(tmp_path):
    path = tmp_path / "single.jpg"
    path.write_bytes(_jpeg_bytes(Image.new("L", (3000, 2000), 200)))
    client = core.LLMClient(provider="gemini", gemini=_CapturingGemini())
    messages = []

    core.transcribe_image(client, path, "system prompt", "gemini-3.1-pro-preview", zoom_pages=True, progress=messages.append)

    assert len(_image_parts(client.gemini.contents)) == 1
    assert any("no clear gutter" in message for message in messages)


class _FakeBatches:
    def __init__(self):
        self.src = None

    def create(self, model, src, config=None):
        self.src = src
        return types.SimpleNamespace(name="batches/fake")


def test_off_peak_gemini_batch_includes_page_crops_when_zoom_is_on(tmp_path):
    path = tmp_path / "spread.jpg"
    path.write_bytes(_jpeg_bytes(_spread()))
    client = types.SimpleNamespace(batches=_FakeBatches())

    bt.submit_gemini_batch(client, "gemini-3.1-pro-preview", "system prompt", [path], zoom_pages=True)
    zoomed = client.batches.src[0].contents
    bt.submit_gemini_batch(client, "gemini-3.1-pro-preview", "system prompt", [path])
    plain = client.batches.src[0].contents

    assert len(_image_parts(zoomed)) == 3
    assert len(_image_parts(plain)) == 1


def _folder_of_spreads(tmp_path, count=3, **kwargs):
    for index in range(count):
        _spread(**kwargs).convert("RGB").save(tmp_path / f"img_{index}.jpg", "JPEG", quality=85)
    return tmp_path


def test_advice_suggests_zoom_for_high_resolution_spreads_on_gemini(tmp_path):
    folder = _folder_of_spreads(tmp_path)
    assert run_support.page_zoom_advice(folder, "jpeg", "gemini-3.1-pro-preview", False) == run_support.PAGE_ZOOM_SUGGEST
    # Already on, and the photos qualify: nothing to add.
    assert run_support.page_zoom_advice(folder, "jpeg", "gemini-3.1-pro-preview", True) == ""


def test_advice_never_suggests_zoom_for_claude_and_warns_if_it_is_on(tmp_path):
    folder = _folder_of_spreads(tmp_path)
    assert run_support.page_zoom_advice(folder, "jpeg", "claude-opus-5-5", False) == ""
    assert run_support.page_zoom_advice(folder, "jpeg", "claude-opus-5-5", True) == run_support.PAGE_ZOOM_CLAUDE


def test_advice_warns_when_zoom_is_on_for_small_or_single_page_photos(tmp_path):
    folder = _folder_of_spreads(tmp_path, width=1600, height=1200)  # below SUGGEST_MIN_LONG_EDGE
    assert run_support.page_zoom_advice(folder, "jpeg", "gemini-3.1-pro-preview", False) == ""
    assert run_support.page_zoom_advice(folder, "jpeg", "gemini-3.1-pro-preview", True) == run_support.PAGE_ZOOM_NOT_SPREADS


def test_advice_respects_a_one_page_profile(tmp_path):
    folder = _folder_of_spreads(tmp_path)
    assert run_support.page_zoom_advice(folder, "jpeg", "gemini-3.1-pro-preview", False, "one_page") == ""


def test_pdf_is_not_a_source_file_type():
    assert "pdf" not in core.FILE_TYPE_EXTENSIONS
    assert core.sniff_file_type(b"%PDF-1.7 rest") is None
    with pytest.raises(RuntimeError):
        run_support.selected_file_type(_form(file_type="pdf"))


# --- Test Mode: per-slot Page zoom ------------------------------------------

def _form(**values):
    return ctapp.FormData({key: [value] for key, value in values.items()})


def test_same_model_is_allowed_only_when_page_zoom_differs():
    model = "gemini-3.1-pro-preview"
    assert run_support.selected_model_pair(_form(model_a=model, model_b=model, zoom_b="on")) == (model, model)
    with pytest.raises(RuntimeError, match="unless Page zoom is on for only one"):
        run_support.selected_model_pair(_form(model_a=model, model_b=model))
    with pytest.raises(RuntimeError):
        run_support.selected_model_pair(_form(model_a=model, model_b=model, zoom_a="on", zoom_b="on"))


def test_implicit_batch_carries_the_zoom_checkboxes():
    with ctapp.test_lock:
        ctapp.test_state["queue"] = []
    model = "gemini-3.1-pro-preview"
    (batch,) = run_support.resolve_run_batches(_form(model_a=model, model_b=model, zoom_b="on"))
    assert (batch["zoom_a"], batch["zoom_b"]) == (False, True)


def test_run_test_job_passes_each_runs_zoom_setting_to_the_batch(sandboxed_user_data, tmp_path, monkeypatch):
    profile = ctapp.save_custom_profile("Zoom Test Profile", "role", "reference", "format")
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    (source_folder / "page_001.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setattr(run_support, "load_source_folder", lambda: source_folder)
    monkeypatch.setattr(run_support, "validate_api_key_with_retry", lambda *args, **kwargs: None)
    seen = {}

    def fake_run_batch(config, project_dir, progress=None, cancel_requested=None):
        seen[config.output_file.name] = config.zoom_pages
        return []

    monkeypatch.setattr(run_support, "run_batch", fake_run_batch)
    with ctapp.test_lock:
        ctapp.test_state["running"] = True
        ctapp.test_state["runs"] = {"run-a": ctapp.new_test_run_state(), "run-b": ctapp.new_test_run_state()}
        ctapp.test_state["runs"]["run-b"]["zoom_pages"] = True
    model = "gemini-3.1-pro-preview"
    run_specs = [
        ("run-a", "Batch · Model A", model, "key", tmp_path / "a.md", tmp_path / "a.docx"),
        ("run-b", "Batch · Model B (Page zoom)", model, "key", tmp_path / "b.md", tmp_path / "b.docx"),
    ]
    try:
        ctapp.run_test_job(
            _form(profile_id=profile["id"], profile_action="use", order="oldest", file_type="jpeg"), run_specs
        )
    finally:
        with ctapp.test_lock:
            ctapp.test_state["running"] = False
            ctapp.test_state["runs"] = {}
    assert seen == {"a.md": False, "b.md": True}


# --- Profile default ----------------------------------------------------------


def test_profile_zoom_default_comes_from_prompt_builder_answers():
    def profile(layout, checked):
        return {"pb_answers": {"fields": {"pageLayout": layout}, "checked": {"zoomPages": checked}}}

    assert profile_zoom_pages(profile("two_facing", ["on"])) is True
    assert profile_zoom_pages(profile("two_facing", [])) is False
    # The checkbox is hidden for other layouts, so a stale value is ignored.
    assert profile_zoom_pages(profile("one_page", ["on"])) is False
    assert profile_zoom_pages({"pb_answers": None}) is False
    assert profile_zoom_pages({}) is False
