#!/usr/bin/env python3
"""Clean an indexer-corrected genealogy spreadsheet.

Rules
-----
1. Struck-through runs are deletions -> removed entirely.
2. Blue runs are the indexer's corrections.
   - Parenthesised correction replaces the immediately preceding word
     (or, in the Sponsor column when the correction contains a comma,
     the whole preceding "Surname, Given" entry).
   - A short lowercase fragment splices into the preceding word
     ("Cardo (i)" -> "Cardi", "Joseph" + "a" -> "Josepha").
   - A bare "(?)" carries no correction -> the name it marks is dropped.
3. All remaining question marks are deleted.
"""

import json
import re
import sys

import openpyxl
from openpyxl.cell.rich_text import CellRichText

BLUE = "FF0000FF"
SPONSOR_COL = "G"


# --------------------------------------------------------------------------
# 1. flatten rich text into (char, is_blue) after dropping struck runs
# --------------------------------------------------------------------------
def flatten(value):
    """Return list of [text, kind] segments.

    kind: 'n' plain, 'b' blue correction, 's' struck (text kept only so the
    caller knows a deletion happened at that spot).
    """
    segs = []
    for block in value:
        if isinstance(block, str):
            segs.append([block, "n"])
            continue
        font = block.font
        if font is not None and font.strike:
            segs.append([block.text, "s"])  # crossed out -> incorrect
            continue
        blue = (
            font is not None
            and font.color is not None
            and getattr(font.color, "rgb", None) == BLUE
        )
        segs.append([block.text, "b" if blue else "n"])
    merged = []
    for text, kind in segs:
        if merged and merged[-1][1] == kind:
            merged[-1][0] += text
        else:
            merged.append([text, kind])
    return merged


# --------------------------------------------------------------------------
# 2. helpers for editing the accumulated output
# --------------------------------------------------------------------------
PARTICLES = {"de", "di", "del", "della", "dello", "la", "le", "li", "lo", "da"}


def drop_preceding_word(text):
    """Remove the last whitespace-delimited word (keeps , and ; separators).

    A Sicilian surname particle ("de Sisto", "li Cassi") is taken with the
    word it belongs to, so "de Sisto (Vito)" yields "Vito", not "de Vito".
    """
    stripped = text.rstrip()
    m = re.search(r"[^\s,;]+\s*$", stripped)
    if not m:
        return text
    head = stripped[: m.start()]
    tail = re.search(r"[^\s,;]+\s*$", head.rstrip())
    if tail and tail.group(0).strip().lower() in PARTICLES:
        head = head.rstrip()[: tail.start()]
    return head


def drop_preceding_entry(text):
    """Remove everything back to the last ';' (a whole sponsor entry)."""
    idx = text.rfind(";")
    return text[: idx + 1] + " " if idx >= 0 else ""


def strip_wrappers(seg_text, prev_text):
    """Peel correction parentheses off a blue segment.

    Handles runs where the '(' landed in the black run and the ')' in the
    blue one, and unmatched parentheses left by the indexer.
    Returns (inner_text, was_parenthesised, new_prev_text).
    """
    parenthesised = False
    inner = seg_text

    # opening paren at the start of the blue run, possibly after a space
    lead = inner.lstrip()
    if lead.startswith("("):
        inner = lead[1:]
        parenthesised = True
    else:
        # opening paren trailing the preceding black run
        pt = prev_text.rstrip()
        if pt.endswith("("):
            prev_text = pt[:-1]
            parenthesised = True

    # closing paren at the end of the blue run
    tail = inner.rstrip()
    if tail.endswith(")"):
        inner = tail[:-1]
        parenthesised = True

    # stray unmatched parens left by the indexer, e.g. ")Scolastica Paola)"
    inner_stripped = inner.strip()
    if inner_stripped.startswith(")"):
        inner = inner_stripped[1:]
        parenthesised = True

    return inner, parenthesised, prev_text


DROP = "\x00"  # marks a sponsor entry to be deleted forward to the next ';'

ANNOTATION = re.compile(
    r"(?:^|[\s,;])(?:and\s+)?"
    r"(?:daughter|son|wife|husband|sister|brother)\s+of\b.*$"
    r"|[\s,]*\bdeceased\b\s*$",
    re.I,
)


