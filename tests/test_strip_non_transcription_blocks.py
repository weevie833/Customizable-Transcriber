"""Test Mode scoring scores the transcription only (strip_non_transcription_blocks())."""

from test_mode.comparison import score_transcription, strip_non_transcription_blocks

ENTRY = """Page 4:

Date: Die 4 Augusti 1694 [4 August 1694]

Notes: Ink faded.

Latin Transcription:

Vitus de Pappone obijt."""


def test_basic_entry_keeps_date_and_transcription():
    out = strip_non_transcription_blocks(ENTRY)
    assert "Vitus de Pappone obijt." in out
    assert "Die 4 Augusti 1694" in out
    assert "Ink faded" not in out and "Page 4" not in out


def test_notes_line_without_blank_line_is_dropped():
    text = ENTRY.replace("\n\nNotes: Ink faded.", "\nNotes: Ink faded.")
    out = strip_non_transcription_blocks(text)
    assert "Ink faded" not in out
    assert "Die 4 Augusti 1694" in out


def test_every_translation_label_is_dropped():
    for label in ("English Translation:", "Italian Translation:", "Traduzione in Inglese:", "Traduzione in italiano:"):
        bare = ENTRY + f"\n\n{label}\n\nOn the 4th day of August 1694. Vitus died."
        inline = ENTRY + f"\n\n{label} On the 4th day of August 1694. Vitus died."
        attached = ENTRY + f"\n{label}\nOn the 4th day of August 1694. Vitus died."
        for text in (bare, inline, attached):
            out = strip_non_transcription_blocks(text)
            assert "Vitus died" not in out, (label, text)
            assert "Vitus de Pappone obijt." in out


def test_church_wedding_translation_dropped_but_record_kept():
    text = ENTRY + (
        "\n\nChurch Wedding Record: Die 5 Januarii celebratum est.\n\n"
        "Church Wedding Record (English translation): On 5 January it was celebrated."
    )
    out = strip_non_transcription_blocks(text)
    assert "Die 5 Januarii celebratum est." in out
    assert "it was celebrated" not in out


def test_translation_block_is_followed_by_next_entry():
    text = ENTRY + "\n\nEnglish Translation:\n\nVitus died.\n\nPage 5:\n\nDate: Die 9 Augusti 1694\n\nLatin Transcription:\n\nBartholomeus obijt."
    out = strip_non_transcription_blocks(text)
    assert "Vitus died" not in out
    assert "Bartholomeus obijt." in out and "Die 9 Augusti 1694" in out


def test_different_notes_and_translations_do_not_change_the_score():
    reference = ENTRY + "\n\nItalian Translation: Il 4 agosto 1694 morì Vito."
    hypothesis = ENTRY.replace("Ink faded.", "Confidence: High.").replace(
        "\n\nNotes: Confidence: High.", "\nNotes: Confidence: High."
    ) + "\n\nItalian Translation: Nel giorno 4 agosto morì."
    assert score_transcription(reference, hypothesis)["cer"] == 0.0


def test_bold_markdown_labels_are_dropped_with_their_content():
    text = ENTRY + "\n\n**English Translation:**\n\nVitus died.\n\n**Notes:** faded"
    out = strip_non_transcription_blocks(text)
    assert "Vitus died" not in out and "faded" not in out
    assert "Vitus de Pappone obijt." in out
