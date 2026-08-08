# Transcription Bot — working context

Local Python web app that sends archival page images to Gemini, writes a plain-text
transcription, and exports `.docx`. A separate browser tool then converts that text
into a spreadsheet for a human indexer.

Launch: `cd path/to/Transcription-Bot && .venv/bin/python app.py`
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

## Prompt Builder page (`/prompt-builder`)

Guided profile-creation page, added because writing a strong three-part system
prompt from scratch is a different skill than knowing what a project needs.
`prompt_builder_page()` in `app.py` (near `test_mode_page()`). Pre-populates the
same three fields every profile uses (`role_context`, `reference_context`,
`output_format`) from `PROMPT_BUILDER_TEMPLATE_ID = "chiusa-sclafani-battesimi-v3"`
— loaded live via `load_profile()`, not a hardcoded copy, so it stays in sync if
that profile is ever rebuilt — but the UI only ever calls it "Template", never
by name, since it's meant to generalize to any register type. Each of the three
fields sits in its own collapsible `<details>` with a fixed (non-editable)
caption above it saying what's project-specific to replace and what structural
scaffolding to keep; captions live in `PROMPT_BUILDER_SECTION_HELP`.

Saving posts to `/prompt-builder/save-profile` (`Handler.save_prompt_builder_profile`),
which just calls the existing `save_custom_profile()` — always creates a new
profile (auto-suffixed `-2`/`-3` on a name collision), never edits the template
or an existing profile in place. Editing an existing saved profile still happens
on the Transcribe page, which already supports that; Prompt Builder is
deliberately a creation tool, not a full profile manager, and doesn't support
delete either.

The page's "Full prompt preview" panel mirrors `build_system_prompt()` /
`neutral_system_scaffold()` client-side in JS (`pbAssembleFullPrompt`), because
the real assembled prompt is NOT just the three fields concatenated — it's
wrapped with fixed headers and 9 hardcoded "CORE TRANSCRIPTION RULES" bullets
that get added regardless of profile content. If those Python functions change,
the JS mirror needs updating to match or the preview will lie about what's
actually sent to Gemini. Verified byte-for-byte identical against a real
`build_system_prompt()` call. (An earlier version of this check found 609
literal `\r\n` escape sequences baked into `chiusa-sclafani-battesimi-v3.json`'s
string fields — invisible to a raw-byte scan of the file since they were
JSON-escaped text, not actual CR bytes, but `json.loads` decodes escapes, so
they became real CRLF characters once loaded and made the live preview ~600
characters shorter than what `build_system_prompt()` actually assembled.
Fixed by rebuilding the profile from source — `build_prompt.py`'s literal
strings only ever use `\n` — rather than hand-patching the JSON. If a profile
file's assembled-prompt length ever looks off again, check for the same
JSON-escaped-CRLF pattern before assuming a logic bug.)

Same nav bar (`app.py` ×2, `xls_conversion/index.html` ×1) and same
stale-embedded-snapshot footgun as the rest of the app: Transcribe and Test
Mode read the profile list once when their page renders, so a profile saved
here needs a real reload of those tabs before it appears there — the save
banner says so.

## Accessibility (WCAG)

Page `<h1>` titles: Transcribe = "Customizable Transcription", XLS Conversion =
"XLSX Conversion" (nav label matches), Test Mode = "Test Mode: Model
Comparison", Prompt Builder = "Prompt Builder". The XLS Conversion page's
`<h1>` used to literally read "Customizable Transcription Interface" — a
copy-paste leftover from before that page existed as its own file — fixed
alongside this pass.

Audited against WCAG 2.1 AA and fixed, across `app.py`'s three page functions
and `xls_conversion/index.html` + `styles.css`:

- **No skip link.** Added `.skip-link` (visually hidden until focused) as the
  first focusable element in `<body>` on all four pages, targeting
  `<main id="main-content" tabindex="-1">`.
- **Radio groups had no programmatic group name.** "Process order" and "File
  type" on Transcribe/Test Mode were a bare `<label>` (not associated with any
  control) followed by a `<div>` of radios. Changed to `<fieldset><legend>`,
  with `fieldset`/`legend` CSS reset to look identical to the old
  `<label>`/`<div>` pair. (XLS Conversion's record-type radios already used
  `role="radiogroup" aria-label="Source material"` — no change needed there.)
- **Status regions weren't announced to screen readers.** Added
  `role="status" aria-live="polite"` to `#summary` and `#run-status`, and
  `aria-live="polite"` to `#output`, on Transcribe/Test Mode. (XLS Conversion
  already had this right.) Deliberately did NOT make `#log` or Test Mode's
  `#progress-rows` live — they update too frequently/verbosely; a live region
  there would re-announce constantly instead of helping.
