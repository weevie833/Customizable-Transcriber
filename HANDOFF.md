# Customizable Transcription Interface Handoff

## Current State

This project is a local Python web app running at:

```text
http://127.0.0.1:8765
```

Launch command:

```bash
cd "/Users/stevecovello/Documents/Codex/Transcription Bot" && .venv/bin/python app.py
```

The app uses Gemini to transcribe local archival images from this hardcoded source folder:

```text
/Users/stevecovello/Desktop/MM/Transcription Sources
```

It creates timestamped `.docx` output in `outputs/` and also writes an intermediate timestamped `.md` file.

## Current Workflow

The former top-level mode buttons have been removed. Runs are now driven by saved prompt profiles in `profiles/`. The Rendi profiles were migrated from the old `.md` prompts into JSON files and behave like user-created custom profiles.

Current saved profiles include:

- `profiles/rendi-battesimi.json`
- `profiles/rendi-morti.json`
- `profiles/rendi-matrimoni.json`
- `profiles/rendi-generic.json`

`profiles/settings.json` stores the last selected profile and is ignored by git.

Each profile has these editable plain-text sections:

- `role_context`: Role plus tone/style/local context.
- `reference_context`: Ground truth, taxonomy, names, places, formulas, dictionaries, and other reference material.
- `output_format`: Output structure plus transcription/translation examples.

The UI shows these sections as plain text, not raw JSON. The app handles JSON escaping and formatting when saving, so brackets, quotes, commas, and long pasted text do not break profile-file syntax.

## Profile Saving

The UI has a `Save Profile` button beside `Save new custom profile as`.

- If the profile name field is blank, `Save Profile` updates the selected profile.
- If a new name is entered, `Save Profile` creates a new reusable profile.
- If the entered name matches an existing profile, the browser prompts the user to replace the existing profile or create a renamed new version.
- Backend save logic also supports explicit replacement so direct POSTs behave predictably.

If edited profile boxes are submitted with `Run transcription`, the app still prompts the user to update the selected profile or save a new named version before running.

## API Key Handling

The web UI now includes a `Gemini API key` field under the model dropdown. A user can paste their own key for a run. The pasted key is used as a runtime override and is not saved to project files.

Private local use can still rely on `.env`, but `.env` is ignored by git and should not be committed.

## Source File Ordering

The source scanner in `transcription_bot/core.py` recursively scans image files in subdirectories, parses date folder names like `1786 December 2`, sorts chronologically, and includes relative source paths in output record headers.

The web app has process-order controls:

- `Newest-to-oldest`: default; most recent record appears first in the output document.
- `Oldest-to-newest`: oldest record appears first in the output document.

The UI shows a small explanatory hint that changes when the user selects either order.

## Model Selection

The web app uses a Gemini model dropdown:

- `gemini-3.5-flash`: default, faster/lower cost.
- `gemini-3.1-pro-preview`: higher accuracy.

## Run Control

The web page polls `/status` while a run is active, so the log and summary update automatically.

A `Stop` button requests cooperative cancellation. If Gemini is already processing an image, the current request is allowed to finish. A partial `.docx` is generated from the `.md` content already written.

## Key Files

- `app.py`: local web app, profile dropdown/editor, profile saving, API key field, model dropdown, order selector, stop/status/download flow, `.docx` generation.
- `transcription_bot/core.py`: Gemini client, runtime API key override, recursive image discovery, date-aware sorting, cancellable batch transcription, output cleanup.
- `profiles/`: saved JSON prompt profiles.
- `README.md`: setup and usage notes.
- `.env`: local Gemini API key, ignored by git.
- `.env.example`: template for the API key.

## To-Do For Next Session

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
We are continuing work on the local Customizable Transcription Interface app at /Users/stevecovello/Documents/Codex/Transcription Bot. Read HANDOFF.md first. The app uses saved JSON prompt profiles, recursive chronological image scanning from /Users/stevecovello/Desktop/MM/Transcription Sources, model selection, a per-run Gemini API key field, newest/oldest process-order controls with explanatory hints, automatic status updates, a stop button, incremental `.md` output, and timestamped `.docx` output. Next task: add a user-friendly feature to transform raw pasted ground-truth material, such as a long unformatted list of names, into structured profile reference content before saving. Please inspect the current code and continue from the handoff.
```
