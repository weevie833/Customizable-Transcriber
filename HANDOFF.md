# Customizable Transcription Interface Handoff

## To-Do — Next Session

**Test Mode: add XLSX comparison, not just DOCX.** Test Mode currently only
compares candidate *transcripts* (DOCX) against a corrected DOCX — see
`test_mode/comparison.py`'s `score_transcription()`. The ask is to extend
Test Mode so it can also compare the *XLSX conversion output* (spreadsheet
index rows produced by `xls_conversion/ai_parser.py`) against a corrected
XLSX, not just the transcription stage. Needs scoping next session: what a
row-level/cell-level accuracy metric looks like for a spreadsheet (vs.
CER/WER for text), how it fits into the existing batch/model-pair UI, and
whether it's a new comparison mode alongside the DOCX one or a second stage
after it.

## Committed 2026-09-01: product rebrand, "Transcription Bot" → "Customizable Transcription"

Full rebrand, not just the GitHub repo name — see CLAUDE.md's "Product
rename" section for the complete list. Summary:

- Python package `transcription_bot/` → `customizable_transcription/`
  (directory + every import).
- User-data directory renamed (`~/Library/Application Support/Transcription
  Bot/` → `.../Customizable Transcription/`, similarly on Windows/Linux),
  with a one-time self-healing migration in `ensure_profiles_dir()` so
  existing installs' saved profiles move automatically on first run rather
  than being orphaned. **Verified on this actual dev machine**: the real
  `~/Library/Application Support/Transcription Bot/` directory (8 saved
  profiles, including `chiusa-sclafani-battesimi-v4`) migrated cleanly on
  server restart; app listed all profiles correctly afterward.
- Import/Export format identifier changed to `"customizable-transcription-
  profile"`, with the old `"transcription-bot-profile"` string kept as
  `PROFILE_EXPORT_FORMAT_LEGACY` and still accepted on import — verified a
  synthetic old-format `.tbprofile.json` still imports cleanly.
- Local project folder and the GitHub repo (`weevie833/Transcription-Bot` →
  `weevie833/Customizable-Transcription`) renamed; local `origin` remote
  updated to match.
- README.md, CLAUDE.md, this file, and `GETTING_STARTED.html`/`.it.html`'s
  app-data-folder examples all updated. `profiles/worksheets/build.js`'s
  DOCX `creator` metadata updated and the shipped
  `static/prompt-builder-worksheets/*.zip` worksheets rebuilt so the change
  reaches the actual downloadable files, not just the source script.
- `VERSION` bumped `0.1.0` → `0.2.0` (structural rename + migration, not a
  breaking change from the user's own perspective since it self-migrates).

## Committed 2026-08-31

Everything in this file marked "Not yet committed" below (profiles/settings.json
removal, rendi-* retirement, Chiusa Sclafani v3→v4, Import/Export Profiles, nav
order + i18n audit, user profiles moved out of the repo) was committed and
pushed to origin/main in this session, along with this session's own work:

- **Prompt Builder Preflight Test now accepts PDF, not just JPEG/PNG** —
  format is sniffed from the file's own leading bytes (`sniff_file_type()` in
  `transcription_bot/core.py`), not trusted from the filename extension, so a
  mislabeled upload is handled correctly instead of silently sent to the AI
  provider under the wrong MIME type.
- **Prompt Builder's top panel redesigned**: "Create a new profile" and "Load
  an existing profile to edit" are now side-by-side equal-height panels
  (`.pb-top-split`); Expand all/Collapse all/Reset form moved to their own row
  above Section 1; Download DOCX floated up under the Create panel's title.
- **Getting Started page (`/getting-started`) built out** from a placeholder
  stub to full bilingual content — 7 collapsible sections, content sourced
  from `GETTING_STARTED.html`/`GETTING_STARTED.it.html` (new files at the repo
  root, plain HTML fragments) rather than inline in `app.py`, specifically so
  the user can edit the text directly without touching page-shell code. Links
  to AI Studio/Claude's Platform dashboard match the homepage Overview's
  hrefs; the Italian Parish Records mention links to their indexing-guide URL.
