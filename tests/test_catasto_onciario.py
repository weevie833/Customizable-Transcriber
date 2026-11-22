"""Prompt Builder's Catasto Onciario record type: its prompt asks for the
register's own line structure (one person per line, each item on its own
line), which the Catasto Visualizer reads households from. The marker in
the role context switches the core rules and keeps the lines when the
transcript is written (render_entry())."""

import handlers.profiles as profiles_handler
from customizable_transcriber.core import LINE_STRUCTURE_MARKER, keeps_line_structure, render_entry
from pages.prompt_builder import prompt_builder_page
from prompt_builder_content import (
    COLLAPSE_LINE_BREAKS_CORE_RULE,
    ENTRY_NUMBER_CORE_RULE,
    LINE_STRUCTURE_CORE_RULE,
    PROMPT_BUILDER_CORE_RULES,
    PROMPT_BUILDER_RECORD_TYPES,
    core_rules_for,
)
from run_support import neutral_system_scaffold

CATASTO_ROLE = "# FIDELITY RULES\n\n- " + LINE_STRUCTURE_MARKER + " exactly as the OUTPUT FORMAT describes."

PAGE = """Italian Transcription:

Antonio Guagliardo Bracciale d'anni — 60
Isabella Principe Moglie d'anni — 45
Nicolò figlio bracciale d'anni — 19


Abita in campagna in casa propria nel luogo di San Nicola

Sono in tutto oncie — 40: 25

English Translation:

Antonio Guagliardo, day laborer, age 60
"""


def test_catasto_record_type_is_registered():
    assert PROMPT_BUILDER_RECORD_TYPES["catasto_onciario"]["label"] == "Catasto Onciario"


def test_core_rules_keep_line_structure_for_catasto():
    rules = core_rules_for(CATASTO_ROLE)
    assert COLLAPSE_LINE_BREAKS_CORE_RULE not in rules
    assert ENTRY_NUMBER_CORE_RULE not in rules
    assert LINE_STRUCTURE_CORE_RULE in rules
    assert core_rules_for("Role.") == PROMPT_BUILDER_CORE_RULES


def test_scaffold_uses_the_same_rules():
    prompt = neutral_system_scaffold("generic", CATASTO_ROLE, "Format.")
    assert "- " + LINE_STRUCTURE_CORE_RULE + "\n" in prompt
    assert COLLAPSE_LINE_BREAKS_CORE_RULE not in prompt
    assert keeps_line_structure(prompt)
    assert not keeps_line_structure(neutral_system_scaffold("generic", "Role.", "Format."))


def test_render_keeps_each_person_on_their_own_line():
    out = render_entry("1743 Rende Catasto_004.png", PAGE, keep_line_structure=True)
    assert out.startswith("\n\n--- START OF RECORD: 1743 Rende Catasto_004.png ---\n\n")
    assert "Antonio Guagliardo Bracciale d'anni — 60\nIsabella Principe Moglie d'anni — 45\n" in out
    # Runs of blank lines shrink to one; lines are otherwise untouched.
    assert "d'anni — 19\n\nAbita" in out
    assert "\n\n\n" not in out.strip()


def test_default_render_still_joins_lines():
    out = render_entry("a.png", PAGE)
    assert "Antonio Guagliardo Bracciale d'anni — 60 Isabella Principe" in out


def test_prompt_builder_page_offers_catasto():
    page = prompt_builder_page()
    assert 'value="catasto_onciario"' in page
    assert 'data-record-type="catasto_onciario"' in page
    assert "lineStructure" in page


def test_preflight_critique_compares_the_whole_page(monkeypatch):
    seen = {}

    def fake_call(key, model, system_prompt, user_message):
        seen["system"] = system_prompt
        return [
            {"category": "role_vocab", "value": "x", "note": "n"},
            {"category": "lexicon_surname", "value": "Guagliardo", "note": "n"},
        ]

    monkeypatch.setattr(profiles_handler, "call_ai_json", fake_call)
    suggestions = profiles_handler.critique_prompt_gap(
        model="gemini-3.1-pro-preview",
        full_prompt="prompt",
        example_entry="page",
        raw_output="output",
        record_type="catasto_onciario",
        api_key_override="key",
    )
    assert "whole uploaded page" in seen["system"]
    assert "single entry in the AI's output" not in seen["system"]
    assert [s["category"] for s in suggestions] == ["lexicon_surname"]


def test_watermark_option_is_on_by_default():
    page = prompt_builder_page()
    assert '<input type="checkbox" name="ignoreWatermark" checked>' in page


def test_catasto_abbreviation_presets_are_offered_checked():
    page = prompt_builder_page()
    assert 'id="pb-catasto-abbrev-checklist"' in page
    assert 'name="catastoAbbrev" value="Cap.le|Capitale|principal sum" checked' in page


def test_new_presets_and_name_abbreviation_section():
    page = prompt_builder_page()
    assert 'name="catastoAbbrev" value="q.m|quondam|the late, deceased (Latin)" checked' in page
    assert 'id="pb-name-abbrev-section" hidden' in page
    assert 'id="pb-add-name-abbrev"' in page
