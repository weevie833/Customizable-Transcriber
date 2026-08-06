# Transcription Bot — working context

Local Python web app that sends archival page images to Gemini, writes a plain-text
transcription, and exports `.docx`. A separate browser tool then converts that text
into a spreadsheet for a human indexer.

Launch: `cd "/Users/stevecovello/Documents/Codex/Transcription Bot" && .venv/bin/python app.py`
→ http://127.0.0.1:8765

See `HANDOFF.md` for app/UI state. **Do not commit or push without being asked.**

## The pipeline, and who reads what

1. **Gemini → text.** Prompt comes from a profile in `profiles/`. Temperature is
   pinned to 0 in `transcription_bot/core.py`'s `transcribe_image` — the prompt
   asked for this from the start but the code didn't actually set it until this
   was caught and fixed.
2. **`transcription_bot/core.py` → `.md` / `.docx`.** `render_entry` strips any
   model-emitted `--- START OF RECORD ---`, then `collapse_source_line_breaks`
   merges consecutive lines into paragraphs, then `write_docx` writes each line as
   a Word paragraph. **There is no parser here** — whatever the model emits lands
   in the DOCX verbatim. JSON output produces a DOCX full of raw JSON.
3. **XLS conversion — two separate implementations exist. Only one is live.**
   - **`xls_conversion/ai_parser.py` is what the app actually runs.** The
     `/xls-conversion` page's `app.js` calls `/api/xls-conversion/parse` and
     `/preflight`, which call `parse_records_with_ai`/`preflight_records_with_ai`
     in this file. It makes its own Gemini call to turn the transcription text
     into the full official template schema (`Page #`, `Image #`, split
     Year/Month/Day ×2, Given/Last Name ×3, Gender, Sponsor(s), Notes — matching
     `Church Baptism Record Index - Template.xlsx`). Its extraction is semantic,
     not regex: the system prompt describes each field in natural language and
     Gemini fills it in, which is more tolerant of phrasing drift than a regex
     parser but also non-deterministic and unauditable line-by-line.
   - **`xls_conversion/baptism-parser.js` is not loaded anywhere in the live
     UI** — `index.html` only loads `app.js`. It's a deterministic regex parser
     against the exact English phrasings below, reachable today only through
     `xls_conversion/tests/harness.js` / `run_parser_test.py`. It's still useful
     as a fast, free, offline regression check of the transcription prompt's
     format compliance (no API key, no cost, exact pass/fail), and its bugs are
     worth fixing since a static, inspectable contract catches things an AI
     extractor's silent misreads won't — but it is not what runs when you click
     through `/xls-conversion` in the browser. Don't assume a `baptism-parser.js`
     fix changed what the live tool does; it didn't. `matrimony-parser.js` and
     `morti-parser.js` are the same kind of orphaned-but-reference-worthy code.

## The parser contract (this is what breaks silently in `baptism-parser.js`)

Get one of these wrong and the DOCX still looks perfect while spreadsheet columns
come back empty in the (offline, test-only) regex parser. `ai_parser.py`'s
semantic extraction is far more tolerant of phrasing drift, but the transcription
prompt still targets these exact phrasings for both parsers' sake, and because
they're what the regression suite checks.

| Field | Required phrasing | What fails |
|---|---|---|
| Date | `On the 23rd day of September 1752.` | Omitting the year blanks the Year column |
| Parents | `to the spouses X and Y` | "married couple" matches nothing |
| Child | `was given the name X.` | "upon whom was imposed the name" matches nothing |
| Godparents | `The godfather was X; the godmother was Y.` | "The godparents were X and Y" matches nothing |
| Page number | `Page 34 - Entry 1: ...` | Missing entirely blanks Page # for every entry |

Structural requirements, equally load-bearing:

- **Blank line between every block.** Without them `collapse_source_line_breaks`
  welds the `Entry N:` heading onto the `Date:` line and the whole merged string
  lands in the Child column.
