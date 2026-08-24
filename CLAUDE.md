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
     in this file. It makes its own AI call (Gemini or Claude — see the model
     list) to turn the transcription text into the full official template
     schema for whichever of the 6 record types is selected — see "XLS
     Conversion record types" below. Its extraction is semantic, not regex:
     the system prompt describes each field in natural language and the
     model fills it in, which is more tolerant of phrasing drift than a
     regex parser but also non-deterministic and unauditable line-by-line.
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

## XLS Conversion record types (`xls_conversion/ai_parser.py`)

All 6 record types the app supports are live: Church Battesimi, Church
Matrimoni, Church Morti, Civil Birth, Civil Marriage, Civil Death. Each maps
1:1 to one of the real templates the user supplied (`~/Desktop/Claude-Codex
Projects/Customizable Transcription Bot/Index templates/*.xlsx`) —
`RECORD_TYPES: dict[str, RecordTypeConfig]` is keyed by the same `record_type`
string the frontend's `#recordType` dropdown sends (`battesimi`, `matrimoni`,
`morti`, `civil_birth`, `civil_marriage`, `civil_death`). Each
`RecordTypeConfig` bundles: the exact template's group/column header rows and
field-key list (verified byte-for-byte against the real templates when
built), its own system prompt, which fields (if any) get Male/Female
normalization, which columns get numeric/zero-padded XLSX formatting, and
column widths.

battesimi was the only type implemented before this; it keeps its original
`BATTESIMI_SYSTEM_PROMPT` completely untouched (not routed through the
shared rules block below) to avoid any risk of regressing its already-tuned
output, and keeps its own hand-tuned XLSX column widths rather than the
generic ones the other 5 use.

The 5 new types share one `GENERAL_EXTRACTION_RULES` block (uncertainty →
`""`, extract from the English translation not the source language, don't
anglicize/normalize names, split given name from surname keeping Italian
prefixes with the surname, `image_link` always `""`, same-day-language date
inheritance) interpolated into each type's own prompt, which then adds only
its own FIELDS list and type-specific rules.

Two schema differences that drive real code branches, not just different
field names:
- **Civil records have no Image # output column** (only `Act #` — civil
  registry acts don't carry a separate photographed-page number the way
  church register pages do). The parser still needs an image number
  internally for image-block splitting and carry-forward context, so
  `normalize_rows()` always stashes it on a `_image_number` key that's
  stripped back out before rows are returned to the caller — `_image_number`
  is never one of a `RecordTypeConfig.fields`, so it never leaks into a CSV/
  XLSX column.
- **`remove_parent_marital_details()` stays battesimi-only**, wired via
  `RecordTypeConfig.post_process_fields`. It exists because battesimi's
  Father/Mother "Other Information" is an open bucket field prone to
  leaking marital-status text that belongs elsewhere; none of the other 5
  templates have an equivalent open bucket field (civil records use
  structured Age/Occupation columns instead), so there's nothing to leak.

`xls_conversion/spreadsheet_export.py`'s `rows_to_xlsx()` used to hardcode
battesimi's numeric columns, its zero-padded Image # column, and its 20
exact column widths as module-level constants. These are now parameters
(`numeric_columns`, `padded_column`, `column_widths`), defaulting to
battesimi's original values so its output is unaffected; the other 5 types
pass their own. The 5 new types don't get battesimi's hand-tuned widths —
`_generic_column_widths()` applies a simple rule instead (narrow for the
locator column(s), a uniform width for everything else, wide for the
trailing Notes column) since hand-tuning 4 more column-width tables wasn't
worth it for a cosmetic concern Excel's own auto-fit solves in two clicks.

