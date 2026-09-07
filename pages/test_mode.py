"""Test Mode page ("/test-mode"). Split out of app.py as part of the
app.py-modularization pass -- see CLAUDE.md."""

from __future__ import annotations

import html

from customizable_transcription.core import MODELS
from pages import FOOTER_HTML, file_picker_html, json_for_inline_script
from profiles_store import profile_options_html, profiles_for_browser
from app_state import load_source_folder, test_lock, test_state


def tm_info_button_html(panel_id: str, text: str) -> str:
    # Small "i" popup button, mirroring Prompt Builder's own
    # pb_info_button_html (pages/prompt_builder.py) under Test Mode's own
    # class names -- Test Mode's JS is inline rather than loaded from
    # static/prompt-builder.js, so this is a deliberate parallel copy, not a
    # shared import, matching how this codebase already tolerates per-page
    # duplication for styling only two pages need (see CLAUDE.md's
    # base.css/app-shell.css tiering notes).
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
    let icCandidateCount = 0;

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
      const translateStatus = window.tbTranslateStatusText || function (text) {{ return text; }};
      document.getElementById("summary").textContent = translateStatus(status.summary || "");
      document.getElementById("log").textContent = translateStatus(status.log || "");
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
      let message;
      if (!missing.length) return "";
      if (missing.length === 1) {{
        message = `Before running transcription, please ${{missing[0]}}.`;
      }} else {{
        const last = missing[missing.length - 1];
        const rest = missing.slice(0, -1).join(", ");
        message = `Before running transcription, please ${{rest}} and ${{last}}.`;
      }}
      // This sentence is assembled from variable parts, so it can't be a
      // single i18n.js DICTIONARY key -- window.tbTranslateStatusText()
      // (i18n.js) pattern-matches it instead (see DYNAMIC_LINE_PATTERNS)
      // and is safe to call from English too (returns the text unchanged).
      return typeof window.tbTranslateStatusText === "function" ? window.tbTranslateStatusText(message) : message;
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
      const message = problems.join(" ");
      // Same reasoning as missingRunSettingMessage() above -- assembled
      // from variable parts, pattern-translated via tbTranslateStatusText().
      return typeof window.tbTranslateStatusText === "function" ? window.tbTranslateStatusText(message) : message;
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
      // A raw .title assignment (above) bypasses i18n.js's DICTIONARY --
      // see showSettingsAlert()'s own comment (static/app-common.js) for
      // the same underlying bug. tbRefreshLanguage() re-applies whatever
      // language is currently active.
      if (typeof window.tbRefreshLanguage === "function") window.tbRefreshLanguage();
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
        {json_for_inline_script(file_picker_html(accept=".docx", extra_attrs="data-extra-file"))} +
        '<button type="button" class="danger extra-file-remove">Remove</button>';
      row.querySelector(".extra-file-remove").addEventListener("click", () => row.remove());
      container.appendChild(row);
      // Newly-inserted markup (the "Choose file" .file-picker button and
      // "No file selected" placeholder) bypasses i18n.js's initial-load
      // translation pass entirely -- it runs once, over content that
      // exists at that moment. tbRefreshLanguage() re-applies whatever
      // language is currently active and is exposed for exactly this case.
      if (typeof window.tbRefreshLanguage === "function") window.tbRefreshLanguage();
    }}

    function addIndexCandidateRow() {{
      const container = document.getElementById("ic-candidate-files");
      if (!container) return;
      icCandidateCount++;
      const row = document.createElement("div");
      row.className = "extra-file-row";
      row.innerHTML =
        '<input type="text" placeholder="Label for this model" data-ic-label>' +
        {json_for_inline_script(file_picker_html(accept=".xlsx", extra_attrs="data-ic-file"))} +
        '<button type="button" class="danger extra-file-remove">Remove</button>';
      row.querySelector(".extra-file-remove").addEventListener("click", () => row.remove());
      container.appendChild(row);
      if (typeof window.tbRefreshLanguage === "function") window.tbRefreshLanguage();
    }}

    // ---- Index Compare: run / mapping / results (see index_compare/ and
    // app.py's /api/index-compare/* handlers) ----

    let lastIndexCompareResult = null;
    let lastIndexCompareGroundTruthLabel = "";
    let lastIndexCompareRecordType = "";

    function icCandidateEntries() {{
      const entries = [];
      document.querySelectorAll("#ic-candidate-files .extra-file-row").forEach((row) => {{
        const fileInput = row.querySelector("[data-ic-file]");
        const file = fileInput && fileInput.files[0];
        if (!file) return;
        const labelInput = row.querySelector("[data-ic-label]");
        const label = (labelInput && labelInput.value.trim()) || ("Candidate " + (entries.length + 1));
        entries.push({{ file: file, label: label, slot: "candidate_" + entries.length }});
      }});
      return entries;
    }}

    function setIndexCompareReportButtonAvailable(available) {{
      const wrap = document.getElementById("ic-report-actions");
      const button = document.getElementById("ic-download-report-button");
      if (wrap) wrap.hidden = !available;
      if (button) button.disabled = !available;
    }}

    function renderIndexCompareMapping(needsMapping, recordTypes) {{
      const area = document.getElementById("ic-mapping-area");
      if (!area) return;
      area.innerHTML = "";
      area.hidden = false;
      needsMapping.forEach((entry) => {{
        const worksheet = entry.worksheets[0];
        const panel = document.createElement("div");
        panel.className = "ic-mapping-panel";
        panel.dataset.slot = entry.slot;
        panel.dataset.sheetName = worksheet.name;

        const title = document.createElement("p");
        title.className = "hint";
        title.textContent = '"' + worksheet.name + '" doesn\\'t match a known layout -- pick its record type to map columns, then run again.';
        panel.appendChild(title);

        const select = document.createElement("select");
        select.innerHTML =
          '<option value="">Select a record type\\u2026</option>' +
          recordTypes.map((rt) => '<option value="' + rt.value + '">' + escapeHtml(rt.label) + "</option>").join("");
        panel.appendChild(select);

        const fieldsContainer = document.createElement("div");
        fieldsContainer.className = "ic-mapping-fields";
        panel.appendChild(fieldsContainer);

        select.addEventListener("change", async () => {{
          fieldsContainer.innerHTML = "";
          if (!select.value) return;
          const response = await fetch("/api/index-compare/suggest-mapping", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{
              record_type: select.value,
              header_row1: worksheet.header_row1,
              header_row2: worksheet.header_row2,
            }}),
          }});
          const data = await response.json();
          if (!response.ok || data.error) return;
          const columnOptions = worksheet.header_row2
            .map((columnLabel, index) => {{
              const groupLabel = worksheet.header_row1[index] || "";
              const text = (groupLabel ? groupLabel + " / " : "") + (columnLabel || "(blank)");
              return '<option value="' + index + '">' + escapeHtml(text) + "</option>";
            }})
            .join("");
          data.fields.forEach((field, index) => {{
            const row = document.createElement("div");
            row.className = "ic-mapping-field-row";
            const groupLabel = data.field_group_labels[index];
            const fieldLabel = (groupLabel ? groupLabel + " / " : "") + data.field_column_labels[index];
            const label = document.createElement("label");
            label.textContent = fieldLabel;
            row.appendChild(label);
            const fieldSelect = document.createElement("select");
            fieldSelect.dataset.field = field;
            fieldSelect.innerHTML = '<option value="">(not mapped)</option>' + columnOptions;
            const suggested = data.mapping[field];
            if (suggested !== null && suggested !== undefined) fieldSelect.value = String(suggested);
            row.appendChild(fieldSelect);
            fieldsContainer.appendChild(row);
          }});
        }});

        area.appendChild(panel);
      }});
    }}

    function collectIndexCompareMappings() {{
      const mappings = {{}};
      document.querySelectorAll(".ic-mapping-panel").forEach((panel) => {{
        const recordType = panel.querySelector("select").value;
        if (!recordType) return;
        const mapping = {{}};
        panel.querySelectorAll("[data-field]").forEach((fieldSelect) => {{
          mapping[fieldSelect.dataset.field] = fieldSelect.value === "" ? null : Number(fieldSelect.value);
        }});
        mappings[panel.dataset.slot] = {{
          record_type: recordType,
          sheet_name: panel.dataset.sheetName,
          mapping: mapping,
        }};
      }});
      return mappings;
    }}

    let lastIndexCompareReportBlob = null;

    async function buildIndexCompareReportBlob(result, groundTruthLabel, recordType) {{
      const response = await fetch("/api/index-compare/report", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ result: result, ground_truth_label: groundTruthLabel, record_type: recordType }}),
      }});
      if (!response.ok) {{
        const data = await response.json().catch(() => ({{}}));
        throw new Error(data.error || "Report generation failed.");
      }}
      return response.blob();
    }}

    async function runIndexCompare() {{
      const button = document.getElementById("ic-run-button");
      const status = document.getElementById("ic-status");
      const mappingArea = document.getElementById("ic-mapping-area");

      const groundTruthFile = document.getElementById("ic-ground-truth-file").files[0];
      const groundTruthLabel = (document.getElementById("ic-ground-truth-label").value || "").trim() || "Ground truth";
      if (!groundTruthFile) {{
        if (status) status.textContent = "Upload a 100% Corrected index to compare candidates against.";
        return;
      }}
      const candidateEntries = icCandidateEntries();
      if (!candidateEntries.length) {{
        if (status) status.textContent = "Add at least one candidate index to compare.";
        return;
      }}

      const body = new FormData();
      body.append("ground_truth_file", groundTruthFile);
      body.append("ground_truth_label", groundTruthLabel);
      candidateEntries.forEach((entry, index) => {{
        body.append("candidate_file_" + index, entry.file);
        body.append("candidate_label_" + index, entry.label);
      }});

      const mappings = collectIndexCompareMappings();
      Object.keys(mappings).forEach((slot) => {{
        body.append(slot + "_mapping", JSON.stringify(mappings[slot]));
      }});

      button.disabled = true;
      if (status) status.textContent = "Comparing...";
      lastIndexCompareReportBlob = null;
      setIndexCompareReportButtonAvailable(false);
      try {{
        const response = await fetch("/api/index-compare/analyze", {{ method: "POST", body: body }});
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || "Comparison failed.");
        if (data.needs_mapping) {{
          renderIndexCompareMapping(data.needs_mapping, data.record_types);
          if (status) status.textContent = "Some files need a column mapping before comparing -- fill them in above and run again.";
          return;
        }}
        if (mappingArea) {{
          mappingArea.hidden = true;
          mappingArea.innerHTML = "";
        }}
        // The comparison itself isn't shown on screen -- Run Comparison
        // goes straight to a downloadable report instead of an on-page
        // results view (a deliberate choice: see the "Compare Indexes"
        // section this replaced its inline results table for).
        lastIndexCompareResult = data.result;
        lastIndexCompareGroundTruthLabel = data.ground_truth_label || "";
        lastIndexCompareRecordType = data.record_type || "";
        if (status) status.textContent = "Building report...";
        lastIndexCompareReportBlob = await buildIndexCompareReportBlob(
          lastIndexCompareResult,
          lastIndexCompareGroundTruthLabel,
          lastIndexCompareRecordType
        );
        setIndexCompareReportButtonAvailable(true);
        if (status) status.textContent = "Report ready -- click Download to save it.";
      }} catch (error) {{
        if (status) status.textContent = escapeHtml(error.message || "Comparison failed.");
      }} finally {{
        button.disabled = false;
      }}
    }}

    async function downloadIndexCompareReport() {{
      const status = document.getElementById("ic-status");
      const button = document.getElementById("ic-download-report-button");
      if (!lastIndexCompareReportBlob) return;
      button.disabled = true;
      try {{
        const url = URL.createObjectURL(lastIndexCompareReportBlob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "index-comparison-report.docx";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      }} catch (error) {{
        if (status) status.textContent = error.message || "Download failed.";
      }} finally {{
        button.disabled = false;
      }}
    }}

    // ---- Info-button popups (see tm_info_button_html() in test_mode.py) ----
    // Mirrors Prompt Builder's own wireInfoButtons()/closeAllInfoPanels()
    // (static/prompt-builder.js) under Test Mode's own class names.

    function closeAllTmInfoPanels(except) {{
      document.querySelectorAll(".tm-info-panel").forEach((panel) => {{
        if (panel === except) return;
        panel.hidden = true;
        const btn = document.querySelector('.tm-info-btn[aria-controls="' + panel.id + '"]');
        if (btn) btn.setAttribute("aria-expanded", "false");
      }});
    }}

    function wireTmInfoButtons() {{
      document.addEventListener("click", (event) => {{
        const btn = event.target.closest(".tm-info-btn");
        if (btn) {{
          // preventDefault() here also stops the click from being treated
          // as a click on the enclosing <summary> -- these buttons sit
          // inside a collapsible section's <summary> (next to its title),
          // and without this, opening the info popup would also toggle the
          // section open/closed.
          event.preventDefault();
          const panel = document.getElementById(btn.getAttribute("aria-controls"));
          const wasOpen = panel && !panel.hidden;
          closeAllTmInfoPanels();
          if (panel && !wasOpen) {{
            panel.hidden = false;
            btn.setAttribute("aria-expanded", "true");
          }}
          return;
        }}
        if (!event.target.closest(".tm-info-panel")) closeAllTmInfoPanels();
      }});
      document.addEventListener("keydown", (event) => {{
        if (event.key === "Escape") closeAllTmInfoPanels();
      }});
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

    // Shows the chosen filename next to the .file-picker translatable
    // stand-in button (static/base.css) -- see file_picker_html()'s own
    // docstring (pages/__init__.py) for why this never needs to restore
    // the placeholder text itself. Delegated on document so it also
    // covers rows added later by "Add another" (addExtraFileRow()/
    // addIndexCandidateRow() above), with nothing extra to wire up.
    document.addEventListener("change", (event) => {{
      const input = event.target;
      if (!input || input.tagName !== "INPUT" || input.type !== "file") return;
      const picker = input.closest(".file-picker");
      const nameEl = picker && picker.querySelector(".file-picker-name");
      if (nameEl && input.files && input.files.length) nameEl.textContent = input.files[0].name;
    }});

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
      const addIcCandidateButton = document.getElementById("ic-add-candidate-button");
      if (addIcCandidateButton) {{
        addIcCandidateButton.addEventListener("click", addIndexCandidateRow);
      }}
      const icRunButton = document.getElementById("ic-run-button");
      if (icRunButton) {{
        icRunButton.addEventListener("click", runIndexCompare);
      }}
      const icDownloadReportButton = document.getElementById("ic-download-report-button");
      if (icDownloadReportButton) {{
        icDownloadReportButton.addEventListener("click", downloadIndexCompareReport);
      }}
      wireTmInfoButtons();
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
    #refresh-status-button, #open-outputs-folder-button {{
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
    .extra-file-row input, .extra-file-row .file-picker {{
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
    /* Collapsible section shell, adapted from Prompt Builder's
       details.pb-section (pages/prompt_builder.py) -- Test Mode had no
       collapsible-section pattern of its own before Index Compare needed
       one. Kept as a local copy rather than shared CSS since exactly these
       two pages need it, not the same Transcribe+Test Mode pair
       static/app-shell.css already covers -- see CLAUDE.md's modularization
       notes on why this codebase tolerates that kind of duplication. */
    details.tm-section {{
      background: #ffffff;
      border: 1px solid #d9d4c8;
      border-radius: 8px;
      padding: 14px 18px;
      margin-top: 20px;
      margin-bottom: 20px;
    }}
    details.tm-section summary {{
      cursor: pointer;
      list-style: none;
      display: flex;
      justify-content: flex-start;
      align-items: baseline;
      gap: 10px;
      font-weight: 700;
      font-size: 16px;
      padding: 2px 0;
    }}
    details.tm-section summary::-webkit-details-marker {{
      display: none;
    }}
    details.tm-section summary::before {{
      content: "\\25B8";
      margin-right: 8px;
      color: #255c99;
      display: inline-block;
      transition: transform 0.12s ease;
    }}
    details.tm-section[open] summary::before {{
      transform: rotate(90deg);
    }}
    .tm-section-hint {{
      margin-top: 4px;
    }}
    .ic-mapping-panel {{
      margin-top: 12px;
      padding: 10px 12px;
      border: 1px solid #d9d4c8;
      border-radius: 6px;
      background: #fbfaf7;
    }}
    .ic-mapping-panel select {{
      margin-top: 6px;
    }}
    .ic-mapping-fields {{
      display: grid;
      gap: 6px;
      margin-top: 10px;
    }}
    .ic-mapping-field-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      align-items: center;
    }}
    .ic-mapping-field-row label {{
      margin: 0;
      font-size: 13px;
    }}
    .ic-mapping-field-row select {{
      margin: 0;
    }}
    /* Info-button popups, adapted from Prompt Builder's .pb-info-wrap/
       .pb-info-btn/.pb-info-panel (pages/prompt_builder.py) under Test
       Mode's own class names -- see tm_info_button_html()'s own comment. */
    .tm-info-wrap {{
      position: relative;
      display: inline-block;
      vertical-align: middle;
    }}
    .tm-info-btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      padding: 0;
      border-radius: 50%;
      background: #5f6b76;
      color: #fff;
      font-size: 13px;
      font-weight: 400;
      font-style: italic;
      font-family: Georgia, "Times New Roman", serif;
      line-height: 1;
      vertical-align: middle;
    }}
    .tm-info-btn:hover {{
      background: #45505a;
    }}
    .tm-info-panel {{
      position: absolute;
      z-index: 20;
      top: 30px;
      left: 0;
      width: max-content;
      max-width: 320px;
      padding: 10px 12px;
      border-radius: 6px;
      background: #1f2933;
      color: #eef2f6;
      font-size: 12.5px;
      font-weight: 400;
      line-height: 1.45;
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
    }}
    @media (max-width: 720px) {{
      main {{
        width: min(100% - 28px, 980px);
        padding-top: 20px;
      }}
      .tm-info-panel {{ max-width: calc(100vw - 60px); }}
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
