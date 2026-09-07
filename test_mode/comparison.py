from __future__ import annotations

import re
from collections import Counter

from rapidfuzz.distance import Levenshtein

# Metric definitions follow Crosilla, Klic & Colavizza (2025), "Benchmarking
# Large Language Models for Handwritten Text Recognition" (arXiv:2503.15195),
# section 3.5 — the standard ASR/HTR evaluation trio: Character Error Rate,
# Word Error Rate, and order-independent Bag-of-Words WER, all built on
# Levenshtein (1965) edit distance. This replaces an earlier ad hoc
# word-similarity score with a real keystroke-level count instead.

_LINEBREAK_RUN = re.compile(r"\s*\n\s*")
_TRAILING_PUNCTUATION = re.compile(r"[^\w\s]+(?=\s|$)")
_WHITESPACE_RUN = re.compile(r"\s+")

_BLOCK_SPLIT = re.compile(r"\n\s*\n")
_LABEL_NOTES = re.compile(r"^notes:\s*", re.IGNORECASE)
_LABEL_LOCATOR = re.compile(r"^page\s+\S+\s*(?:[-–—]\s*entry\s+\S+\s*)?:\s*$", re.IGNORECASE)
_LABEL_ENGLISH_TRANSLATION_BARE = re.compile(r"^english translation:\s*$", re.IGNORECASE)
_LABEL_ENGLISH_TRANSLATION_INLINE = re.compile(r"^english translation:\s*(.*)$", re.IGNORECASE | re.DOTALL)


def strip_non_transcription_blocks(text: str) -> str:
    """Drop the English Translation, Notes, and synthetic Page/Entry locator
    blocks, leaving only the native-language transcription content (including
    a Marginal Heading block, when present — that's a verbatim transcription
    of what the scribe wrote, not commentary, so it stays scored).

    Test Mode compares models on transcription accuracy specifically; without
    this, CER/WER conflates transcription quality with translation-phrasing
    conformance and note-writing style, neither of which is what's being
    benchmarked. See docs/DESIGN.md's "Test Mode scoring" section for the
    block-structure contract this relies on. `Notes:`/`Latin Transcription:`
    label text itself is left in place exactly like every other block's own
    label — only whole blocks are dropped, never partial content.

    _LABEL_LOCATOR matches the locator line with or without a trailing
    "- Entry N" (Prompt Builder profiles stopped emitting that suffix; an
    entry's own number, when the source has one, now lives in the Marginal
    Heading block instead), so both an older profile's "Page 34 - Entry 1:"
    and a current one's "Page 34:" still get stripped.
    """
    blocks = _BLOCK_SPLIT.split(text)
    kept: list[str] = []
    skip_next = False
    for block in blocks:
        if skip_next:
            skip_next = False
            continue
        stripped = block.strip()
        if _LABEL_NOTES.match(stripped):
            continue
        if _LABEL_LOCATOR.match(stripped):
            continue
        if _LABEL_ENGLISH_TRANSLATION_BARE.match(stripped):
            skip_next = True
            continue
        inline_match = _LABEL_ENGLISH_TRANSLATION_INLINE.match(stripped)
        if inline_match and inline_match.group(1).strip():
            continue
        kept.append(block)
    return "\n\n".join(kept)


def normalize_transcription_text(text: str) -> str:
    """Collapse line breaks/empty lines and strip word-boundary punctuation.

    Matches the paper's own normalization step: "the output length is
    normalized to the one of the GT, while line breaks, empty lines and all
    punctuation followed by a whitespace are removed. This ensures that
    whitespaces are the only separators between words" — so the score
    reflects transcribed content, not paragraph/line-break formatting.
    """
    collapsed = _LINEBREAK_RUN.sub(" ", text)
    unpunctuated = _TRAILING_PUNCTUATION.sub("", collapsed)
    return _WHITESPACE_RUN.sub(" ", unpunctuated).strip()


def _tokenize_words(text: str) -> list[str]:
    normalized = normalize_transcription_text(text).casefold()
    return [word for word in normalized.split(" ") if word]


def character_edit_stats(reference: str, hypothesis: str) -> tuple[int, int]:
    """(character-level edit distance, reference character count), the raw
    counts CER is a ratio of. Exposed separately so callers (the comparison
    report) can turn a percentage back into an estimated number of edits."""
    ref = normalize_transcription_text(reference)
    hyp = normalize_transcription_text(hypothesis)
    return Levenshtein.distance(ref, hyp), len(ref)


def word_edit_stats(reference: str, hypothesis: str) -> tuple[int, int]:
    """(word-level edit distance, reference word count), the raw counts WER
    is a ratio of."""
    ref_words = _tokenize_words(reference)
    hyp_words = _tokenize_words(hypothesis)
    return Levenshtein.distance(ref_words, hyp_words), len(ref_words)


def bag_of_words_mismatch_stats(reference: str, hypothesis: str) -> tuple[int, int]:
    """(words in the reference with no matching occurrence in the hypothesis,
    reference word count), the raw counts WER-BoW is a ratio of — ignores word
    order (Moysset et al., 2017).

    The intersection is multiset-based (via Counter): a word appearing twice
    in the reference needs two matching occurrences in the hypothesis to
    count twice, so a hypothesis can't inflate its score by repeating one
    correct word.
    """
    ref_words = _tokenize_words(reference)
    hyp_words = _tokenize_words(hypothesis)
    intersection = sum((Counter(ref_words) & Counter(hyp_words)).values())
    return len(ref_words) - intersection, len(ref_words)


def _rate(edits: int, total: int) -> float:
    if total == 0:
        return 0.0 if edits == 0 else 1.0
    return edits / total


def score_transcription(reference: str, hypothesis: str) -> dict[str, object]:
    """CER/WER/WER-BoW for one model's native-language transcription against the
    corrected reference, plus the raw edit counts each rate is computed from
    (used by the downloadable comparison report to state an estimated number
    of character/word-level fixes, not just a percentage).

    Both sides are run through strip_non_transcription_blocks() first, applied
    symmetrically so neither side is penalized for content the other lacks.
    This measures transcription/paleography accuracy in isolation — English
    Translation, Notes, and the synthetic Page/Entry locator are excluded, so
    the score doesn't conflate reading the handwriting with writing an English
    sentence or a commentary note. See strip_non_transcription_blocks().

    No quality label is included deliberately — labeling a CER as "Good" or
    "Poor" bakes in a threshold judgment call the person reading the score,
    not this function, should make for their own use case.
    """
    ref = strip_non_transcription_blocks(reference)
    hyp = strip_non_transcription_blocks(hypothesis)
    char_edits, ref_chars = character_edit_stats(ref, hyp)
    word_edits, ref_words = word_edit_stats(ref, hyp)
    bow_mismatches, _ = bag_of_words_mismatch_stats(ref, hyp)
    return {
        "cer": round(_rate(char_edits, ref_chars), 4),
        "wer": round(_rate(word_edits, ref_words), 4),
        "wer_bow": round(_rate(bow_mismatches, ref_words), 4),
        "char_edits": char_edits,
        "ref_chars": ref_chars,
        "word_edits": word_edits,
        "ref_words": ref_words,
        "bow_mismatches": bow_mismatches,
    }
