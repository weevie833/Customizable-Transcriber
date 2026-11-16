"""General extraction rules about content the transcript doesn't contain
(marginal headings, crossed-out entries, register front matter) are dropped
from that run's system prompt; everything else is kept line for line."""

from __future__ import annotations

from xls_conversion import ai_parser

PROMPT = ai_parser.RECORD_TYPES["matrimoni"].system_prompt
PLAIN = "Page 1 - Entry 1:\n\nDate: x\n\nEnglish Translation: y"


def test_all_three_rules_exist_in_the_unpruned_prompt():
    for prefix, _ in ai_parser.CONDITIONAL_GENERAL_RULES:
        assert any(line.startswith(prefix) for line in PROMPT.split("\n")), prefix


def test_inactive_rules_removed_and_nothing_else():
    pruned = ai_parser.prune_inactive_general_rules(PROMPT, PLAIN)
    removed = set(PROMPT.split("\n")) - set(pruned.split("\n"))
    assert len(removed) == 3
    assert all(any(line.startswith(p) for p, _ in ai_parser.CONDITIONAL_GENERAL_RULES) for line in removed)
    assert len(pruned.split("\n")) == len(PROMPT.split("\n")) - 3


def test_rules_kept_when_transcript_has_the_content():
    text = PLAIN + "\n\nMarginal Heading: a\n\nFront Matter:\nx\n\n[ENTRY CROSSED OUT BY SCRIBE]"
    assert ai_parser.prune_inactive_general_rules(PROMPT, text) == PROMPT


def test_parse_generic_prunes_for_non_battesimi_only(monkeypatch):
    seen = {}

    def fake_call_ai(api_key, model, system_prompt, *_a, **_k):
        seen.setdefault("prompts", []).append(system_prompt)
        return []

    monkeypatch.setattr(ai_parser, "call_ai", fake_call_ai)
    monkeypatch.setattr(ai_parser, "create_gemini_prompt_cache", lambda *a, **k: None)
    for key in ("matrimoni", "battesimi"):
        ai_parser.parse_generic(
            config=ai_parser.RECORD_TYPES[key], text="--- START OF RECORD: img_001.jpg ---\n\n" + PLAIN,
            image_range="", image_overrides="", api_key="k", model="gemini-3.1-pro-preview",
            target_language="English", target_role="", process_all=True,
        )
    matrimoni_prompt, battesimi_prompt = seen["prompts"]
    assert "CROSSED-OUT ENTRIES:" not in matrimoni_prompt
    assert battesimi_prompt == ai_parser.RECORD_TYPES["battesimi"].system_prompt.replace(
        ai_parser.TARGET_RULE_TOKEN, ai_parser.target_rule_sentence("English", "")
    ).replace(ai_parser.TARGET_SOURCE_TOKEN, ai_parser.target_source_description("English", "")).replace(
        ai_parser.TARGET_LANGUAGE_TOKEN, "English")
