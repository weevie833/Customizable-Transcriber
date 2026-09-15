"""Regression tests for explicit Gemini prompt caching (create_gemini_prompt_cache()/
delete_gemini_prompt_cache()) and Claude's stateless cache_control flag, and for how
run_batch() (core.py) and parse_generic()/preflight_generic() (xls_conversion/ai_parser.py)
wire both into their per-image/per-block loops.

Neither provider is called for real here -- every SDK client is a fake with just enough
surface (models.generate_content / messages.stream / messages.create / caches.create /
caches.delete) to prove what was actually sent and to prove cache creation failures are
swallowed rather than aborting a batch. See "Prompt caching" in CLAUDE.md's task list for
why this exists: the same system prompt was previously resent in full on every single
image/block in a batch that can run into the thousands."""

from __future__ import annotations

import types as pytypes
from pathlib import Path

import pytest
from google.genai import types

import customizable_transcription.core as core
import xls_conversion.ai_parser as ai_parser


# --- core.py: per-call plumbing -------------------------------------------------


class _FakeGeminiModels:
    def __init__(self):
        self.captured_configs: list[types.GenerateContentConfig] = []

    def generate_content(self, model, contents, config):
        self.captured_configs.append(config)
        return pytypes.SimpleNamespace(text="transcribed", candidates=[])


class _FakeGeminiCaches:
    def __init__(self, name="cachedContents/fake123", fail=False):
        self._name = name
        self._fail = fail
        self.created_with: list[types.CreateCachedContentConfig] = []
        self.deleted_names: list[str] = []

    def create(self, model, config):
        if self._fail:
            raise RuntimeError("caching not supported for this model")
        self.created_with.append((model, config))
        return pytypes.SimpleNamespace(name=self._name)

    def delete(self, name):
        self.deleted_names.append(name)


class _FakeGeminiClient:
    def __init__(self, fail_cache_create=False):
        self.models = _FakeGeminiModels()
        self.caches = _FakeGeminiCaches(fail=fail_cache_create)


class _FakeClaudeStream:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._response


class _FakeClaudeMessages:
    def __init__(self):
        self.stream_kwargs: dict[str, object] = {}

    def stream(self, **kwargs):
        self.stream_kwargs = kwargs
        response = pytypes.SimpleNamespace(
            content=[pytypes.SimpleNamespace(type="text", text="transcribed")],
            stop_reason="end_turn",
        )
        return _FakeClaudeStream(response)


class _FakeClaudeClient:
    def __init__(self):
        self.messages = _FakeClaudeMessages()


