"""Transcribe page ("/transcribe", the app's original page() function).
Split out of app.py as part of the app.py-modularization pass -- see
docs/DESIGN.md's "Codebase structure" section."""

from __future__ import annotations

import html

from app_state import load_source_folder, lock, state
from customizable_transcriber.core import MODELS
from pages import FOOTER_HTML, file_picker_html, info_button_html, json_data_island_html
from profiles_store import load_profile, profile_options_html, profiles_for_browser

OFF_PEAK_INFO_TEXT = (
    "Off-Peak Mode submits your whole run to your provider's batch queue instead of "
    "processing images in real time -- typically billed at roughly half the standard "
    "per-token rate. The app must stay open and running for the entire job; there is no "
    "way to submit it and close the app. The provider processes it on its own schedule, "
    "which can take anywhere from a few minutes to several hours -- there is no "
    "guaranteed turnaround time. Clicking Stop cancels the batch entirely on the "
    "provider's side: any images not yet completed are lost, not paused."
)

TRANSLATE_OFF_PEAK_INFO_TEXT = (
    "Translate Off-Peak sends the same translation requests to your provider's batch queue, "
    "typically billed at roughly half the standard per-token rate. Keep the app open until it "
    "finishes; the provider works on its own schedule, from a few minutes to several hours. "
    "Any request the batch could not translate is sent again in real time at the end. Clicking "
    "Stop cancels the batch; pages already translated are kept in the document."
)

PAGE_ZOOM_INFO_TEXT = (
    "Page zoom sends each photo to Gemini together with a full-resolution crop of each page. "
    "AI models shrink large photos before reading them, so on a high-resolution photo of two "
    "facing pages the handwriting loses detail; the page crops give it back. Use it with Gemini "
    "models on photos of two facing pages at least about 3000 pixels wide. In tests on two "
    "registers it corrected misread capital letters and names, at little or no extra cost. It "
    "does not help Claude models, single-page photos, or small photos, and a photo with no clear "
    "gutter between the pages is sent whole. It is new: before a large run, compare a few images "
    "with and without it."
)

# Only used on this page -- moved here rather than left as an app.py
# constant, since importing it from app.py would be circular (app.py
# imports this module's page() function).
DOWNLOAD_HELP_TEXT = "The DOCX file will be downloaded to wherever your browser saves downloaded files. Check your browser's Downloads button for download history."


def output_status_text() -> str:
    if state["download"]:
        return "DOCX document ready."
    if state["running"] and state["output"]:
        return "DOCX document is being prepared."
    return ""