Live-AI extraction quality for the 5 new types hasn't been tested against a
real transcription the way battesimi's has been (see the v3 test-results
section below) — only verified structurally (config schemas match the real
templates byte-for-byte, exports round-trip through openpyxl correctly, and
a real API call reaches the provider and gets a real auth response rather
than erroring inside this app's own code). Worth a real test pass with
actual transcribed civil/matrimoni/morti material before relying on it.

## Prompt Builder page (`/prompt-builder`)

**Rebuilt as a guided questionnaire** — the target user has no prompt-
engineering skill, so the page no longer asks them to edit raw prompt text at
all (the old version pre-loaded Chiusa Sclafani v3's actual text into three
textareas with "replace this, keep that" captions; that still assumed someone
could write a strong system prompt by hand). Now it's presets and short text
fields — selects, checkboxes, small inputs — whose answers get assembled
client-side into the same three fields every profile always used
(`role_context`/`reference_context`/`output_format`). The backend contract
never changed: `save_prompt_builder_profile()` → `save_custom_profile()` still
just takes three plain strings and writes a profile JSON, exactly like every
profile before this rework, including Chiusa Sclafani v3 itself.

**Record type gates everything.** A select at the top of Section 1 covers all
6 record types the app now supports (matching the XLS Conversion dropdown
exactly: Church Battesimi/Matrimoni/Morti, Civil Birth/Marriage/Death).
Type-specific field groups for Sections 2 and 3 (entry-formula sub-fields,
role-clause vocabulary, required-phrasing suggestions) are pre-rendered for
all 6 types in the HTML (`PROMPT_BUILDER_RECORD_TYPES` dict in `app.py`,
generated via `pb_section2_type_group_html()`/`pb_section3_type_group_html()`)
and simply shown/hidden by `static/prompt-builder.js` based on the selected
type — deliberately static markup + JS visibility toggling rather than
dynamically building DOM, matching how the rest of the app favors static
HTML over templating. Assembly only ever reads fields inside the *currently
selected* type's group (fields are named `<type>_formula_body`,
`<type>_phrasing_family`, etc.), so switching record type can't leak a
hidden type's stale answers into the generated prompt.

**The assembly logic lives in `static/prompt-builder.js`, not inline in
`prompt_builder_page()`'s f-string** — the one deliberate precedent-deviation
in this rework. Every other page's script is inlined; this one is comparable
in size to `build_prompt.py` and is pure client logic with no Python
templating need, so it goes through the `/static/` route already built for
`static/i18n.js`. `prompt_builder_page()` only embeds a small
`window.PB_CORE_RULES` JSON blob (same `json.dumps(...).replace("</", "<\\/")`
pattern used for `profiles` elsewhere); the small `RECORD_TYPES` noun/label
metadata the JS itself needs for boilerplate substitution ("baptism" vs
"marriage" in a sentence) is hand-authored directly in the JS file, not piped
through from Python — it's static reference data that never varies per
request, so there was no reason to templatize it.

Each of the three collapsible `<details class="pb-section">` sections (same
collapsible shell as before, "Expand all"/"Collapse all" toolbar intact) now
shows the questionnaire followed by a **read-only** generated-text preview
scoped to that section (`#pb-role-preview`/`#pb-reference-preview`/
`#pb-format-preview`) instead of an editable textarea. This sidesteps a real
design problem: if the preview were editable, a hand-edit and a later
questionnaire-field change would fight over which one wins. Power users who
need surgical control over exact wording after creating a profile still have
it — that's what the Transcribe page's existing free-text profile editor is
for, unchanged by this rework. Three `<input type="hidden">` fields
(`role_context`/`reference_context`/`output_format`) carry the assembled text
to the existing save endpoint on submit.

**Worked examples are required, minimum 1** (`#pb-example-rows`, a repeatable
group of source/transcription/translation text, "Add another example" button)
— the Save button is disabled client-side until at least one is filled in.
This is a deliberate product choice, not a technical default: it's the
single highest-leverage element in Chiusa Sclafani v3 (show, don't just
tell), but it does mean a brand-new user with zero transcription experience
has nothing to paste in on their first profile. Not solved here — a future
"transcribe one sample, then correct it into your example" assisted flow
would close that gap, but this pass just enforces the requirement, it doesn't
help anyone meet it.

