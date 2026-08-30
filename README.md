# Customizable Transcription Interface

Local Gemini transcription app for archival records. It replaces the Colab/Google Drive workflow with local folder input, saved prompt profiles, selected JPEG/PNG/PDF source processing, timestamped Markdown output, and timestamped Word document output.

## Setup

This is a one-time setup. You'll need Terminal — it's already on your Mac, in
Applications → Utilities → Terminal (or press `⌘ Space`, type "Terminal", press
Return).

**1. Check that Python 3 is installed.** Paste this into Terminal and press
Return:

```bash
python3 --version
```

If you see something like `Python 3.11.5`, you're set — skip to step 2. If you
get an error, or a prompt asking to install Command Line Tools, install Python
from [python.org/downloads](https://www.python.org/downloads/) first, then run
`python3 --version` again to confirm.

**2. Move into the project folder.** In Terminal, type `cd ` (with a trailing
space, don't press Return yet), then drag the `Transcription Bot` folder from
Finder into the Terminal window — it fills in the correct path for you — then
press Return:

```bash
cd path/to/Transcription-Bot
```

**3. Create and activate a virtual environment.** This keeps this app's Python
packages separate from anything else on your Mac. Paste each line below
separately, pressing Return after each one:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your Terminal prompt should now start with `(.venv)` — that confirms it
worked.

**4. Install the app's dependencies:**

```bash
pip install -r requirements.txt
```

**5. Set up your Gemini API key.** Pick one of these — you don't need both:

- **Paste it into the browser each run (simplest).** Skip this step. The web
  app has a `Gemini API key` field you paste into before each run; it's never
  written to a file.
- **Save it once** so you don't have to paste it every time:

  ```bash
  cp .env.example .env
  ```

  Then open `.env` in any text editor (TextEdit works fine) and replace
  `your_api_key_here` with your real key:

  ```bash
  GEMINI_API_KEY=your_api_key_here
  ```

## Run The Local Web App

```bash
python3 app.py
```

Leave that Terminal window open — the app keeps running there for as long as
the window stays open. Then open this address in your web browser:

```text
http://127.0.0.1:8765
```

To stop the app, click back into that Terminal window and press `Control C`.

### Running it again later

You don't need to repeat the setup above every time — that part is one-time.
Each time you come back to use the app, open Terminal and run just these three
lines:

```bash
cd path/to/Transcription-Bot
source .venv/bin/activate
python3 app.py
```

### Updating to a newer version

Download the latest copy of this project and replace your existing
`Transcription-Bot` folder with it, then repeat steps 3–4 above
(`python3 -m venv .venv` / `source .venv/bin/activate` / `pip install -r
requirements.txt`) inside the new folder — dependencies can change between
versions, so it's worth reinstalling them rather than assuming the old
`.venv` still matches.

**Your own saved profiles are not affected by this.** They live outside the
app folder (see "Saved profiles" below), so replacing the folder never
touches them — everything you've created will still be there the first time
you open the updated app.

The home-page header links to the unified XLS Conversion interface:

```text
http://127.0.0.1:8765/xls-conversion
```

XLS Conversion accepts a local DOCX transcription and produces downloadable
XLSX and CSV files. Select the source type, image range, Gemini model, and API
key, then run the semantic preflight before conversion. The preflight reviews
the requested image range for existing English translations without changing
the source content. Battesimi extraction is currently configured.

Choose the source folder with the `Browse…` button on the Transcribe or Test Mode page (native folder dialog); it's saved locally on your machine, not in the repo, and reused until you change it. Select a saved prompt profile before running; the selected profile controls the role/local context, reference material, and output format.

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

- The app ships with a few example profiles (Rendi Morti, Rendi Matrimoni,
  Rendi Generic, Rendi Battesimi, and the Chiusa Sclafani battesimi profile)
  as JSON files inside the app's own `profiles/` folder.
- **Every profile you create or edit yourself — through `Save Profile`,
  Prompt Builder, or the profile-editor boxes — is saved outside the app
  folder entirely**, in a per-user data location:
  - macOS: `~/Library/Application Support/Transcription Bot/profiles/`
  - Windows: `%APPDATA%\Transcription Bot\profiles\`
  - Linux: `$XDG_DATA_HOME/Transcription Bot/profiles/` (or
    `~/.local/share/Transcription Bot/profiles/` if that variable isn't set)

  This is deliberate: it's what keeps your own profiles safe when you update
  the app later. Updating means downloading a fresh copy of this project and
  replacing the old `Transcription-Bot` folder — since your profiles live
  outside that folder, replacing it never touches them. You'll see every
  profile you've saved again the moment you launch the updated app, with
  nothing to move or back up yourself.
- The most recently selected profile is remembered in `profiles/settings.json`
  and is reselected when the app starts.
- To create a new profile directly, enter a name in `Save new custom profile as`, fill the three profile text boxes, and click `Save Profile`.

Prompt behavior:

- The app adds the source-relative `START OF RECORD` header automatically.
- Prompts tell Gemini not to add duplicate record headers or filenames.
- Source line breaks are collapsed into continuous paragraph text.
- Italian transcriptions preserve source abbreviations such as `Ant:o`.
- English translations expand clear abbreviations, for example `Ant:o` as `Antonio`.

## Files

- `app.py`: localhost web app.
- `transcription_bot/core.py`: shared transcription logic and selected source-type scanning.
- `profiles/`: saved JSON prompt profiles — the single source of truth the app reads. `profiles/sources/` holds source material (lexicons, corrections, build scripts) that generates specific profiles; it is not itself loaded by the app.
- `outputs/`: generated Markdown and Word document files.
- `xls_conversion/`: unified DOCX-to-XLSX/CSV page and source-specific extraction helpers.

## Data & Privacy

This app runs entirely locally — there is no hosted service and no central
server operated by its authors. The one exception: transcription and
extraction requests send source content to whichever AI provider (Google
Gemini or Anthropic Claude) you select, directly from your machine. If
you're deploying this for an institution (a parish, a diocesan archive) or
processing material that could involve living individuals, see
[`PRIVACY.md`](PRIVACY.md) for what that means for GDPR and similar
regulatory obligations, and who is responsible for what.