def page() -> str:
    with lock:
        running = bool(state["running"])
        log = "\n".join(state["log"])
        output = output_status_text()
        download = str(state["download"])
        summary = str(state["summary"])
        model = str(state["model"])
        order = str(state["order"])
        file_type = str(state["file_type"])
        profile_id = str(state["profile_id"])
        new_profile_name = str(state["new_profile_name"])
        role_context = str(state["role_context"])
        reference_context = str(state["reference_context"])
        output_format = str(state["output_format"])
        off_peak = bool(state["off_peak"])
        zoom_pages = bool(state["zoom_pages"])
        report_download = bool(state["report_download"])

    if profile_id:
        active_profile = load_profile(profile_id)
        if active_profile.get("kind") == "custom" and not any((role_context, reference_context, output_format)):
            role_context = active_profile.get("role_context", "")
            reference_context = active_profile.get("reference_context", "")
            output_format = active_profile.get("output_format", "")

    source_folder = load_source_folder()
    source_folder_display = html.escape(str(source_folder)) if source_folder else "No folder selected"
    source_folder_selected = "true" if source_folder else "false"
    # The folder this page shows, sent back with Run so the server can refuse
    # a run if the shared setting changed since (another tab):
    # reviews/CODEX_REVIEW_8.md H-2.
    source_folder_value = html.escape(str(source_folder), quote=True) if source_folder else ""
    disabled = "disabled" if running else ""
    stop_disabled = "" if running else "disabled"
    escaped_log = html.escape(log)
    escaped_output = html.escape(output)
    escaped_summary = html.escape(summary)
    escaped_new_profile_name = html.escape(new_profile_name)
    escaped_role_context = html.escape(role_context)
    escaped_reference_context = html.escape(reference_context)
    escaped_output_format = html.escape(output_format)
    escaped_download_help = html.escape(DOWNLOAD_HELP_TEXT)
    model_options = "\n".join(
        f'<option value="{html.escape(model_id)}" {"selected" if model == model_id else ""}>{html.escape(label)}</option>'
        for model_id, label in MODELS.items()
    )
    newest_checked = "checked" if order == "newest" else ""
    oldest_checked = "checked" if order != "newest" else ""
    jpeg_checked = "checked" if file_type == "jpeg" else ""
    png_checked = "checked" if file_type == "png" else ""
    profile_options = profile_options_html(profile_id)
    # One data island instead of two separate window/const assignments --
    # see json_data_island_html()'s own docstring (pages/__init__.py) and
    # reviews/CODEX_REVIEW.md finding L-2 / reviews/HUMAN_DECISIONS.md.
    initial_data_html = json_data_island_html(
        "transcribe-initial-data",
        {"profiles": profiles_for_browser(), "running": running, "off_peak": off_peak},
    )
    off_peak_info_html = info_button_html("offpeak-info-panel", OFF_PEAK_INFO_TEXT)
    translate_off_peak_info_html = info_button_html("translate-offpeak-info-panel", TRANSLATE_OFF_PEAK_INFO_TEXT)
    page_zoom_info_html = info_button_html("page-zoom-info-panel", PAGE_ZOOM_INFO_TEXT)
    zoom_checked = "checked" if zoom_pages else ""
    download_disabled_class = "" if download else " disabled-link"
    report_hidden = "" if report_download else "hidden"
    translate_profile_options = profile_options_html("").replace(
        '<option value="" disabled selected>Select a Profile</option>',
        '<option value="" selected>Use the profile named in the document</option>',
        1,
    )
    translate_file_picker = file_picker_html("translate-source-file", ".docx", 'name="source_file"', drop_zone=True)
    download_aria_disabled = "false" if download else "true"

    return f"""<!doctype html>
<html lang="en">
  <head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Customizable Transcriber</title>
  <script src="/static/i18n.js" defer></script>
  <script src="/static/app-common.js"></script>
  {initial_data_html}
  <script src="/static/transcribe.js"></script>
  <script src="/static/transcribe-translate.js"></script>
  <link rel="stylesheet" href="/static/base.css">
  <link rel="stylesheet" href="/static/app-shell.css">
  <link rel="stylesheet" href="/static/transcribe.css">
</head>
<body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<div id="settings-alert" class="settings-alert" role="alertdialog" aria-modal="true" aria-labelledby="settings-alert-title" hidden>
  <div class="settings-alert-box">
    <p id="settings-alert-title" class="settings-alert-title">Run settings needed</p>
    <p id="settings-alert-message" class="settings-alert-message"></p>
    <button id="settings-alert-close" type="button">OK</button>
  </div>
</div>
<main id="main-content" tabindex="-1">
  <header class="site-header">
    <h1 class="sr-only">Transcribe</h1>
    <div class="header-nav-row">
      <nav class="site-nav" aria-label="Primary navigation">
        <a class="nav-link nav-home" href="/" aria-label="Home" title="Home">🏠</a>
        <a class="nav-link" href="/prompt-builder">Prompt Builder</a>
        <a class="nav-link" href="/transcribe" aria-current="page">Transcribe</a>
        <a class="nav-link" href="/xls-conversion">XLSX Conversion</a>
        <a class="nav-link" href="/test-mode">Test Mode</a>
      </nav>
      <div class="header-right">
        <a class="nav-link nav-secondary" href="/getting-started">Getting Started</a>
        <div class="lang-toggle" role="group" aria-label="Language / Lingua">
          <button type="button" class="lang-flag" data-lang="en" aria-pressed="true" title="English" aria-label="English">🇺🇸</button>
          <button type="button" class="lang-flag" data-lang="it" aria-pressed="false" title="Italiano" aria-label="Italiano">🇮🇹</button>
        </div>
      </div>
    </div>
  </header>
  <form method="post" action="/run">
    <div class="path-control">
      <label>Source folder</label>
      <div class="path-control-row">
        <button id="browse-source-button" type="button" class="button-tiny">Browse&hellip;</button>
        <div class="path-display" id="source-folder-display" data-selected="{source_folder_selected}">{source_folder_display}</div>
        <input type="hidden" name="source_folder" id="source-folder-value" value="{source_folder_value}">
        <button id="reset-button" type="submit" formaction="/reset" formmethod="post" {disabled}>Reset All</button>
      </div>
    </div>
    <div class="path-manual-row" hidden>
      <input type="text" id="source-folder-manual-input" placeholder="Or paste an absolute folder path">
      <button id="source-folder-manual-button" type="button" class="button-secondary">Use this path</button>
    </div>
    <p class="hint" hidden>Browse opens a native folder dialog.</p>
    <div class="row">
      <label>Model
        <select name="model">
          {model_options}
        </select>
      </label>
      <label>API key
        <input type="password" name="gemini_api_key" autocomplete="off" placeholder="Paste your API key for this run">
        <p class="hint">Used only for this browser session/request. It is not saved to the project files. Submitting a run sends this key and the selected source content directly to your chosen AI provider's API — see PRIVACY.md.</p>
      </label>
    </div>
    <hr class="section-divider">
    <div class="run-options">
      <fieldset>
        <legend>Process order</legend>
        <div class="radio-row">
          <label class="radio-option"><input type="radio" name="order" value="oldest" required {oldest_checked}>Oldest-to-newest</label>
          <label class="radio-option"><input type="radio" name="order" value="newest" required {newest_checked}>Newest-to-oldest</label>
        </div>
        <p id="order-hint" class="hint"></p>
      </fieldset>
      <fieldset>
        <legend>File type</legend>
        <div class="radio-row">
          <label class="radio-option"><input type="radio" name="file_type" value="jpeg" required {jpeg_checked}>JPEG</label>
          <label class="radio-option"><input type="radio" name="file_type" value="png" required {png_checked}>PNG</label>
        </div>
        <p class="hint">JPEG includes .jpg and .jpeg files.</p>
      </fieldset>
    </div>
    <fieldset class="page-zoom-option">
      <legend>Page zoom</legend>
      <span class="page-zoom-row">
        <label class="check"><input type="checkbox" name="zoom_pages" value="on" {zoom_checked}>Zoom into each page (Gemini, photos of two facing pages)</label>
        {page_zoom_info_html}
      </span>
    </fieldset>
    <label>Prompt profile
      <select name="profile_id">
        {profile_options}
      </select>
      <input type="hidden" name="profile_action" value="use">
      <input type="hidden" name="duplicate_profile_action" value="">
    </label>
    <p class="hint">Use the Prompt Builder page to create prompts, or bypass the Prompt Builder and place your prompt in the sections below. Manual prompts cannot be edited in the Prompt Builder.</p>
    <div class="actions run-actions">
      <div class="run-button-stack">
        <button id="run-button" type="submit" disabled>Preflight Check</button>
        <button id="confirm-run-button" type="submit" disabled>Confirm and Run Now</button>
        <span class="offpeak-button-row">
          <button id="confirm-run-offpeak-button" type="submit" formaction="/run-offpeak" formmethod="post" disabled>Confirm and Run<br>Off-Peak</button>
          {off_peak_info_html}
        </span>
      </div>
      <span id="run-confirmation" class="run-confirmation">
        <span class="run-confirmation-title">Confirm settings:</span>
        <span id="run-confirmation-settings" class="run-confirmation-settings" hidden>
          <span>Order: <strong id="confirm-order"></strong></span>
          <span>File type: <strong id="confirm-file-type"></strong></span>
          <span>Prompt Profile: <strong id="confirm-profile"></strong></span>
          <span>Page zoom: <strong id="confirm-zoom"></strong></span>
          <span id="page-zoom-advice" class="page-zoom-advice" hidden></span>
          <span id="source-file-advice" class="source-file-advice" hidden></span>
          <span id="offpeak-cost-estimate" hidden></span>
        </span>
        <span id="run-status" class="run-status" role="status" aria-live="polite" hidden><span class="spinner" aria-hidden="true"></span>Process running. Review the Progress Console below.</span>
      </span>
    </div>
    <details class="manual-override-section">
      <summary>Manual Prompt Override</summary>
      <div class="profile-work-area">
        <p><strong>Manual prompts can only be edited here - they cannot be edited in the Prompt Builder.</strong></p>
        <p class="hint">The profile sections below are plain text fields. The app handles JSON formatting automatically when it saves, so quotes, brackets, and commas typed here will not break the profile file.</p>
        <label>Save new custom profile as
        <p class="hint">"Save Profile" always overwrites the profile selected above with the three boxes below -- there is no confirmation step, so only click it when you mean to replace the saved version. Type a name here and click "Save as New Profile" instead to keep the original and save these edits as a separate profile.</p>
        <div class="profile-save-row">
          <input type="text" name="new_profile_name" value="{escaped_new_profile_name}" placeholder="Example: Palermo baptisms">
          <button id="profile-save-button" type="submit" formaction="/save-profile" formmethod="post" {disabled}>Save Profile</button>
          <button id="profile-save-new-button" type="submit" formaction="/save-profile" formmethod="post" {disabled}>Save as New Profile</button>
        </div>
        </label>
        <label>Role and local context
        <p class="hint">Plain text. Shows the profile role plus tone and style. Edit this box to update the selected profile or create a new version when you run transcription.</p>
        <textarea name="role_context">{escaped_role_context}</textarea>
        </label>
        <label>Ground truth and reference material
        <p class="hint">Plain text. Shows the profile technical reference, taxonomy, dictionaries, names, places, formulas, and ground truth material.</p>
        <textarea name="reference_context">{escaped_reference_context}</textarea>
        </label>
        <label>Output format
        <p class="hint">Plain text. Shows the profile output structure and transcription/translation examples.</p>
        <textarea name="output_format">{escaped_output_format}</textarea>
        </label>
      </div>
    </details>
  </form>
  <form id="translate-form" class="translate-form" novalidate>
    <details class="translate-section">
      <summary>Translate completed transcript</summary>
      <div class="translate-body">
        <p class="hint">Use this after you have corrected your final native-language transcript.</p>
        <label>Corrected transcript (DOCX)
          <span class="translate-file-row">{translate_file_picker}</span>
        </label>
        <fieldset>
          <legend>Translate into</legend>
          <div class="translate-language-row">
            <label class="translate-checkbox"><input type="checkbox" name="translate_language" value="English">English</label>
            <label class="translate-checkbox"><input type="checkbox" name="translate_language" value="Italian">Italian</label>
          </div>
        </fieldset>
        <fieldset>
          <legend>Translation style</legend>
          <div class="translate-language-row">
            <label class="translate-checkbox"><input type="checkbox" name="translate_expand_abbreviations" value="on">Expand abbreviations</label>
            <label class="translate-checkbox"><input type="checkbox" name="translate_convert_names" value="on">Convert names to ENG or IT equivalents</label>
          </div>
        </fieldset>
        <fieldset>
          <legend>Honorifics kept with a name in a role</legend>
          <p class="hint">For example "The godfather was Don Carolus Calsi". Any other title is left out of the translation; the transcription still shows it.</p>
          <div class="translate-language-row">
            <label class="translate-checkbox"><input type="checkbox" name="translate_honorific" value="Don" checked>Don</label>
            <label class="translate-checkbox"><input type="checkbox" name="translate_honorific" value="Master" checked>Master</label>
          </div>
          <input type="text" name="translate_other_honorifics" class="translate-other-honorifics" placeholder="Other honorifics to keep, separated by commas">
        </fieldset>
        <div id="translate-profile-wrap" hidden>
          <label>Prompt profile for background
            <select name="translate_profile_id">
              {translate_profile_options}
            </select>
            <p class="hint">The profile's description of the register (date conventions, abbreviations, names) helps the translation. Its translation settings are not used.</p>
          </label>
        </div>
        <p class="hint">Uses the Model and API key selected above.</p>
        <div class="actions translate-actions">
          <button id="translate-preflight-button" type="button">Preflight Check</button>
          <button id="translate-run-button" type="button" disabled>Translate</button>
          <span class="translate-offpeak-row">
            <button id="translate-run-offpeak-button" type="button" disabled>Translate Off-Peak</button>
            {translate_off_peak_info_html}
          </span>
        </div>
        <div id="translate-preflight-result" class="translate-preflight-result" role="status" aria-live="polite" hidden></div>
      </div>
    </details>
  </form>
  <section class="panel">
    <h2 class="panel-title">Progress Console</h2>
    <div id="summary" class="summary" role="status" aria-live="polite">{escaped_summary}</div>
    <div class="actions">
      <form method="post" action="/stop">
        <button id="stop-button" class="danger" type="submit" {stop_disabled}>Stop</button>
      </form>
      <a id="download-link" class="download{download_disabled_class}" href="/download" download aria-disabled="{download_aria_disabled}">Download Document</a>
      <a id="translate-report-link" class="download" href="/download-translation-report" download {report_hidden}>Download Translation Report</a>
      <span class="download-note">{escaped_download_help}</span>
      <button id="open-outputs-folder-button" class="button-secondary" type="button">Open Outputs Folder</button>
    </div>
    <p id="output" aria-live="polite">Output: {escaped_output}</p>
    <button id="refresh-status-button" class="button-secondary" type="button">Refresh Status</button>
    <pre id="log">{escaped_log}</pre>
  </section>
  {FOOTER_HTML}
</main>
</body>
</html>"""