**Required-phrasing rigor is deliberately left unresolved.** Section 3 offers
suggested, fully-editable default phrasings per record type (e.g. battesimi's
"The godfather was [Name]." role-clause default) rather than v3's rigid
"these exact words or the parser breaks" discipline. That rigidity existed to
feed the dormant offline regex parser (`baptism-parser.js`), not the live
`ai_parser.py` extraction path, which tolerates phrasing drift — but whether
the *new* questionnaire-generated profiles should still enforce exact-match
phrasing is an open question pending real testing against `ai_parser.py`,
not decided in this pass. The underlying facts are collected either way, so
that decision doesn't require touching the input step again later.

**"Fill with Chiusa Sclafani v3 example answers"** (`fillChiusaSclafaniExample()`
in `static/prompt-builder.js`) reverse-engineers v3's actual prose back into
questionnaire answers for the one record type with a proven, tested example.
It's both a real feature (one concrete worked example for new users to look
at) and the main verification step for this rework: the generated
role_context/reference_context/output_format aren't byte-identical to v3
(the questionnaire generalizes some wording — e.g. "records" instead of
hardcoding "baptism registers" everywhere), but every fact v3's hand-written
prompt states should be present in the generated version. Re-check this
whenever the assembly functions change.

An older byte-for-byte check against `build_system_prompt()`/
`neutral_system_scaffold()` (back when the "Full prompt preview" mirrored a
single pre-loaded template's raw text) once caught 609 literal `\r\n` escape
sequences baked into `chiusa-sclafani-battesimi-v3.json`'s string fields —
invisible to a raw-byte scan since they were JSON-escaped text, not actual CR
bytes, but `json.loads` decodes escapes, so they became real CRLF characters
once loaded. Fixed by rebuilding the profile from source rather than
hand-patching the JSON. That specific failure mode doesn't apply to the new
design (there's no more single template being compared byte-for-byte), but
the underlying lesson generalizes: if a generated-prompt length or preview
ever looks unexpectedly short, check for JSON-escaped whitespace before
assuming a logic bug.

Saving still posts to `/prompt-builder/save-profile`
(`Handler.save_prompt_builder_profile`) → `save_custom_profile()` — always
creates a new profile (auto-suffixed `-2`/`-3` on a name collision), never
edits an existing profile in place. Editing an existing saved profile still
happens on the Transcribe page; Prompt Builder remains a creation tool, not a
full profile manager. One real regression from the rework: on a save error
(in practice, only a blank profile name, since role/reference/format can
never be empty — the fixed boilerplate blocks are always present), the page
reloads with every questionnaire answer lost, because there's no way to
reconstruct structured answers from already-assembled prose. Mitigated by a
`required` attribute on the name field, not solved.

**Both of the above — no in-place editing, and the save-error regression —
were superseded in a later session** — see "Later session: profile editing
added" near the end of this Prompt Builder section.

Same nav bar (`app.py` ×2, `xls_conversion/index.html` ×1) and same
stale-embedded-snapshot footgun as the rest of the app: Transcribe and Test
Mode read the profile list once when their page renders, so a profile saved
here needs a real reload of those tabs before it appears there — the save
banner says so.

**First round of revisions after user testing, same session:**

- **The "required-phrasing rigor" question is resolved — by deleting the
  fields, not by picking a rigor level.** Section 3 no longer asks "how
  should the parents/principal individual/role-clause be introduced" at
  all; those 3 fields (and their `phrasing_fields` config, and the
  `# REQUIRED PHRASINGS` sentences they generated) are gone. Reasoning: they
  existed to feed the dormant regex parsers, worked examples do the same
  teaching job more effectively (show beats tell), and once transcription-
  only became a real option (below) a rule about *translation* phrasing
  stopped making sense as a universal field anyway. The date-opening
  convention and the honorific-stripping rule both survive as fixed
  boilerplate, gated on whether a translation is being produced at all.
- **Translation is now an explicit, optional choice** — two checkboxes
  (English / Italian), both unchecked by default, first thing in Section 3.
  Unchecking both produces a transcription-only profile: no translation
  block in `# BLOCK STRUCTURE`, no date-opening-phrasing rule, no
  honorifics rule (that rule is about how a *translated* name reads, so
  it's meaningless without one), and the worked-example rows' translation
  textareas (`.pb-example-lang-en`/`.pb-example-lang-it`, toggled by
  `updateTranslationVisibility()` in `static/prompt-builder.js`) stay
  hidden. Checking English, Italian, or both ripples into Section 1 too —
  `buildRoleContext()`'s task sentence and `fidelityRulesBlock()` (now a
  function of the selected languages, not a fixed constant) adapt their
  wording, since both live in the same generated role_context text.
- **All checklists (relative-date vocabulary, role-clause vocabulary,
  relationship terms, common abbreviations, scribal quirks) now start fully
  checked**, styled as hollow boxes with a checkmark on select
  (`.pb-checkbox input[type="checkbox"]`, `appearance: none` + a CSS
  `::after` checkmark) instead of browser-default checkboxes — every preset
  is a plausible-by-default fact about the kind of register being
  described; unchecking one is the override, not the normal path.
- **Every lone "Add another X" text field became a proper repeatable list**
  (relative-date terms, scribal quirks, relationship terms, honorifics) —
  each now has its own `#pb-<name>-rows` container + "Add another" button,
  matching the abbreviation table's existing pattern
  (`addSimpleRow()`/`pbSimpleValues()` in `static/prompt-builder.js`). The
  single dead-end text field they replaced technically worked (its value
  was appended to the generated text) but only ever held one extra entry
  and gave no visual sign it was a list at all.
- **Name lexicon: split-on-paste to avoid pairing bias.** A new
  `nameLexiconSplit` checkbox (default on) assumes the pasted list is
  complete names ("Giuseppe de Natale") and runs `splitFullName()`
  client-side into two separate, deduplicated Surnames/Given-names lists
  before they reach the generated reference_context — matching how Chiusa
  Sclafani's own lexicon keeps the two apart. Rationale: feeding the model
  raw full-name pairs risks teaching it that a given name and a surname
  that merely co-occurred in the source list *belong together*, biasing
  toward one specific match instead of letting each name component break
  ties independently. The splitter uses the same surname-particle list as
  `ai_parser.py`'s `GENERAL_EXTRACTION_RULES` (da/dal/de/del/della/di/d'/
  la/le/li/lo) so "de Natale" stays one surname instead of losing "de" to
  the given-name half. Turning the toggle off sends the pasted text through
  verbatim, for a user who already has a properly separated lexicon.
- **"Fill with Chiusa Sclafani v3 example answers" button removed.** It
  served its purpose as this feature's main verification step (proving the
  questionnaire could reconstruct v3's actual content) and as a worked
  example for early testing, but the user asked for it gone once that
  verification was done — it's no longer part of the shipped UI. The
  `fillChiusaSclafaniExample()` function it called was deleted along with
  it, not just hidden.

**Second round of revisions, same session:**

- **Per-section "Generated text:" previews removed.** Each of the 3
  collapsible sections used to show its own read-only rendering of
  role_context/reference_context/output_format below the questionnaire;
  now only the "Full prompt preview" section (the assembled system prompt
  as actually sent to the model) shows generated text at all. The
  `pb-role-preview`/`pb-reference-preview`/`pb-format-preview` elements and
  the `pbRefresh()` lines that filled them are gone; `pb-preview-content`
  (Full prompt preview) is unaffected. Same treatment for the Section 3
  "Locator line format" hint line (`pb-locator-preview`) — the
  `locatorPreviewText()` function it displayed stays, since
  `buildOutputFormat()` still uses it to build the actual block-structure
  text, it's just not echoed as a separate standalone line anymore.
- **Checklists that need to stay unwrapped now get a purpose-built grid
  class instead of the generic auto-fit `.pb-checklist`.** New:
  `.pb-checklist-2col` (role-clause vocabulary — exactly 2 columns,
  `minmax(max-content, 1fr)` so an item never wraps). This round also
  added a 3-column `.pb-checklist-3col` for the common-abbreviation
  checklist, with `PROMPT_BUILDER_COMMON_ABBREVIATIONS`'s list order
  rearranged so the longest label landed in the one 3-column slot wide
  enough not to wrap. **Both the 3-column class and that ordering
  rationale were superseded the same session** — see "Third round of
  revisions" below, which moved the abbreviation checklist (and scribal
  quirks) onto the same `.pb-checklist-2col` class instead.