- **Version number added to every page's footer**, after the Privacy link.
  Single source of truth is a new root `VERSION` file (SemVer, currently
  `0.1.0`), served via `GET /version` and filled into `#app-version` by
  `static/i18n.js` on every page load — including the static
  `xls_conversion/index.html`, which has no Python templating of its own.
  Deliberately not git-derived (commit hash/tag): real end users run a
  downloaded-and-unzipped copy with no `.git` directory. **Convention going
  forward: bump `VERSION` per SemVer (MAJOR.MINOR.PATCH) as part of each
  commit to main** — saved as a standing memory so this isn't forgotten.

## Done this session (2026-08-30): profiles/settings.json removed

User asked what it was for. Traced every read site: it was write-only in
practice — recorded the last-used profile on each run, but nothing ever
read that value back (the profile dropdown always starts empty on
purpose, to prevent an accidental run with the wrong profile). Its only
other use, a self-cleanup check in `delete_profile()`, had no visible
effect either once nothing consumed the value. Removed entirely at the
user's choice: `PROFILE_SETTINGS_FILE`, `save_selected_profile_id()`, and
all 5 of its call sites deleted from `app.py`; the file itself deleted
from disk; the now-unnecessary `.gitignore` entry removed.
`load_custom_profiles()` still defensively skips a file literally named
`settings.json` so a stale leftover on an existing install can't be
mistaken for a profile. README/CLAUDE.md updated to match; verified the
app starts and all three pages load with no errors, and that a stray
`settings.json` on disk is still correctly ignored. Not yet committed.

## Done this session (2026-08-30): rendi-* shipped examples deleted by user

The user deleted all 5 `profiles/rendi-*.json` files directly (outside the
app) — obsolete now that new profiles are built through the Prompt Builder
questionnaire — and archived them separately in case they're ever needed
again. `profiles/` now ships zero example profiles.

This surfaced and fixed a real bug: `load_profile()` used to fall back to a
hardcoded `DEFAULT_PROFILE_ID = "rendi-battesimi"` when a requested id
wasn't found; with that file gone, the fallback itself failed, turning any
missing-profile lookup into a hard "No prompt profiles are available" error
even though other profiles (e.g. Chiusa Sclafani v4) existed. Now falls back
to whichever profile happens to be first in the list instead. Verified via
a direct `load_profile()` call with a bogus id — resolves cleanly to an
existing profile. `DEFAULT_PROFILE_ID` removed as dead code.

README's "Saved profiles" section and CLAUDE.md's "Profile storage" section
updated to stop naming specific shipped profiles that no longer exist. Not
yet committed.

## Done this session (2026-08-30): Chiusa Sclafani v3 retired, replaced by v4

