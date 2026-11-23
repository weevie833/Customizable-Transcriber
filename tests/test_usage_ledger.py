"""The usage ledger (customizable_transcriber/usage_ledger.py) is measurement only:
these tests pin what it records AND that it can never change or break a run.

Providers are faked at the SDK-client level, same as test_prompt_caching.py.

The "exactly one billed call per image" and "prompt goes through the cache" checks
double as the structural regression guard for token cost: a code change that quietly
adds a call per image, or stops using the cache, fails here without a real API call."""

from __future__ import annotations

import json
import types as pytypes
from pathlib import Path

import pytest
from google.genai import types

from customizable_transcriber import core, usage_ledger
from xls_conversion import ai_parser


@pytest.fixture(autouse=True)
def _reset_ledger():
    usage_ledger.configure(None)
    yield
    usage_ledger.configure(None)


def _read(ledger_dir: Path) -> list[dict]:
    files = sorted(ledger_dir.glob("*.jsonl"))
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text().splitlines()]


def _gemini_usage(prompt=1000, cached=0, output=200, thoughts=50):
    return pytypes.SimpleNamespace(
        prompt_token_count=prompt,
        cached_content_token_count=cached,
        candidates_token_count=output,
        thoughts_token_count=thoughts,
    )


class _FakeGeminiModels:
    def __init__(self, finish_reasons=None):
        self.calls = 0
        self._finish_reasons = list(finish_reasons or [])

    def generate_content(self, model, contents, config):
        self.calls += 1
        finish = self._finish_reasons.pop(0) if self._finish_reasons else None
        return pytypes.SimpleNamespace(
            text="transcribed",
            candidates=[pytypes.SimpleNamespace(finish_reason=finish)] if finish else [],
            usage_metadata=_gemini_usage(cached=800 if config.cached_content else 0),
        )


class _FakeGeminiCaches:
    def create(self, model, config):
        return pytypes.SimpleNamespace(
            name="cachedContents/fake", usage_metadata=pytypes.SimpleNamespace(total_token_count=800)
        )

    def delete(self, name):
        pass


class _FakeGeminiClient:
    def __init__(self, finish_reasons=None):
        self.models = _FakeGeminiModels(finish_reasons)
        self.caches = _FakeGeminiCaches()


