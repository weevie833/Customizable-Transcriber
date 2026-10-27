"""The preset continuation notes render_entry() writes, and that XLS Conversion
still recognises them (that is what links the split entry across two images)."""

from customizable_transcriber.core import physical_neighbors, render_entry
from xls_conversion.ai_parser import (
    _says_continues_from_previous,
    _says_continues_on_next,
    block_ends_with_open_entry,
    split_leading_continuation,
)


def test_next_image_note_moves_to_end_of_record():
    text = (
        "Date: 1 Jan\n\nNotes: Entry appears to continue on the next image.\n\nItalian Transcription:\n\nbody\n\n"
        "Baptism Record:\n\nbaptism text"
    )
    out = render_entry("a_002.jpg", text, next_name="a_003.jpg", previous_name="a_001.jpg")
    note = "Notes: ENTRY CONTINUES ON THE NEXT IMAGE -- the rest of this entry is in the record for a_003.jpg."
    assert out.rstrip().endswith("baptism text\n\n" + note)
    assert out.count("ENTRY CONTINUES") == 1
    assert "appears to continue" not in out
    assert "Notes:\n" not in out and "Date: 1 Jan\n\nItalian Transcription" in out


def test_other_notes_stay_and_only_continuation_moves():
    text = "Notes: Surname uncertain. Entry appears to continue on the next image.\n\nItalian Transcription:\n\nbody"
    out = render_entry("a.jpg", text, "b.jpg", None)
    assert "Notes: Surname uncertain.\n" in out
    assert out.rstrip().endswith("record for b.jpg.")


def test_flag_on_earlier_entry_is_not_moved():
    text = (
        "Notes: Entry appears to continue on the next image.\n\nItalian Transcription:\n\nfirst\n\n"
        "Date: 2 Jan\n\nItalian Transcription:\n\nsecond"
    )
    out = render_entry("a.jpg", text, "b.jpg", None)
    assert not out.rstrip().endswith("b.jpg.")
    assert out.count("ENTRY CONTINUES ON THE NEXT IMAGE") == 1


def test_from_previous_note_and_other_notes_kept():
    text = "Notes: Entry appears to continue from the previous image. Surname uncertain.\n\nItalian Transcription:\n\nbody"
    out = render_entry("a_003.jpg", text, next_name="a_004.jpg", previous_name="a_002.jpg")
    assert out.split("\n\n")[2].startswith("Notes: ENTRY CONTINUES FROM THE PREVIOUS IMAGE")
    assert "ENTRY CONTINUES FROM THE PREVIOUS IMAGE -- the beginning of this entry is in the record for a_002.jpg. Surname uncertain." in out


def test_edge_of_run_has_no_filename():
    out = render_entry("a_009.jpg", "Notes: Entry appears to continue on the next image.\n\nItalian Transcription:\n\nx")
    assert "the next image is not part of this run" in out


def test_notes_without_continuation_untouched():
    text = "Notes: Surname uncertain.\n\nItalian Transcription:\n\nbody"
    assert "Notes: Surname uncertain." in render_entry("a.jpg", text, "b.jpg", None)


def test_physical_neighbors_respect_reverse_order():
    names = ["c", "b", "a"]  # processing order of a reverse run
    assert physical_neighbors(names, 1, True) == ("c", "a")
    assert physical_neighbors(["a", "b", "c"], 0, False) == ("b", None)


def test_xls_conversion_still_recognises_preset_notes():
    nxt = "ENTRY CONTINUES ON THE NEXT IMAGE -- the rest of this entry is in the record for a_003.jpg."
    prev = "ENTRY CONTINUES FROM THE PREVIOUS IMAGE -- the beginning of this entry is in the record for a_002.jpg."
    assert _says_continues_on_next(nxt) and not _says_continues_from_previous(nxt)
    assert _says_continues_from_previous(prev) and not _says_continues_on_next(prev)
    block = f"Notes: {nxt}\n\nItalian Transcription:\n\nbody"
    assert block_ends_with_open_entry(block)
    end_block = f"Date: 1 Jan\n\nItalian Transcription:\n\nbody\n\nBaptism Record:\n\nbaptism\n\nNotes: {nxt}\n"
    assert block_ends_with_open_entry(end_block)
    assert not block_ends_with_open_entry(end_block.replace("ENTRY CONTINUES ON THE NEXT", "Surname uncertain, see the"))
    fragment_block = f"Notes: {prev}\n\nItalian Transcription:\n\nfrag\n\nDate: 1 Jan\n\nNotes:\n\nItalian Transcription:\n\nnew"
    fragment, remainder = split_leading_continuation(fragment_block)
    assert fragment and "frag" in fragment and "new" in remainder


def test_italian_continuation_clauses_are_recognised():
    from xls_conversion.ai_parser import merge_notes

    assert _says_continues_from_previous("continuato dall'immagine precedente")
    assert _says_continues_from_previous("Continuazione dall'immagine precedente")
    assert _says_continues_on_next("l'atto continua nell'immagine successiva")
    assert _says_continues_on_next("La voce prosegue nell'immagine successiva (non inclusa in questa conversione).")
    assert not _says_continues_on_next("Battesimo amministrato il 19 luglio 1834")
    # The merge call dropped the departure row's own note: keep it, drop the flags.
    assert merge_notes(
        "Battesimo amministrato il 19 luglio 1834; l'atto continua nell'immagine successiva",
        "Continuazione dall'immagine precedente",
    ) == "Battesimo amministrato il 19 luglio 1834; Continuazione dall'immagine precedente"


def test_civil_birth_prompt_requires_the_baptism_note():
    from xls_conversion.ai_parser import CIVIL_BIRTH_SYSTEM_PROMPT

    assert "Baptism Record" in CIVIL_BIRTH_SYSTEM_PROMPT
    assert "ALWAYS include a note giving the date the baptism was administered" in CIVIL_BIRTH_SYSTEM_PROMPT
