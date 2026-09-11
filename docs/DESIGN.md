# Design notes

This document explains the "why" behind a number of decisions in this
codebase that aren't obvious from reading the code alone — architecture
choices, fixed security defects, and register-specific parsing rules. Code
comments throughout the repo point here by section.

## Codebase structure

`app.py` originally held every page's HTML/CSS/JS render function, all
request routing, and most business logic in one file. It has since been
split by concern:

- **`pages/`** — one module per page (`transcribe.py`, `test_mode.py`,
  `prompt_builder.py`, `home.py`, `privacy.py`), each holding the render
  function for that page. `pages/__init__.py` holds `json_for_inline_script()`,
  `json_data_island_html()`, and `file_picker_html()`, small helpers more
  than one page needs.
- **`app_state.py`** — the in-memory run state (`state`/`test_state` and
  their locks/events), the user-facing outputs directory, and app-settings
  persistence. This exists as its own module because both `app.py` (the
  HTTP handlers) and `pages/*.py` (which render live run status into the
  page) need it, and importing it from either side directly would create a
  circular import.
- **`profiles_store.py`** — every profile path-resolution/load/save/update/
  delete/import/export function, plus the per-OS user-data-directory
  helpers. See "Profile storage" below for what it actually manages.
- **`prompt_builder_content.py`** — pure-data constants (record-type
  formulas, vocabulary checklists) with no logic of their own, consumed by
  Prompt Builder's HTML-building functions.
- **`static/base.css`** and **`static/app-shell.css`** — CSS shared across
  pages, split into two tiers: `base.css` holds rules identical across all
  pages (shell layout, nav, forms, buttons); `app-shell.css` holds rules
  shared only between Transcribe and Test Mode (run controls, the
  settings-alert modal), since Prompt Builder's own styling has diverged
  too far from those two to share past the base tier.
- **`static/app-common.js`** — JS functions with identical bodies across
  Transcribe and Test Mode's inline scripts (`showSettingsAlert`,
  `pickSourceFolder`, `openOutputsFolder`, and others). Functions whose
  bodies have diverged between the two pages are deliberately left
  page-local, not forced into a shared file.