def _config(tmp_path: Path, model: str, images: int) -> core.TranscriptionConfig:
    folder = tmp_path / "images"
    folder.mkdir()
    for number in range(images):
        (folder / f"{number}.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
    return core.TranscriptionConfig(
        image_folder=folder,
        output_file=tmp_path / "output.md",
        prompt_file=tmp_path / "unused.txt",
        model=model,
        delay_seconds=0,
        system_prompt="a long shared system prompt",
        api_key_override="fake-key",
        profile_id="test-profile",
        profile_label="Test Profile",
    )


def test_normalize_gemini_usage_splits_cached_from_uncached_and_keeps_thinking_separate():
    assert usage_ledger.normalize_gemini_usage(_gemini_usage(prompt=1000, cached=800, output=200, thoughts=50)) == {
        "input_uncached": 200,
        "input_cached": 800,
        "input_cache_write": 0,
        "output": 200,
        "thinking": 50,
    }


def test_normalize_claude_usage_treats_cache_fields_as_separate_from_input_tokens():
    usage = pytypes.SimpleNamespace(
        input_tokens=120, cache_read_input_tokens=3000, cache_creation_input_tokens=10, output_tokens=400
    )
    assert usage_ledger.normalize_claude_usage(usage) == {
        "input_uncached": 120,
        "input_cached": 3000,
        "input_cache_write": 10,
        "output": 400,
        "thinking": 0,
    }


def test_missing_usage_is_recorded_as_not_reported_not_as_zero(tmp_path):
    usage_ledger.configure(tmp_path / "usage")
    ledger_run = usage_ledger.start_run(mode="regular", stage="transcribe", provider="gemini", model="m")
    usage_ledger.record_call(provider="gemini", model="m", usage=None, run=ledger_run, image="a.jpg")
    usage_ledger.end_run(ledger_run)
    call = next(r for r in _read(tmp_path / "usage") if r["type"] == "call")
    assert call["usage_reported"] is False
    assert call["input_uncached"] is None


def test_unconfigured_ledger_writes_nothing_and_run_batch_is_unaffected(tmp_path, monkeypatch):
    config = _config(tmp_path, "gemini-3.1-pro-preview", images=2)
    fake = _FakeGeminiClient()
    monkeypatch.setattr(core, "make_client", lambda *a, **k: core.LLMClient(provider="gemini", gemini=fake))

    results = core.run_batch(config, tmp_path)

    assert all(result.ok for result in results)
    assert not (tmp_path / "usage").exists()


def test_run_batch_ledger_has_exactly_one_call_per_image_and_uses_the_cache(tmp_path, monkeypatch):
    usage_ledger.configure(tmp_path / "usage")
    config = _config(tmp_path, "gemini-3.1-pro-preview", images=3)
    fake = _FakeGeminiClient()
    monkeypatch.setattr(core, "make_client", lambda *a, **k: core.LLMClient(provider="gemini", gemini=fake))

    core.run_batch(config, tmp_path)

    records = _read(tmp_path / "usage")
    start = records[0]
    assert start["type"] == "run_start"
    assert (start["mode"], start["stage"], start["image_count"]) == ("regular", "transcribe", 3)
    assert (start["profile_id"], start["profile_label"]) == ("test-profile", "Test Profile")
    assert start["prompt_chars"] == len("a long shared system prompt") and len(start["prompt_sha"]) == 12
    assert "a long shared system prompt" not in json.dumps(records)

    calls = [r for r in records if r["type"] == "call"]
    assert [c["image"] for c in calls] == ["0.jpg", "1.jpg", "2.jpg"]
    assert all(c["attempt"] == "initial" and c["cache_expected"] is True for c in calls)
    assert all(c["input_cached"] == 800 and c["input_uncached"] == 200 for c in calls)

    kinds = [r["kind"] for r in records if r["type"] == "event"]
    assert kinds.count("cache_created") == 1
    assert kinds.count("image_done") == 3

    end = records[-1]
    assert end["type"] == "run_end" and end["calls"] == 3
    assert end["tokens"]["input_cached"] == 2400 and end["tokens"]["thinking"] == 150
    assert (end["images_processed"], end["failures"], end["stopped"]) == (3, 0, False)


def test_truncation_retry_is_recorded_as_a_second_labelled_call(tmp_path, monkeypatch):
    usage_ledger.configure(tmp_path / "usage")
    config = _config(tmp_path, "gemini-3.1-pro-preview", images=1)
    fake = _FakeGeminiClient(finish_reasons=[types.FinishReason.MAX_TOKENS, types.FinishReason.STOP])
    monkeypatch.setattr(core, "make_client", lambda *a, **k: core.LLMClient(provider="gemini", gemini=fake))

    core.run_batch(config, tmp_path)

    records = _read(tmp_path / "usage")
    calls = [r for r in records if r["type"] == "call"]
    assert [c["attempt"] for c in calls] == ["initial", "truncation_retry"]
    assert calls[0]["finish_reason"] == "MAX_TOKENS"
    events = {r["kind"]: r for r in records if r["type"] == "event"}
    assert events["truncated_output"]["provider"] == "gemini"
    assert events["truncation_retry_result"]["resolved"] is True


def test_claude_run_records_cache_read_and_write_tokens(tmp_path, monkeypatch):
    usage_ledger.configure(tmp_path / "usage")
    config = _config(tmp_path, "claude-sonnet-5", images=1)

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return pytypes.SimpleNamespace(
                content=[pytypes.SimpleNamespace(type="text", text="transcribed")],
                stop_reason="end_turn",
                usage=pytypes.SimpleNamespace(
                    input_tokens=50, cache_read_input_tokens=0, cache_creation_input_tokens=3000, output_tokens=900
                ),
            )

    fake = pytypes.SimpleNamespace(messages=pytypes.SimpleNamespace(stream=lambda **kw: _Stream()))
    monkeypatch.setattr(core, "make_client", lambda *a, **k: core.LLMClient(provider="claude", claude=fake))

    core.run_batch(config, tmp_path)

    call = next(r for r in _read(tmp_path / "usage") if r["type"] == "call")
    assert (call["input_uncached"], call["input_cache_write"], call["output"]) == (50, 3000, 900)
    assert call["finish_reason"] == "end_turn"


def test_ledger_failure_never_breaks_a_run(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    usage_ledger.configure(blocker / "usage")  # cannot be created: parent is a file
    config = _config(tmp_path, "gemini-3.1-pro-preview", images=2)
    fake = _FakeGeminiClient()
    monkeypatch.setattr(core, "make_client", lambda *a, **k: core.LLMClient(provider="gemini", gemini=fake))

    results = core.run_batch(config, tmp_path)

    assert len(results) == 2 and all(result.ok for result in results)


def test_xls_claude_call_is_recorded_under_its_stage(tmp_path, monkeypatch):
    usage_ledger.configure(tmp_path / "usage")

    class _Messages:
        def create(self, **kwargs):
            return pytypes.SimpleNamespace(
                content=[pytypes.SimpleNamespace(type="text", text="[]")],
                usage=pytypes.SimpleNamespace(
                    input_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0, output_tokens=5
                ),
                stop_reason="end_turn",
            )

    monkeypatch.setattr(
        ai_parser.anthropic, "Anthropic", lambda **kw: pytypes.SimpleNamespace(messages=_Messages())
    )

    with usage_ledger.run(mode="regular", stage="xls_parse", provider="claude", model="claude-sonnet-5"):
        ai_parser.call_claude_json("sk-ant-key", "claude-sonnet-5", "system", "user")

    records = _read(tmp_path / "usage")
    assert records[0]["stage"] == "xls_parse"
    call = next(r for r in records if r["type"] == "call")
    assert (call["input_uncached"], call["output"]) == (10, 5)


def test_gemini_batch_collection_fills_usage_sink_without_changing_results():
    from batch_transcription import collect_gemini_batch_results

    item = pytypes.SimpleNamespace(
        metadata={"index": "0"},
        error=None,
        response=pytypes.SimpleNamespace(
            text="hello",
            candidates=[pytypes.SimpleNamespace(finish_reason="STOP")],
            usage_metadata=_gemini_usage(),
        ),
    )
    job = pytypes.SimpleNamespace(dest=pytypes.SimpleNamespace(inlined_responses=[item]))
    sink: list = []

    results = collect_gemini_batch_results(job, usage_sink=sink)

    assert results == {0: ("hello", "")}
    assert sink[0]["index"] == 0 and sink[0]["finish_reason"] == "STOP" and sink[0]["text_chars"] == 5
    assert collect_gemini_batch_results(job) == results  # sink is optional


def test_off_peak_usage_is_recorded_with_mode_off_peak(tmp_path):
    from batch_transcription import _record_batch_usage

    usage_ledger.configure(tmp_path / "usage")
    _record_batch_usage(
        provider="gemini",
        model="gemini-3.1-pro-preview",
        system_prompt="prompt",
        names=["a.jpg", "b.jpg"],
        results={0: ("x", ""), 1: ("", "boom")},
        usage_sink=[{"index": 0, "usage": _gemini_usage(), "finish_reason": None, "text_chars": 1}],
        profile={"id": "p", "label": "P"},
        job_id="batches/1",
        submitted_at="2026-09-21T10:00:00",
        counts={"succeeded": 1, "failed": 1},
    )

    records = _read(tmp_path / "usage")
    assert records[0]["mode"] == "off_peak" and records[0]["job_id"] == "batches/1"
    call = next(r for r in records if r["type"] == "call")
    assert call["image"] == "a.jpg" and call["cache_expected"] is False
    failed = next(r for r in records if r["type"] == "event" and r["kind"] == "image_done")
    assert failed["image"] == "b.jpg" and failed["ok"] is False
    assert records[-1]["failures"] == 1
    assert records[-1]["wall_seconds"] > 0  # submission -> collection, not the ledger's own ~0s clock
