"""The date-range sentence: background only, and older profiles' wording is
rewritten at run time (modernize_volume_range_sentence() in run_support.py)."""

import re
from pathlib import Path

from run_support import build_system_prompt, modernize_volume_range_sentence, volume_range_sentence

OLD_SHORT = "This volume covers 1762-1770. If an entry's year is unclear or absent, infer it from adjacent entries and record how you inferred it."
OLD_LONG = (
    "This volume covers 1693-1712. If an entry's year is unclear or absent, infer it from adjacent entries on this "
    "image, write the inferred year in square brackets with a question mark (for example [1754?]) wherever it "
    "appears, and record how you inferred it in Notes. You see one image at a time, so an entry near the top of an "
    "image may have no adjacent entry to infer from: leave that year as [year?] rather than guessing."
)


def test_both_old_wordings_are_rewritten_and_surrounding_text_kept():
    for old, years in ((OLD_SHORT, "1762-1770"), (OLD_LONG, "1693-1712")):
        text = "Before.\r\n\r\n" + old + "\r\nAfter."
        result = modernize_volume_range_sentence(text)
        assert result == "Before.\r\n\r\n" + volume_range_sentence(years) + "\r\nAfter."
        assert "This volume covers" not in result


def test_new_wording_tells_the_model_never_to_fit_years_to_the_range():
    sentence = volume_range_sentence("1752-1759")
    assert "background only" in sentence
    assert "never change a year to fit it" in sentence


def test_text_without_the_sentence_is_unchanged():
    assert modernize_volume_range_sentence("No range here.") == "No range here."


def test_build_system_prompt_uses_the_new_wording():
    prompt = build_system_prompt("generic", {"role_context": OLD_SHORT, "reference_context": "", "output_format": "x"})
    assert "This volume covers" not in prompt
    assert volume_range_sentence("1762-1770") in prompt


def test_javascript_sentence_matches_python():
    js = (Path(__file__).resolve().parents[1] / "static" / "prompt-builder.js").read_text(encoding="utf-8")
    match = re.search(r'parts\.push\("The register\'s cover gives its dates as " \+ volumeRange \+ "(.*?)"\);', js)
    assert match, "date-range sentence not found in prompt-builder.js"
    assert "The register's cover gives its dates as RANGE" + match.group(1) == volume_range_sentence("RANGE")
