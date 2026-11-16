"""Test Mode page ("/test-mode"). Split out of app.py as part of the
app.py-modularization pass -- see docs/DESIGN.md's "Codebase structure"
section."""

from __future__ import annotations

import html

from app_state import load_source_folder, test_lock, test_state
from customizable_transcriber.core import MODELS
from pages import FOOTER_HTML, file_picker_html, json_data_island_html
from profiles_store import profile_options_html, profiles_for_browser

TM_PAGE_ZOOM_HINT = (
    "Page zoom (Gemini only) sends each photo of two facing pages together with a full-resolution "
    "crop of each page. To see whether it helps your register, choose the same Gemini model for "
    "Model A and Model B and turn Page zoom on for only one of them."
)


TM_OFF_PEAK_INFO_TEXT = (
    "Off-Peak submits every queued run to its provider's batch queue instead of processing "
    "images in real time -- typically billed at roughly half the standard per-token rate. All "
    "runs are submitted at once and finish on the provider's own schedule, which can take from "
    "a few minutes to several hours. The app must stay open and running until every run "
    "finishes. Clicking Stop cancels every batch on the provider's side: images not yet "
    "completed are lost, not paused."
)


def tm_info_button_html(panel_id: str, text: str) -> str:
    # Small "i" popup button, mirroring Prompt Builder's own
    # pb_info_button_html (pages/prompt_builder.py) under Test Mode's own
    # class names -- Test Mode's JS is inline rather than loaded from
    # static/prompt-builder.js, so this is a deliberate parallel copy, not a
    # shared import, matching how this codebase already tolerates per-page
    # duplication for styling only two pages need (see docs/DESIGN.md's
    # "Codebase structure" section on the base.css/app-shell.css tiering).
    return (
        f'<span class="tm-info-wrap">'
        f'<button type="button" class="tm-info-btn" aria-expanded="false" aria-controls="{panel_id}" aria-label="More information">i</button>'
        f'<span class="tm-info-panel" id="{panel_id}" role="note" hidden>{html.escape(text)}</span>'
        f"</span>"
    )