- **Marginal-heading toggle reworded** from "This register has a separate
  marginal heading zone" to "This register has a separate margin for each
  entry that states the name" — same field (`{type}_hasMarginalHeading`),
  clearer to a non-expert reader.
- **Name-lexicon splitting was already built (previous round) — only the
  UI copy was unclear.** The `nameLexiconSplit` toggle and
  `splitFullName()` already handled both "Given Surname" and "Surname,
  Given" automatically; the checkbox label read like it was asking the
  *user* to pre-split names by hand. Reworded to say explicitly that the
  app does it automatically, and the textarea placeholder now states both
  supported input orders.

**Third round of revisions, same session:**

- **Marginal-heading checkbox moved from Section 3 to the top of each
  type's Section 2 group**, with its formula textarea now living directly
  underneath it and shown/hidden by its state (`updateMarginalHeadingVisibility()`
  in `prompt-builder.js`, called on record-type switch and on the checkbox's
  own `input` event via a `.pb-marginal-toggle` class hook). This puts "does
  this register have one" and "what does it look like" next to each other
  instead of in different sections, and the checkbox now doubles as the
  optional/required signal for the field below it — so the field's label
  changed from "Marginal heading formula (optional — leave blank if this
  register has none)" to a plain "Marginal heading structure", the note
  deleted as redundant. `pb_section3_type_group_html()` (which rendered
  only this checkbox) and the `{section3_type_groups}` placeholder are gone
  entirely — Section 3 has no per-type content left. The field name
  (`{type}_hasMarginalHeading`) and the formula's (`{type}_formula_marginalHeading`)
  are unchanged, so `buildOutputFormat()`/`buildReferenceContext()` needed no
  changes beyond the new visibility wiring — both already look these up by
  `[name="..."]`, not by DOM position. Civil types (which default this
  checkbox unchecked) got a new `marginal_heading_placeholder` config value
  too, so checking the box on a civil type still shows a sensible formula
  field instead of an empty one meant only for church registers.