- **Download links stayed keyboard-activatable while "disabled."**
  `aria-disabled="true"` + `pointer-events: none` blocks mouse clicks but not
  a keyboard Enter on a focused `<a href>` (the `<a>` never had `disabled`
  removed, unlike a real `<button disabled>`, which is why the old markup
  didn't just use a button). Added a delegated `click` listener on both pages
  that calls `preventDefault()` when `aria-disabled="true"` regardless of
  input method.
- **Settings-alert modal didn't return focus.** `showSettingsAlert()` moved
  focus into the dialog (correct) but `hideSettingsAlert()` left focus
  wherever the browser dropped it. Now stores `document.activeElement` before
  opening and restores it on close.
- **Contrast failures.** `.pb-word-count` (`#8d99a6` on white, 2.9:1) darkened
  to `#5f6b76` (5.0:1, matches `.hint`). The shared input/textarea/select
  border `#b8b2a5` (2.1:1 against white, below the 3:1 UI-component minimum)
  darkened to `#8a8377` (3.75:1) everywhere it appeared — 4 spots in `app.py`
  plus `xls_conversion/styles.css`.

Checked and already compliant, not touched: `lang="en"` on all four documents,
no images needing alt text (icons are CSS, not `<img>`), heading hierarchy
(`.panel-title` is a real `<h2>`, not a styled `<div>`), focus-visible outlines
present on links/buttons with no `outline: none` anywhere, labels correctly
associated with their inputs via wrapping.

Noted but not fixed (low priority / judgment calls, revisit if it matters):
the disclosure-triangle character in Prompt Builder's `<summary>::before` is
decorative and could theoretically be announced by some AT even though
`<details>`'s native expanded/collapsed state already covers the same
information; the settings-alert modal moves focus in/out correctly but
doesn't hard-trap Tab within it while open, so a sighted keyboard user could
in principle Tab past it into the obscured page behind the overlay.

## Test Mode scoring — native-language transcription accuracy only

`test_mode/comparison.py`'s `score_transcription()` runs both sides through
`strip_non_transcription_blocks()` before computing CER/WER/WER-BoW. This is
deliberate, not an oversight: Test Mode's whole purpose is comparing models on
transcription/paleography accuracy, and scoring the raw full text (as it did
before) conflated that with translation-phrasing quality and note-writing
style — neither of which reflects how well a model reads handwriting. Notes
are English commentary, not transcribed content, so a model that writes a
differently-worded but equally correct note used to be penalized as if it
had misread the page.

What gets dropped: the entire `English Translation:` block, the entire
`Notes:` block, and the synthetic `Page N - Entry n:` locator line (that
number doesn't exist on the page — see the heading redesign below — so it
isn't transcription content either). What's kept: `Marginal Heading:` (a
verbatim transcription of what the scribe wrote, so it's real content now
that Section 3 no longer fabricates it — see below), `Date:`, and
`Latin Transcription:`, labels and all, exactly as they'd have been scored
before. Both the ground-truth corrected text and every candidate's text are
stripped the same way, so neither side is unfairly penalized for content the
other lacks.

This relies on the label `English Translation:` being a stable, consistent
string across profiles (confirmed true for both Chiusa Sclafani's own
`Latin Transcription:`/`English Translation:` pair and the generic profile
default's `Italian Transcription:`/`English Translation:` pair — the native
label varies, the English one doesn't) — not something enforced by the
schema, so a custom Prompt-Builder-authored profile that uses different
wording for its English block would silently bypass the strip. Not fixed
here; worth revisiting if Test Mode is ever run against a profile that
deviates from that convention.

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
cd profiles/sources/chiusa-sclafani && python3 build_prompt.py
```

Prose in `build_prompt.py`'s `SECTION_1`/`SECTION_2_HEAD`/`SECTION_3` string
literals is hard-wrapped one sentence-flow per line purely for source
readability — reflowed into single lines per paragraph before every commit, so
the generated profile's `role_context`/`reference_context`/`output_format`
read as continuous prose in the Prompt Builder / Transcribe textareas, not
mid-sentence line breaks. Structural line breaks are NOT touched: markdown
headers, bullet/numbered list items, the `# ABBREVIATION KEY` table, the
`# BLOCK STRUCTURE` required output template, and the worked examples all keep
their own required line/blank-line layout. If you edit these string literals
by hand later, keep new prose on one line per paragraph (wrap in your editor,
not in the source) rather than reintroducing hard 80-column wraps.

**Known footgun: the browser can silently revert this file.** The app embeds a
JS snapshot of a profile's fields when the page renders; re-selecting the
profile from the dropdown repopulates from *that snapshot*, not a fresh fetch.
If the boxes match the tab's own stale baseline, the app treats the run as
"unchanged" and can write that stale snapshot back over a freshly-rebuilt file
— this actually happened mid-session (rebuilt profile → user ran from a
not-reloaded tab → file got overwritten with a 3-fixes-behind version,
confirmed by matching mtimes). **After every `build_prompt.py` rebuild, do a
real browser reload (Cmd+R), not just a dropdown re-select, before running.**

**Entry heading is now a locator + a real Marginal Heading block, not a
fabricated summary.** Section 3 used to require `Page 34 - Entry 1: Manfre,
Filippa Maria` — a heading the model invented by reformatting names it read
elsewhere; nothing on the actual page looks like that. Section 2 already
documented the register's real marginal-heading formula (`[child] filius/filia
[father] et [mother] [surname]`), so Section 3 was rewritten to actually use
it: `Page 34 - Entry 1:` is now a pure locator (synthetic — this register has
no entry numbers of its own; a register that does should transcribe its own
instead, which is a per-profile decision, not universal), and a new
`Marginal Heading:` block carries a verbatim transcription of what the scribe
wrote in the margin, omitted entirely for registers with no separate heading.
`Latin Transcription:` now holds the body only (from `Ego Sac.os...` onward),
not the heading text repeated. This also fixed a real information loss: the
worked examples already documented cases where the heading and body disagree
(image 194's Collica entry has the names in a different order in each; the
Collura entry has an illegible name in the body but a legible one in the
heading) — the old single fabricated heading silently discarded whichever
version it didn't use. Both now survive, each in its own block, with the
disagreement flagged on the Notes line per the Section 3 rule.

Rippled to `xls_conversion/ai_parser.py`'s `BATTESIMI_SYSTEM_PROMPT`: its
child-surname fallback used to say "use a supported surname from the entry
title or parents" — the entry title no longer carries a name, so this now
says "Marginal Heading block" instead, preserving the same fallback behavior
since the model still sees that block in the source text it's extracting
from (the instruction to "ignore Latin/Italian transcription text" was
already treated as not applying to this one fallback case, same as before).

**Known gap, not fixed: `baptism-parser.js`'s Child-column surname is now
broken for this register** (offline parser only — not live, see the pipeline
section above). Its `parseChild()` got the child's surname from the old
fabricated heading via a `titleName` parameter; that's now always empty, so
Child comes back given-names-only (or blank entirely, for the rarer entries
whose translation has no "was given the name" clause). The fix would be
parsing the surname out of the Marginal Heading's own Latin formula, but a
naive "last token after et" heuristic is unsafe: entry 6 in
`xls_conversion/tests/fixture-expected-format.md` (Collica) has the surname
trailing the *father* before "et", not the mother after it, unlike entry 1
(Manfre) where it trails the mother — real structural variation within the
same register, not a hypothetical edge case. `run_parser_test.py`'s
`EXPECTED` values were updated to the honest current output rather than left
silently wrong; see its comment block for the full reasoning.

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
- **Latin declension means the same name legitimately appears in more than
  one written form within a single entry — this is not a heading/body
  disagreement.** Flagged after image 194 Entry 3 showed both `Michaelis`
  (genitive, in the Marginal Heading's `filia Michaelis` = "daughter OF
  Michael") and `Michaele` (ablative, in the body's `ex ... Michaele` = "born
  FROM Michael") for the same person. Section 1 now has a dedicated `# LATIN
  NAME DECLENSION` block explaining nominative/genitive/ablative/accusative
  with worked examples (`Franciscus`/`Francisci`/`Francisco`/`Franciscum`,
  the last commonly abbreviated to a macron over the vowel), and both the
  Marginal Heading disagreement rule and the `Notes:` block description in
  Section 3 were amended to explicitly exclude a pure case-ending difference
  from what counts as a disagreement to flag. Before this, the prompt's own
  disagreement rule ("a different name order, a different spelling...") was
  ambiguous about whether `Michaelis` vs `Michaele` counted — plausibly
  either prompting an unnecessary Notes flag or, worse, tempting the model to
  "resolve" it by silently normalizing one occurrence to match the other,
  which the fidelity rules elsewhere explicitly forbid. Not yet re-tested
  against a real image since this was a same-session fix, unlike the other
  entries in this list.

## Where things live

```
profiles/                                    single live location for all profiles (app.py reads only this)
  chiusa-sclafani-battesimi-v3.json          active prompt (generated — do not hand-edit)
  sources/chiusa-sclafani/                   build source for the profile above — not itself loaded by the app
    build_prompt.py                          generates the profile; edit this
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

Ground truth: `Chiusa Sclafani Transcription V2 193-195 Corrected.xlsx` (and
`UnCorrected.xlsx`), kept locally outside the repo, resolved via
`clean_index.py` with `SPONSOR_COL = "R"`. 23 entries, images 193/194/195,
dated 1753 (with one disputed 1754 — see below).

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
- **Parse the child's surname out of the Marginal Heading block in
  `baptism-parser.js`.** See "Chiusa Sclafani battesimi — decisions" above —
  not a simple last-token-after-"et" regex, since the surname's position
  relative to "et" varies for real reasons within this same register. Not
  live-critical (offline regression parser only), but the regression suite
  currently documents the gap rather than testing correct behavior.
