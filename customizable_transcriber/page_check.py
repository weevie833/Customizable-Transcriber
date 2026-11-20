"""Page check: flag page numbers that don't fit the page numbers on the
images around them, and suggest one where the page number was illegible.

The model reads each image on its own, so a misread page number (a real run
read pages 4, 5, 6 as 4, 9, 6) goes unnoticed. Consecutive photos of one
register advance by a fixed number of pages per image: 1 for one page per
photo (or a register numbered by leaf), 2 for two facing pages. An image's
page numbers are checked against the progression its neighbours form.

Like the year check (year_check.py), this only flags. It never changes a
page number: missing photos or misbound leaves really do break the
sequence, and the indexer has to look at the manuscript. The flag goes on
the entry's Notes line, so it reaches the DOCX and the XLSX Notes column,
and the run log gets one summary line.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from customizable_transcriber.year_check import _DATE_LINE_RE, _NOTES_LINE_RE, _RECORD_RE, _TRANSCRIPTION_LABEL_RE

# How many images either side are used to build the expected progression
# (the nearest ones that have a readable page number).
WINDOW = 3
# Pages advanced per image: one page per photo, or two facing pages.
ALLOWED_STEPS = (1, 2)

# "Page 34:", "Page 34 - Entry 1: ...", "Page [illegible]:"
_LOCATOR_RE = re.compile(r"^\s*Page\s+(\d+|\[[^\]]*\])", re.IGNORECASE)


@dataclass
class _Entry:
    line: int  # index of the locator line
    page: int | None  # None when the page number isn't a plain number


@dataclass
class _Record:
    name: str
    start: int
    end: int  # exclusive
    entries: list[_Entry] = field(default_factory=list)

    def pages(self) -> list[int]:
        return [entry.page for entry in self.entries if entry.page is not None]

    def first_page(self) -> int | None:
        pages = self.pages()
        return min(pages) if pages else None


def _parse(lines: list[str]) -> list[_Record]:
    records: list[_Record] = []
    for index, line in enumerate(lines):
        match = _RECORD_RE.match(line.strip())
        if match:
            if records:
                records[-1].end = index
            records.append(_Record(match.group(1), index, len(lines)))
            continue
        if not records:
            continue
        locator = _LOCATOR_RE.match(line)
        if locator:
            value = locator.group(1)
            records[-1].entries.append(_Entry(index, int(value) if value.isdigit() else None))
    return records


@dataclass
class _Expectation:
    first: int  # expected first page on the image
    step: int  # pages per image

    def pages_text(self) -> str:
        if self.step == 1:
            return f"page {self.first}"
        return f"pages {self.first}-{self.first + self.step - 1}"

    def accepts(self, page: int) -> bool:
        return self.first <= page <= self.first + self.step - 1


def _expectations(reading: list[_Record], position: int, excluded: set[int]) -> list[_Expectation]:
    """Every expected page range for `position` implied by a pair of
    neighbours (up to WINDOW readable images each side) whose own first
    pages advance by a whole ALLOWED_STEPS number of pages per image. A
    pair that doesn't (a gap in the photos, a non-consecutive sample, a
    misread neighbour) says nothing."""
    sides: list[list[tuple[int, int]]] = []
    for direction in (-1, 1):
        found: list[tuple[int, int]] = []
        other = position + direction
        while 0 <= other < len(reading) and len(found) < WINDOW:
            page = reading[other].first_page()
            if other not in excluded and page is not None:
                found.append((other, page))
            other += direction
        if not found:
            return []
        sides.append(found)
    result: list[_Expectation] = []
    for before, before_page in sides[0]:
        for after, after_page in sides[1]:
            span = after - before
            difference = after_page - before_page
            if difference % span:
                continue
            step = difference // span
            if step not in ALLOWED_STEPS:
                continue
            result.append(_Expectation(before_page + step * (position - before), step))
    return result


def _best(expectations: list[_Expectation]) -> _Expectation:
    counts = Counter((item.first, item.step) for item in expectations)
    (first, step), _ = counts.most_common(1)[0]
    return _Expectation(first, step)


def page_check_note(page: int, expectation: _Expectation) -> str:
    return (
        f"PAGE CHECK -- this entry's page number ({page}) does not fit the page numbers on the surrounding "
        f"images (expected {expectation.pages_text()}). Check the page number against the manuscript."
    )


def page_suggestion_note(expectation: _Expectation) -> str:
    return (
        f"PAGE CHECK -- the page number is illegible; the surrounding images suggest {expectation.pages_text()}. "
        "Check the page number against the manuscript."
    )


def _add_note(lines: list[str], locator: int, end: int, note: str) -> None:
    """Append `note` to the entry's Notes line, or add one after its Date
    line (or its locator line when it has no Date line)."""
    anchor = locator
    for index in range(locator + 1, end):
        line = lines[index]
        if _LOCATOR_RE.match(line) or _TRANSCRIPTION_LABEL_RE.match(line):
            break
        if _NOTES_LINE_RE.match(line):
            lines[index] = line.rstrip() + " " + note
            return
        if _DATE_LINE_RE.match(line):
            anchor = index
    lines[anchor + 1:anchor + 1] = ["", f"Notes: {note}"]


@dataclass
class PageCheckResult:
    text: str
    flagged_entries: int
    flagged_images: list[str]
    suggested_entries: int
    suggested_images: list[str]
    judged_images: int = 0


def check_page_numbers(text: str, reverse_order: bool = False) -> PageCheckResult:
    """Flag entries whose page number fits none of the progressions their
    neighbours form, and suggest a page for entries whose page number is
    illegible. The first and last images of a run are never judged.

    Misread images are set aside one at a time before judging (the one
    furthest from its expected page first), so a misread image can't
    spoil the expectation for the images next to it."""
    lines = text.split("\n")
    records = _parse(lines)
    reading = list(reversed(records)) if reverse_order else records

    def misfit(position: int, excluded: set[int]) -> tuple[int, _Expectation] | None:
        pages = reading[position].pages()
        if not pages:
            return None
        expectations = _expectations(reading, position, excluded)
        if not expectations or any(item.accepts(page) for item in expectations for page in pages):
            return None
        best = _best(expectations)
        return min(abs(page - best.first) for page in pages), best

    excluded: set[int] = set()
    while True:
        worst: tuple[int, int] | None = None
        for position in range(len(reading)):
            if position in excluded:
                continue
            found = misfit(position, excluded)
            if found and (worst is None or found[0] > worst[0]):
                worst = (found[0], position)
        if worst is None:
            break
        excluded.add(worst[1])

    notes: list[tuple[int, int, str]] = []  # (locator line, record end, note)
    flagged: list[str] = []
    suggested: list[str] = []
    flagged_count = suggested_count = judged = 0
    for position, record in enumerate(reading):
        others = excluded - {position}
        expectations = _expectations(reading, position, others)
        if not expectations:
            continue
        best = _best(expectations)
        if record.pages():
            judged += 1
            # Every entry whose page fits no expectation: the whole image when
            # it was set aside, or a single misread entry on a good image.
            misfits = [
                entry for entry in record.entries
                if entry.page is not None and not any(item.accepts(entry.page) for item in expectations)
            ]
            for entry in misfits:
                notes.append((entry.line, record.end, page_check_note(entry.page, best)))
                flagged_count += 1
            if misfits:
                flagged.append(record.name)
        elif record.entries:
            for entry in record.entries:
                notes.append((entry.line, record.end, page_suggestion_note(best)))
                suggested_count += 1
            suggested.append(record.name)

    # Insert from the bottom up so earlier line indexes stay valid.
    for locator, end, note in sorted(notes, key=lambda item: item[0], reverse=True):
        _add_note(lines, locator, end, note)

    order = {record.name: index for index, record in enumerate(records)}
    return PageCheckResult(
        "\n".join(lines),
        flagged_count,
        sorted(flagged, key=order.get),
        suggested_count,
        sorted(suggested, key=order.get),
        judged,
    )


def apply_page_check(markdown_file: Path, reverse_order: bool, log) -> None:
    """Run the check over a finished transcript file in place and log one line."""
    if not markdown_file.exists():
        return
    result = check_page_numbers(markdown_file.read_text(encoding="utf-8"), reverse_order)
    if not result.flagged_entries and not result.suggested_entries:
        if result.judged_images:
            log("Page check passed: every page number fits with the surrounding images.")
        return
    temp = markdown_file.with_name(markdown_file.name + ".tmp")
    temp.write_text(result.text, encoding="utf-8")
    temp.replace(markdown_file)
    if result.flagged_entries:
        entries = "entry" if result.flagged_entries == 1 else "entries"
        log(
            f"Page check: {result.flagged_entries} {entries} on {len(result.flagged_images)} image(s) have a page "
            f"number that doesn't fit the surrounding images ({', '.join(result.flagged_images)}). Each is flagged "
            "on its Notes line -- check those page numbers against the manuscript."
        )
    if result.suggested_entries:
        entries = "entry" if result.suggested_entries == 1 else "entries"
        log(
            f"Page check: suggested a page number for {result.suggested_entries} {entries} with an illegible page "
            f"number on {len(result.suggested_images)} image(s) ({', '.join(result.suggested_images)}), on each "
            "entry's Notes line."
        )
