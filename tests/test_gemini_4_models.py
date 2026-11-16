"""Gemini 4 (Carbon, Argon) request handling: no explicit prompt cache and no
sampling parameters, per Google's "What's new in Gemini 4" guides."""

from types import SimpleNamespace

import pytest

from customizable_transcriber import core

GEMINI_4 = ["gemini-4-carbon", "gemini-4-argon"]


@pytest.mark.parametrize("model", GEMINI_4)
def test_gemini_4_models_are_offered_as_gemini(model):
    assert model in core.MODELS
    assert core.provider_for_model(model) == "gemini"
    assert core._gemini_thinking_is_cappable(model)


@pytest.mark.parametrize("model", GEMINI_4)
def test_no_explicit_cache_is_created_for_gemini_4(model):
    calls = []
    client = SimpleNamespace(caches=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs)))
    messages = []
    assert core.create_gemini_prompt_cache(client, model, "system prompt", progress=messages.append) is None
    assert calls == []
    assert messages == []


@pytest.mark.parametrize("model", GEMINI_4)
def test_gemini_4_requests_carry_no_temperature(model, tmp_path):
    seen = {}

    def generate_content(model, contents, config):
        seen["config"] = config
        return SimpleNamespace(text="Entry text", candidates=[], usage_metadata=None)

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    core._transcribe_image_gemini(client, b"\xff\xd8\xff", "image/jpeg", "system prompt", model, False)
    assert seen["config"].temperature is None
    assert seen["config"].system_instruction == "system prompt"


def test_older_gemini_models_keep_temperature_zero_and_explicit_cache():
    assert core.gemini_sampling_kwargs("gemini-3.1-pro-preview") == {"temperature": 0}
    assert core.gemini_supports_explicit_cache("gemini-3.1-pro-preview")