def _write_jpeg(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
    return path


def test_gemini_transcribe_uses_cached_content_instead_of_system_instruction(tmp_path):
    image = _write_jpeg(tmp_path, "image_001.jpg")
    client = core.LLMClient(provider="gemini", gemini=_FakeGeminiClient())

    core.transcribe_image(
        client, image, "a long system prompt", "gemini-2.5-pro", cached_content="cachedContents/abc"
    )

    config = client.gemini.models.captured_configs[0]
    assert config.cached_content == "cachedContents/abc"
    assert config.system_instruction is None


def test_gemini_transcribe_falls_back_to_system_instruction_with_no_cache(tmp_path):
    image = _write_jpeg(tmp_path, "image_001.jpg")
    client = core.LLMClient(provider="gemini", gemini=_FakeGeminiClient())

    core.transcribe_image(client, image, "a long system prompt", "gemini-2.5-pro")

    config = client.gemini.models.captured_configs[0]
    assert config.cached_content is None
    assert config.system_instruction == "a long system prompt"


def test_claude_transcribe_requests_cache_control_when_enabled(tmp_path):
    image = _write_jpeg(tmp_path, "image_001.jpg")
    client = core.LLMClient(provider="claude", claude=_FakeClaudeClient())

    core.transcribe_image(
        client, image, "a long system prompt", "claude-sonnet-5", use_prompt_cache=True
    )

    assert client.claude.messages.stream_kwargs.get("cache_control") == {"type": "ephemeral"}


def test_claude_transcribe_omits_cache_control_by_default(tmp_path):
    image = _write_jpeg(tmp_path, "image_001.jpg")
    client = core.LLMClient(provider="claude", claude=_FakeClaudeClient())

    core.transcribe_image(client, image, "a long system prompt", "claude-sonnet-5")

    assert "cache_control" not in client.claude.messages.stream_kwargs


# --- core.py: cache lifecycle helpers -------------------------------------------


def test_create_gemini_prompt_cache_returns_name_on_success():
    gemini = _FakeGeminiClient()
    name = core.create_gemini_prompt_cache(gemini, "gemini-2.5-pro", "system prompt text")
    assert name == "cachedContents/fake123"
    (model, config) = gemini.caches.created_with[0]
    assert model == "gemini-2.5-pro"
    assert config.system_instruction == "system prompt text"


def test_create_gemini_prompt_cache_returns_none_on_failure_and_reports_progress():
    gemini = _FakeGeminiClient(fail_cache_create=True)
    messages: list[str] = []
    name = core.create_gemini_prompt_cache(
        gemini, "gemini-3.1-pro-preview", "system prompt text", progress=messages.append
    )
    assert name is None
    assert messages and "caching not supported" in messages[0]


def test_delete_gemini_prompt_cache_swallows_errors():
    class _ExplodingCaches:
        def delete(self, name):
            raise RuntimeError("already expired")

    gemini = pytypes.SimpleNamespace(caches=_ExplodingCaches())
    # Must not raise -- cleanup is best-effort, see the function's own docstring.
    core.delete_gemini_prompt_cache(gemini, "cachedContents/whatever")


# --- core.py: run_batch() wiring ------------------------------------------------


def _batch_config(tmp_path: Path, model: str) -> core.TranscriptionConfig:
    folder = tmp_path / "images"
    folder.mkdir()
    return core.TranscriptionConfig(
        image_folder=folder,
        output_file=tmp_path / "output.md",
        prompt_file=tmp_path / "unused_prompt.txt",
        model=model,
        delay_seconds=0,
        system_prompt="a long shared system prompt",
        api_key_override="fake-key",
    )


def test_run_batch_creates_and_deletes_gemini_cache_for_a_multi_image_run(tmp_path, monkeypatch):
    config = _batch_config(tmp_path, "gemini-2.5-pro")
    _write_jpeg(config.image_folder, "a.jpg")
    _write_jpeg(config.image_folder, "b.jpg")

    fake_gemini = _FakeGeminiClient()
    monkeypatch.setattr(
        core, "make_client", lambda *a, **k: core.LLMClient(provider="gemini", gemini=fake_gemini)
    )

    results = core.run_batch(config, tmp_path)

    assert all(result.ok for result in results)
    assert len(fake_gemini.caches.created_with) == 1
    assert fake_gemini.caches.deleted_names == ["cachedContents/fake123"]
    # Both images used the cache, and neither resent system_instruction.
    for captured in fake_gemini.models.captured_configs:
        assert captured.cached_content == "cachedContents/fake123"
        assert captured.system_instruction is None


def test_run_batch_skips_gemini_cache_for_a_single_image_run(tmp_path, monkeypatch):
    config = _batch_config(tmp_path, "gemini-2.5-pro")
    _write_jpeg(config.image_folder, "a.jpg")

    fake_gemini = _FakeGeminiClient()
    monkeypatch.setattr(
        core, "make_client", lambda *a, **k: core.LLMClient(provider="gemini", gemini=fake_gemini)
    )

    core.run_batch(config, tmp_path)

    assert fake_gemini.caches.created_with == []
    assert fake_gemini.models.captured_configs[0].system_instruction == "a long shared system prompt"


def test_run_batch_requests_claude_prompt_cache_for_a_multi_image_run(tmp_path, monkeypatch):
    config = _batch_config(tmp_path, "claude-sonnet-5")
    _write_jpeg(config.image_folder, "a.jpg")
    _write_jpeg(config.image_folder, "b.jpg")

    fake_claude = _FakeClaudeClient()
    monkeypatch.setattr(
        core, "make_client", lambda *a, **k: core.LLMClient(provider="claude", claude=fake_claude)
    )

    core.run_batch(config, tmp_path)

    assert fake_claude.messages.stream_kwargs.get("cache_control") == {"type": "ephemeral"}


def test_run_batch_continues_when_gemini_cache_creation_fails(tmp_path, monkeypatch):
    """Caching is a cost optimization, never a correctness requirement -- a batch
    must still complete normally (falling back to sending system_instruction on
    every call) when explicit cache creation fails for any reason."""
    config = _batch_config(tmp_path, "gemini-3.1-pro-preview")
    _write_jpeg(config.image_folder, "a.jpg")
    _write_jpeg(config.image_folder, "b.jpg")

    fake_gemini = _FakeGeminiClient(fail_cache_create=True)
    monkeypatch.setattr(
        core, "make_client", lambda *a, **k: core.LLMClient(provider="gemini", gemini=fake_gemini)
    )

    results = core.run_batch(config, tmp_path)

    assert all(result.ok for result in results)
    for captured in fake_gemini.models.captured_configs:
        assert captured.cached_content is None
        assert captured.system_instruction == "a long shared system prompt"
    assert fake_gemini.caches.deleted_names == []  # nothing to clean up


# --- xls_conversion/ai_parser.py: call_gemini_json()/call_claude_json() --------


class _FakeGenaiClientForJson:
    def __init__(self, response_text):
        self._response_text = response_text
        self.captured_configs: list[types.GenerateContentConfig] = []

    @property
    def models(self):
        outer = self

        class _Models:
            def generate_content(self, model, contents, config):
                outer.captured_configs.append(config)
                return pytypes.SimpleNamespace(text=outer._response_text)

        return _Models()


def test_call_gemini_json_uses_cached_content_when_given(monkeypatch):
    fake_client = _FakeGenaiClientForJson("[]")
    monkeypatch.setattr(ai_parser.genai, "Client", lambda **kwargs: fake_client)

    ai_parser.call_gemini_json("key", "gemini-2.5-pro", "system prompt", "user", "cachedContents/xyz")

    config = fake_client.captured_configs[0]
    assert config.cached_content == "cachedContents/xyz"
    assert config.system_instruction is None


def test_call_claude_json_requests_cache_control_when_enabled(monkeypatch):
    captured = {}

    class _FakeAnthropicClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                return pytypes.SimpleNamespace(
                    content=[pytypes.SimpleNamespace(type="text", text="[]")]
                )

    monkeypatch.setattr(ai_parser.anthropic, "Anthropic", lambda **kwargs: _FakeAnthropicClient())

    ai_parser.call_claude_json("key", "claude-sonnet-5", "system prompt", "user", use_prompt_cache=True)

    assert captured.get("cache_control") == {"type": "ephemeral"}


def test_call_claude_json_omits_cache_control_by_default(monkeypatch):
    captured = {}

    class _FakeAnthropicClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                return pytypes.SimpleNamespace(
                    content=[pytypes.SimpleNamespace(type="text", text="[]")]
                )

    monkeypatch.setattr(ai_parser.anthropic, "Anthropic", lambda **kwargs: _FakeAnthropicClient())

    ai_parser.call_claude_json("key", "claude-sonnet-5", "system prompt", "user")

    assert "cache_control" not in captured
