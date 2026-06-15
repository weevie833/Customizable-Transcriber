# Transcription Bot

Local Gemini transcription app for archival images. It replaces the Colab/Google Drive workflow with local folder input and local Markdown output.

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

The web app uses the hardcoded source folder in `app.py`. Select one transcription mode before running: `Morti`, `Battisme`, `Matrimoni`, or `Generic`. Each mode uses its own prompt file in `prompts/`, recursively scans source subfolders, sorts date folders chronologically, creates a new timestamped `.docx` Word document in `outputs/`, and makes it available through `Download Document` when processing finishes.

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
python3 transcribe.py "/path/to/image/folder" --model gemini-3-flash-preview
python3 transcribe.py "/path/to/image/folder" --delay 0
```

## Files

- `prompt.md`: original paleography prompt from the Colab notebook.
- `app.py`: localhost web app.
- `transcribe.py`: command-line runner.
- `transcription_bot/core.py`: shared transcription logic.
- `outputs/`: generated Markdown files.
