# Transcription Bot

Local Gemini transcription app for archival images. It replaces the Colab/Google Drive workflow with local folder input, timestamped Markdown output, and timestamped Word document output.

## Setup

```bash
cd "/Users/stevecovello/Documents/Codex/Transcription Bot"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and add your Gemini API key:

```bash
GEMINI_API_KEY=your_api_key_here
```

## Run The Local Web App

```bash
python3 app.py
```

Open:

```text
http://127.0.0.1:8765
```

The web app uses the hardcoded source folder in `app.py`. Select one transcription mode before running: `Morti`, `Battisme`, `Matrimoni`, or `Generic`. Each mode uses its own prompt file in `prompts/`.

Current web app behavior:

- Recursively scans source subfolders for image files.
- Sorts date folders chronologically.
- Lets you choose `Newest-to-oldest` or `Oldest-to-newest`; `Newest-to-oldest` is the default.
- Lets you choose between `Gemini 3.5 Flash` for faster/lower-cost runs and `Gemini 3.1 Pro Preview` for higher-accuracy runs.
- Writes each processed image to a timestamped `.md` file as soon as the response is received.
- Creates a timestamped `.docx` Word document in `outputs/` when the run finishes or is stopped.
- Updates run status automatically while processing.
- Supports a `Stop` button that stops before the next image or during the delay between images. If Gemini is already processing an image, stop takes effect after that request finishes.

Prompt behavior:

- The app adds the source-relative `START OF RECORD` header automatically.
- Prompts tell Gemini not to add duplicate record headers or filenames.
- Source line breaks are collapsed into continuous paragraph text.
- Italian transcriptions preserve source abbreviations such as `Ant:o`.
- English translations expand clear abbreviations, for example `Ant:o` as `Antonio`.

## Run From The Command Line

```bash
python3 transcribe.py "/path/to/image/folder"
```

Optional output file:

```bash
python3 transcribe.py "/path/to/image/folder" --output "/path/to/output.md"
```

Useful options:

```bash
python3 transcribe.py "/path/to/image/folder" --reverse
python3 transcribe.py "/path/to/image/folder" --model gemini-3.5-flash
python3 transcribe.py "/path/to/image/folder" --delay 0
```

## Files

- `prompt.md`: original paleography prompt from the Colab notebook.
- `app.py`: localhost web app.
- `transcribe.py`: command-line runner.
- `transcription_bot/core.py`: shared transcription logic.
- `prompts/`: mode-specific system prompts.
- `outputs/`: generated Markdown and Word document files.