def test_mode_page() -> str:
    with test_lock:
        running = bool(test_state["running"])
        log = "\n".join(test_state["log"])
        summary = str(test_state["summary"])
        model_a = str(test_state["model_a"])
        model_b = str(test_state["model_b"])
        off_peak = bool(test_state["off_peak"])
        zoom_a = bool(test_state["zoom_a"])
        zoom_b = bool(test_state["zoom_b"])
        order = str(test_state["order"])
        file_type = str(test_state["file_type"])
        profile_id = str(test_state["profile_id"])
        queue = [dict(batch) for batch in test_state["queue"]]
        runs = {run_id: dict(run) for run_id, run in test_state["runs"].items()}

    source_folder = load_source_folder()
    source_folder_display = html.escape(str(source_folder)) if source_folder else "No folder selected"
    source_folder_selected = "true" if source_folder else "false"
    disabled = "disabled" if running else ""
    stop_disabled = "" if running else "disabled"
    escaped_log = html.escape(log)
    escaped_summary = html.escape(summary)

    def model_options_for(selected: str) -> str:
        return "\n".join(
            f'<option value="{html.escape(model_id)}" {"selected" if selected == model_id else ""}>{html.escape(label)}</option>'
            for model_id, label in MODELS.items()
        )

    model_a_options = model_options_for(model_a)
    model_b_options = model_options_for(model_b)
    zoom_a_checked = "checked" if zoom_a else ""
    zoom_b_checked = "checked" if zoom_b else ""

    def model_name(batch: dict, slot: str) -> str:
        name = html.escape(MODELS.get(batch[f"model_{slot}"], batch[f"model_{slot}"]))
        return name + (" (Page zoom)" if batch.get(f"zoom_{slot}") else "")

    newest_checked = "checked" if order == "newest" else ""
    oldest_checked = "checked" if order != "newest" else ""
    jpeg_checked = "checked" if file_type == "jpeg" else ""
    png_checked = "checked" if file_type == "png" else ""
    profile_options = profile_options_html(profile_id)
    # One data island instead of three separate window/const assignments --
    # see json_data_island_html()'s own docstring (pages/__init__.py) for
    # why this is what lets static/test-mode.js keep reading this per-request
    # data after CSP's script-src drops 'unsafe-inline' (reviews/CODEX_REVIEW.md
    # finding L-2 / reviews/HUMAN_DECISIONS.md). Read back near the top of that file
    # into the same profiles/MODEL_LABELS/initialRuns/queueLength/running
    # names the rest of the script already used.
    initial_data_html = json_data_island_html(
        "test-mode-initial-data",
        {
            "profiles": profiles_for_browser(),
            "modelLabels": MODELS,
            "initialRuns": runs,
            "queueLength": len(queue),
            "running": running,
            "offPeak": off_peak,
        },
    )

    queue_list_html = "\n".join(
        f'''<li class="queue-item">
          <span>{html.escape(batch["label"])}: {model_name(batch, "a")}
            vs {model_name(batch, "b")}</span>
          <button type="submit" class="danger queue-remove-button" formaction="/test-mode/queue/remove" formmethod="post" formnovalidate name="batch_id" value="{html.escape(batch["batch_id"])}" {disabled}>Remove</button>
        </li>'''
        for batch in queue
    ) or '<li class="queue-empty hint">No batches queued yet. Click "Add to Batch" to queue the Model A/B pair above, or leave the queue empty and just run this one pair directly.</li>'

    return f"""<!doctype html>
<html lang="en">
  <head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Test Mode - Model Comparison</title>
  <script src="/static/i18n.js" defer></script>
  <script src="/static/app-common.js"></script>
  {initial_data_html}
  <script src="/static/test-mode.js"></script>
  <link rel="stylesheet" href="/static/base.css">
  <link rel="stylesheet" href="/static/app-shell.css">
  <link rel="stylesheet" href="/static/test-mode.css">
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
    <h1 class="sr-only">Test Mode</h1>
    <div class="header-nav-row">
      <nav class="site-nav" aria-label="Primary navigation">
        <a class="nav-link nav-home" href="/" aria-label="Home" title="Home">🏠</a>
        <a class="nav-link" href="/prompt-builder">Prompt Builder</a>
        <a class="nav-link" href="/transcribe">Transcribe</a>
        <a class="nav-link" href="/xls-conversion">XLSX Conversion</a>
        <a class="nav-link" href="/test-mode" aria-current="page">Test Mode</a>
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
  <form method="post" action="/test-mode/run">
    <div class="path-control">
      <label>Source folder</label>
      <div class="path-control-row">
        <button id="browse-source-button" type="button" class="button-tiny">Browse&hellip;</button>
        <div class="path-display" id="source-folder-display" data-selected="{source_folder_selected}">{source_folder_display}</div>
        <button id="reset-button" type="submit" formaction="/test-mode/reset" formmethod="post" {disabled}>Reset All</button>
      </div>
    </div>
    <div class="path-manual-row" hidden>
      <input type="text" id="source-folder-manual-input" placeholder="Or paste an absolute folder path">
      <button id="source-folder-manual-button" type="button" class="button-secondary">Use this path</button>
    </div>
    <p class="hint" hidden>Browse opens a native folder dialog.</p>
    <p class="hint">Runs the same source images and prompt profile through different models to compare performance.</p>
    <div class="row">
      <label>Model A
        <select name="model_a">
          {model_a_options}
        </select>
      </label>
      <label>Model B
        <select name="model_b">
          {model_b_options}
        </select>
      </label>
    </div>
    <div class="row zoom-row">
      <label class="zoom-check"><input type="checkbox" name="zoom_a" value="on" {zoom_a_checked}>Page zoom for Model A</label>
      <label class="zoom-check"><input type="checkbox" name="zoom_b" value="on" {zoom_b_checked}>Page zoom for Model B</label>
    </div>
    <p class="hint">{html.escape(TM_PAGE_ZOOM_HINT)}</p>
    <div class="row">
      <label>Gemini API key
        <input type="password" name="api_key_gemini" autocomplete="off" placeholder="Paste your Gemini API key">
      </label>
      <label>Claude API key
        <input type="password" name="api_key_claude" autocomplete="off" placeholder="Paste your Claude API key">
      </label>
    </div>
    <p class="hint">Only the key(s) actually needed are required -- if every model in use is Gemini, the Claude field can stay blank, and vice versa. Whichever key matches a given run's own model is the one used for that run, so one queue can freely mix Gemini and Claude models. Not saved to the project files. Submitting a run sends the matching key and the selected source content directly to that provider's API — see PRIVACY.md.</p>
    <div class="row">
      <label>Batch label (optional)
        <input type="text" name="batch_label" placeholder="Example: Gemini 3.1 Pro Preview vs Claude Opus 5">
      </label>
      <label>&nbsp;<br>
        <button id="add-to-batch-button" type="submit" formaction="/test-mode/queue/add" formmethod="post" {disabled}>Add to Batch</button>
      </label>
    </div>
    <label>Batch queue
      <ul class="queue-list">
        {queue_list_html}
      </ul>
    </label>
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
    <label>Prompt profile
      <select name="profile_id">
        {profile_options}
      </select>
      <input type="hidden" name="profile_action" value="use">
      <input type="hidden" name="duplicate_profile_action" value="">
      <input type="hidden" name="new_profile_name" value="">
      <p class="hint">Test Mode runs the profile as saved &mdash; edit or create profiles from the Transcribe page.</p>
    </label>
    <div class="actions run-actions">
      <div class="run-button-stack">
        <button id="run-button" type="submit" disabled>Preflight Check</button>
        <button id="confirm-run-button" type="submit" disabled>Confirm and run</button>
        <span class="offpeak-button-row">
          <button id="confirm-run-offpeak-button" type="submit" formaction="/test-mode/run-offpeak" formmethod="post" disabled>Confirm and Run<br>Off-Peak</button>
          {tm_info_button_html("tm-info-offpeak", TM_OFF_PEAK_INFO_TEXT)}
        </span>
      </div>
      <span id="run-confirmation" class="run-confirmation">
        <span class="run-confirmation-title">Confirm settings:</span>
        <span id="run-confirmation-settings" class="run-confirmation-settings" hidden>
          <span>Batches: <strong id="confirm-batches"></strong></span>
          <span>Order: <strong id="confirm-order"></strong></span>
          <span>File type: <strong id="confirm-file-type"></strong></span>
          <span>Prompt Profile: <strong id="confirm-profile"></strong></span>
        </span>
        <span id="run-status" class="run-status" role="status" aria-live="polite" hidden><span class="spinner" aria-hidden="true"></span>Process running. Review the Progress Console below.</span>
      </span>
    </div>
  </form>
  <details class="tm-section">
    <summary>
      <span>Compare transcripts (DOCX)</span>
      {tm_info_button_html("tm-info-compare-transcripts", "Compare each transcript against a fully corrected version of the same content. Results show different types of error rates.")}
    </summary>
    <p class="hint tm-section-hint">Upload uncorrected DOCX transcripts to compare to a corrected DOCX.</p>
    <div id="extra-model-files">
      <div class="extra-file-row">
        <input type="text" placeholder="Label for this model" data-extra-label>
        {file_picker_html(accept=".docx", extra_attrs="data-extra-file")}
      </div>
      <div class="extra-file-row">
        <input type="text" placeholder="Label for this model" data-extra-label>
        {file_picker_html(accept=".docx", extra_attrs="data-extra-file")}
      </div>
    </div>
    <button id="add-extra-file-button" class="button-tiny" type="button">Add another</button>
    <label>100% Corrected DOCX</label>
    <div class="extra-file-row">
      <input type="text" id="corrected-label-input" placeholder="Label for this model">
      {file_picker_html("corrected-file-input", ".docx")}
    </div>
    <p id="compare-file-status" class="hint"></p>
    <div class="actions">
      <button id="run-compare-button" class="button-secondary" type="button">Run Comparison</button>
    </div>
    <div id="compare-results"></div>
    <div class="actions" id="compare-report-actions" hidden>
      <button id="download-report-button" class="button-secondary" type="button" disabled>Download Comparison Report</button>
    </div>
  </details>
  <details class="tm-section">
    <summary>
      <span>Compare Indexes (XLSX)</span>
      {tm_info_button_html("tm-info-compare-indexes", "Each candidate XLSX index is scored for statistical accuracy against the 100% Corrected XLSX index -- a downloadable report ranks them by character error rate, the same way the Compare Transcripts report above ranks transcripts. It does not list individual field differences; review a candidate's own spreadsheet against the corrected index by eye to find and fix specific entries.")}
    </summary>
    <div id="ic-candidate-files">
      <div class="extra-file-row">
        <input type="text" placeholder="Label for this model" data-ic-label>
        {file_picker_html(accept=".xlsx", extra_attrs="data-ic-file")}
      </div>
      <div class="extra-file-row">
        <input type="text" placeholder="Label for this model" data-ic-label>
        {file_picker_html(accept=".xlsx", extra_attrs="data-ic-file")}
      </div>
    </div>
    <button id="ic-add-candidate-button" class="button-tiny" type="button">Add another</button>
    <label>100% Corrected XLSX</label>
    <div class="extra-file-row">
      <input type="text" id="ic-ground-truth-label" placeholder="Label for this index">
      {file_picker_html("ic-ground-truth-file", ".xlsx")}
    </div>
    <p id="ic-status" class="hint"></p>
    <div class="actions">
      <button id="ic-run-button" class="button-secondary" type="button">Run Comparison</button>
    </div>
    <div id="ic-mapping-area" hidden></div>
    <div class="actions" id="ic-report-actions" hidden>
      <button id="ic-download-report-button" class="button-secondary" type="button" disabled>Download Comparison Report</button>
    </div>
  </details>
  <section class="panel">
    <h2 class="panel-title">Progress Console</h2>
    <div id="summary" class="summary" role="status" aria-live="polite">{escaped_summary}</div>
    <div class="actions">
      <form method="post" action="/test-mode/stop">
        <button id="stop-button" class="danger" type="submit" {stop_disabled}>Stop</button>
      </form>
      <button id="refresh-status-button" class="button-secondary" type="button">Refresh Status</button>
      <button id="open-outputs-folder-button" class="button-secondary" type="button">Open Outputs Folder</button>
    </div>
    <div id="progress-rows" class="progress-rows"></div>
    <pre id="log">{escaped_log}</pre>
  </section>
  {FOOTER_HTML}
</main>
</body>
</html>"""
