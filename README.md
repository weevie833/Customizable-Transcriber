# Customizable Transcription Interface

Local Gemini transcription app for archival images. It replaces the Colab/Google Drive workflow with local folder input, saved prompt profiles, timestamped Markdown output, and timestamped Word document output.

## Setup

```bash
cd "/Users/stevecovello/Documents/Codex/Transcription Bot"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

For local private use, you can edit `.env` and add your Gemini API key:

```bash
GEMINI_API_KEY=your_api_key_here
```

The web app also includes a `Gemini API key` field. A user can paste their own key there for a run without saving it to the project files, which keeps personal keys out of GitHub commits.

## Run The Local Web App

```bash
python3 app.py
```

Open:

```text
http://127.0.0.1:8765
```

The web app uses the hardcoded source folder in `app.py`. Select a saved prompt profile before running; the selected profile controls the role/local context, reference material, and output format.

Current web app behavior:

- Recursively scans source subfolders for image files.
- Sorts date folders chronologically.
- Lets you choose `Newest-to-oldest` or `Oldest-to-newest`; `Newest-to-oldest` is the default.
- Lets you choose between `Gemini 3.5 Flash` for faster/lower-cost runs and `Gemini 3.1 Pro Preview` for higher-accuracy runs.
- Lets the user paste a Gemini API key for the current run without storing it in the repo.
- Lets you choose a saved prompt profile from a dropdown. The default saved profile is Rendi Battesimi.
- Selecting a prompt profile loads its saved role/local context, reference material, and output format into plain-text editable boxes for inspection before running.
- The app saves profile edits as JSON automatically, so quotes, brackets, and commas typed into the editor boxes do not break profile-file syntax.
- If those boxes are edited before running, the app prompts to update the selected profile or save a new named version.
- The `Save Profile` button saves a new named profile, or updates the selected profile when the name field is blank, without starting transcription.
- Writes each processed image to a timestamped `.md` file as soon as the response is received.
- Creates a timestamped `.docx` Word document in `outputs/` when the run finishes or is stopped.
- Updates run status automatically while processing.
- Supports a `Stop` button that stops before the next image. If Gemini is already processing an image, stop takes effect after that request finishes.

Saved profiles:

- All profiles are saved as JSON files in `profiles/`, including Rendi Morti, Rendi Matrimoni, Rendi Generic, and Rendi Battesimi.
- The most recently selected profile is saved in `profiles/settings.json` and is reselected when the app starts.
- To create a new profile directly, enter a name in `Save new custom profile as`, fill the three profile text boxes, and click `Save Profile`.

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
- `profiles/`: saved JSON prompt profiles.
- `outputs/`: generated Markdown and Word document files.