**Next step, not yet done:** run a real Preflight Test (or a full batch) with
`chiusa-sclafani-battesimi-v4` against actual register images before relying
on it for real work — it's verified structurally and via round-trip, but has
no real-image test history yet, unlike v3 (see CLAUDE.md's "v3 real-image
test results" section, images 193-195).

v3 was the one profile in the app with no `pb_answers` — a bespoke
`build_prompt.py` script, not editable back in Prompt Builder, inconsistent
with every other profile. Rebuilt field-by-field through the actual
questionnaire UI (driven via injected JS, so the real client-side assembly
code produced the prose, not a hand-simulated approximation); added a new
"Additional editorial rules" field to the questionnaire for the handful of
v3 rules (filius/filia cross-check, marginal-heading-disagreement, never-
copy-a-surname, etc.) that didn't fit any existing field. Also fixed a
separate bug found along the way: v3's shipped file still had the literal
unsubstituted `{VOLUME_YEAR_RANGE}` placeholder in its role_context.

`chiusa-sclafani-battesimi-v1/v2/v3.json` and all of
`profiles/sources/chiusa-sclafani/` (build_prompt.py, clean_index.py,
lex.json, the cleaned-index xlsx, the corrections audit, the readable copy)
were deleted at the user's request — staged (`git rm`), not committed. Full
mapping and what didn't transfer: CLAUDE.md's "Chiusa Sclafani battesimi —
decisions" section, "Superseded, later session" note.

## Done this session (2026-08-30): Import/Export Profiles

New collapsible panel on the Prompt Builder page, below the questionnaire's
Save controls: export any saved profile as a small `.tbprofile.json` file
(plain JSON, no macros/executable content — deliberately email-safe, not on
any mail provider's blocked-attachment list), and import one someone sends
you back in. Import always adds a new profile (auto-suffixed on a name
collision), never overwrites one you already have. See CLAUDE.md's
"Later session: Import/Export Profiles" note (end of the Prompt Builder
section) for the file format, endpoints, and what was verified.

Not yet committed.

## Done this session (2026-08-30): nav order + Prompt Builder i18n audit

- **Header nav reordered** on all 4 pages (`app.py` ×3 + `xls_conversion/index.html`)
  to Prompt Builder, Transcribe, XLSX Conversion, Test Mode. `aria-current="page"`
  preserved on each page's own link.
- **Audited `static/i18n.js`'s Italian coverage against the live Prompt Builder
  page** (rendered the page, extracted every visible text node/placeholder/
  title/aria-label, diffed against `DICTIONARY`'s keys) and fixed real gaps,
  mostly from the Preflight Test feature and civil-record fields that landed
  without matching translations:
  - Added ~22 missing entries: the whole Preflight Test UI ("Example entries",
    "Add another example" + its dynamically-added row placeholder, "Preflight
    Test", "Run Preflight Test", the API-key hint variant, "Suggestions --
    check the ones...", etc.) and the civil-record Page format/act-continuation/
    baptism-column fields and their info-button text.
  - Found and fixed **3 stale dictionary entries**: the civil birth/marriage/
    death Marginal Heading info-button text has 3 translations keyed to an
    *old* placeholder wording (no `Numero [Act #]` prefix, "and" instead of
    "e") that no longer matches any live string — the placeholders were
    changed after the translations were written. Replaced with the 3 correct,
    currently-live variants.
  - Bonus find, not Prompt-Builder-specific: the shared footer's license
    sentence (`app.py` ×3, `xls_conversion/index.html`) has silently stopped
    translating on **all 4 pages** since the `/privacy` link was added — the
    footer's actual DOM text node is the license sentence *plus* the trailing
    "&middot;" separator before the Privacy link, which no longer exact-matched
    the dictionary key (missing that trailing "·"). Fixed both the long and
    short license-string dictionary entries to include it.
  - Confirmed non-issues, left alone: `JPEG`/`PDF`/`PNG` (format acronyms,
    same in both languages), `Don`/`Master` (literal honorific terms the
    model must recognize verbatim in the source, not UI copy), the "0 words"
    live counter and the worksheet-download button/caption (both already
    correctly excluded from DICTIONARY by design, per comments already in
    the code), the language-toggle button labels (English/Italiano are
    correctly untranslated proper nouns), and "Privacy" (identical in both
    languages, so its absence from DICTIONARY is a no-op, not a bug).
  - Verified via a fresh server render + re-diff: 0 unexplained gaps remain
    on any of the 4 pages.

Not yet committed — see the note at the end of the entry below.

## Done this session (2026-08-30): user profiles moved out of the repo

Fixed a real data-loss risk: this app's documented update process is
"download a fresh copy, replace the old folder" (no git pull), and every
saved profile — shipped examples and anything a user created — used to live
in the same git-tracked `profiles/` folder. A full folder replace would have
silently deleted any profile a user had made.

Now: `profiles/` stays git-tracked and ships only reference examples
(`rendi-*`, `chiusa-sclafani-*`); every profile saved or edited through the
running app writes to a new per-OS external directory instead (macOS
`~/Library/Application Support/Customizable Transcription/profiles/`; see
CLAUDE.md's "Profile storage: shipped examples vs. user data" section for
the Windows/Linux paths and the full design). Six profiles that were real
working profiles rather than shipped examples (`caiazzo-matrimoni-v1`,
`grimaldi-church-morti-v1`/`-v2`, `marano-marchesato-catasto-v1`,
`montalto-uffago-morti-v1`, `san-mango-d-aquino-marriages-v1`) were moved
there and `git rm`'d from the repo — staged, not committed. Verified the app
starts clean and lists all 6 relocated profiles correctly alongside the
shipped ones. README's "Saved profiles" section and a new "Updating to a
newer version" section now explain this to end users.

Not yet committed — review `git status`/`git diff` before committing/pushing
per the standing instruction below.

(The old "add a Privacy link" to-do that lived here is done — see `/privacy`.
The rest of this HANDOFF.md below "Current State" describes an old model
list and workflow from early in the project; kept as history, not current
behavior — CLAUDE.md is the up-to-date working reference.)

## Current State

This project is a local Python web app running at:

```text
http://127.0.0.1:8765
```

Launch command:

```bash
cd path/to/Customizable-Transcription && .venv/bin/python app.py
```

The app uses Gemini to transcribe local archival images from a source folder chosen via
a native folder-picker dialog (Transcribe and Test Mode pages both have a `Browse…`
button beside the Source folder display, which reads "No folder selected" until one is
picked). The picker calls `pick_source_folder_dialog()` in `app.py`, which dispatches by
`platform.system()` to a native dialog run as a separate OS process — `osascript` on
macOS, PowerShell's `System.Windows.Forms.FolderBrowserDialog` on Windows, `zenity` on
Linux (with a clear error if zenity isn't installed) — because there is no browser-side
way to get an absolute filesystem path for backend `Path` access, so this has to be a
real native dialog, not an HTML file input. There's also a manual-entry fallback (a text
field + "Use this path" button next to Browse) for any platform/setup where the native
dialog isn't available. The chosen path is persisted to `app_settings.json` (gitignored,
machine-specific) via `save_source_folder()`/`load_source_folder()`, so it survives
restarts. **There is deliberately no hardcoded personal-path default** — this app is
shared across users on different machines, so `load_source_folder()` returns `None` until
someone actually picks a folder, and every run/preflight path refuses to run with a clear
error ("Choose a source folder before running") rather than silently falling back to
someone else's path. Every place that used to read the old hardcoded `SOURCE_FOLDER`
constant now calls `load_source_folder()` fresh, so a folder picked from either page takes
effect immediately without a server restart.

The Windows and Linux code paths are implemented per the same pattern as the working
macOS one but have not been run on an actual Windows or Linux machine — only exercised
via code review and the macOS path's live behavior. Worth a real test on both before
distributing to non-Mac users.

It creates timestamped `.docx` output in `outputs/` and also writes an intermediate timestamped `.md` file.

Commit/push policy: only when the user explicitly asks (see CLAUDE.md's global instructions) — not a blanket "never commit."

## Current Workflow

The former top-level mode buttons have been removed. Runs are now driven by saved prompt profiles in `profiles/`. The Rendi profiles were migrated from the old `.md` prompts into JSON files and behave like user-created custom profiles.

Current saved profiles include:

- `profiles/rendi-battesimi.json`
- `profiles/rendi-morti.json`
- `profiles/rendi-matrimoni.json`
- `profiles/rendi-generic.json`

`profiles/settings.json` stores the last selected profile and is ignored by git, but the UI now starts with `Select a Profile` so users must actively choose a profile before running a batch.

Each profile has these editable plain-text sections:

- `role_context`: Role plus tone/style/local context.
- `reference_context`: Ground truth, taxonomy, names, places, formulas, dictionaries, and other reference material.
- `output_format`: Output structure plus transcription/translation examples.

The UI shows these sections as plain text, not raw JSON. The app handles JSON escaping and formatting when saving, so brackets, quotes, commas, and long pasted text do not break profile-file syntax.

## Profile Saving

The UI has a `Save Profile` button beside `Save new custom profile as`.

- If the profile name field is blank, `Save Profile` prompts the user to replace the selected profile or save a new named version.
- If a new name is entered, `Save Profile` creates a new reusable profile.
- If the entered name matches an existing profile, the browser prompts the user to replace the existing profile or create a renamed new version.
- Backend save logic also supports explicit replacement so direct POSTs behave predictably.

If edited profile boxes are submitted with `Run transcription`, the app still prompts the user to update the selected profile or save a new named version before running.

## API Key Handling

The web UI now includes a `Gemini API key` field beside the model dropdown. A user must paste their own key before `Run transcription` is enabled. The pasted key is used as a runtime override and is not saved to project files. The app validates the key/model combination with a small preflight request before starting the image batch.

Private local use can still rely on `.env`, but `.env` is ignored by git and should not be committed.

## Source File Type And Ordering

The source scanner in `transcription_bot/core.py` recursively scans source files in subdirectories, parses date folder names like `1786 December 2`, sorts chronologically, and includes relative source paths in output record headers.

The web UI now has a compact file-type radio selector beside process order:

- `JPEG`: processes `.jpg` and `.jpeg`.
- `PNG`: processes `.png`.
- `PDF`: processes `.pdf`.

The selected file type is passed into `TranscriptionConfig.source_extensions`, so the batch only processes the selected type. A preflight check counts files in the currently-picked source folder (see above) before the Gemini key check. If the selected type is not present, the run stops early with a clear message showing available JPEG/PNG/PDF counts.

The web app has compact process-order radio controls:

- `Oldest-to-newest`: default; oldest record appears first in the output document.
- `Newest-to-oldest`: most recent record appears first in the output document.

The UI shows a small explanatory hint that changes when the user selects either order. A `Reset` button sits beside the Source folder and restores default settings, returning the prompt dropdown to `Select a Profile`. The run flow now uses a `Preflight Check` button and a disabled-by-default `Confirm and run` button directly underneath it. Clicking `Preflight Check` without a Gemini API key or selected prompt profile shows a centered audible alert instead of only writing to the progress console. With valid settings, `Preflight Check` fills the always-visible `Confirm settings` box with the selected order, file type, and prompt profile, disables `Preflight Check`, and enables `Confirm and run`. The batch starts only after `Confirm and run` is clicked. The profile-editing controls below the run area are separated by a divider and pale grey background to keep configuration decisions visually grouped above.

## Model Selection

The web app uses a Gemini model dropdown:

- `gemini-3.5-flash`: default, faster/lower cost.
- `gemini-3.1-pro-preview`: higher accuracy.

## Run Control

The web page polls `/status` while a run is active, so the log and summary update automatically. The Progress Console `Refresh Status` control also calls `/status` directly and updates only the console/download area; it does not reload the whole page or reset the main form.

A `Stop` button requests cooperative cancellation. If Gemini is already processing an image, the current request is allowed to finish. A partial `.docx` is generated from the `.md` content already written.

## Key Files

- `app.py`: local web app, profile dropdown/editor, profile saving, API key field, model dropdown, compact order and file-type radio selectors, source-type preflight checks, stop/status/download flow, `.docx` generation.
- `transcription_bot/core.py`: Gemini client, runtime API key override, recursive source discovery for selected JPEG/PNG/PDF extensions, date-aware sorting, cancellable batch transcription, output cleanup.
- `profiles/`: saved JSON prompt profiles.
- `README.md`: setup and usage notes.
- `.env`: local Gemini API key, ignored by git.
- `.env.example`: template for the API key.

## To-Do For Next Session

- Replace the hardcoded source-folder display with a user-facing source-folder picker so users can navigate to their source folder before running.
- Later, consider adding less-common file types such as WebP/TIFF/HEIC if needed.

Add a profile-assistant feature that can take raw pasted ground-truth material, such as a long unformatted list of names, and transform it into structured profile content before saving. The current app saves pasted ground truth safely as plain text inside JSON, but it does not parse or convert the content into structured JSON dictionaries automatically.

Possible design:

- Add a `Structure Ground Truth` or `Format Reference Material` button near the Ground Truth panel.
- Let the user choose a target type such as surnames, given names, place names, abbreviations, formulas, or mixed reference notes.
- Convert raw lines into a predictable structured text or JSON-like dictionary inside the plain-text panel.
- Preview the structured result before replacing the Ground Truth panel content.
- Keep the saved profile JSON syntax protected by app-side serialization.

## Prompt For Next Session

Use this prompt to continue:

```text
We are continuing work on the local Customizable Transcription Interface app at path/to/Customizable-Transcription. Read HANDOFF.md first. Current state is local WIP/dev only; do not commit or push to GitHub unless explicitly asked. The app uses saved JSON prompt profiles, recursive chronological source scanning from a user-selected source folder, JPEG/PNG/PDF file-type radio selection with preflight source-folder checks, model selection, a per-run Gemini API key field, compact oldest/newest process-order radio controls with oldest-to-newest as the default, a Reset button beside Source folder, a Preflight Check plus disabled-by-default `Confirm and run` flow with an always-visible `Confirm settings` box, visually separated profile-editing controls below the run area, automatic status updates, a stop button, incremental `.md` output, and timestamped `.docx` output. Next task: continue UI/testing refinements or add a user-friendly feature to transform raw pasted ground-truth material, such as a long unformatted list of names, into structured profile reference content before saving. Please inspect the current code and continue from the handoff.
```
