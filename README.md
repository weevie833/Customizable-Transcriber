# Customizable Transcription Interface

Local Gemini transcription app for archival records. It replaces the Colab/Google Drive workflow with local folder input, saved prompt profiles, selected JPEG/PNG/PDF source processing, timestamped Markdown output, and timestamped Word document output.

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

The home-page header links to the unified XLS Conversion interface:

```text
http://127.0.0.1:8765/xls-conversion
```

XLS Conversion accepts a local DOCX transcription and produces downloadable
XLSX and CSV files. Select the source type, image range, Gemini model, and API
key, then run the semantic preflight before conversion. The preflight reviews
the requested image range for existing English translations without changing
the source content. Battesimi extraction is currently configured.

The web app uses the hardcoded source folder in `app.py`. Select a saved prompt profile before running; the selected profile controls the role/local context, reference material, and output format.

Current web app behavior:

- Recursively scans source subfolders for the selected source file type.
- Supports `JPEG` (`.jpg`, `.jpeg`), `PNG` (`.png`), and `PDF` (`.pdf`) from the web UI.
- Runs a preflight check before transcription to confirm the selected file type exists in the source folder.
- Sorts date folders chronologically.
- Lets you choose `Oldest-to-newest` or `Newest-to-oldest`; `Oldest-to-newest` is the default.
- Provides Gemini Flash, Flash-Lite, and Pro model options.
- Requires the user to paste a Gemini API key and choose a saved prompt profile before a run can start. The dropdown starts at `Select a Profile` to prevent accidental runs with the wrong profile.
- Shows a centered audible alert if `Preflight Check` is clicked before a Gemini API key is pasted or before a prompt profile is selected.
- Keeps a visible `Confirm settings` box beside the run controls. Clicking `Preflight Check` fills it with process order, file type, and prompt profile, disables `Preflight Check`, and enables `Confirm and run`.
- Selecting a prompt profile loads its saved role/local context, reference material, and output format into plain-text editable boxes for inspection before running.
- The app saves profile edits as JSON automatically, so quotes, brackets, and commas typed into the editor boxes do not break profile-file syntax.
- If those boxes are edited before running, the app prompts to update the selected profile or save a new named version.
- The `Save Profile` button stays active when the app is not running. It saves a new named profile, or lets you replace the selected profile or save a new version when the name field is blank.
- The `Reset` button beside the Source folder restores default settings, clears the profile editor, and returns the prompt dropdown to `Select a Profile`.
- The profile-editing area below the preflight/run controls is visually separated with a divider and pale grey background, keeping run configuration decisions grouped above it.
- The app validates the pasted Gemini API key with a small preflight request before starting the image batch.
- Writes each processed image to a timestamped `.md` file as soon as the response is received.
- Creates a timestamped `.docx` Word document in `outputs/` when the run finishes or is stopped.
- Updates run status automatically while processing.
- Lets `Refresh Status` update only the Progress Console without reloading or resetting the rest of the app.
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
- `transcription_bot/core.py`: shared transcription logic and selected source-type scanning.
- `profiles/`: saved JSON prompt profiles.
- `outputs/`: generated Markdown and Word document files.
- `xls_conversion/`: unified DOCX-to-XLSX/CSV page and source-specific extraction helpers.
