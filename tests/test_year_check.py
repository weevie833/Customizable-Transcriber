"""Year check (customizable_transcriber/year_check.py): flags an entry whose
year is out of sequence with the surrounding images. Modelled on a real run
where 37 of 38 century misreads (1799 read as 1779, 1797 as 1777, 1800 as
1780) were on images 187, 191 and 192, while the images around them had the
right century."""

from __future__ import annotations

from customizable_transcriber.core import render_entry
from customizable_transcriber.year_check import (
    apply_year_check,
    flag_year_outliers,
    year_from_date_line,
)


def _entry(n: int, date_line: str, notes: str = "") -> str:
    notes_block = f"Notes: {notes}\n\n" if notes else ""
    return (
        f"Entry {n}:\n\n{date_line}\n\n{notes_block}Latin Transcription:\n\nAnno Domini ... Rendis.\n\n"
        "English Translation:\n\nOn the 1st day of ...\n\n"
    )


def _record(name: str, *years: int) -> str:
    body = "".join(_entry(i + 1, f"Date: die {i + 1} [{i + 1} March {year}]") for i, year in enumerate(years))
    return render_entry(name, body)


# Images 184-195 in reading order; 187, 191 and 192 carry the misread century.
GOOD = {184: 1797, 185: 1797, 186: 1797, 188: 1798, 189: 1798, 190: 1799, 193: 1800, 194: 1800, 195: 1800}
BAD = {187: (1777, 1777), 191: (1779, 1779, 1779), 192: (1780, 1780)}


def _register() -> str:
    parts = ["# Transcription Output\n\nSource folder: x\n"]
    for number in range(184, 196):
        years = BAD.get(number) or (GOOD[number], GOOD[number])
        parts.append(_record(f"IMG_{number}.jpg", *years))
    return "".join(parts)


def test_flags_every_entry_on_the_misread_images_and_nothing_else():
    result = flag_year_outliers(_register())
    assert result.flagged_images == ["IMG_187.jpg", "IMG_191.jpg", "IMG_192.jpg"]
    assert result.flagged_entries == 7
    assert result.text.count("YEAR CHECK") == 7
    assert "this entry's year (1779) does not fit the years on the surrounding images (around 1800)" in result.text


def test_flags_land_inside_the_right_record():
    text = flag_year_outliers(_register()).text
    record_187 = text.split("START OF RECORD: IMG_187.jpg")[1].split("START OF RECORD")[0]
    record_188 = text.split("START OF RECORD: IMG_188.jpg")[1].split("START OF RECORD")[0]
    assert record_187.count("Notes: YEAR CHECK") == 2
    assert "YEAR CHECK" not in record_188
    # The new Notes line sits between the Date line and the transcription.
    assert record_187.index("Date: die 1") < record_187.index("Notes: YEAR CHECK") < record_187.index("Latin Transcription:")


def test_reverse_order_run_gives_the_same_flags():
    parts = ["# Transcription Output\n\nSource folder: x\n"]
    for number in range(195, 183, -1):
        years = BAD.get(number) or (GOOD[number], GOOD[number])
        parts.append(_record(f"IMG_{number}.jpg", *years))
    result = flag_year_outliers("".join(parts), reverse_order=True)
    assert sorted(result.flagged_images) == ["IMG_187.jpg", "IMG_191.jpg", "IMG_192.jpg"]
    assert result.flagged_entries == 7


def test_appends_to_an_existing_notes_line():
    body = _entry(1, "Date: die 1 [1 March 1779]", notes="Ink faded at the margin.")
    text = (
        _record("a.jpg", 1799) + _record("b.jpg", 1799) + render_entry("c.jpg", body)
        + _record("d.jpg", 1799) + _record("e.jpg", 1799)
    )
    result = flag_year_outliers(text)
    record = result.text.split("START OF RECORD: c.jpg")[1]
    assert "Notes: Ink faded at the margin. YEAR CHECK -- this entry's year (1779)" in record
    assert record.count("Notes:") == 1


def test_normal_year_changes_are_not_flagged():
    # A register crossing a few years, and a loose leaf a few years off, stay quiet.
    text = "".join(_record(f"{i}.jpg", year) for i, year in enumerate([1762, 1763, 1763, 1764, 1769, 1765, 1766, 1767]))
    assert flag_year_outliers(text).flagged_entries == 0


def test_needs_two_neighbouring_images_with_years():
    assert flag_year_outliers(_record("a.jpg", 1799) + _record("b.jpg", 1779)).flagged_entries == 0


def test_images_without_dates_are_ignored():
    text = (
        _record("a.jpg", 1799) + render_entry("b.jpg", "ERROR: provider failed")
        + _record("c.jpg", 1799) + _record("d.jpg", 1779) + _record("e.jpg", 1799)
    )
    result = flag_year_outliers(text)
    assert result.flagged_images == ["d.jpg"]


def test_year_comes_from_the_bracketed_standard_form():
    assert year_from_date_line("Date: Anno D.ñi 1779 die 3 [3 March 1799]") == 1799
    assert year_from_date_line("Date: die 3 Martii [3 March [1799?]]") == 1799
    assert year_from_date_line("Date: due del mese di Gennaro milleottocentoventitre [2 January 1823]") == 1823
    assert year_from_date_line("Date: 3 Martii 1799") == 1799
    assert year_from_date_line("Date: [illegible]") is None


def test_apply_year_check_rewrites_the_file_and_logs(tmp_path):
    path = tmp_path / "run.md"
    path.write_text(_register(), encoding="utf-8")
    messages: list[str] = []
    apply_year_check(path, False, messages.append)
    assert path.read_text(encoding="utf-8").count("YEAR CHECK") == 7
    assert len(messages) == 1
    assert "7 entries on 3 image(s)" in messages[0]
    assert "IMG_187.jpg, IMG_191.jpg, IMG_192.jpg" in messages[0]
    assert not list(tmp_path.glob("*.tmp"))


def test_apply_year_check_leaves_a_clean_file_alone(tmp_path):
    path = tmp_path / "run.md"
    original = "".join(_record(f"{i}.jpg", 1799) for i in range(5))
    path.write_text(original, encoding="utf-8")
    messages: list[str] = []
    apply_year_check(path, False, messages.append)
    assert path.read_text(encoding="utf-8") == original
    assert messages == ["Year check: no entry's year is out of sequence with the surrounding images."]


def test_sampled_non_consecutive_pages_are_not_flagged():
    # A real San Mango run of pages 4, 5, 24 and 32: the years jump because
    # pages were skipped, not because anything was misread.
    text = _record("p4.jpg", 1768, 1768) + _record("p5.jpg", 1768) + _record("p24.jpg", 1776) + _record("p32.jpg", 1778)
    assert flag_year_outliers(text).flagged_entries == 0


def test_first_and_last_images_of_a_run_are_not_judged():
    text = _record("a.jpg", 1779) + "".join(_record(f"{i}.jpg", 1799) for i in range(4)) + _record("z.jpg", 1779)
    assert flag_year_outliers(text).flagged_entries == 0


def test_a_single_misread_entry_on_a_good_image_is_flagged():
    text = (
        _record("a.jpg", 1799, 1799) + _record("b.jpg", 1799, 1779, 1799) + _record("c.jpg", 1799, 1800)
    )
    result = flag_year_outliers(text)
    assert result.flagged_entries == 1
    assert result.flagged_images == ["b.jpg"]
