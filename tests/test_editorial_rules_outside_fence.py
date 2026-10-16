"""Additional editorial rules are instructions, so build_system_prompt() must
place them outside the 'reference only' code fence, and a reference containing
backticks must not be able to close that fence early."""

from __future__ import annotations

import json
from pathlib import Path

import run_support

PROFILE = {"role_context": "role", "output_format": "format"}


def _prompt(reference: str) -> str:
    return run_support.build_system_prompt("transcribe", {**PROFILE, "reference_context": reference})


def test_editorial_rules_follow_the_closed_fence():
    prompt = _prompt("# LEXICON\n\nnames\n\n# ADDITIONAL EDITORIAL RULES\n\nNever copy a surname.")
    fence_close = prompt.index("\n```", prompt.index("```text") + 3)
    assert prompt.index("# ADDITIONAL EDITORIAL RULES") > fence_close
    assert "Never copy a surname." in prompt.split("# ADDITIONAL EDITORIAL RULES", 1)[1]
    assert "Never copy a surname." not in prompt[:fence_close]


def test_reference_without_rules_is_unchanged_in_shape():
    prompt = _prompt("just names")
    assert "# ADDITIONAL EDITORIAL RULES" not in prompt
    assert prompt.rstrip().endswith("```")


def test_rules_only_reference_has_no_empty_fence():
    prompt = _prompt("# ADDITIONAL EDITORIAL RULES\n\nRule one.")
    assert "```" not in prompt
    assert prompt.rstrip().endswith("Rule one.")


def test_backticks_in_reference_cannot_close_the_fence():
    prompt = _prompt("a ``` b\n\n# ADDITIONAL EDITORIAL RULES\n\nRule.")
    assert "````text" in prompt


def test_shipped_v4_rules_land_outside_fence():
    profile = json.loads(Path("profiles/chiusa-sclafani-battesimi-v4.json").read_text(encoding="utf-8"))
    prompt = run_support.build_system_prompt("transcribe", profile)
    marker = "# ADDITIONAL EDITORIAL RULES"
    if marker in profile["reference_context"]:
        head = prompt.split(marker, 1)[0]
        assert head.count("```") % 2 == 0


def test_extraction_rules_cover_bracketed_inferred_year():
    from xls_conversion import ai_parser

    assert "[1754?]" in ai_parser.GENERAL_EXTRACTION_RULES