- **`static/transcribe.js`/`test-mode.js`/`prompt-builder.js`** and
  **`static/home.css`/`privacy.css`/`getting-started.css`/`transcribe.css`/
  `test-mode.css`/`prompt-builder.css`** — each page's own remaining
  script/styling, previously inline `<script>`/`<style>` blocks in the
  corresponding `pages/*.py` render function (and, for Getting Started,
  `app.py`'s `getting_started_page()`). Extracted so the CSP's `script-src`/
  `style-src` could drop `'unsafe-inline'` — see "Security hardening
  history" below. Per-request dynamic data (profile lists, run history,
  Prompt Builder's questionnaire-restore state) that these scripts need is
  passed via a `<script type="application/json">` "data island"
  (`json_data_island_html()`) instead of an executable inline assignment —
  a JSON-typed script element is inert to the browser's JS engine, so
  `script-src` never governs it, unlike a plain `<script>` block.
- **`docx_package.py`** — the generic OOXML package-XML functions
  (`content_types_xml()`, `root_rels_xml()`) that every DOCX writer in this
  codebase needs, plus `strip_xml_illegal_chars()` (see "Security hardening
  history" below).

## Profile storage: shipped examples vs. user data

This app's documented update path is "download a fresh copy, replace the
old folder" — there is no `git pull` step for an end user. Profiles
therefore live in two separate places so a folder-replace update can never
delete a user's own saved work:

- **`profiles/`** (git-tracked) — shipped reference examples only,
  read-only at runtime. Nothing the running app does ever writes here.
- **A per-OS user-data directory**, outside the app's own install folder
  (e.g. `~/Library/Application Support/Customizable Transcription/profiles/`
  on macOS) — every profile a user saves or edits through the running app
  goes here instead. If a user edits a shipped profile, the edit is saved
  as their own copy in the user directory, shadowing the shipped original
  for them without ever modifying the tracked file on disk.

Every DOCX this app writes stamps a small header box declaring record
type, language(s), and which AI model/profile produced the run — written
deterministically from the profile's own saved fields, not inferred from
the model's output.

## Security hardening history

An external review of the app's HTTP layer and file-ingestion paths found
several defects, all reproduced and fixed:

- **No CSRF/Host/Origin defense.** Binding to `127.0.0.1` alone doesn't
  stop a malicious page open in the same browser from POSTing to this
  app's endpoints (same-origin policy blocks reading a cross-origin
  response, not sending the request; DNS rebinding can defeat even that
  read restriction). Fixed with Host-header validation on every request,
  Origin validation on state-changing requests, and a per-launch random
  `SameSite=Strict` CSRF token.
- **DOCTYPE/entity-expansion bypass in DOCX ingestion.** A DOCX-reading
  guard that only rejected a DOCTYPE anchored at the very start of the XML
  let a leading comment or processing instruction slide a DOCTYPE (and any
  entities it declares) straight past the check, reopening a classic
  "billion laughs" expansion. Fixed by searching for `<!DOCTYPE`/`<!ENTITY`
  anywhere in the document rather than anchoring the check — a real Word
  `document.xml` never contains either.
- **Unbounded numeric-range expansion.** A user-typed image range like
  `1-1000000000` was expanded into a literal list before any bound was
  checked. Fixed with explicit caps on range span and total image count,
  and rejection of descending or malformed ranges.
- **Excel sheet-name injection.** A sheet name built from AI-detected text
  with no sanitization could contain characters Excel's own XML format
  forbids, corrupting the workbook. Fixed with a sanitizer that strips
  forbidden characters, truncates to Excel's 31-character limit, and
  de-duplicates case-insensitively.
- **A run-reservation race, and a related deadlock.** A check-then-set
  race let two near-simultaneous requests both start a background job.
  Fixing the race (moving the reservation inside the same lock as the
  check) surfaced a second, more serious bug: several handlers called a
  page-render function that acquires the *same* lock from *inside* the
  block already holding it — `threading.Lock` isn't reentrant, so this
  deadlocked the request thread indefinitely. Fixed by moving those calls
  outside the lock block.
- **Batch failures not bounded.** A narrow exception catch in the batch
  AI-extraction loop meant one malformed provider response could abort an
  entire remaining batch instead of being recorded as one failed item.
  Widened the catch, and added retry-with-backoff-and-jitter for
  transient errors (HTTP 429/5xx) so most of these never reach the
  per-item failure path at all.
- **XML control characters could corrupt generated files.** Standard XML
  escaping handles `<`/`>`/`&` but not a raw control character like
  `\x00`, which produces XML that isn't well-formed no matter how it's
  escaped. `strip_xml_illegal_chars()` (`docx_package.py`) uses XML 1.0's
  own `Char` production as its allowlist, so it's provably complete rather
  than a patch for one specific reproduced character.
- **Path traversal in profile deletion/update.** A profile id was used to
  build a filesystem path with no validation, so an id like
  `../app_settings` could delete or overwrite a file outside the profiles
  directory. Fixed with a strict id-format check plus a check that the
  resolved path actually stays inside the intended directory.
- **A dependency-reported CVE** (an insecure temp-directory handling
  advisory against a pinned `pytest` version) was fixed by upgrading past
  the patched release. Dependencies are now audited automatically
  (`pip-audit`, `npm audit`) on a weekly schedule in CI, not just at
  release time.
- **CSP allowed `unsafe-inline` for scripts and styles.** Existing escaping
  discipline (`json_for_inline_script()`, `html.escape()`) made this a
  defense-in-depth gap rather than an active exploit — but this app has had
  exactly one real script-injection bug before (a profile label once
  embedded via bare `json.dumps()` instead of the safe pattern), and
  `unsafe-inline` would have let an equivalent future bug execute anyway.
  Fixed by moving every page's inline `<script>`/`<style>` content to
  `/static/*.js`/`*.css` (see "Codebase structure" above), with per-request
  dynamic data passed via an inert `<script type="application/json">` data
  island instead of an executable assignment. `script-src`/`style-src` now
  read plain `'self'`, no exception.

A more recent hardening pass added the same category of defense to XLSX
uploads accepted by the Index Compare feature (see below): a zip archive's
declared per-entry and total uncompressed size are checked before
`openpyxl` ever decompresses anything, and a worksheet's row/column counts
are capped, closing the same "tiny compressed file, huge decompressed
payload" attack shape the DOCX guard above already closes.

## Index Compare: matching and scoring design

Index Compare scores one or more AI-generated candidate spreadsheet
indexes against a corrected, ground-truth index, field by field, for the
same record type.

**Row alignment** (`index_compare/align.py`) pairs rows between the two
files in two passes. First, rows are grouped by locator (page number or
act number) and matched *within* each locator's group by primary-person
name (and year, when both sides state one) — fuzzy, to tolerate the kind
of spelling/declension variation a real transcript legitimately has —
falling back to file-position order only for whatever identity can't
place. Matching by position alone, before identity, has a real failure
mode: if a candidate is missing the first of several entries sharing one
page number, position-only pairing shifts every later entry on that page
into a wrong pairing, and reports the wrong record as missing. Identity
matching within the locator group re-anchors correctly regardless of a
gap earlier in the group. Second, whatever neither pass could place gets
one more attempt by name+date identity across the whole file — added
because a real ground-truth file, tracked by name and date with no
locator column filled in at all, produced zero matches under
locator-only matching even though every record was genuinely present in
both files. Both matching passes use "global best-first" assignment
(score every candidate pair, claim the highest-scoring pairs first,
skip a row once claimed) rather than resolving row-by-row in file order,
since a fixed-order resolution can let a mediocre match claim a row a
later pair would have matched almost perfectly.

**Difference classification** (`index_compare/heuristics.py`) buckets
each field difference deterministically (match / missing / wrong value /
Latin-form variant / spelling variant / differs / unclassified) — check
order matters, since a difference could plausibly fit more than one
bucket. This is deliberately not an attempt at general Latin
morphological parsing: it recognizes a fixed set of common
declension-ending patterns explicitly, rather than trying to derive them.

**Scoring** (character-level edit distance, reused from Test Mode's own
comparison module) is scoped to only the fields the ground truth actually
populates — comparing a field the ground truth never fills in can only
manufacture noise, not a real accuracy signal.

A ground-truth file is required; there is no "compare candidates only to
each other" mode. The feature's purpose is answering "which candidate is
closer to the corrected index," which presupposes a corrected index to
compare against.

The output is a DOCX report (an overall ranking table, a matched/missing/
extra-rows table, a field-group error-rate table, and an aggregate
category-count table), not a per-row XLSX diff — the target workflow
already reviews every row of the corrected index by eye regardless, so a
per-entry diff list adds no value on top of that; the one number that
workflow can't produce on its own is the aggregate ranking.

## XLS Conversion: parser contract and register-specific rules

Two independent extraction paths exist. The one the app's UI actually
runs is `xls_conversion/ai_parser.py`: a semantic AI extraction that
tolerates real phrasing drift. A second, offline, deterministic regex
parser (`xls_conversion/baptism-parser.js`) is not wired into the live
UI — it exists as a fast, free, exact-match regression check of the
transcription prompt's format compliance, reachable through
`xls_conversion/tests/run_parser_test.py`. Both parsers depend on the
transcription prompt targeting a consistent output shape; the table below
is the contract that keeps the offline regex parser meaningful as a
regression check even though it isn't what a live conversion runs.

| Field | Required phrasing | What breaks if violated |
|---|---|---|
| Date | `On the 23rd day of September 1752.` | Omitting the year blanks the Year column |
| Parents | `to the spouses X and Y` | Alternate phrasing matches nothing |
| Child | `was given the name X.` | Alternate phrasing matches nothing |
| Godparents | `The godfather was X; the godmother was Y.` | Alternate phrasing matches nothing |
| Page number | `Page 34 - Entry 1: ...` | Missing entirely blanks Page # for every entry |

Structural requirements: a blank line must separate every block (otherwise
adjacent blocks get merged into one field), each language's transcription
must be one unbroken line, and `Notes:` must come before the native-
language transcription block (otherwise later content gets swallowed into
the notes).

Bugs found and fixed in the offline regex parser (not necessarily present
in the live semantic parser, which handles free-form phrasing
differently):

- **A spouse-aside inside a godparent clause could invent a phantom
  godparent.** With two or more godparent clauses present, a "wife of"/
  "husband of" aside inside one clause used to discard the real godparents
  and return a `[name, spouse]` pair instead. Fixed so each clause keeps
  only its own name.
- **A bracketed, honestly-flagged uncertain surname could drop both
  parents.** A parent-name regex whose character class didn't allow `[`,
  `]`, or `?` failed outright on an uncertain surname like
  `[de Pocopila?]`, discarding even the parent whose name was fully
  legible.
- **A stray honorific beyond the two allowed titles leaked into the
  spreadsheet cell.** Name cleanup now strips a wider set of titles
  defensively.
- **The page-number heading wasn't parsed for a separate column** until
  added explicitly, including support for a different page number per
  column within one image and an honestly-flagged illegible page number.

One register-specific set of editorial rules, encoded in a real
transcription profile rather than in code, is worth documenting since
it's easy to "improve" incorrectly:

- **Never copy a surname between parents, or from a child to a father.**
  Measured against a real verified index, most rows had a shared surname,
  but the exceptions were exactly the records a genealogist is hunting
  for (spelling variants, a child carrying the mother's surname,
  foundlings). Leave a surname blank when the source doesn't state it
  rather than inferring it.
- **Two historically-attested surname particles are not interchangeable.**
  Both forms are transcribed exactly as written, never normalized to one.
- **A one-letter Latin ending difference can silently regender a name.**
  Two Latin words differing by a single letter, used to identify a person
  by their parentage, are a frequent scribal misreading; misreading one
  for the other silently regenders that person's given names throughout a
  transcription and translation, because fidelity rules normalize name
  endings to agree with whichever was read. An explicit cross-check
  (given-name endings must agree with which of the two words appears)
  catches this class of error.
- **The same name legitimately takes more than one written form within a
  single entry.** Latin grammatical case changes a name's ending
  depending on its grammatical role in the sentence; this is not a
  transcription disagreement to flag, and fidelity rules must not
  "resolve" it by normalizing one occurrence to match another.

## Prompt Builder design

Prompt Builder assembles a transcription profile's system prompt from a
guided questionnaire (presets, checklists, short text fields) rather than
asking a user to hand-write prose — the target user has no
prompt-engineering background. The questionnaire's answers assemble into
the same three fields every profile has always used
(`role_context`/`reference_context`/`output_format`); the save endpoint's
contract never changed.

A few decisions worth calling out:

- **Record type gates the whole form.** Type-specific field groups
  (entry-formula sub-fields, role-clause vocabulary) are pre-rendered for
  every supported record type and shown/hidden client-side by the
  selected type, rather than built dynamically — matching how the rest of
  the app favors static markup over templated DOM construction. Assembly
  only ever reads fields inside the currently-selected type's group, so
  switching record type can't leak a hidden type's stale answers into the
  generated prompt.
- **Translation is an explicit, optional choice.** Leaving both
  translation-language checkboxes unchecked produces a transcription-only
  profile — no translation block, no translation-phrasing rules (a rule
  about how a translated name reads is meaningless without a
  translation).
- **Honorifics inside a role-introducing clause are deliberately
  restricted to a small allowed set** (e.g. a courtesy title for clergy);
  any other title the source mentions gets moved to a separate notes
  field instead, so a role clause like "The godfather was Don Carolus
  Calsi" keeps a predictable shape a downstream reader — or a later AI
  pass — can rely on.
- **A Latin case-declension cross-check** catches the same
  parentage-word misreading class described above, generalized across
  every record type that uses parentage words in its own formula fields
  (not assuming a child specifically, since marriage and death records
  use the same words for a groom/bride or the deceased's own filiation).
- **Worked examples were considered required, then removed.** Concrete
  worked examples calibrate an AI's transcription/translation judgment
  against a specific register's paleography in a way no boilerplate rule
  can substitute for — but requiring at least one in the UI meant a
  brand-new user with no prior transcription had nothing to paste in on
  their first profile. The requirement was dropped; a user who wants that
  benefit can still append a worked example to a saved profile's
  reference/output fields by hand.

## Test Mode scoring

Test Mode's `strip_non_transcription_blocks()` removes the translation
block, the notes block, and the synthetic per-entry locator line before
computing character/word error rates, on both the corrected reference and
every candidate. Test Mode's purpose is comparing models on transcription
accuracy specifically; scoring the full raw text conflates that with
translation-phrasing style and note-writing style, neither of which
reflects how well a model reads handwriting.

A separate `continuation_merge` step in the transcription pipeline handles
an entry whose content spans two consecutive source images (a register
entry that starts at the bottom of one photographed page and continues
onto the next) — recognizing and merging the split rather than scoring
or exporting it as two separate, truncated entries.

## Accessibility

Each page keeps a real, page-identifying `<h1>` for screen-reader heading
navigation, visually hidden via a standard clip technique (present in the
DOM and the accessibility tree, unlike `display:none`, which removes a
node from both) rather than removed, alongside the page's actual visible
heading content.

## Additional notes

- **Profile-save behavior on the Transcribe page is a true destructive
  overwrite with no confirmation dialog**, by deliberate design: "Save
  Profile" always overwrites the currently-loaded profile in place, and a
  separate "Save as New Profile" button always creates a new one — no
  native `confirm()`/`prompt()` fork between the two, which previously
  made it easy to create an unwanted duplicate profile by mistake.
