# Transcription Bot Handoff

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

It creates a new timestamped `.docx` file for each run in:

```text
/Users/stevecovello/Documents/Codex/Transcription Bot/outputs
```

It also writes an intermediate `.md` file beside the `.docx`.

## App Modes

The web interface requires one transcription mode before running:

- `Morti`
- `Battisme`
- `Matrimoni`
- `Generic`

Each mode uses a separate prompt file:

```text
prompts/morti.md
prompts/battesimi.md
prompts/matrimoni.md
prompts/generic.md
```

`Generic` outputs only:

- Italian Transcription
- English Translation

All prompts now:

- Avoid duplicate filename or `START OF RECORD` headers, because the app adds the source-relative record header.
- Avoid matching source line breaks; output uses continuous paragraphs.
- Preserve abbreviations in the Italian transcription, such as `Ant:o`.
- Expand clear abbreviations in the English translation, such as `Ant:o` as `Antonio`.

## Source File Ordering

The source scanner was updated in `transcription_bot/core.py` to:

- Recursively scan image files in subdirectories.
- Parse date folder names like `1786 December 2`, `1790 May 23`, `1790 July 14`, and `1791 Aug 18`.
- Sort chronologically by parsed date folder.
- Sort image files within each date folder by filename.
- Include relative source paths in the output record headers.

The web app now has process-order radio buttons:

```text
Newest-to-oldest
Oldest-to-newest
```

`Newest-to-oldest` is selected by default.

## Model Selection

The web app uses a Gemini model dropdown:

- `gemini-3.5-flash`: default, faster/lower cost.
- `gemini-3.1-pro-preview`: higher accuracy.

`gemini-3-flash-preview` was removed from the dropdown after comparing it with the stable Flash model family.

## Run Control

The web page now polls `/status` while a run is active, so the log and summary update automatically without manual refresh.

A `Stop` button requests cooperative cancellation:

- Stops before the next image.
- Stops during the delay between images.
- If Gemini is already processing an image, the current request is allowed to finish.
- A partial `.docx` is generated from the `.md` content already written.

## Key Files

- `app.py`: local web app, mode selector, model dropdown, order selector, stop/status/download flow, `.docx` generation.
- `transcription_bot/core.py`: Gemini client, recursive image discovery, date-aware sorting, cancellable batch transcription, output cleanup.
- `prompts/`: mode-specific system prompts.
- `README.md`: setup and usage notes.
- `.env`: local Gemini API key. This is intentionally ignored by git.
- `.env.example`: template for the API key.

## Current Source Folder Structure Observed

The source folder currently contains one project folder with date subfolders:

```text
Transcription Sources/
  20. Mazziotta, Francesco Antonio - 1786-1814/
    1786 December 2/
    1787 November 3/
    1790 May 23/
    1790 July 14/
    ...
```

The scanner found `160` image files during testing.

## Known Decisions

- Source content does not need to live in the app folder.
- The source folder path is hardcoded for now.
- The app no longer copies source images into `uploads/`.
- The app no longer asks for an existing destination Word document.
- A new `.docx` is created every run.
- The page polls status automatically while a run is active.
- New records append to the bottom of the `.md` in processing order.

## Next Recommended Work

Potential follow-up:

- Add a source-folder selector or config field later.
- Improve `.docx` formatting with headings and page breaks.
- Replace the deprecated Python `cgi` module before moving to Python 3.13.

## Prompt For Next Session

Use this prompt to continue:

```text
We are continuing work on the local Transcription Bot app at /Users/stevecovello/Documents/Codex/Transcription Bot. Read HANDOFF.md first. The app has four modes (Morti, Battisme, Matrimoni, Generic), recursive chronological image scanning from /Users/stevecovello/Desktop/MM/Transcription Sources, model selection, newest/oldest process-order controls, automatic status updates, a stop button, incremental `.md` output, and timestamped `.docx` output. Please inspect the current code and continue from the handoff.
```
