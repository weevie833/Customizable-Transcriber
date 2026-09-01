# Customizable Transcription Interface

Local Gemini transcription app for archival records. It replaces the Colab/Google Drive workflow with local folder input, saved prompt profiles, selected JPEG/PNG/PDF source processing, timestamped Markdown output, and timestamped Word document output.

## Setup

This is a one-time setup, requiring **Python 3.9 or newer** (developed and
tested on 3.11–3.12). The steps below are written for macOS; a Windows-
specific callout with the two commands that differ follows step 4.

You'll need Terminal — it's already on your Mac, in Applications → Utilities
→ Terminal (or press `⌘ Space`, type "Terminal", press Return).

**1. Check that Python 3 is installed.** Paste this into Terminal and press
Return:

```bash
python3 --version
```

If you see `Python 3.9` or newer, you're set — skip to step 2. If you get an
error, or a prompt asking to install Command Line Tools, install Python from
[python.org/downloads](https://www.python.org/downloads/) first, then run
`python3 --version` again to confirm.

**2. Move into the project folder.** In Terminal, type `cd ` (with a trailing
space, don't press Return yet), then drag the `Customizable Transcription` folder from
Finder into the Terminal window — it fills in the correct path for you — then
press Return:

```bash
cd path/to/Customizable-Transcription
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

**Using Windows instead of macOS?** Steps 1–4 are the same idea, but two
commands differ:

- Open a terminal via Command Prompt or PowerShell (Start menu → type
  "cmd" or "PowerShell") instead of Terminal.app.
- Step 2's `cd` works the same way; there's no drag-and-drop shortcut, so
  type or paste the full path yourself, e.g. `cd C:\Users\you\Documents\
  Customizable-Transcription`.
- Step 3's activation command is different — use this instead of
  `source .venv/bin/activate`:

  ```bat
  .venv\Scripts\activate
  ```

  (PowerShell users: if this is blocked by the execution policy, run
  `.venv\Scripts\Activate.ps1` instead, or launch `cmd.exe` for this step.)
- Everywhere else in this README, `python3` and `pip` also work as plain
  `python` and `pip` on most Windows Python installs — use whichever one
  step 1 confirmed works for you.

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
cd path/to/Customizable-Transcription
source .venv/bin/activate
python3 app.py
```

(On Windows, use `.venv\Scripts\activate` in place of the middle line — see
the Windows callout under step 4 above.)

### Updating to a newer version

Download the latest copy of this project and replace your existing
`Customizable-Transcription` folder with it, then repeat steps 3–4 above
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
XLSX and CSV files. Select the source type, image range, model, and API key,
then run the semantic preflight before conversion. The preflight reviews the
requested image range for existing English translations without changing the
source content. Six record types are configured: Church Battesimi, Church
Matrimoni, Church Morti, Civil Birth, Civil Marriage, and Civil Death.

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
- Creates a timestamped `.docx` Word document when the run finishes or is stopped, saved to the same per-user data location as saved profiles (see "Saved profiles" below) — not inside the app folder.
- Updates run status automatically while processing.
- Lets `Refresh Status` update only the Progress Console without reloading or resetting the rest of the app.
- Supports a `Stop` button that stops before the next image. If Gemini is already processing an image, stop takes effect after that request finishes.

Saved profiles:

- The app's own `profiles/` folder is reserved for shipped, read-only example
  profiles, but doesn't currently include any — every profile you see in the
  app is one you (or the Prompt Builder questionnaire) created yourself.
- **Every profile you create or edit yourself — through `Save Profile`,
  Prompt Builder, or the profile-editor boxes — is saved outside the app
  folder entirely**, in a per-user data location:
  - macOS: `~/Library/Application Support/Customizable Transcription/profiles/`
  - Windows: `%APPDATA%\Customizable Transcription\profiles\`
  - Linux: `$XDG_DATA_HOME/Customizable Transcription/profiles/` (or
    `~/.local/share/Customizable Transcription/profiles/` if that variable isn't set)

  This is deliberate: it's what keeps your own profiles safe when you update
  the app later. Updating means downloading a fresh copy of this project and
  replacing the old `Customizable-Transcription` folder — since your profiles live
  outside that folder, replacing it never touches them. You'll see every
  profile you've saved again the moment you launch the updated app, with
  nothing to move or back up yourself.
- Every generated `.docx`/`.md` output (Transcribe and Test Mode alike) is
  saved to the same per-user location, in an `outputs` subfolder next to
  `profiles` above (e.g. `~/Library/Application Support/Customizable
  Transcription/outputs/` on macOS) — for the same folder-replace-safety
  reason.
- The prompt profile dropdown always starts at `Select a Profile` when the app
  starts or reloads, even if you used one last time — this is deliberate, to
  prevent an accidental run with the wrong profile.
- To create a new profile directly, enter a name in `Save new custom profile as`, fill the three profile text boxes, and click `Save Profile`.

Prompt behavior:

- The app adds the source-relative `START OF RECORD` header automatically.
- Prompts tell Gemini not to add duplicate record headers or filenames.
- Source line breaks are collapsed into continuous paragraph text.
- Italian transcriptions preserve source abbreviations such as `Ant:o`.
- English translations expand clear abbreviations, for example `Ant:o` as `Antonio`.

## Files

- `app.py`: localhost web app — routing and the Handler class only.
- `pages/`: the five page-rendering functions (Transcribe, Test Mode, Prompt Builder, Home, Privacy), one module each.
- `app_state.py`: in-memory run state (the live Transcribe/Test Mode status) and machine-local settings (remembered source folder, output location).
- `profiles_store.py`: where prompt profiles live on disk and every load/save/update/delete/import/export operation on them.
- `prompt_builder_content.py`: static reference content (record-type formulas, vocabulary checklists) for the Prompt Builder page.
- `docx_package.py` / `test_mode/report_docx.py`: DOCX-writing helpers — generic OOXML package XML, and the Test Mode comparison-report builder specifically.
- `customizable_transcription/core.py`: shared transcription logic, model registry, and selected source-type scanning.
- `profiles/`: saved JSON prompt profiles — the single source of truth the app reads. `profiles/sources/` holds source material (lexicons, corrections, build scripts) that generates specific profiles; it is not itself loaded by the app.
- `xls_conversion/`: unified DOCX-to-XLSX/CSV page and source-specific extraction helpers.
- `static/`: shared CSS/JS every page loads (`base.css`, `app-shell.css`, `app-common.js`) plus page-specific scripts (`i18n.js`, `prompt-builder.js`).
- `tests/`: pytest regression suite (see "Running the tests" below).

Generated Markdown and Word document output, and every profile you save,
live outside this folder entirely — see "Saved profiles" above and the
paragraph below it. Nothing this app writes while running lands inside the
project folder itself, so a full folder replace during an update (see
"Updating to a newer version" above) can never delete it.

## Running the tests

Only needed for development, not for regular use of the app.

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/
```

There's a second, separate offline regression suite for `xls_conversion/`'s
non-live regex parser (see `xls_conversion/tests/run_parser_test.py` for what
it does and doesn't cover); it needs Node on `PATH` but no API key or network
access:

```bash
python3 xls_conversion/tests/run_parser_test.py
```

Both run automatically on every push and pull request via GitHub Actions
(`.github/workflows/tests.yml`), across Linux, Windows, and macOS.

## Data & Privacy

This app runs entirely locally — there is no hosted service and no central
server operated by its authors. The one exception: transcription and
extraction requests send source content to whichever AI provider (Google
Gemini or Anthropic Claude) you select, directly from your machine. If
you're deploying this for an institution (a parish, a diocesan archive) or
processing material that could involve living individuals, see
[`PRIVACY.md`](PRIVACY.md) for what that means for GDPR and similar
regulatory obligations, and who is responsible for what.