- **Formula textareas switched from a `placeholder` attribute to live,
  pre-filled, directly editable text.** Previously the sample formula
  (`Ego Sac.os D. [CELEBRANT] ... hodie baptizavi...`) was grey hint text
  that vanished the moment the user typed anything, forcing them to
  reconstruct the whole bracketed-slot pattern from scratch. Now it's the
  textarea's actual starting value — `pb_formula_fields_html()` puts the
  sample text between `<textarea>` tags instead of in a `placeholder=`
  attribute — so the user edits a working example in place. Applied to
  every formula field (marginal heading, body, groom, bride, witness, act),
  not just the one the request named ("Body Formula"), since leaving some
  fields as vanishing placeholders and others as live text would be an
  inconsistent pattern for no reason. Side effect, intentional: if a user
  saves without touching one of these fields, the generic template text
  becomes the profile's real formula rather than an empty field — a better
  default than nothing. No i18n impact: `TEXTAREA` is in `i18n.js`'s
  `SKIP_TAGS`, so this content was never translated either as a placeholder
  or now as a value, which is correct since these formulas are written in
  the register's own historical language, not English UI copy.
- **"Body formula" relabeled to "Entry structure - write out the structure
  used in each entry"** for battesimi and morti (the two types that have a
  body-formula field at all) — more instructional for a first-time user
  than the bare noun phrase it replaced. Groom/Bride/Witness/Act formula
  labels were left as-is; only "Body formula" was named in the request.
- **Abbreviation key and Scribal quirks both moved onto `.pb-checklist-2col`.**
  Round 2's dedicated `.pb-checklist-3col` class, and the abbreviation
  list's "D. placed last to land in the 3-column middle slot" ordering
  rationale, are both gone — see the correction in "Second round of
  revisions" above. Two columns turns out to solve the original
  non-wrapping requirement more simply than a specially-ordered 3-column
  grid did: at 2 columns each column is wide enough for the longest label
  regardless of which row it falls in, so there's no longer a "one correct
  position" for any item. 8 abbreviations now render as 4 full rows of 2;
  5 scribal quirks as 2 full rows plus a single trailing item. Verified via
  `getBoundingClientRect()` that both grids place their items in the
  expected rows with zero line-wrapping, including the (unmoved) "D. = Don /
  Dominus (courtesy title for clergy and gentry)" item.
