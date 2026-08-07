from __future__ import annotations

import re
from collections import Counter

from rapidfuzz.distance import Levenshtein

# Metric definitions follow Crosilla, Klic & Colavizza (2025), "Benchmarking
# Large Language Models for Handwritten Text Recognition" (arXiv:2503.15195),
# section 3.5 — the standard ASR/HTR evaluation trio: Character Error Rate,
# Word Error Rate, and order-independent Bag-of-Words WER, all built on
# Levenshtein (1965) edit distance. This replaces an earlier ad hoc
# word-similarity score with the metric this project's own CLAUDE.md flagged
# as the real backstop ("a method to determine the difference, such as
# keystrokes") — CER *is* that keystroke-level count.

_LINEBREAK_RUN = re.compile(r"\s*\n\s*")
_TRAILING_PUNCTUATION = re.compile(r"[^\w\s]+(?=\s|$)")
_WHITESPACE_RUN = re.compile(r"\s+")

_BLOCK_SPLIT = re.compile(r"\n\s*\n")
_LABEL_NOTES = re.compile(r"^notes:\s*", re.IGNORECASE)
_LABEL_LOCATOR = re.compile(r"^page\s+\S+\s*[-–—]\s*entry\s+\S+\s*:\s*$", re.IGNORECASE)
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
    benchmarked. See CLAUDE.md "Chiusa Sclafani battesimi — decisions" for the
    block-structure contract this relies on. `Notes:`/`Latin Transcription:`
    label text itself is left in place exactly like every other block's own
    label — only whole blocks are dropped, never partial content.
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


def character_error_rate(reference: str, hypothesis: str) -> float:
    """CER = (I + S + D) / N, N = character count of the reference."""
    ref = normalize_transcription_text(reference)
    hyp = normalize_transcription_text(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return Levenshtein.distance(ref, hyp) / len(ref)


def word_error_rate(reference: str, hypothesis: str) -> float:
    """WER = word-level Levenshtein distance / word count of the reference."""
    ref_words = _tokenize_words(reference)
    hyp_words = _tokenize_words(hypothesis)
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return Levenshtein.distance(ref_words, hyp_words) / len(ref_words)


def word_error_rate_bag_of_words(reference: str, hypothesis: str) -> float:
    """WER-BoW = (N - |ref ∩ hyp|) / N — ignores word order (Moysset et al., 2017).

    The intersection is multiset-based (via Counter): a word appearing twice
    in the reference needs two matching occurrences in the hypothesis to
    count twice, so a hypothesis can't inflate its score by repeating one
    correct word.
    """
    ref_words = _tokenize_words(reference)
    hyp_words = _tokenize_words(hypothesis)
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    intersection = sum((Counter(ref_words) & Counter(hyp_words)).values())
    return (len(ref_words) - intersection) / len(ref_words)


def cer_quality_label(cer: float) -> str:
    """Thresholds cited in the paper (Muehlberger et al., 2019; Hodel et al., 2021)."""
    if cer < 0.025:
        return "Excellent"
    if cer < 0.05:
        return "Very good"
    if cer <= 0.10:
        return "Good"
    return "Poor"


def score_transcription(reference: str, hypothesis: str) -> dict[str, object]:
    """CER/WER/WER-BoW for one model's native-language transcription against the
    corrected reference.

    Both sides are run through strip_non_transcription_blocks() first, applied
    symmetrically so neither side is penalized for content the other lacks.
    This measures transcription/paleography accuracy in isolation — English
    Translation, Notes, and the synthetic Page/Entry locator are excluded, so
    the score doesn't conflate reading the handwriting with writing an English
    sentence or a commentary note. See strip_non_transcription_blocks().
    """
    ref = strip_non_transcription_blocks(reference)
    hyp = strip_non_transcription_blocks(hypothesis)
    cer = character_error_rate(ref, hyp)
    wer = word_error_rate(ref, hyp)
    wer_bow = word_error_rate_bag_of_words(ref, hyp)
    return {
        "cer": round(cer, 4),
        "wer": round(wer, 4),
        "wer_bow": round(wer_bow, 4),
        "quality": cer_quality_label(cer),
    }