- **Latin and English each on ONE unbroken line.** A line break inside the English
  truncates the parse at that point.
- **`Notes:` must come before `Latin Transcription:`.** Anything after the English
  translation gets swallowed into it. Verified safe in that position even with
  adversarial content ("Entry 2 below", "The godfather was…", "23:").
- **Entry numbers restart per image, not per page.** The prompt says so
  explicitly, but Gemini has been observed restarting at 1 when crossing from
  the left page to the right page within one image (image 194: `Page 36 -
  Entry 1..4`, then `Page 37 - Entry 1..3` instead of continuing `5..7`).
  Harmless for `ai_parser.py`'s schema (no Record # column), but would confuse
  `baptism-parser.js`'s `Record #` column if that were ever wired back in. Not
  yet worth a prompt fix — watch for recurrence.

Run `python3 xls_conversion/tests/run_parser_test.py` after any prompt change.
It pushes fixtures through the real `core.py` helpers and the real
`baptism-parser.js` under Node, and asserts every case produces correct rows.
Node required; no API key. This only exercises the offline regex parser — it
cannot validate `ai_parser.py`, which needs a real Gemini call to test.

## Fixed bugs — `xls_conversion/baptism-parser.js`

(Regex parser only. Not yet confirmed whether `ai_parser.py` has equivalent
failure modes — it's semantic, not regex, so these specific bugs likely don't
translate directly, but its behavior on edge cases hasn't been audited.)

- **Godparent spouse clause.** `parseGodparents`: a "wife of"/"husband of" aside
  inside one clause, combined with 2+ godparent clauses, used to discard the
  real godparents and return `[name, spouse]` — inventing a phantom godparent.
  Fixed: with 2+ clauses, each keeps only its own name. Fixture:
  `fixture-godparent-spouse-clause.md`.
- **Bracketed uncertain parent names.** `parseParents`: an honestly-flagged
  uncertain surname like `[de Pocopila?]` used to fail the whole "to the
  spouses X and Y" regex (character class didn't allow `[`, `]`, `?`) and drop
  **both** parents, even the legible one. Fixed the character class and a
  downstream surname-prefix check. Fixture: `fixture-bracketed-parent-name.md`.
- **Stray honorific in godparent clause.** A title beyond Don/Master (e.g.
  "Doctor") left inside the clause instead of moved to Notes used to leak
  straight into the spreadsheet cell (`Calsi, Doctor Carolus`). `cleanName` now
  strips Doctor/Dr/Reverend/Rev/Signor/Signora/Sir defensively too. Fixture:
  `fixture-godparent-stray-title.md`.
- **Page number extraction.** Added support for the `Page <N> - Entry <n>:`
  heading (`parsePageNumber`, new `Page #` column, `entryHeadingPattern` now
  accepts the optional page prefix). Handles a different page number per
  column within one image and an honestly-flagged `[illegible]` page number.
  Fixture: `fixture-page-number.md`.

## Chiusa Sclafani battesimi — decisions

Active profile: `profiles/chiusa-sclafani-battesimi-v3.json`. Rebuild it, don't
hand-edit:

```bash
cd prompts/chiusa-sclafani && python3 build_prompt.py
```

**Known footgun: the browser can silently revert this file.** The app embeds a
JS snapshot of a profile's fields when the page renders; re-selecting the
profile from the dropdown repopulates from *that snapshot*, not a fresh fetch.
If the boxes match the tab's own stale baseline, the app treats the run as
"unchanged" and can write that stale snapshot back over a freshly-rebuilt file
— this actually happened mid-session (rebuilt profile → user ran from a
not-reloaded tab → file got overwritten with a 3-fixes-behind version,
confirmed by matching mtimes). **After every `build_prompt.py` rebuild, do a
real browser reload (Cmd+R), not just a dropdown re-select, before running.**

Editorial rules, each of which someone will be tempted to "improve" — don't:

- **Never copy a surname between parents, or from the child to the father.**
  Measured against the verified index: 341/349 rows match but 8 do not, plus 13
  with no father's surname. The exceptions are spelling variants
  (`Marturana`/`Martorana`), children carrying the *mother's* surname (rows 90,
  210), and foundlings (`parents ignorante`, 7 rows). Copying would silently
  normalize exactly the records a genealogist is hunting for. Leave the father's
  surname blank when the document doesn't state it.