def rest_text(segs, idx, col):
    """Name text still following segment idx within the same name.

    In the sponsor column a comma separates surname from given name, so it
    ends the run just as a semicolon ends the entry.
    """
    tail = ""
    for text, kind in segs[idx + 1:]:
        if kind == "s":
            continue
        tail += text
    tail = tail.split(";")[0]
    if col == SPONSOR_COL:
        tail = tail.split(",")[0]
    return tail.strip(" ,")


def strip_unmatched_parens(text):
    """Drop parentheses the indexer never balanced."""
    keep, stack = [True] * len(text), []
    for i, ch in enumerate(text):
        if ch == "(":
            stack.append(i)
        elif ch == ")":
            if stack:
                stack.pop()
            else:
                keep[i] = False
    for i in stack:
        keep[i] = False
    return "".join(c for c, k in zip(text, keep) if k)


def append(out, correction):
    """Add a correction, keeping a separator between it and what precedes."""
    if out and not out[-1].isspace() and out[-1] not in "(":
        out += " "
    return out + correction + " "


def tidy(text):
    """Final whitespace / punctuation normalisation."""
    text = re.sub(DROP + r"[^;]*;?", "", text)   # entries flagged for removal
    text = text.replace("?", "")
    text = re.sub(r"\(\s*\)", "", text)          # empty parens
    text = strip_unmatched_parens(text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,;])", r"\1", text)      # no space before , ;
    text = re.sub(r"([,;])(?=\S)", r"\1 ", text)  # one space after , ;
    text = re.sub(r"(^|;)\s*,\s*", r"\1 ", text)  # entry with no surname
    text = re.sub(r";\s*(?=;|$)", ";", text)      # empty entries
    text = text.strip(" ;,")
    # a cell that is nothing but a parenthesised name: keep the name
    m = re.fullmatch(r"\(([^()]+)\)", text.strip())
    if m:
        text = m.group(1)
    return text.strip()


