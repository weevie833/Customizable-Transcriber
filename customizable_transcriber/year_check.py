"""Year check: flag entries whose year is out of sequence with the images
around them.

The model reads each image on its own and never sees its neighbours' years,
so a misread digit (a real run read 1799 as 1779 and 1800 as 1780 on three
images) goes unnoticed even when every image around it carries the right
century. Registers are kept in date order, so a year far from the years on
the surrounding images is almost always a misreading.

This only flags. It never changes a year: loose or misbound leaves really can
be out of order, and the indexer has to look at the manuscript to decide. The
flag goes on the entry's Notes line, so it reaches the DOCX and the XLSX
Notes column, and the run log gets one summary line.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

# How many images either side of an image are compared with it (the nearest
# ones that have a year and haven't been set aside as misread).
WINDOW = 3
# A misread tens digit is always at least 10 years off.
MIN_DIFFERENCE_YEARS = 10
# Neighbouring images (with at least one year each) needed before judging.
MIN_NEIGHBOUR_IMAGES = 2

_RECORD_RE = re.compile(r"^--- START OF RECORD: (.+?) ---$")
_DATE_LINE_RE = re.compile(r"^\s*(?:Date|Data)\s*:", re.IGNORECASE)
_NOTES_LINE_RE = re.compile(r"^\s*Notes\s*:", re.IGNORECASE)
_TRANSCRIPTION_LABEL_RE = re.compile(r"^\s*(?:.+?\s+Transcription|Trascrizione in .+?)\s*:", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")
_BRACKET_RE = re.compile(r"\[([^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*)\]")


@dataclass
class _Record:
    name: str
    start: int  # line index of the START OF RECORD line
    end: int  # exclusive
    dates: list[tuple[int, int]] = field(default_factory=list)  # (Date line index, year)

    def median_year(self) -> float | None:
        years = [year for _, year in self.dates]
        return statistics.median(years) if years else None


def year_from_date_line(line: str) -> int | None:
    """The year of a `Date: <as written> [<day> <Month> <year>]` line: taken
    from the standard bracketed form when there is one (the as-written part
    may spell the year out in words), else the last year in the line."""
    for content in reversed(_BRACKET_RE.findall(line)):
        years = _YEAR_RE.findall(content)
        if years:
            return int(years[-1])
    years = _YEAR_RE.findall(line)
    return int(years[-1]) if years else None


def _parse(lines: list[str]) -> list[_Record]:
    records: list[_Record] = []
    for index, line in enumerate(lines):
        match = _RECORD_RE.match(line.strip())
        if match:
            if records:
                records[-1].end = index
            records.append(_Record(match.group(1), index, len(lines)))
        elif records and _DATE_LINE_RE.match(line):
            year = year_from_date_line(line)
            if year is not None:
                records[-1].dates.append((index, year))
    return records


def year_check_note(year: int, around: int) -> str:
    return (
        f"YEAR CHECK -- this entry's year ({year}) does not fit the years on the surrounding images "
        f"(around {around}). Check the year against the manuscript."
    )


def _add_note(lines: list[str], date_index: int, end: int, note: str) -> int:
    """Append `note` to the entry's Notes line, or add one right after its
    Date line. Returns how many lines were inserted."""
    for index in range(date_index + 1, end):
        line = lines[index]
        if _DATE_LINE_RE.match(line) or _TRANSCRIPTION_LABEL_RE.match(line):
            break
        if _NOTES_LINE_RE.match(line):
            lines[index] = line.rstrip() + " " + note
            return 0
    lines[date_index + 1:date_index + 1] = ["", f"Notes: {note}"]
    return 2


@dataclass
class YearCheckResult:
    text: str
    flagged_entries: int
    flagged_images: list[str]


def _reference_year(
    reading: list[_Record], position: int, excluded: set[int], require_consistent: bool = False
) -> int | None:
    """Typical year of the nearest images either side of `position` (up to
    WINDOW each side, skipping excluded images and images with no year).

    None when there isn't an image with a year on BOTH sides (the first and
    last images of a run can't be judged: a run of non-consecutive pages
    can jump years at its ends), or, with require_consistent, when those
    neighbours themselves span MIN_DIFFERENCE_YEARS or more -- then the
    images aren't a continuous stretch of one register and nothing can be
    said about the image between them."""
    years: list[float] = []
    for step in (-1, 1):
        found = 0
        other = position + step
        while 0 <= other < len(reading) and found < WINDOW:
            year = reading[other].median_year()
            if other not in excluded and year is not None:
                years.append(year)
                found += 1
            other += step
        if not found:
            return None
    if len(years) < MIN_NEIGHBOUR_IMAGES:
        return None
    if require_consistent and max(years) - min(years) >= MIN_DIFFERENCE_YEARS:
        return None
    return round(statistics.median(years))


def flag_year_outliers(text: str, reverse_order: bool = False) -> YearCheckResult:
    """Flag every entry whose year is MIN_DIFFERENCE_YEARS or more from the
    typical year of the nearest images either side (in reading order). The
    first and last images of a run are never judged; see _reference_year().

    Bad images are set aside one at a time, worst first, before anything is
    judged, so a cluster of misread images close together (the real case
    had three within five images) can't drag the reference year for the
    good images between them."""
    lines = text.split("\n")
    records = _parse(lines)
    reading = list(reversed(records)) if reverse_order else records

    excluded: set[int] = set()
    while True:
        worst: tuple[float, int] | None = None
        for position, record in enumerate(reading):
            year = record.median_year()
            if position in excluded or year is None:
                continue
            around = _reference_year(reading, position, excluded)
            if around is None:
                continue
            gap = abs(year - around)
            if gap >= MIN_DIFFERENCE_YEARS and (worst is None or gap > worst[0]):
                worst = (gap, position)
        if worst is None:
            break
        excluded.add(worst[1])

    to_flag: list[tuple[_Record, int, int, int]] = []  # (record, date line, year, around)
    for position, record in enumerate(reading):
        around = _reference_year(reading, position, excluded, require_consistent=True)
        if around is None:
            continue
        for date_index, year in record.dates:
            if abs(year - around) >= MIN_DIFFERENCE_YEARS:
                to_flag.append((record, date_index, year, around))

    # Insert from the bottom up so earlier line indexes stay valid.
    for record, date_index, year, around in sorted(to_flag, key=lambda item: item[1], reverse=True):
        _add_note(lines, date_index, record.end, year_check_note(year, around))

    flagged_names = [record.name for record in reading if any(item[0] is record for item in to_flag)]
    return YearCheckResult("\n".join(lines), len(to_flag), flagged_names)


def apply_year_check(markdown_file: Path, reverse_order: bool, log) -> None:
    """Run the check over a finished transcript file in place and log one line."""
    if not markdown_file.exists():
        return
    result = flag_year_outliers(markdown_file.read_text(encoding="utf-8"), reverse_order)
    if not result.flagged_entries:
        log("Year check: no entry's year is out of sequence with the surrounding images.")
        return
    temp = markdown_file.with_name(markdown_file.name + ".tmp")
    temp.write_text(result.text, encoding="utf-8")
    temp.replace(markdown_file)
    entries = "entry" if result.flagged_entries == 1 else "entries"
    images = ", ".join(result.flagged_images)
    log(
        f"Year check: {result.flagged_entries} {entries} on {len(result.flagged_images)} image(s) have a year "
        f"out of sequence with the surrounding images ({images}). Each is flagged on its Notes line -- "
        "check those years against the manuscript."
    )