- **`nameLexiconSplit` checkbox deleted; splitting is now unconditional.**
  The toggle asked the user to confirm the pasted lexicon was made of full
  names before `splitFullName()` would run — a decision the app can already
  make itself for any register, so the checkbox was pure friction. Deleted
  the checkbox, its label, and the `splitMode`/`splitToggle` branch in
  `buildReferenceContext()` (`static/prompt-builder.js`); the given/surname
  split (and its "these are NOT paired combinations" note) now always runs
  when the Name lexicon field is non-empty. `i18n.js`'s translation entry
  for the deleted label was removed too.
- **"Honorifics kept inside a role clause" explained inline, no code
  change**: the checked honorifics (Don, Master, plus anything added) are
  the only titles allowed to stay attached to a name inside an
  introducing phrase like "The godfather was Don Carolus Calsi"; any other
  title the source mentions (Doctor, Reverend, a religious order, …) gets
  moved out to the Notes block instead, so the role clause keeps a
  predictable shape a downstream reader (or the AI itself, on a later
  pass) can rely on. Only matters when a translation is being produced —
  a verbatim transcription has no "clause" to keep clean.

**Fourth round of revisions, same session — info-button popups added.**
The request asked for explanatory "info bugs" (small (i) buttons that reveal
a popup) after five specific fields, plus three unrelated wording/behavior
tweaks. New shared building block: `pb_info_button_html(panel_id, text)` in
`app.py` emits a `<button class="pb-info-btn" aria-expanded aria-controls>`
next to a `<span class="pb-info-panel" role="note" hidden>` holding the
text; `wireInfoButtons()` in `static/prompt-builder.js` (delegated on
`document`, so it needs wiring only once) opens one panel at a time —
opening a second closes the first — and closes on outside click or Escape,
with `aria-expanded` kept in sync for screen readers.