- **`de` and `di` are both attested** and are not interchangeable: `de Natale` and
  `di Natale`, `de Giorgio` and `di Giorgio`, `de Bella` and `di Bella` all appear.
  Transcribe the particle as written; never regularize.
- **Latin name forms everywhere**, including in the English. `Archangelus` not
  "Archangel", `Gregorius` not "Gregory". The source index mixes Latin and Italian
  because the human indexer modernized some entries; the scribe wrote Latin.
- **Alias surnames** are real: `Gendusa alias Gassarella`. Transcribe whole.
- Months count from March: `7bris` = September … `10bris` = December. Hours are
  Italian hours counted from sunset, not clock time.
- **`filius`/`filia` differ by one letter and are a frequent misreading.**
  Confirmed against real image output: it silently regenders the child's given
  names throughout the transcription and translation, because the fidelity
  rules normalize name endings to match whichever was read. Two confirmed
  instances fixed by adding an explicit cross-check (given-name endings must
  agree with `filius`/`filia`) to `build_prompt.py`'s Section 2 formula intro.
  Two other instances (image 195, `Bentivegna`/`Cammarata`) remain unresolved
  as of the last test — those entries never produce a marginal-heading line at
  all in v3's output (unlike 193/194, which reliably do), so there's no
  internal cross-check available for the model to catch itself with. Worth
  checking whether image 195's actual page layout has a heading the model is
  missing, or genuinely lacks one.
- **Never fabricate an entry.** Added an explicit anti-hallucination
  instruction + pre-output entry-count self-check to Section 1 after a
  suspicious entry appeared in early testing (see Open Items — page 36/37,
  "Bella"/"Serra"/"Sebbia"). This reduces the rate; it cannot guarantee zero,
  since hallucination is a probabilistic failure mode a prompt instruction
  can't fully rule out. The real backstop is the not-yet-built review tool
  below, or a human spot-check.
- **Godparent clause honorifics: Don/Master only, everything else to Notes,
  never both.** "Doctor" leaking into a clause caused the stray-title parser
  bug above; the prompt now gives an explicit wrong/right example.

## Where things live

```
profiles/chiusa-sclafani-battesimi-v3.json   active prompt (generated — do not hand-edit)
prompts/chiusa-sclafani/
  build_prompt.py                            generates the profile; edit this
  lex.json                                   407 surnames + 320 given names, frequency-tiered
  clean_index.py                             rebuilds the index from the indexer's marked-up xlsx;
                                              also reusable for other marked-up ground-truth files
                                              (set SPONSOR_COL to match the sheet's own layout —
                                              "G" for the SG-364 index, "R" for the Church Baptism
                                              Record Index Template layout used by the 193-195
                                              ground-truth spreadsheets)
  Chiusa Sclafani battesimi SG-364 - cleaned index.xlsx
  index-corrections-audit.json               915 cell-level corrections, original → cleaned
  prompt-v3-readable.md                      readable copy of the three sections
xls_conversion/tests/                        baptism-parser.js regression tests (offline, no API key)
xls_conversion/ai_parser.py                  the LIVE xls-conversion parser (see pipeline section above)
```

The lexicon came from an indexer-corrected spreadsheet: strikethrough marked
deletions, blue text marked corrections. `clean_index.py` resolves that markup.
Re-run it if a newer marked-up index arrives, then rebuild the prompt.

## v3 real-image test results (images 193–195, Gemini 3.1 Pro Preview)

