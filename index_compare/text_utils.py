from __future__ import annotations

# Shared by align.py (locator normalization), heuristics.py (diff
# classification), and reader.py-adjacent code that needs the same
# "is this cell effectively empty" judgment -- an honestly-flagged
# "[illegible]" (the convention this app's own transcription/extraction
# prompts use, see docs/DESIGN.md's "XLS Conversion" section) means the same thing
# as a blank cell for every one of these purposes, so this is written once
# rather than reimplemented per module.


def is_blank_or_illegible(value: object) -> bool:
    text = str(value or "").strip()
    return not text or text.strip("[]").casefold() == "illegible"


def normalize_for_comparison(value: object) -> str:
    """Whitespace-collapsed, case-insensitive comparison key -- for
    deciding whether two cell values are "the same text", not for display."""
    return " ".join(str(value or "").split()).casefold()
