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
    """CER/WER/WER-BoW for one model's transcription against the corrected reference."""
    cer = character_error_rate(reference, hypothesis)
    wer = word_error_rate(reference, hypothesis)
    wer_bow = word_error_rate_bag_of_words(reference, hypothesis)
    return {
        "cer": round(cer, 4),
        "wer": round(wer, 4),
        "wer_bow": round(wer_bow, 4),
        "quality": cer_quality_label(cer),
    }
