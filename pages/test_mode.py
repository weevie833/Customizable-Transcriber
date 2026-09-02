"""Test Mode page ("/test-mode"). Split out of app.py as part of the
app.py-modularization pass -- see CLAUDE.md."""

from __future__ import annotations

import html

from customizable_transcription.core import MODELS
from pages import json_for_inline_script
from profiles_store import profile_options_html, profiles_for_browser
from app_state import load_source_folder, test_lock, test_state


def test_mode_page() -> str:
    with test_lock:
        running = bool(test_state["running"])
        log = "\n".join(test_state["log"])
        summary = str(test_state["summary"])
        model_a = str(test_state["model_a"])
        model_b = str(test_state["model_b"])
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

    newest_checked = "checked" if order == "newest" else ""
    oldest_checked = "checked" if order != "newest" else ""
    jpeg_checked = "checked" if file_type == "jpeg" else ""
    png_checked = "checked" if file_type == "png" else ""
    pdf_checked = "checked" if file_type == "pdf" else ""
    profile_options = profile_options_html(profile_id)
    profile_data_json = json_for_inline_script(profiles_for_browser())
    model_labels_json = json_for_inline_script(MODELS)
    initial_runs_json = json_for_inline_script(runs)

    queue_list_html = "\n".join(
        f'''<li class="queue-item">
          <span>{html.escape(batch["label"])}: {html.escape(MODELS.get(batch["model_a"], batch["model_a"]))}
            vs {html.escape(MODELS.get(batch["model_b"], batch["model_b"]))}</span>
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
  <script>
    document.addEventListener("click", function (event) {{
      const link = event.target.closest("a.download");
      if (link && link.getAttribute("aria-disabled") === "true") {{
        event.preventDefault();
      }}
    }});

    const profiles = {profile_data_json};
    const MODEL_LABELS = {model_labels_json};
    const initialRuns = {initial_runs_json};
    const queueLength = {len(queue)};
    let runConfirmed = false;
    let preflightComplete = false;
    let completionAlertShown = false;
    let extraFileCount = 0;

    function modelLabelFor(modelId) {{
      return MODEL_LABELS[modelId] || modelId || "";
    }}

    function escapeHtml(value) {{
      const div = document.createElement("div");
      div.textContent = value === null || value === undefined ? "" : String(value);
      return div.innerHTML;
    }}

    function renderRunRows(runs) {{
      const container = document.getElementById("progress-rows");
      if (!container) return;
      const runIds = Object.keys(runs || {{}});
      if (!runIds.length) {{
        container.innerHTML = '<p class="hint">No runs yet.</p>';
        return;
      }}
      container.innerHTML = "";
      runIds.forEach((runId) => {{
        const run = runs[runId];
        const available = Boolean(run.download);
        const row = document.createElement("div");
        row.className = "run-row";
        row.innerHTML =
          '<div class="run-row-label">' + escapeHtml(run.label || runId) + " &mdash; " + escapeHtml(modelLabelFor(run.model)) + "</div>" +
          '<div class="run-row-summary">' + escapeHtml(run.summary || "") + "</div>" +
          '<a class="download' + (available ? "" : " disabled-link") + '" href="/test-mode/download/' + encodeURIComponent(runId) + '" download aria-disabled="' + (available ? "false" : "true") + '">Download DOCX</a>';
        const link = row.querySelector("a");
        link.addEventListener("click", (event) => {{
          if (link.getAttribute("aria-disabled") === "true") event.preventDefault();
        }});
        container.appendChild(row);
      }});
    }}

    async function refreshStatus() {{
      const response = await fetch("/test-mode/status", {{ cache: "no-store" }});
      if (!response.ok) return;
      const status = await response.json();
      document.getElementById("summary").textContent = status.summary || "";
      document.getElementById("log").textContent = status.log || "";
      updateRunButton(status.running);
      updateRunStatus(status.running);
      document.getElementById("stop-button").disabled = !status.running;
      renderRunRows(status.runs);

      if (status.completed) {{
        showCompletionAlert();
      }}

      if (status.running) {{
        window.setTimeout(refreshStatus, 1500);
      }}
    }}

    function showCompletionAlert() {{
      if (completionAlertShown) return;
      completionAlertShown = true;
      showSettingsAlert("Scroll down and review the Progress Console and download each model's document.", "Batch completed");
    }}

    let settingsAlertReturnFocus = null;

    function providerForModel(model) {{
      return model && model.startsWith("claude-") ? "claude" : "gemini";
    }}

    function looksLikeClaudeKey(key) {{
      return key.trim().startsWith("sk-ant-");
    }}

    function keyMatchesProvider(model, key) {{
      const provider = providerForModel(model);
      const looksClaude = looksLikeClaudeKey(key);
      return provider === "claude" ? looksClaude : !looksClaude;
    }}

    function missingRunSettingMessage() {{
      const missing = [];
      const sourceFolderDisplay = document.getElementById("source-folder-display");
      if (!sourceFolderDisplay || sourceFolderDisplay.dataset.selected !== "true") {{
        missing.push("choose a source folder");
      }}
      if (!document.querySelector('[name="api_key_a"]').value.trim()) {{
        missing.push("paste an API key for Model A");
      }}
      if (!document.querySelector('[name="api_key_b"]').value.trim()) {{
        missing.push("paste an API key for Model B");
      }}
      if (!document.querySelector('[name="profile_id"]').value) {{
        missing.push("select a prompt profile");
      }}
      if (!missing.length) return "";
      if (missing.length === 1) return `Before running transcription, please ${{missing[0]}}.`;
      const last = missing[missing.length - 1];
      const rest = missing.slice(0, -1).join(", ");
      return `Before running transcription, please ${{rest}} and ${{last}}.`;
    }}

    function apiKeyMismatchMessage() {{
      const modelASelect = document.querySelector('[name="model_a"]');
      const modelBSelect = document.querySelector('[name="model_b"]');
      const apiKeyA = document.querySelector('[name="api_key_a"]').value.trim();
      const apiKeyB = document.querySelector('[name="api_key_b"]').value.trim();
      const problems = [];
      if (modelASelect && apiKeyA && !keyMatchesProvider(modelASelect.value, apiKeyA)) {{
        const provider = providerForModel(modelASelect.value) === "claude" ? "Claude" : "Gemini";
        problems.push(`The Model A API key doesn't look like a ${{provider}} key.`);
      }}
      if (modelBSelect && apiKeyB && !keyMatchesProvider(modelBSelect.value, apiKeyB)) {{
        const provider = providerForModel(modelBSelect.value) === "claude" ? "Claude" : "Gemini";
        problems.push(`The Model B API key doesn't look like a ${{provider}} key.`);
      }}
      return problems.join(" ");
    }}

    function updateRunButton(running) {{
      const runButton = document.getElementById("run-button");
      if (!runButton) return;
      const confirmButton = document.getElementById("confirm-run-button");
      const profileSelected = Boolean(document.querySelector('[name="profile_id"]').value);
      const apiKeyAEntered = Boolean(document.querySelector('[name="api_key_a"]').value.trim());
      const apiKeyBEntered = Boolean(document.querySelector('[name="api_key_b"]').value.trim());
      runButton.disabled = Boolean(running);
      if (confirmButton && running) confirmButton.disabled = true;
      if (running) {{
        runButton.title = "A test run is already in progress.";
      }} else if (!apiKeyAEntered || !apiKeyBEntered) {{
        runButton.title = "Paste an API key for both Model A and Model B before running.";
      }} else if (!profileSelected) {{
        runButton.title = "Select a prompt profile before running.";
      }} else {{
        runButton.title = "Check selected settings before running.";
      }}
    }}

    function selectedRunSettings() {{
      const selectedOrder = document.querySelector('[name="order"]:checked');
      const selectedFileType = document.querySelector('[name="file_type"]:checked');
      const profileId = document.querySelector('[name="profile_id"]').value;
      const profile = profiles[profileId];
      const modelASelect = document.querySelector('[name="model_a"]');
      const modelBSelect = document.querySelector('[name="model_b"]');
      const orderLabel = selectedOrder && selectedOrder.value === "oldest" ? "Oldest-to-newest" : "Newest-to-oldest";
      const fileTypeLabel = selectedFileType ? selectedFileType.value.toUpperCase() : "Not selected";
      const profileLabel = profile ? profile.profile_label || profile.label : "Select a Profile";
      const modelALabel = modelASelect ? modelASelect.options[modelASelect.selectedIndex].text : "";
      const modelBLabel = modelBSelect ? modelBSelect.options[modelBSelect.selectedIndex].text : "";
      const batchSummary = queueLength > 0
        ? queueLength + " queued batch" + (queueLength === 1 ? "" : "es")
        : modelALabel + " vs " + modelBLabel;
      return {{ orderLabel, fileTypeLabel, profileLabel, modelALabel, modelBLabel, batchSummary }};
    }}

    function runPreflightCheck() {{
      const panel = document.getElementById("run-confirmation");
      if (!panel) return;
      const settings = selectedRunSettings();
      document.getElementById("confirm-order").textContent = settings.orderLabel;
      document.getElementById("confirm-file-type").textContent = settings.fileTypeLabel;
      document.getElementById("confirm-profile").textContent = settings.profileLabel;
      document.getElementById("confirm-batches").textContent = settings.batchSummary;
      const settingsWrap = document.getElementById("run-confirmation-settings");
      const confirmButton = document.getElementById("confirm-run-button");
      const runButton = document.getElementById("run-button");
      if (settingsWrap) settingsWrap.hidden = false;
      if (confirmButton) confirmButton.disabled = false;
      if (runButton) runButton.disabled = true;
      preflightComplete = true;
    }}

    function setOrderHint() {{
      const selectedOrder = document.querySelector('[name="order"]:checked');
      const hint = document.getElementById("order-hint");
      if (!selectedOrder || !hint) return;
      hint.textContent = selectedOrder.value === "oldest"
        ? "Oldest-to-newest shows the oldest record at the top of each output document with newer entries following afterwards as you scroll."
        : "Newest-to-oldest shows the most recent record at the top of each output document with older entries following afterwards as you scroll.";
    }}

    function excludeSelectedValue(sourceSelect, targetSelect) {{
      const sourceValue = sourceSelect.value;
      let targetChanged = false;
      Array.from(targetSelect.options).forEach((option) => {{
        option.disabled = option.value === sourceValue;
      }});
      if (targetSelect.value === sourceValue) {{
        const fallback = Array.from(targetSelect.options).find((option) => !option.disabled);
        if (fallback) {{
          targetSelect.value = fallback.value;
          targetChanged = true;
        }}
      }}
      return targetChanged;
    }}

    function syncModelSelects() {{
      const selectA = document.querySelector('[name="model_a"]');
      const selectB = document.querySelector('[name="model_b"]');
      if (!selectA || !selectB) return;
      excludeSelectedValue(selectA, selectB);
      excludeSelectedValue(selectB, selectA);
    }}

    function handleProfileEditsBeforeSubmit(event) {{
      if (event.submitter && event.submitter.id === "reset-button") return;
      if (event.submitter && event.submitter.id === "profile-delete-button") return;
      if (event.submitter && event.submitter.id === "add-to-batch-button") return;
      if (event.submitter && event.submitter.id === "run-button") {{
        const missingMessage = missingRunSettingMessage();
        if (missingMessage) {{
          event.preventDefault();
          resetPreflight();
          showSettingsAlert(missingMessage);
          return;
        }}
        const mismatchMessage = apiKeyMismatchMessage();
        if (mismatchMessage) {{
          event.preventDefault();
          resetPreflight();
          showSettingsAlert(mismatchMessage);
          return;
        }}
        event.preventDefault();
        runPreflightCheck();
        return;
      }}
      if (event.submitter && event.submitter.id === "confirm-run-button" && !preflightComplete) {{
        event.preventDefault();
        showSettingsAlert("Please run the preflight check before starting.");
        return;
      }}
      if (event.submitter && event.submitter.id === "confirm-run-button") {{
        runConfirmed = false;
        preflightComplete = false;
      }}
    }}

    function formatPercent(fraction) {{
      return (fraction * 100).toFixed(2) + "%";
    }}

    function renderCompareResults(results) {{
      const container = document.getElementById("compare-results");
      container.innerHTML = "";
      if (!results || !results.length) {{
        container.innerHTML = '<p class="hint">No results.</p>';
        return;
      }}
      const table = document.createElement("table");
      table.className = "compare-table";
      const header = document.createElement("tr");
      header.innerHTML = "<th>Rank</th><th>Contestant</th><th>CER</th><th>WER</th><th>WER-BoW</th>";
      table.appendChild(header);
      results.forEach((entry) => {{
        const row = document.createElement("tr");
        if (entry.rank === 1) row.className = "compare-row-winner";
        const modelText = entry.model ? " (" + escapeHtml(modelLabelFor(entry.model)) + ")" : "";
        row.innerHTML =
          "<td>" + entry.rank + "</td>" +
          "<td>" + escapeHtml(entry.label) + modelText + "</td>" +
          "<td>" + formatPercent(entry.cer) + "</td>" +
          "<td>" + formatPercent(entry.wer) + "</td>" +
          "<td>" + formatPercent(entry.wer_bow) + "</td>";
        table.appendChild(row);
      }});
      container.appendChild(table);
    }}

    function addExtraFileRow() {{
      const container = document.getElementById("extra-model-files");
      if (!container) return;
      extraFileCount++;
      const row = document.createElement("div");
      row.className = "extra-file-row";
      row.innerHTML =
        '<input type="text" placeholder="Label for this model" data-extra-label>' +
        '<input type="file" accept=".docx" data-extra-file>' +
        '<button type="button" class="danger extra-file-remove">Remove</button>';
      row.querySelector(".extra-file-remove").addEventListener("click", () => row.remove());
      container.appendChild(row);
    }}

    let lastCompareResults = null;
    let lastCorrectedLabel = "";

    function setReportButtonAvailable(available) {{
      const wrap = document.getElementById("compare-report-actions");
      const button = document.getElementById("download-report-button");
      if (wrap) wrap.hidden = !available;
      if (button) button.disabled = !available;
    }}

    async function runCompare() {{
      const button = document.getElementById("run-compare-button");
      const status = document.getElementById("compare-file-status");
      const container = document.getElementById("compare-results");
      const correctedFile = document.getElementById("corrected-file-input").files[0];
      const correctedLabelInput = document.getElementById("corrected-label-input");
      const correctedLabel = (correctedLabelInput && correctedLabelInput.value.trim()) || "100% corrected reference";
      if (!correctedFile) {{
        if (status) status.textContent = "Upload the 100% Corrected DOCX before comparing.";
        return;
      }}

      const body = new FormData();
      body.append("corrected_file", correctedFile);

      let extraCount = 0;
      document.querySelectorAll("#extra-model-files .extra-file-row").forEach((row) => {{
        const fileInput = row.querySelector("[data-extra-file]");
        const file = fileInput && fileInput.files[0];
        if (!file) return;
        const labelInput = row.querySelector("[data-extra-label]");
        const label = (labelInput && labelInput.value.trim()) || ("Uploaded model " + extraCount);
        body.append("extra_model_file_" + extraCount, file);
        body.append("extra_model_label_" + extraCount, label);
        extraCount += 1;
      }});

      if (extraCount === 0) {{
        if (status) status.textContent = "Add at least one model DOCX to compare.";
        return;
      }}

      button.disabled = true;
      if (status) status.textContent = "Comparing...";
      container.innerHTML = "";
      setReportButtonAvailable(false);
      try {{
        const response = await fetch("/api/test-mode/compare", {{ method: "POST", body }});
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || "Comparison failed.");
        renderCompareResults(data.results);
        lastCompareResults = data.results;
        lastCorrectedLabel = correctedLabel;
        setReportButtonAvailable(true);
        if (status) status.textContent = "";
      }} catch (error) {{
        container.innerHTML = '<p class="hint">' + escapeHtml(error.message || "Comparison failed.") + "</p>";
        if (status) status.textContent = "";
      }} finally {{
        button.disabled = false;
      }}
    }}

    async function downloadCompareReport() {{
      const status = document.getElementById("compare-file-status");
      const button = document.getElementById("download-report-button");
      if (!lastCompareResults || !lastCompareResults.length) return;
      button.disabled = true;
      if (status) status.textContent = "Building report...";
      try {{
        const response = await fetch("/api/test-mode/compare-report", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ results: lastCompareResults, corrected_label: lastCorrectedLabel }}),
        }});
        if (!response.ok) {{
          const data = await response.json().catch(() => ({{}}));
          throw new Error(data.error || "Report generation failed.");
        }}
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "transcription-comparison-report.docx";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        if (status) status.textContent = "";
      }} catch (error) {{
        if (status) status.textContent = error.message || "Report generation failed.";
      }} finally {{
        button.disabled = false;
      }}
    }}

    window.addEventListener("DOMContentLoaded", () => {{
      const profileSelect = document.querySelector('[name="profile_id"]');
      if (profileSelect) {{
        profileSelect.addEventListener("change", () => {{
          updateRunButton(false);
          updateDeleteButton(false);
          resetPreflight();
          hideSettingsAlert();
        }});
      }}
      document.querySelectorAll('[name="api_key_a"], [name="api_key_b"]').forEach((input) => {{
        input.addEventListener("input", () => {{
          updateRunButton(false);
          resetPreflight();
          hideSettingsAlert();
        }});
      }});
      document.querySelectorAll('[name="order"]').forEach((input) => {{
        input.addEventListener("change", () => {{
          setOrderHint();
          resetPreflight();
        }});
      }});
      document.querySelectorAll('[name="file_type"]').forEach((input) => {{
        input.addEventListener("change", resetPreflight);
      }});
      document.querySelectorAll('[name="model_a"], [name="model_b"]').forEach((input) => {{
        input.addEventListener("change", () => {{
          syncModelSelects();
          resetPreflight();
        }});
      }});
      syncModelSelects();
      setOrderHint();
      const confirmRunButton = document.getElementById("confirm-run-button");
      if (confirmRunButton) {{
        confirmRunButton.addEventListener("click", (event) => {{
          event.preventDefault();
          runConfirmed = true;
          completionAlertShown = false;
          if (runForm) runForm.requestSubmit(confirmRunButton);
        }});
      }}
      const closeAlertButton = document.getElementById("settings-alert-close");
      if (closeAlertButton) {{
        closeAlertButton.addEventListener("click", hideSettingsAlert);
      }}
      const refreshStatusButton = document.getElementById("refresh-status-button");
      if (refreshStatusButton) {{
        refreshStatusButton.addEventListener("click", refreshStatus);
      }}
      const resetButton = document.getElementById("reset-button");
      if (resetButton) {{
        resetButton.addEventListener("click", () => {{
          resetPreflight();
          hideSettingsAlert();
          refreshStatus();
        }});
      }}
      const browseSourceButton = document.getElementById("browse-source-button");
      if (browseSourceButton) {{
        browseSourceButton.addEventListener("click", pickSourceFolder);
      }}
      const openOutputsFolderButton = document.getElementById("open-outputs-folder-button");
      if (openOutputsFolderButton) {{
        openOutputsFolderButton.addEventListener("click", openOutputsFolder);
      }}
      const sourceFolderManualButton = document.getElementById("source-folder-manual-button");
      if (sourceFolderManualButton) {{
        sourceFolderManualButton.addEventListener("click", setSourceFolderManually);
      }}
      const addExtraFileButton = document.getElementById("add-extra-file-button");
      if (addExtraFileButton) {{
        addExtraFileButton.addEventListener("click", addExtraFileRow);
      }}
      const runCompareButton = document.getElementById("run-compare-button");
      if (runCompareButton) {{
        runCompareButton.addEventListener("click", runCompare);
      }}
      const downloadReportButton = document.getElementById("download-report-button");
      if (downloadReportButton) {{
        downloadReportButton.addEventListener("click", downloadCompareReport);
      }}
      const runForm = document.querySelector('form[action="/test-mode/run"]');
      if (runForm) {{
        runForm.addEventListener("submit", handleProfileEditsBeforeSubmit);
        runForm.addEventListener("submit", confirmProfileDelete);
        runForm.addEventListener("submit", confirmReset);
      }}
      renderRunRows(initialRuns);
      updateRunButton({str(running).lower()});
      updateRunStatus({str(running).lower()});
      updateDeleteButton({str(running).lower()});
      if ({str(running).lower()}) {{
        window.setTimeout(refreshStatus, 1500);
      }}
    }});
  </script>
  <link rel="stylesheet" href="/static/base.css">
  <link rel="stylesheet" href="/static/app-shell.css">
  <style>
    input[type="file"]::file-selector-button {{
      margin-right: 8px;
      padding: 6px 10px;
      border: 1px solid #8a8377;
      border-radius: 6px;
      font: inherit;
      font-size: 13px;
      background: #f4f5f6;
      color: #1f2933;
      cursor: pointer;
    }}
    input[type="file"]::file-selector-button:hover {{
      background: #e9eaec;
    }}
    #refresh-status-button {{
      margin-top: 0;
    }}
    .queue-list {{
      list-style: none;
      margin: 6px 0 0;
      padding: 0;
      display: grid;
      gap: 8px;
    }}
    .queue-item {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 12px;
      border: 1px solid #d9d4c8;
      border-radius: 6px;
      background: #fbfaf7;
      font-size: 13px;
    }}
    .queue-item form {{
      margin: 0;
      padding: 0;
      border: 0;
      background: transparent;
    }}
    .queue-remove-button {{
      margin-top: 0;
      padding: 6px 10px;
      font-size: 12px;
    }}
    .queue-empty {{
      list-style: none;
      padding: 8px 0 0;
    }}
    .progress-rows {{
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }}
    .run-row {{
      display: grid;
      grid-template-columns: 1fr 1fr auto;
      gap: 12px;
      align-items: center;
      padding: 10px 14px;
      border: 1px solid #d9d4c8;
      border-radius: 8px;
      background: #fbfaf7;
    }}
    .run-row-label {{
      font-weight: 650;
      font-size: 13px;
    }}
    .run-row-summary {{
      color: #4b5563;
      font-size: 13px;
    }}
    .run-row .download {{
      margin-top: 0;
    }}
    .extra-file-row {{
      display: grid;
      grid-template-columns: 1fr 1fr auto;
      gap: 10px;
      align-items: center;
      margin-top: 8px;
    }}
    .extra-file-row input {{
      margin-top: 0;
    }}
    .extra-file-remove {{
      margin-top: 0;
      padding: 6px 10px;
      font-size: 12px;
    }}
    #add-to-batch-button {{
      margin-top: 6px;
    }}
    .compare-table {{
      width: 100%;
      margin-top: 14px;
      border-collapse: collapse;
      font-size: 13px;
    }}
    .compare-table th, .compare-table td {{
      border: 1px solid #d9d4c8;
      padding: 8px 10px;
      text-align: left;
    }}
    .compare-table th {{
      background: #f4f5f6;
      font-weight: 650;
    }}
    .compare-row-winner {{
      background: #eef7ef;
      font-weight: 650;
    }}
    @media (max-width: 720px) {{
      main {{
        width: min(100% - 28px, 980px);
        padding-top: 20px;
      }}
      .row, .run-options, .profile-select-row, .profile-save-row, .run-row, .extra-file-row {{ grid-template-columns: 1fr; }}
      .path-control-row, .path-manual-row {{ grid-template-columns: 1fr; }}
      .run-actions {{ grid-template-columns: 1fr; }}
      .site-header {{ align-items: stretch; }}
      .run-button-stack button {{ width: 100%; }}
    }}
  </style>
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
    <div class="site-heading">
      <h1>Test Mode</h1>
      <div class="byline-row">
        <p class="byline">Created by Steve Covello, 2026</p>
        <div class="lang-toggle" role="group" aria-label="Language / Lingua">
          <button type="button" class="lang-flag" data-lang="en" aria-pressed="true" title="English" aria-label="English">🇺🇸</button>
          <button type="button" class="lang-flag" data-lang="it" aria-pressed="false" title="Italiano" aria-label="Italiano">🇮🇹</button>
        </div>
      </div>
    </div>
    <nav class="site-nav" aria-label="Primary navigation">
      <a class="nav-link nav-home" href="/" aria-label="Home" title="Home">🏠</a>
      <a class="nav-link" href="/prompt-builder">Prompt Builder</a>
      <a class="nav-link" href="/transcribe">Transcribe</a>
      <a class="nav-link" href="/xls-conversion">XLSX Conversion</a>
      <a class="nav-link" href="/test-mode" aria-current="page">Test Mode</a>
    </nav>
  </header>
  <p class="hint">Runs the same source images and prompt profile through different models to compare performance.</p>
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
    <div class="row">
      <label>API key for Model A
        <input type="password" name="api_key_a" autocomplete="off" placeholder="Paste the API key for Model A">
      </label>
      <label>API key for Model B
        <input type="password" name="api_key_b" autocomplete="off" placeholder="Paste the API key for Model B">
      </label>
    </div>
    <p class="hint">Each key must match its model's provider (a Gemini key for a Gemini model, a Claude key for a Claude model). Used for every run in the queue. Not saved to the project files. Submitting a run sends each key and the selected source content directly to that provider's API — see PRIVACY.md.</p>
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
          <label class="radio-option"><input type="radio" name="file_type" value="pdf" required {pdf_checked}>PDF</label>
        </div>
        <p class="hint">JPEG includes .jpg and .jpeg files.</p>
      </fieldset>
    </div>
    <label>Prompt profile
      <div class="profile-select-row">
        <select name="profile_id">
          {profile_options}
        </select>
        <button id="profile-delete-button" class="danger" type="submit" formaction="/test-mode/delete-profile" formmethod="post" disabled>Delete Profile</button>
      </div>
      <input type="hidden" name="profile_action" value="use">
      <input type="hidden" name="duplicate_profile_action" value="">
      <input type="hidden" name="new_profile_name" value="">
      <p class="hint">Test Mode runs the profile as saved &mdash; edit or create profiles from the Transcribe page.</p>
    </label>
    <div class="actions run-actions">
      <div class="run-button-stack">
        <button id="run-button" type="submit" disabled>Preflight Check</button>
        <button id="confirm-run-button" type="submit" disabled>Confirm and run</button>
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
  <section class="panel">
    <h2 class="panel-title">Compare Results</h2>
    <p class="hint">Upload uncorrected DOCX transcripts to compare to a corrected DOCX.</p>
    <div id="extra-model-files">
      <div class="extra-file-row">
        <input type="text" placeholder="Label for this model" data-extra-label>
        <input type="file" accept=".docx" data-extra-file>
      </div>
      <div class="extra-file-row">
        <input type="text" placeholder="Label for this model" data-extra-label>
        <input type="file" accept=".docx" data-extra-file>
      </div>
    </div>
    <button id="add-extra-file-button" class="button-tiny" type="button">Add another</button>
    <label>100% Corrected DOCX</label>
    <div class="extra-file-row">
      <input type="text" id="corrected-label-input" placeholder="Label for this model">
      <input type="file" id="corrected-file-input" accept=".docx">
    </div>
    <p class="hint">This label doesn't appear in the results table (the corrected file is the yardstick every row is measured against, not a row itself) &mdash; it's carried into the downloadable report so the ground truth used is easy to identify later.</p>
    <p id="compare-file-status" class="hint"></p>
    <div class="actions">
      <button id="run-compare-button" class="button-secondary" type="button">Run Comparison</button>
      <span class="hint">Compare each transcript against a fully corrected version of the same content. Results show different types of error rates.</span>
    </div>
    <div id="compare-results"></div>
    <div class="actions" id="compare-report-actions" hidden>
      <button id="download-report-button" class="button-secondary" type="button" disabled>Download Comparison Report (.docx)</button>
      <span class="hint">Explains CER/WER/WER-BoW in plain language and estimates the correction effort each score implies.</span>
    </div>
  </section>
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
  <footer class="license">Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). Free to use, modify, and share — derivative works, including hosted versions, must stay open source under the same license. &middot; <a href="/privacy">Privacy</a> <span id="app-version"></span></footer>
</main>
</body>
</html>"""
