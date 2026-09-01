#!/usr/bin/env python3
"""Regression test: does a model transcription still parse into correct rows?

Runs a fixture through the app's own paragraph merger (customizable_transcription/core.py)
and then through the real baptism-parser.js under Node, exactly as the browser
would. Catches the failure mode where a prompt change quietly empties spreadsheet
columns while the DOCX still looks fine.

    python3 xls_conversion/tests/run_parser_test.py

Requires node on PATH. No network, no API key.
"""

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# The row every fixture entry must produce. Compare against the transcription in
# fixture-expected-format.md if one of these ever fails.
#
# Child surname (fixed — was a tracked gap): Section 3's entry heading used to
# be a fabricated "Page N - Entry n: Surname, Given Names" line that
# baptism-parser.js's parseChild() read the child's surname from (via the
# titleName parameter). That heading was replaced with a pure locator plus a
# verbatim "Marginal Heading:" block (see CLAUDE.md "Chiusa Sclafani battesimi
# — decisions"), so titleName went permanently empty and Child regressed to
# given-names-only.
#
# Fixed via parseChildSurnameFromHeading() + childSurname() in
# baptism-parser.js: parses the Marginal Heading's own "et <mother>" clause
# structurally (token count after stripping a trailing "jug."/"conj." — not a
# naive "last token after et" positional guess, which is unsafe here — entry
# 6 (Collica) has the surname trailing the FATHER before "et" in the heading,
# not the mother after it, unlike entry 1 (Manfre)). When the heading itself
# doesn't state a trailing surname (entry 6's "...et Rosae jug." has nothing
# left after stripping "jug." but the mother's bare given name), falls back
# to whichever parent's own already-parsed name has one — father first, then
# mother, since entry 6's own body attaches "Collica" to the mother instead
# of the father, so trying both recovers it either way.
#
# Entries 2 and 7 still come back Child: "" — a separate, still-open gap: the
# English translation has no "was given the name X" clause to read a given
# name from at all (entry 2: no naming formula in the body; entry 7: the name
# is "[illegible]" in the body). Not what this fix addresses.
EXPECTED = {
    "1": {"Year": "1752", "Date": "23 September", "Child": "Manfre, Filippa Maria",
          "Child's Father": "Josephus", "Child's Mother": "Manfre, Anna Maria",
          "Godparent 1": "Guagliano, Josephus"},
    "2": {"Year": "1752", "Date": "24 September", "Child": "",
          "Child's Father": "Franciscus", "Child's Mother": "Chiantella, Francisca",
          "Godparent 1": ""},
    "3": {"Year": "1752", "Date": "26 September",
          "Child": "de Chiara, Vincentius Hiacynthus Josephus",
          "Child's Father": "Stephanus", "Child's Mother": "de Chiara, Antonia",
          "Godparent 1": "Ragusa, Cajetanus", "Godparent 2": "Creddo, Rosa"},
    "5": {"Year": "1752", "Date": "3 October", "Child": "Giordano, Franciscus Blasius",
          "Child's Father": "Petrus", "Child's Mother": "Giordano, Rosaria",
          "Godparent 1": "Vernaci, Francius", "Godparent 2": "Vernaci, Anna Maria"},
    "6": {"Year": "1752", "Date": "7 October",
          "Child": "Collica, Rosarius Marianus Archangelus",
          "Child's Father": "Joachimus", "Child's Mother": "Collica, Rosa",
          "Godparent 1": "Cusenza, Franciscus"},
    "7": {"Year": "1752", "Date": "8 October", "Child": "",
          "Child's Father": "Ignatius", "Child's Mother": "Collura, Antonina",
          "Godparent 1": "Genduza, Crispinus"},
}


def load_core_helpers():
    """Import core.py's text helpers without pulling in the genai dependency."""
    src = (REPO / "customizable_transcription" / "core.py").read_text(encoding="utf-8")
    ns = {"re": re}
    wanted = {"collapse_source_line_breaks", "strip_model_record_headers",
              "render_entry"}
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            exec(compile(ast.Module([node], []), "<core>", "exec"), ns)
    return ns


def parse(markdown_text):
    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8",
                                     delete=False) as fh:
        fh.write(markdown_text)
        tmp = fh.name
    try:
        out = subprocess.run(
            ["node", str(HERE / "harness.js"), tmp],
            capture_output=True, text=True, check=True,
        )
    finally:
        os.unlink(tmp)
    return json.loads(out.stdout)