- **Declension checkbox** ("Include Latin grammatical case-declension
  guidance") gets one, explaining what Latin case declension is with a
  worked example (Franciscus/Francisci/Francisco) and why the same name
  legitimately taking different forms in one entry isn't a spelling error.
  This checkbox was the first spot an info button sat next to a
  `.pb-checkbox` rather than a `<p class="hint">` — the two needed
  different fixes to lay out on one line (two more checkboxes later got
  the same treatment: confidence-rationale in round 5, marginal-heading
  in a follow-up — see below; the `.pb-inline-row` fix this round
  established is what both of them reused). First attempt changed
  `.pb-checkbox` itself to
  `inline-flex`, which broke: an inline-level flex box's shrink-to-fit width
  is computed from the *remaining horizontal space on its line*, not its
  content's natural width, so at this checkbox's position that resolved to
  ~112px and the label text wrapped across six lines. Fixed by reverting
  `.pb-checkbox` to plain `flex` (its original value, correct everywhere
  else it's used) and instead wrapping just this one checkbox + button pair
  in a new `.pb-inline-row` flex container (`display:flex; align-items:
  center`), with `.pb-inline-row .pb-checkbox { flex: 0 0 auto }` so the
  checkbox sizes to its own content as a flex *item* of a container with
  real available width, not as a bare inline box guessing at line space.
  Verified via `getBoundingClientRect()` afterward that this didn't regress
  the `.pb-checklist-2col` grids (abbreviations, scribal quirks, role
  vocab) — they're a separate CSS context and were never at risk, but it's
  the kind of change worth re-checking given how fiddly this turned out.
- **Role-clause vocabulary** (all 6 record types, not just the Church
  Battesimi example in the request — same reasoning as every other
  per-type UI element in this page: one type getting a feature and the
  other five not would be an arbitrary inconsistency) explains that these
  are the register's own words for entry roles (e.g. "P.nus" vs "PP." for
  one vs. multiple godparents) and that checking one teaches the AI to
  recognize and use it correctly.
- **Scribal / paleographic quirks** explains the concept in one sentence
  with two concrete examples (long ſ misread as f, macron marking a
  dropped letter) and why checking them helps — so the AI doesn't misread
  a normal habit of the hand as an unfamiliar name.
- **Name lexicon**: relabeled from "Name lexicon (optional)" to "Name
  lexicon" (the field already reads as optional from context; the parenthetical
  was redundant once an info button exists to explain it), its old always-
  visible hint paragraph ("Adding a lexicon greatly increases...") moved
  verbatim into the new info button instead of staying as permanent page
  furniture, and its placeholder text tightened to "Paste known family
  names and given names - either as "Given Surname" or "Surname, Given
  name"" per the exact wording requested. Needed one structural fix beyond
  the button itself: this label uses the page's generic `label { display:
  grid }` rule (text on row 1, the control on row 2), so appending the
  info button as a bare sibling after the label text would have landed it
  on its own grid row below the text and above the textarea. Fixed by
  wrapping just the "Name lexicon" text and the button together in an
  explicit `<span>`, which becomes row 1 as a single item with both
  contents flowing inline inside it.
- **Translation hint reworded** from "Translation — leave both unchecked
  for a transcription-only profile with no translation at all" to
  "Translation is optional — leave both unchecked for a transcription-only
  output with no translation at all" (leads with "optional" instead of
  making the reader infer it, and "output" instead of "profile" since the
  sentence is describing what gets produced, not the saved profile itself).
- **Honorifics section gets an info button** with the explanation of what
  a "role clause" is (same content given inline in this session's own
  answer to the equivalent question, now placed in the UI), **and the
  entire section is now hidden unless a translation language is
  checked** (`#pb-honorifics-section`, toggled in
  `updateTranslationVisibility()`). This isn't a new behavior so much as
  making the UI match logic that already existed: `buildOutputFormat()`
  has always nested the honorifics-rule sentence inside `if (langs.length)`
  — a translation-only rule about how a name reads in translated prose —
  so a honorifics checkbox with no translation selected already had zero
  effect on the generated prompt. Hiding it now makes that dead-end
  visible before the user wastes a click on it, not after.

**Fifth round of revisions, same session:**

- **Relative-date vocabulary moved onto `.pb-checklist-2col`**, same
  treatment as the abbreviation key and scribal quirks in the third round.
  5 terms now render as 2 full rows plus a single trailing item, verified
  non-wrapping via `getBoundingClientRect()`.
- **Two wording tweaks**: Section 1's fixed-boilerplate sentence now ends
  "...no matter what you select below" (was "...answer above" — stale
  once the per-section preview panels were removed in round 2, since
  "above" no longer pointed at anything on the page); the page's top
  sub-heading was rewritten from a longer sentence explaining the preset/
  free-text split to a shorter, more direct one ("Pick from presets below
  to describe your register...") that also states the reload requirement
  as an instruction ("you must reload those pages first") rather than a
  parenthetical aside.
- **Confidence-rationale checkbox gets an info button**, explaining what
  the High/Medium/Low + one-line-reason rule actually produces and why
  it's useful (a fast way to spot entries worth a second look). Needed
  the same `.pb-inline-row` wrapper fix as the declension checkbox in the
  fourth round, for the same reason (a bare `.pb-checkbox` can't safely
  sit inline next to a following sibling). **This checkbox was removed
  entirely in a later session** — see "Later session: profile editing
  added" near the end of this Prompt Builder section.
- **Worked Examples section deleted outright** — the hint paragraph, the
  repeatable source/transcription/translation row group, the "Add another
  example" button, and the requirement that gated the Save button on
  having at least one filled in. Removed the matching JS:
  `collectExampleRows()`, `addExampleRow()`, the `# WORKED EXAMPLES` block
  in `buildOutputFormat()`, the save-button disable/title logic in
  `pbRefresh()`, and the `.pb-example-lang-en`/`.pb-example-lang-it`
  toggling that used to live in `updateTranslationVisibility()`. **This is
  specifically the old *repeatable, multi-row* group — a separate, single,
  non-repeatable "Example entry" field (`textarea name="exampleEntry"`)
  still exists in `app.py` and is still consumed by `buildOutputFormat()`
  via `pbVal("exampleEntry")`; it was never part of this deletion.** The
  stance going in was that output formatting (locator line with image
  filename/number, the per-entry block headers, the no-line-break
  protocol, blank-line spacing between blocks) is already fully specified
  by `# BLOCK STRUCTURE` and the other fixed rules `buildOutputFormat()`
  assembles from the questionnaire's own answers — none of that actually
  depended on a worked example.
  **That's true, and format compliance doesn't regress.** But it's only
  half of what worked examples were doing. The other half — calibrating
  the AI's actual *transcription and translation judgment* against this
  specific register's paleography and phrasing register (how literal to
  be, what a borderline-legible letterform should resolve to, how terse
  or expansive a translation should read) — has no boilerplate substitute;
  nothing else in the questionnaire shows the AI a real correct answer to
  pattern-match against. This was flagged in the original build (see
  "Worked examples are required, minimum 1" above) as "the single
  highest-leverage element in Chiusa Sclafani v3 (show, don't just
  tell)" — that assessment doesn't change with this deletion, only the
  UI's insistence on collecting one. A user who wants that benefit back
  still can: the Transcribe page's free-text profile editor can append a
  worked example to `reference_context` or `output_format` by hand after
  saving, same as any other post-hoc edit to a generated profile.

