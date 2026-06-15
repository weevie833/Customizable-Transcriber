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

`Generic` was revised to preserve source layout and output only:

- Italian Transcription
- English Translation

## Source File Ordering

The source scanner was updated in `transcription_bot/core.py` to:

- Recursively scan image files in subdirectories.
- Parse date folder names like `1786 December 2`, `1790 May 23`, `1790 July 14`, and `1791 Aug 18`.
- Sort chronologically by parsed date folder.
- Sort image files within each date folder by filename.
- Include relative source paths in the output record headers.

The reverse checkbox is unchecked by default and labeled:

```text
Process in reverse chronological order
```

## Key Files

- `app.py`: local web app, mode selector, `.docx` generation, run/download flow.
- `transcription_bot/core.py`: Gemini client, recursive image discovery, date-aware sorting, batch transcription.
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
- The page no longer auto-refreshes, because that reset selected mode buttons.
- Use `Refresh Status` manually while a run is active.

## Next Recommended Work

Add a small test limit before running large batches, for example:

```text
Max images: 6
```

or a test-mode checkbox. This will make it safer to validate recursive chronological ordering without processing all images.

Potential follow-up:

- Add a source-folder selector or config field later.
- Add progress auto-refresh that preserves form state.
- Improve `.docx` formatting with headings and page breaks.
- Replace the deprecated Python `cgi` module before moving to Python 3.13.

## Prompt For Next Session

Use this prompt to continue:

```text
We are continuing work on the local Transcription Bot app at /Users/stevecovello/Documents/Codex/Transcription Bot. Read HANDOFF.md first. The app has four modes (Morti, Battisme, Matrimoni, Generic), recursive chronological image scanning from /Users/stevecovello/Desktop/MM/Transcription Sources, and timestamped .docx output. Please inspect the current code and continue from the handoff. The next likely task is to add a safe test limit / max images control before running large batches.
```
