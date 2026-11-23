"""One place that decides what a provider's finish/stop reason means for a
transcribed page (CODEX_REVIEW_2.md H-5).

Every adapter (real-time Gemini/Claude, Gemini/Claude batch) and the usage
ledger classify through this module, so a page is counted the same way in the
document, the run summary and the ledger:

- COMPLETE   the model finished normally; the text is saved as is.
- TRUNCATED  the model hit its output limit; the partial text is saved with a
             [TRUNCATED: ...] notice (and real-time runs may retry it).
- INCOMPLETE the model stopped early for another non-blocking reason (context
             window exceeded, an unrecognised or unspecified reason); the
             partial text is saved with an [INCOMPLETE: ...] notice naming
             the reason.
- BLOCKED    a refusal or a safety/recitation block; the page fails, because
             any text returned is not a transcription.

Leaf module: imports nothing from the app, so core.py, batch_transcription.py
and usage_ledger.py can all use it.
"""

from __future__ import annotations

COMPLETE = "complete"
TRUNCATED = "truncated"
INCOMPLETE = "incomplete"
BLOCKED = "blocked"

_CLAUDE = {
    "end_turn": COMPLETE,
    "stop_sequence": COMPLETE,
    "max_tokens": TRUNCATED,
    "model_context_window_exceeded": INCOMPLETE,
    "refusal": BLOCKED,
}

_GEMINI = {
    "STOP": COMPLETE,
    "MAX_TOKENS": TRUNCATED,
    "SAFETY": BLOCKED,
    "RECITATION": BLOCKED,
    "BLOCKLIST": BLOCKED,
    "PROHIBITED_CONTENT": BLOCKED,
    "SPII": BLOCKED,
    "IMAGE_SAFETY": BLOCKED,
    "IMAGE_PROHIBITED_CONTENT": BLOCKED,
    "IMAGE_RECITATION": BLOCKED,
}


def reason_text(reason: object) -> str:
    """A finish reason as plain text ("STOP", "refusal"), or "unknown"."""
    if reason is None:
        return "unknown"
    return str(getattr(reason, "name", reason))


def classify(provider: str, reason: object) -> str:
    """The outcome for a reply that carried text. Anything not listed
    (tool_use, pause_turn, OTHER, LANGUAGE, unspecified, None) is INCOMPLETE:
    the text is kept but never counted as a finished page."""
    text = reason_text(reason)
    table = _CLAUDE if provider == "claude" else _GEMINI
    return table.get(text, INCOMPLETE)


INCOMPLETE_MARKER = "[INCOMPLETE:"


def incomplete_notice(reason: object) -> str:
    return (
        f"\n\n{INCOMPLETE_MARKER} the model stopped before finishing this image "
        f"(stop reason: {reason_text(reason)}). Everything above is genuine model output, "
        "but later entries on this image may be missing. Re-run this image on its own to "
        "try to recover the rest.]"
    )


def blocked_error(reason: object) -> str:
    return (
        "The model returned no transcription text: the reply was blocked or refused "
        f"(stop reason: {reason_text(reason)})."
    )


def empty_error(reason: object) -> str:
    return f"The model returned no transcription text (stop reason: {reason_text(reason)})."


def finish(provider: str, text: str, reason: object, truncation_notice: str) -> tuple[str, str]:
    """(text_to_save, error). error is "" when the page is saved (complete,
    truncated or incomplete); text_to_save is "" when it failed."""
    if not text.strip():
        return "", empty_error(reason)
    outcome = classify(provider, reason)
    if outcome == BLOCKED:
        return "", blocked_error(reason)
    if outcome == TRUNCATED:
        return text + truncation_notice, ""
    if outcome == INCOMPLETE:
        return text + incomplete_notice(reason), ""
    return text, ""