**Follow-up, same session: marginal-heading checkbox gets an info button
too.** User flagged (correctly) that this checkbox never got one, despite
sitting right next to declension and confidence-rationale, which did.
Added `pb_info_button_html()` for all 6 record types (same
`.pb-inline-row` wrapper as the other checkbox-adjacent buttons), text
explaining what a marginal heading is and why the transcription keeps it
as its own block separate from the entry body (the two occasionally
disagree, and both readings are worth preserving — same reasoning as the
Chiusa Sclafani v3 Marginal Heading rework earlier in this file). Also
confirmed, while investigating the report: the field's `23px` left
indent (`.pb-marginal-formula`) under its checkbox is intentional, not a
bug — it's sized to the checkbox's own 16px width + 7px gap so the
formula field visually nests under the checkbox's label text.

**Later session: profile editing added; confidence-rationale checkbox
removed.** Two changes that make some of the text above stale, noted here
rather than edited in place so the history above stays an accurate record
of what actually happened at the time:

- **Prompt Builder can now load a previously-saved profile back in and edit
  it**, instead of only ever creating new ones. Saving from Prompt Builder
  now writes the questionnaire's structured answers into the profile JSON
  too (`pb_answers`, alongside the three prose fields), and a "Load an
  existing profile to edit" selector at the top of the page replays that
  snapshot into every field, checklist, and repeatable row. "Update
  Profile" (`update_full_profile()` in `app.py`) overwrites the loaded
  profile in place, by id — renaming is safe, since the file is keyed by
  id, not label; "Save as New Profile" forks it instead. **This
  supersedes the "Saving... always creates a new profile... never edits
  an existing profile in place" statement above** (from the original
  rework, before this feature existed) and **fixes the "real regression"
  noted above it** (a failed save used to wipe every questionnaire
  answer; a failed save now restores the submitted answers, and which
  profile was being edited, via the same `pb_answers` snapshot).
- **The Confidence-rationale checkbox (Fifth round, above) was removed
  entirely** at the user's request — the checkbox, its info button, and
  the `Confidence: High/Medium/Low` boilerplate sentence it added to
  generated prompts are all gone from `app.py` and
  `static/prompt-builder.js`, along with the sentence itself from the one
  already-saved profile that had it baked in
  (`profiles/grimaldi-church-morti-v1.json`).

## Accessibility (WCAG)

Page `<h1>` titles: Transcribe = "Customizable Transcription", XLS Conversion =
"XLSX Conversion" (nav label matches), Test Mode = "Test Mode" (shortened
from "Test Mode: Model Comparison" in a later pass so the Italian translation
stays on one line at normal width), Prompt Builder = "Prompt Builder". The
XLS Conversion page's
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
