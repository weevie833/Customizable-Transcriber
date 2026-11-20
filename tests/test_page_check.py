"""Page check (customizable_transcriber/page_check.py)."""

from customizable_transcriber.page_check import apply_page_check, check_page_numbers


def _transcript(images: list[list[str]]) -> str:
    """images: per image, the page value of each entry ("4", "[illegible]")."""
    parts = ["# Transcription Output", ""]
    for number, pages in enumerate(images, start=1):
        parts += ["", f"--- START OF RECORD: img_{number:02d}.png ---", ""]
        for page in pages:
            parts += [f"Page {page}:", "", "Date: Die 4 Augusti 1694 [4 August 1694]", "",
                      "Latin Transcription: text", ""]
    return "\n".join(parts)


def test_misread_single_page_image_is_flagged():
    result = check_page_numbers(_transcript([["4", "4"], ["9", "9"], ["6"]]))
    assert result.flagged_entries == 2
    assert result.flagged_images == ["img_02.png"]
    assert "PAGE CHECK -- this entry's page number (9)" in result.text
    assert "(expected page 5)" in result.text


def test_consistent_run_passes():
    result = check_page_numbers(_transcript([["4"], ["5"], ["6"], ["7"]]))
    assert result.flagged_entries == 0 and result.suggested_entries == 0
    assert result.judged_images == 2


def test_two_facing_pages_shifted_reading_is_flagged():
    images = [["34", "35"], ["35", "36"], ["38", "39"]]
    result = check_page_numbers(_transcript(images))
    assert result.flagged_images == ["img_02.png"]
    assert result.flagged_entries == 1  # the "35" entry; "36" fits pages 36-37
    assert "(expected pages 36-37)" in result.text


def test_two_facing_pages_with_one_page_unread_is_not_flagged():
    result = check_page_numbers(_transcript([["34", "35"], ["37"], ["38", "39"]]))
    assert result.flagged_entries == 0


def test_non_consecutive_sample_pages_are_not_judged():
    result = check_page_numbers(_transcript([["4"], ["5"], ["24"], ["32"]]))
    assert result.flagged_entries == 0
    assert result.judged_images == 0


def test_first_and_last_images_are_never_judged():
    result = check_page_numbers(_transcript([["40"], ["5"], ["6"], ["70"]]))
    assert result.flagged_entries == 0


def test_two_misread_images_together_are_both_flagged():
    result = check_page_numbers(_transcript([["4"], ["5"], ["15"], ["16"], ["8"]]))
    assert result.flagged_images == ["img_03.png", "img_04.png"]


def test_one_misread_entry_on_a_good_image_is_flagged():
    result = check_page_numbers(_transcript([["4"], ["5", "5", "50"], ["6"]]))
    assert result.flagged_entries == 1


def test_illegible_page_gets_a_suggestion():
    result = check_page_numbers(_transcript([["4"], ["[illegible]", "[illegible]"], ["6"]]))
    assert result.suggested_entries == 2
    assert result.suggested_images == ["img_02.png"]
    assert "the surrounding images suggest page 5" in result.text


def test_reverse_order_run_is_read_in_physical_order():
    # A newest-to-oldest run writes the last photo first.
    result = check_page_numbers(_transcript([["6"], ["9"], ["4"]]), reverse_order=True)
    assert result.flagged_images == ["img_02.png"]


def test_note_appended_to_existing_notes_line():
    text = _transcript([["4"], ["9"], ["6"]]).replace(
        "Page 9:\n\nDate: Die 4 Augusti 1694 [4 August 1694]\n",
        "Page 9:\n\nDate: Die 4 Augusti 1694 [4 August 1694]\n\nNotes: Ink faded.\n",
    )
    result = check_page_numbers(text)
    assert "Notes: Ink faded. PAGE CHECK --" in result.text
    assert result.text.count("Notes:") == 1


def test_new_notes_line_goes_after_the_date_line():
    lines = check_page_numbers(_transcript([["4"], ["9"], ["6"]])).text.split("\n")
    date = lines.index("Date: Die 4 Augusti 1694 [4 August 1694]", lines.index("Page 9:"))
    assert lines[date + 2].startswith("Notes: PAGE CHECK")
    assert lines.index("Latin Transcription: text", date) > date + 2


def test_apply_logs_and_rewrites(tmp_path):
    path = tmp_path / "out.md"
    path.write_text(_transcript([["4"], ["9"], ["6"]]), encoding="utf-8")
    messages: list[str] = []
    apply_page_check(path, False, messages.append)
    assert "PAGE CHECK" in path.read_text(encoding="utf-8")
    assert messages and messages[0].startswith("Page check: 1 entry on 1 image(s)")


def test_apply_says_nothing_when_nothing_could_be_judged(tmp_path):
    path = tmp_path / "out.md"
    path.write_text(_transcript([["4"], ["5"]]), encoding="utf-8")
    messages: list[str] = []
    apply_page_check(path, False, messages.append)
    assert messages == []
