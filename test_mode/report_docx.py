"""Comparison report DOCX builder for Test Mode's "Download Comparison
Report" button -- split out of app.py alongside test_mode/comparison.py
(which scores the comparison; this module only renders the downloadable
write-up of those scores) as part of the app.py-modularization pass (see
CLAUDE.md).

Separate small OOXML builder from the main transcription writer
(header_box_element()/document_xml() in app.py): this one needs bold
headings and an actual table, which that flat one-paragraph-per-line writer
doesn't support and wasn't worth complicating for one caller. The actual
paragraph/table/document-assembly building blocks now live in
report_docx_builder.py (split out once index_compare/report_docx.py needed
the exact same blocks for its own downloadable report) -- this module only
holds Test Mode's own report content."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from xml.etree import ElementTree

from customizable_transcription.core import MODELS
from report_docx_builder import assemble_docx_bytes, report_document_xml, report_paragraph, report_table


def compare_report_contestant_label(entry: Mapping[str, object]) -> str:
    label = str(entry.get("label") or "")
    model = str(entry.get("model") or "")
    if model:
        return f"{label} ({MODELS.get(model, model)})"
    return label


def build_compare_report_docx(results: list[Mapping[str, object]], corrected_label: str) -> bytes:
    """Assemble the downloadable comparison report: the same results table
    shown on-screen, plus a plain-language explanation of CER/WER/WER-BoW and
    an estimated correction-effort breakdown per contestant. See CLAUDE.md's
    Test Mode scoring section for what is and isn't included in these scores."""
    ground_truth_label = corrected_label.strip() or "100% corrected reference document"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    elements: list[ElementTree.Element] = [
        report_paragraph("Transcription Comparison Report", bold=True, size_half_points=32, space_after_twips=80),
        report_paragraph(f"Generated {generated}", space_after_twips=40),
        report_paragraph(f"Ground truth used: {ground_truth_label}", space_after_twips=300),
        report_paragraph(
            "Results: Levenshtein Distance (lower scores = less correction required)",
            bold=True,
            size_half_points=26,
            space_after_twips=120,
        ),
        report_table(
            [["Rank", "Contestant", "CER", "WER", "WER-BoW"]]
            + [
                [
                    str(entry.get("rank", "")),
                    compare_report_contestant_label(entry),
                    f"{float(entry.get('cer', 0)) * 100:.2f}%",
                    f"{float(entry.get('wer', 0)) * 100:.2f}%",
                    f"{float(entry.get('wer_bow', 0)) * 100:.2f}%",
                ]
                for entry in results
            ]
        ),
        report_paragraph("", space_after_twips=200),
        report_paragraph("Estimated correction effort", bold=True, size_half_points=26, space_after_twips=120),
        report_paragraph(
            "Figures below are the raw correction counts behind the percentages above. They indicate "
            "roughly how many individual character- or word-level fixes each transcript would need to "
            "match the corrected reference.",
            space_after_twips=160,
        ),
        report_table(
            [["Contestant", "Reference length", "Est. character-level edits", "Est. word-level edits", "Words in wrong position"]]
            + [
                [
                    compare_report_contestant_label(entry),
                    f"{entry.get('ref_chars', 0)} characters / {entry.get('ref_words', 0)} words",
                    str(entry.get("char_edits", 0)),
                    str(entry.get("word_edits", 0)),
                    str(entry.get("bow_mismatches", 0)),
                ]
                for entry in results
            ]
        ),
        report_paragraph("", space_after_twips=200),
        report_paragraph("What these metrics measure", bold=True, size_half_points=26, space_after_twips=120),
        report_paragraph(
            "All three scores compare an AI transcript against the human-corrected reference for the same "
            "source pages. Each is a form of edit distance: the minimum number of insertions, deletions, or "
            "substitutions needed to turn the AI's output into the corrected text, expressed as a percentage of "
            "the reference's own length. None of them are self-explanatory from the number alone — a low "
            "number is good, but “low” means different things at the character level than at the word "
            "level, which is why all three are reported together.",
            space_after_twips=200,
        ),
        report_paragraph("Character Error Rate (CER)", bold=True, size_half_points=24, space_after_twips=100),
        report_paragraph(
            "Counts single-character edits — insert one character, delete one, or swap one for another — "
            "then divides by the number of characters in the corrected text. A CER of 5% means about 5 characters "
            "out of every 100 needed a fix. Because it works letter by letter, one misread character inside an "
            "otherwise-correct word (e.g. a single wrong diacritic) counts as one small edit here, even though "
            "that same letter can spoil the whole word at the word level below.",
            space_after_twips=100,
        ),
        report_paragraph(
            "Cost in practice: CER is close to a literal keystroke count. Multiplying CER by the reference's "
            "character count (the “Est. character-level edits” column above) gives a rough number of "
            "individual character corrections needed. Treat it as a floor, not a total — most people correct "
            "by retyping whole words rather than swapping single letters, and locating each error takes time on "
            "top of the edit itself.",
            space_after_twips=200,
        ),
        report_paragraph("Word Error Rate (WER)", bold=True, size_half_points=24, space_after_twips=100),
        report_paragraph(
            "The same edit-distance calculation at the word level, and it also cares about order — a word has "
            "to appear in the same sequence as the reference to count as correct. WER is almost always higher "
            "than CER for the same document, because a single wrong character is usually enough to make the "
            "whole word it's in count as wrong, even though only one letter was actually mis-transcribed.",
            space_after_twips=100,
        ),
        report_paragraph(
            "Cost in practice: WER is a closer proxy for how many words a person would need to select and "
            "retype, rather than edit character by character. The “Est. word-level edits” column is WER "
            "multiplied by the reference's word count.",
            space_after_twips=200,
        ),
        report_paragraph("Bag-of-Words WER (WER-BoW)", bold=True, size_half_points=24, space_after_twips=100),
        report_paragraph(
            "Ignores word order entirely and asks a narrower question: does the corrected text's set of words "
            "also show up in the AI's output? It doesn't penalize a model for putting a correct word in a "
            "different position — a reordered clause, a title written before a name instead of after. "
            "WER-BoW is always less than or equal to WER for the same text; the gap between the two is "
            "informative on its own.",
            space_after_twips=100,
        ),
        report_paragraph(
            "Cost in practice: the “Words in wrong position” column counts reference words with no "
            "matching occurrence anywhere in the AI's output, regardless of position. A large gap between WER "
            "and this number means many of WER's “errors” are really words that just need to be moved, "
            "not re-transcribed.",
            space_after_twips=200,
        ),
        report_paragraph("Reading the three scores together", bold=True, size_half_points=24, space_after_twips=100),
        report_paragraph(
            "All three low and close together: the AI read both the letters and the words accurately, in the "
            "right order — the correction burden is genuinely light.",
            space_after_twips=60,
        ),
        report_paragraph(
            "CER low but WER noticeably higher: small character-level slips (a wrong diacritic, a similar "
            "letterform) are landing inside otherwise-correct words and spoiling them — worth a look at "
            "recurring letter confusions rather than treating this as many separate errors.",
            space_after_twips=60,
        ),
        report_paragraph(
            "WER high but WER-BoW much lower: the AI likely has the right words in the wrong order or position — "
            "often a faster fix (move text) than a genuine misreading would be.",
            space_after_twips=60,
        ),
        report_paragraph(
            "All three high: this document was a hard read for the model; correction is closer to transcribing "
            "that section from scratch than to proofreading it.",
            space_after_twips=200,
        ),
        report_paragraph("Translating scores into effort", bold=True, size_half_points=24, space_after_twips=100),
        report_paragraph(
            "None of these percentages directly measure correction time — they measure edit distance, not how "
            "long it takes a person to find an error, decide on a fix, and retype it. Real correction time also "
            "depends on how errors are distributed (clustered in a few entries vs. spread evenly) and on how "
            "practiced the corrector is with the register's handwriting and formulas. Treat these numbers as a "
            "relative ranking between models or runs on the same source material, and as a rough proxy — not a "
            "guaranteed prediction — of how much hands-on correction a transcript will need before it's ready "
            "for indexing.",
            space_after_twips=200,
        ),
        report_paragraph("About this comparison", bold=True, size_half_points=24, space_after_twips=100),
        report_paragraph(
            "These scores cover native-language transcription accuracy only. The English Translation and Notes "
            "blocks, and the synthetic Page/Entry locator line, are excluded from both sides before scoring, so "
            "the numbers reflect how accurately the model read the handwriting — not translation phrasing or "
            "note-writing style.",
            space_after_twips=200,
        ),
        report_paragraph(
            "Metric definitions follow Crosilla, Klic & Colavizza (2025), “Benchmarking Large Language Models "
            "for Handwritten Text Recognition” (arXiv:2503.15195), section 3.5; the bag-of-words variant follows "
            "Moysset et al. (2017).",
            space_after_twips=0,
        ),
    ]

    document_xml_bytes = report_document_xml(elements)
    return assemble_docx_bytes(document_xml_bytes)