def main():
    ns = load_core_helpers()
    fixture = (HERE / "fixture-expected-format.md").read_text(encoding="utf-8")
    model_output = fixture.split("--- START OF RECORD:", 1)[1].split("---", 1)[1].strip()
    processed = ns["render_entry"]("Chiusa Sclafani Battesimi_176.jpg", model_output)
    result = parse("# Transcription Output\n\n" + processed)

    rows = {r["Record #"]: r for r in result["rows"]}
    failures = []
    for rec, expected in EXPECTED.items():
        row = rows.get(rec)
        if row is None:
            failures.append(f"entry {rec}: no row produced")
            continue
        for field, want in expected.items():
            got = row.get(field, "")
            if got != want:
                failures.append(f"entry {rec} {field}: expected {want!r}, got {got!r}")

    if result["exceptionLog"]:
        failures.append(f"parser exceptions: {result['exceptionLog']}")

    # control: the pre-v3 phrasings must still fail, or the guard rails are gone
    legacy = (HERE / "fixture-legacy-phrasings.md").read_text(encoding="utf-8")
    legacy_rows = parse(legacy)["rows"]
    if legacy_rows and legacy_rows[0].get("Godparent 1"):
        failures.append(
            "control fixture parsed godparents — the legacy phrasings should NOT work; "
            "baptism-parser.js may have changed"
        )

    # regression: a "wife of"/"husband of" aside inside a multi-godparent entry
    # used to discard the real godparents and return [name, spouse] instead
    # (see CLAUDE.md "Known bug", parseGodparents in baptism-parser.js).
    spouse_clause = (HERE / "fixture-godparent-spouse-clause.md").read_text(encoding="utf-8")
    spouse_rows = parse(spouse_clause)["rows"]
    if not spouse_rows:
        failures.append("godparent-spouse-clause fixture: no row produced")
    else:
        row = spouse_rows[0]
        want = {"Godparent 1": "Ragusa, Cajetanus", "Godparent 2": "Creddo, Rosa"}
        for field, expected in want.items():
            got = row.get(field, "")
            if got != expected:
                failures.append(
                    f"godparent-spouse-clause {field}: expected {expected!r}, got {got!r}"
                )

    # regression: a bracketed, honestly-flagged uncertain parent surname
    # ("to the spouses Nicolaus and Anna [de Pocopila?]") used to fail the
    # whole pattern and drop BOTH parents, even the legible one.
    bracketed_parent = (HERE / "fixture-bracketed-parent-name.md").read_text(encoding="utf-8")
    bracketed_rows = parse(bracketed_parent)["rows"]
    if not bracketed_rows:
        failures.append("bracketed-parent-name fixture: no row produced")
    else:
        row = bracketed_rows[0]
        want = {"Child's Father": "Nicolaus", "Child's Mother": "[de Pocopila?], Anna"}
        for field, expected in want.items():
            got = row.get(field, "")
            if got != expected:
                failures.append(
                    f"bracketed-parent-name {field}: expected {expected!r}, got {got!r}"
                )

    # regression: a stray honorific ("Doctor") left inside a godparent clause
    # used to leak straight into the spreadsheet cell ("Calsi, Doctor Carolus")
    # because cleanName only stripped Don/Master and a handful of others.
    stray_title = (HERE / "fixture-godparent-stray-title.md").read_text(encoding="utf-8")
    stray_title_rows = parse(stray_title)["rows"]
    if not stray_title_rows:
        failures.append("godparent-stray-title fixture: no row produced")
    else:
        row = stray_title_rows[0]
        want = {"Godparent 1": "Calsi, Carolus", "Godparent 2": "di Bello, Rosalia"}
        for field, expected in want.items():
            got = row.get(field, "")
            if got != expected:
                failures.append(
                    f"godparent-stray-title {field}: expected {expected!r}, got {got!r}"
                )

    # regression: the "Page <N> - Entry <n>:" heading must not break entry
    # splitting/record numbering, must extract a different Page # per column
    # within the same image, and must preserve an honestly-flagged illegible
    # page number rather than guessing it from the sequence.
    page_number = (HERE / "fixture-page-number.md").read_text(encoding="utf-8")
    page_number_rows = parse(page_number)["rows"]
    if len(page_number_rows) != 3:
        failures.append(f"page-number fixture: expected 3 rows, got {len(page_number_rows)}")
    else:
        want_pages = {"1": "34", "2": "35", "3": "[illegible]"}
        for row in page_number_rows:
            rec = row.get("Record #", "")
            expected = want_pages.get(rec)
            got = row.get("Page #", "")
            if got != expected:
                failures.append(f"page-number record {rec} Page #: expected {expected!r}, got {got!r}")

    if failures:
        print(f"FAIL ({len(failures)})")
        for f in failures:
            print("  -", f)
        return 1
    print(f"PASS — {len(EXPECTED)} entries parsed, all fields correct, no exceptions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