Ground truth: `/Users/stevecovello/Desktop/Chiusa Sclafani Battesimi/Chiusa
Sclafani Transcription V2 193-195 Corrected.xlsx` (and `UnCorrected.xlsx`),
resolved via `clean_index.py` with `SPONSOR_COL = "R"`. 23 entries, images
193/194/195, dated 1753 (with one disputed 1754 — see below).

**Page number capture: confirmed working end-to-end.** All 23 entries got the
correct `Page #` (193→34/35, 194→36/37, 195→38/39) in the real `ai_parser.py`
XLSX output, including correctly switching values at the left/right column
boundary and preserving an honestly-flagged `[illegible]` page number rather
than guessing it.

**Still-open findings from this test round:**
- **Possible real missed entry, not hallucination (revised assessment).** A
  child named approximately "Innocentius Felix ... Claudius" (surname unstable:
  `Sebbia`/`Serra`/`Bella` across three independent runs with an evolving
  prompt), born 20 October 1753, celebrant Joseph Catalano, appears at image
  194 position 2 in every v3 run so far — but nowhere in the ground truth.
  Ground truth's own position 2 is an unrelated entry (`Viride`, 16 September,
  sponsor Francesca Chiara) that never appears in any v3 run. Initially flagged
  as a likely hallucination; revised after a third run showed the
  date/celebrant/given-names skeleton staying stable while only the surname
  wobbles, plus the model self-flagging a real heading-vs-body naming conflict
  for the mother — a hallucinated entry would likely drift more. Leaning
  "genuinely hard-to-read real entry the human index missed," but **not
  confirmed — needs an actual look at image_194.jpg** around the page 36/37
  boundary.
- **The 1754 year on image 194, positions 6-7, is very likely correct** despite
  v3 saying 1753 — user's own review agrees ground truth is right here. An
  independent prior transcription and the indexer's correction pass (which
  touched Month/Day but left Year untouched) both said 1754; v3's own flagged
  "backward" date jump (Oct 31 → Oct 4) resolves cleanly as a normal ~11-month
  forward gap if the true year is 1754. `ejusdem`/`Eod.` resolution in the
  prompt only ties to month continuity, not year — a model missing an explicit
  year-change marker on the page would produce exactly this failure. Not yet
  fixed in the prompt.
- Confidence calibration is uneven: v3 correctly flagged its two hardest calls
  (an uncertain surname, an odd date sequence) but was fully confident on
  several surname disagreements the ground truth disputes. Self-reported
  confidence alone won't catch everything — see the review tool below.

## Open items

- **Review post-process, not yet built.** Add flag columns to the indexer's XLSX:
  child-vs-father surname mismatch, missing/`[illegible]` names, surname absent
  from the lexicon, register-wide rare-vs-common near matches. On the 362-row
  sample this flags 20 rows (6%) with essentially no false alarms. Agreed design:
  flag columns appended, records left in register order, flagged rows coloured.
  **It writes flags, never values** — a wrong cell is invisible, a blank one isn't.
  Should read both the parser's rows and the raw transcription (to lift
  `[illegible]` and `Confidence: low` out of `Notes:`).
- Check image_194.jpg directly for the "Sebbia/Serra/Bella" entry (see above).
- Consider fixing the `ejusdem`/`Eod.` year-continuity gap that likely caused
  the 1753/1754 mismatch above.
- `ai_parser.py`'s own extraction behavior hasn't been audited the way
  `baptism-parser.js` has — no equivalent regression-test coverage exists for
  it, and it can't be tested offline (needs a real Gemini call). Worth deciding
  whether that's acceptable long-term or whether `baptism-parser.js` should be
  wired back into the live UI as a free, deterministic first pass.
- Decide whether the other registers (matrimoni, morti) need the same
  page-number and fidelity treatment — their parsers have separate,
  unexamined phrasing contracts, and neither prompt has been checked for the
  fixes made here (hallucination guard, `filius`/`filia` cross-check,
  godparent-honorific tightening).
