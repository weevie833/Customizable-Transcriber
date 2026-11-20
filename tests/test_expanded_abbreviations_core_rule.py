"""Prompt Builder's "Write abbreviations out in full in the transcription"
option swaps the core "never expand abbreviations" rules for one that agrees
with it (neutral_system_scaffold() in run_support.py)."""

from prompt_builder_content import (
    EXPANDED_ABBREVIATIONS_CORE_RULE,
    EXPANDED_ABBREVIATIONS_MARKER,
    PRESERVE_ABBREVIATIONS_CORE_RULES,
    PROMPT_BUILDER_CORE_RULES,
    core_rules_for,
)
from run_support import neutral_system_scaffold


def test_preserve_rules_are_the_abbreviation_rules():
    assert len(PRESERVE_ABBREVIATIONS_CORE_RULES) == 2
    assert all("abbreviations" in rule for rule in PRESERVE_ABBREVIATIONS_CORE_RULES)


def test_default_profile_keeps_preserve_rules():
    prompt = neutral_system_scaffold("generic", "Role text.", "Format.")
    for rule in PRESERVE_ABBREVIATIONS_CORE_RULES:
        assert rule in prompt
    assert EXPANDED_ABBREVIATIONS_CORE_RULE not in prompt


def test_expanding_profile_gets_the_expand_rule_only():
    role = "# FIDELITY RULES\n\n- " + EXPANDED_ABBREVIATIONS_MARKER + ", using the ABBREVIATION KEY ..."
    prompt = neutral_system_scaffold("generic", role, "Format.")
    for rule in PRESERVE_ABBREVIATIONS_CORE_RULES:
        assert rule not in prompt
    assert "- " + EXPANDED_ABBREVIATIONS_CORE_RULE + "\n" in prompt


def test_scaffold_core_rules_match_the_preview_list():
    """The preview (prompt-builder.js) builds from PROMPT_BUILDER_CORE_RULES /
    core_rules_for(); the real scaffold must list the same rules in order."""
    for role in ("Role.", EXPANDED_ABBREVIATIONS_MARKER):
        prompt = neutral_system_scaffold("generic", role, "Format.")
        core = prompt.split("# CORE TRANSCRIPTION RULES\n", 1)[1]
        expected = core_rules_for(role)
        found = [line[2:] for line in core.split("\n") if line.startswith("- ")][: len(expected)]
        assert found == expected
    assert core_rules_for("Role.") == PROMPT_BUILDER_CORE_RULES