# --------------------------------------------------------------------------
# 3. per-cell cleaning
# --------------------------------------------------------------------------
def clean_cell(value, col):
    """Return (cleaned_text, notes) for one cell."""
    notes = []
    if value is None:
        return None, notes
    if not isinstance(value, CellRichText):
        return tidy(str(value)), notes

    segs = flatten(value)
    out = ""
    struck_before = False  # a deletion sits immediately left of this point
    partial_word = False   # that deletion cut a word in half

    for idx, (text, kind) in enumerate(segs):
        if kind == "s":
            if not re.search(r"\w", text):
                # a struck comma or space is a selection artefact, not a
                # deleted name - keep the punctuation
                out += text
                continue
            struck_before = True
            # the strike started mid-word ("Bons|egna") -> the stem it leaves
            # behind belongs to the deleted name too
            partial_word = bool(out) and not out[-1].isspace() and text[:1].isalpha()
            continue
        if kind == "n":
            out += text
            if text.strip():
                struck_before = False
            continue

        inner, parenthesised, out = strip_wrappers(text, out)
        # an embedded "(?)" inside a longer correction is just uncertainty
        inner = re.sub(r"\(\s*\?\s*\)", " ", inner)
        correction = inner.replace("?", "").strip()

        # relationship notes ("daughter of the late ...") are commentary,
        # not name corrections
        if ANNOTATION.search(correction):
            stripped_note = ANNOTATION.sub("", correction).strip(" ,;")
            if not stripped_note:
                notes.append(f"removed annotation '{correction}'")
                struck_before = False
                continue
            notes.append(f"removed annotation from '{correction}'")
            correction = stripped_note

        # a splice only happens when the blue run really touches the word
        abuts = (
            bool(out) and not out[-1].isspace() and not text[:1].isspace()
        )
        replaces_deletion = struck_before
        struck_before = False
        # more name text follows in this entry -> the blue text was inserted,
        # not substituted for what precedes it
        followed_by_name = bool(rest_text(segs, idx, col))

        if not correction:
            # bare "(?)" -> indexer could not read the name: drop it
            if col == SPONSOR_COL:
                out = drop_preceding_entry(out) + DROP
            else:
                out = drop_preceding_word(out)
            notes.append("dropped name flagged (?)")
            continue

        if replaces_deletion:
            # the crossed-out text is already gone; nothing else to remove
            if partial_word and parenthesised:
                out = drop_preceding_word(out)  # "Bons|egna (Bona...)" -> "Bona..."
                notes.append("removed stem of partly crossed-out word")
            elif partial_word:
                # "Vit|us" + "ono" -> "Vitono": the correction fixes an ending
                partial_word = False
                out += correction
                notes.append("re-ending of partly crossed-out word")
                continue
            partial_word = False
            out = append(out, correction)
            notes.append("correction replaces crossed-out text")
            continue
        partial_word = False

        if not parenthesised and abuts:
            # sub-word insertion: "Joseph" + "a" -> "Josepha"
            out += correction
            notes.append(f"spliced fragment '{correction}'")
            continue

        if not parenthesised:
            if followed_by_name:
                # blue text sits between two black names -> an insertion
                out = append(out, correction)
                notes.append("REVIEW: unbracketed correction treated as an insertion")
                continue
            notes.append("REVIEW: unbracketed correction replaced preceding word")

        if parenthesised and abuts:
            # "Cosumano" + " (Biledo)" style: paren correction, normal replace
            out = drop_preceding_word(out)
            out = append(out, correction)
            continue

        if parenthesised and len(correction) <= 2 and correction.islower():
            # "Cardo (i)" -> "Cardi": fragment replaces the word's tail
            stripped = out.rstrip()
            m = re.search(r"[^\s,;]+$", stripped)
            if m:
                word = m.group(0)
                new = word[: max(1, len(word) - len(correction))] + correction
                out = stripped[: m.start()] + new + " "
                notes.append(f"spliced fragment '{correction}' into '{word}'")
                continue

        if col == SPONSOR_COL and "," in correction:
            out = drop_preceding_entry(out)
        else:
            out = drop_preceding_word(out)
        out = append(out, correction)

    return tidy(out), notes


# --------------------------------------------------------------------------
def main(src, dst, report):
    wb = openpyxl.load_workbook(src, rich_text=True)
    ws = wb["Battesimi"]

    out_wb = openpyxl.Workbook()
    out_ws = out_wb.active
    out_ws.title = "Battesimi"

    headers = [c.value for c in ws[1]]
    out_ws.append(headers)

    changes = []
    for row in ws.iter_rows(min_row=2):
        vals = []
        for cell in row:
            col = cell.column_letter
            original = cell.value
            cleaned, notes = clean_cell(original, col)
            vals.append(cleaned)
            if isinstance(original, CellRichText):
                raw = "".join(
                    b if isinstance(b, str) else b.text for b in original
                )
                changes.append(
                    {
                        "cell": cell.coordinate,
                        "column": headers[cell.column - 1],
                        "original": raw,
                        "cleaned": cleaned,
                        "notes": "; ".join(notes),
                    }
                )
        out_ws.append(vals)

    for col, width in zip("ABCDEFG", [26, 22, 22, 22, 22, 22, 60]):
        out_ws.column_dimensions[col].width = width
    out_ws.freeze_panes = "A2"

    # second sheet: the judgement calls, so they can be checked by eye
    rev = out_wb.create_sheet("Review")
    rev.append(["Cell", "Column", "As transcribed", "Cleaned", "Why flagged"])
    for ch in changes:
        if "REVIEW" in ch["notes"] or "dropped name flagged" in ch["notes"]:
            rev.append(
                [ch["cell"], ch["column"], ch["original"], ch["cleaned"], ch["notes"]]
            )
    for col, width in zip("ABCDE", [8, 14, 55, 45, 50]):
        rev.column_dimensions[col].width = width
    rev.freeze_panes = "A2"

    out_wb.save(dst)

    with open(report, "w", encoding="utf-8") as fh:
        json.dump(changes, fh, ensure_ascii=False, indent=1)

    print(f"rows: {ws.max_row - 1}  edited cells: {len(changes)}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
