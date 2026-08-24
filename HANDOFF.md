# Customizable Transcription Interface Handoff

## To-Do — Next Session (added 2026-08-23)

Add a **Privacy** link to the footer on all four pages (Transcribe, Test Mode,
Prompt Builder, XLS Conversion — same 4 places the license footer text
already lives, `app.py` ×3 + `xls_conversion/index.html` ×1), pointing to a
full in-app disclosure page.

Context: `PRIVACY.md` (repo root) is the written data-processing/GDPR notice,
and the three API-key field hints now say "see PRIVACY.md" — but nothing in
the running app actually links there, so a user reading that hint has no way
to reach it without leaving the app and finding the raw file on GitHub/disk.
Needs an actual route (e.g. `/privacy`) that renders `PRIVACY.md`'s content
as a real page — reuse the doc's markdown as the source of truth rather than
duplicating its text into `app.py`, so the two can't drift out of sync the
way CLAUDE.md and the code did earlier this session. A simple `markdown`
render step, or even a plain `<pre>`-wrapped read of the file, would satisfy
"opens to a full disclosure" without needing a rich renderer.

(Note, unrelated to the above: the rest of this HANDOFF.md is stale — it
describes an old model list and an outdated "don't commit to GitHub without
asking" instruction that no longer reflects how this project actually works.
Worth a real rewrite pass sometime, not done here due to context budget.)

## Current State

This project is a local Python web app running at:

```text
http://127.0.0.1:8765
```

Launch command:

```bash
cd path/to/Transcription-Bot && .venv/bin/python app.py
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

Current development is saved locally as WIP/dev only. Do not commit or push this state to GitHub until the user explicitly asks.

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
We are continuing work on the local Customizable Transcription Interface app at path/to/Transcription-Bot. Read HANDOFF.md first. Current state is local WIP/dev only; do not commit or push to GitHub unless explicitly asked. The app uses saved JSON prompt profiles, recursive chronological source scanning from a user-selected source folder, JPEG/PNG/PDF file-type radio selection with preflight source-folder checks, model selection, a per-run Gemini API key field, compact oldest/newest process-order radio controls with oldest-to-newest as the default, a Reset button beside Source folder, a Preflight Check plus disabled-by-default `Confirm and run` flow with an always-visible `Confirm settings` box, visually separated profile-editing controls below the run area, automatic status updates, a stop button, incremental `.md` output, and timestamped `.docx` output. Next task: continue UI/testing refinements or add a user-friendly feature to transform raw pasted ground-truth material, such as a long unformatted list of names, into structured profile reference content before saving. Please inspect the current code and continue from the handoff.
```
