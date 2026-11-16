/* Test Mode page ("/test-mode") script, extracted from pages/test_mode.py's
inline <script> block -- see reviews/CODEX_REVIEW.md finding L-2 / reviews/HUMAN_DECISIONS.md.
Content is unchanged from the inline block it replaced, except: (1) braces
are no longer doubled since this isn't inside an f-string anymore; (2) the
per-request dynamic values (profiles/MODEL_LABELS/initialRuns/queueLength/
running) are now read from the test-mode-initial-data JSON data island
(see json_data_island_html() in pages/__init__.py) instead of being
assigned directly by an executable inline <script>; (3) the two
addExtraFileRow()/addIndexCandidateRow() file-picker HTML strings are now
baked-in literals (they never varied per request) instead of computed via
json_for_inline_script(file_picker_html(...)) at render time -- byte-
identical output either way. Not deferred (loaded via a plain <script src>,
same as before) since this script's own top-level statements (the initial
const declarations, the closing IIFE) run in document order exactly where
the inline block used to sit. */
    document.addEventListener("click", function (event) {
      const link = event.target.closest("a.download");
      if (link && link.getAttribute("aria-disabled") === "true") {
        event.preventDefault();
      }
    });

    const TM_INITIAL_DATA = JSON.parse(document.getElementById("test-mode-initial-data").textContent);
    const profiles = TM_INITIAL_DATA.profiles;
    const MODEL_LABELS = TM_INITIAL_DATA.modelLabels;
    const initialRuns = TM_INITIAL_DATA.initialRuns;
    const queueLength = TM_INITIAL_DATA.queueLength;
    const running = TM_INITIAL_DATA.running;
    let runConfirmed = false;
    let preflightComplete = false;
    let completionAlertShown = false;
    let extraFileCount = 0;
    let icCandidateCount = 0;

    function modelLabelFor(modelId) {
      return MODEL_LABELS[modelId] || modelId || "";
    }

    function escapeHtml(value) {
      const div = document.createElement("div");
      div.textContent = value === null || value === undefined ? "" : String(value);
      return div.innerHTML;
    }

    function renderRunRows(runs) {
      const container = document.getElementById("progress-rows");
      if (!container) return;
      const runIds = Object.keys(runs || {});
      if (!runIds.length) {
        container.innerHTML = '<p class="hint">No runs yet.</p>';
        return;
      }
      container.innerHTML = "";
      runIds.forEach((runId) => {
        const run = runs[runId];
        const available = Boolean(run.download);
        const row = document.createElement("div");
        row.className = "run-row";
        row.innerHTML =
          '<div class="run-row-label">' + escapeHtml(run.label || runId) + " &mdash; " + escapeHtml(modelLabelFor(run.model)) + "</div>" +
          '<div class="run-row-summary">' + escapeHtml(run.summary || "") + "</div>" +
          '<a class="download' + (available ? "" : " disabled-link") + '" href="/test-mode/download/' + encodeURIComponent(runId) + '" download aria-disabled="' + (available ? "false" : "true") + '">Download DOCX</a>';
        const link = row.querySelector("a");
        link.addEventListener("click", (event) => {
          if (link.getAttribute("aria-disabled") === "true") event.preventDefault();
        });
        container.appendChild(row);
      });
    }

    async function refreshStatus() {
      const response = await fetch("/test-mode/status", { cache: "no-store" });
      if (!response.ok) return;
      const status = await response.json();
      const translateStatus = window.tbTranslateStatusText || function (text) { return text; };
      document.getElementById("summary").textContent = translateStatus(status.summary || "");
      document.getElementById("log").textContent = translateStatus(status.log || "");
      updateRunButton(status.running);
      updateRunStatus(status.running, status.off_peak);
      document.getElementById("stop-button").disabled = !status.running;
      renderRunRows(status.runs);

      if (status.completed) {
        showCompletionAlert();
      }

      if (status.running) {
        window.setTimeout(refreshStatus, 1500);
      }
    }

    function showCompletionAlert() {
      if (completionAlertShown) return;
      completionAlertShown = true;
      showSettingsAlert("Scroll down and review the Progress Console and download each model's document.", "Batch completed");
    }

    let settingsAlertReturnFocus = null;

    function providerForModel(model) {
      return model && model.startsWith("claude-") ? "claude" : "gemini";
    }

    function looksLikeClaudeKey(key) {
      return key.trim().startsWith("sk-ant-");
    }

    // API keys are entered per provider (one Gemini field, one Claude
    // field), not per A/B slot -- see required_providers() in app.py for
    // why. currentlyNeededProviders() only looks at the Model A/B selects
    // currently shown (the pair about to run or be added to the queue);
    // it can't see providers already-queued batches need, since the queue
    // doesn't expose its own model choices back to this script -- the
    // server-side check in run_test() is authoritative and batch-aware for
    // the full queue, this is just a same-page convenience.
    function currentlyNeededProviders() {
      const modelASelect = document.querySelector('[name="model_a"]');
      const modelBSelect = document.querySelector('[name="model_b"]');
      const needed = new Set();
      if (modelASelect) needed.add(providerForModel(modelASelect.value));
      if (modelBSelect) needed.add(providerForModel(modelBSelect.value));
      return needed;
    }

    function providerKeyInput(provider) {
      return document.querySelector('[name="api_key_' + provider + '"]');
    }

    function missingRunSettingMessage() {
      const missing = [];
      const sourceFolderDisplay = document.getElementById("source-folder-display");
      if (!sourceFolderDisplay || sourceFolderDisplay.dataset.selected !== "true") {
        missing.push("choose a source folder");
      }
      currentlyNeededProviders().forEach((provider) => {
        const input = providerKeyInput(provider);
        if (!input || !input.value.trim()) {
          missing.push(provider === "claude" ? "paste a Claude API key" : "paste a Gemini API key");
        }
      });
      if (!document.querySelector('[name="profile_id"]').value) {
        missing.push("select a prompt profile");
      }
      let message;
      if (!missing.length) return "";
      if (missing.length === 1) {
        message = `Before running transcription, please ${missing[0]}.`;
      } else {
        const last = missing[missing.length - 1];
        const rest = missing.slice(0, -1).join(", ");
        message = `Before running transcription, please ${rest} and ${last}.`;
      }
      // This sentence is assembled from variable parts, so it can't be a
      // single i18n.js DICTIONARY key -- window.tbTranslateStatusText()
      // (i18n.js) pattern-matches it instead (see DYNAMIC_LINE_PATTERNS)
      // and is safe to call from English too (returns the text unchanged).
      return typeof window.tbTranslateStatusText === "function" ? window.tbTranslateStatusText(message) : message;
    }

    function apiKeyMismatchMessage() {
      const geminiKey = document.querySelector('[name="api_key_gemini"]').value.trim();
      const claudeKey = document.querySelector('[name="api_key_claude"]').value.trim();
      const problems = [];
      if (geminiKey && looksLikeClaudeKey(geminiKey)) {
        problems.push("The Gemini API key looks like a Claude key -- check you pasted the right one.");
      }
      if (claudeKey && !looksLikeClaudeKey(claudeKey)) {
        problems.push("The Claude API key doesn't look like a Claude key.");
      }
      const message = problems.join(" ");
      // Same reasoning as missingRunSettingMessage() above -- assembled
      // from variable parts, pattern-translated via tbTranslateStatusText().
      return typeof window.tbTranslateStatusText === "function" ? window.tbTranslateStatusText(message) : message;
    }

    function updateRunButton(running) {
      const runButton = document.getElementById("run-button");
      if (!runButton) return;
      const confirmButton = document.getElementById("confirm-run-button");
      const offPeakButton = document.getElementById("confirm-run-offpeak-button");
      const profileSelected = Boolean(document.querySelector('[name="profile_id"]').value);
      const missingKey = Array.from(currentlyNeededProviders()).some((provider) => {
        const input = providerKeyInput(provider);
        return !input || !input.value.trim();
      });
      runButton.disabled = Boolean(running);
      if (confirmButton && running) confirmButton.disabled = true;
      if (offPeakButton && running) offPeakButton.disabled = true;
      if (running) {
        runButton.title = "A test run is already in progress.";
      } else if (missingKey) {
        runButton.title = "Paste the API key for each model provider in use before running.";
      } else if (!profileSelected) {
        runButton.title = "Select a prompt profile before running.";
      } else {
        runButton.title = "Check selected settings before running.";
      }
      // A raw .title assignment (above) bypasses i18n.js's DICTIONARY --
      // see showSettingsAlert()'s own comment (static/app-common.js) for
      // the same underlying bug. tbRefreshLanguage() re-applies whatever
      // language is currently active.
      if (typeof window.tbRefreshLanguage === "function") window.tbRefreshLanguage();
    }

    function selectedRunSettings() {
      const selectedOrder = document.querySelector('[name="order"]:checked');
      const selectedFileType = document.querySelector('[name="file_type"]:checked');
      const profileId = document.querySelector('[name="profile_id"]').value;
      const profile = profiles[profileId];
      const modelASelect = document.querySelector('[name="model_a"]');
      const modelBSelect = document.querySelector('[name="model_b"]');
      const orderLabel = selectedOrder && selectedOrder.value === "oldest" ? "Oldest-to-newest" : "Newest-to-oldest";
      const fileTypeLabel = selectedFileType ? selectedFileType.value.toUpperCase() : "Not selected";
      const profileLabel = profile ? profile.profile_label || profile.label : "Select a Profile";
      const zoomA = document.querySelector('[name="zoom_a"]');
      const zoomB = document.querySelector('[name="zoom_b"]');
      const modelALabel = (modelASelect ? modelASelect.options[modelASelect.selectedIndex].text : "")
        + (zoomA && zoomA.checked ? " (Page zoom)" : "");
      const modelBLabel = (modelBSelect ? modelBSelect.options[modelBSelect.selectedIndex].text : "")
        + (zoomB && zoomB.checked ? " (Page zoom)" : "");
      const batchSummary = queueLength > 0
        ? queueLength + " queued batch" + (queueLength === 1 ? "" : "es")
        : modelALabel + " vs " + modelBLabel;
      return { orderLabel, fileTypeLabel, profileLabel, modelALabel, modelBLabel, batchSummary };
    }

    function runPreflightCheck() {
      const panel = document.getElementById("run-confirmation");
      if (!panel) return;
      const settings = selectedRunSettings();
      document.getElementById("confirm-order").textContent = settings.orderLabel;
      document.getElementById("confirm-file-type").textContent = settings.fileTypeLabel;
      document.getElementById("confirm-profile").textContent = settings.profileLabel;
      document.getElementById("confirm-batches").textContent = settings.batchSummary;
      const settingsWrap = document.getElementById("run-confirmation-settings");
      const confirmButton = document.getElementById("confirm-run-button");
      const offPeakButton = document.getElementById("confirm-run-offpeak-button");
      const runButton = document.getElementById("run-button");
      if (settingsWrap) settingsWrap.hidden = false;
      if (confirmButton) confirmButton.disabled = false;
      if (offPeakButton) offPeakButton.disabled = false;
      if (runButton) runButton.disabled = true;
      preflightComplete = true;
    }

    function setOrderHint() {
      const selectedOrder = document.querySelector('[name="order"]:checked');
      const hint = document.getElementById("order-hint");
      if (!selectedOrder || !hint) return;
      hint.textContent = selectedOrder.value === "oldest"
        ? "Oldest-to-newest shows the oldest record at the top of each output document with newer entries following afterwards as you scroll."
        : "Newest-to-oldest shows the most recent record at the top of each output document with older entries following afterwards as you scroll.";
    }

    function excludeSelectedValue(sourceSelect, targetSelect) {
      const sourceValue = sourceSelect.value;
      let targetChanged = false;
      Array.from(targetSelect.options).forEach((option) => {
        option.disabled = option.value === sourceValue;
      });
      if (targetSelect.value === sourceValue) {
        const fallback = Array.from(targetSelect.options).find((option) => !option.disabled);
        if (fallback) {
          targetSelect.value = fallback.value;
          targetChanged = true;
        }
      }
      return targetChanged;
    }

    function syncModelSelects() {
      const selectA = document.querySelector('[name="model_a"]');
      const selectB = document.querySelector('[name="model_b"]');
      if (!selectA || !selectB) return;
      // The same model on both sides is a real comparison when Page zoom
      // is on for only one of them (selected_model_pair() in run_support.py).
      const zoomA = document.querySelector('[name="zoom_a"]');
      const zoomB = document.querySelector('[name="zoom_b"]');
      if (zoomA && zoomB && zoomA.checked !== zoomB.checked) {
        Array.from(selectA.options).forEach((option) => { option.disabled = false; });
        Array.from(selectB.options).forEach((option) => { option.disabled = false; });
        return;
      }
      excludeSelectedValue(selectA, selectB);
      excludeSelectedValue(selectB, selectA);
    }

    function handleProfileEditsBeforeSubmit(event) {
      if (event.submitter && event.submitter.id === "reset-button") return;
      if (event.submitter && event.submitter.id === "add-to-batch-button") return;
      if (event.submitter && event.submitter.id === "run-button") {
        const missingMessage = missingRunSettingMessage();
        if (missingMessage) {
          event.preventDefault();
          resetPreflight();
          showSettingsAlert(missingMessage);
          return;
        }
        const mismatchMessage = apiKeyMismatchMessage();
        if (mismatchMessage) {
          event.preventDefault();
          resetPreflight();
          showSettingsAlert(mismatchMessage);
          return;
        }
        event.preventDefault();
        runPreflightCheck();
        return;
      }
      const isConfirmSubmit = event.submitter && (
        event.submitter.id === "confirm-run-button" || event.submitter.id === "confirm-run-offpeak-button"
      );
      if (isConfirmSubmit && !preflightComplete) {
        event.preventDefault();
        showSettingsAlert("Please run the preflight check before starting.");
        return;
      }
      if (isConfirmSubmit) {
        runConfirmed = false;
        preflightComplete = false;
      }
    }

    function formatPercent(fraction) {
      return (fraction * 100).toFixed(2) + "%";
    }

    function renderCompareResults(results) {
      const container = document.getElementById("compare-results");
      container.innerHTML = "";
      if (!results || !results.length) {
        container.innerHTML = '<p class="hint">No results.</p>';
        return;
      }
      const table = document.createElement("table");
      table.className = "compare-table";
      const header = document.createElement("tr");
      header.innerHTML = "<th>Rank</th><th>Contestant</th><th>CER</th><th>WER</th><th>WER-BoW</th>";
      table.appendChild(header);
      results.forEach((entry) => {
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
      });
      container.appendChild(table);
    }

    function addExtraFileRow() {
      const container = document.getElementById("extra-model-files");
      if (!container) return;
      extraFileCount++;
      const row = document.createElement("div");
      row.className = "extra-file-row";
      row.innerHTML =
        '<input type="text" placeholder="Label for this model" data-extra-label>' +
        "<label class=\"file-picker\"><input type=\"file\" accept=\".docx\" data-extra-file><span class=\"file-picker-btn\">Choose file<\/span><span class=\"file-picker-name\">No file selected<\/span><\/label>" +
        '<button type="button" class="danger extra-file-remove">Remove</button>';
      row.querySelector(".extra-file-remove").addEventListener("click", () => row.remove());
      container.appendChild(row);
      // Newly-inserted markup (the "Choose file" .file-picker button and
      // "No file selected" placeholder) bypasses i18n.js's initial-load
      // translation pass entirely -- it runs once, over content that
      // exists at that moment. tbRefreshLanguage() re-applies whatever
      // language is currently active and is exposed for exactly this case.
      if (typeof window.tbRefreshLanguage === "function") window.tbRefreshLanguage();
    }

    function addIndexCandidateRow() {
      const container = document.getElementById("ic-candidate-files");
      if (!container) return;
      icCandidateCount++;
      const row = document.createElement("div");
      row.className = "extra-file-row";
      row.innerHTML =
        '<input type="text" placeholder="Label for this model" data-ic-label>' +
        "<label class=\"file-picker\"><input type=\"file\" accept=\".xlsx\" data-ic-file><span class=\"file-picker-btn\">Choose file<\/span><span class=\"file-picker-name\">No file selected<\/span><\/label>" +
        '<button type="button" class="danger extra-file-remove">Remove</button>';
      row.querySelector(".extra-file-remove").addEventListener("click", () => row.remove());
      container.appendChild(row);
      if (typeof window.tbRefreshLanguage === "function") window.tbRefreshLanguage();
    }

    // ---- Index Compare: run / mapping / results (see index_compare/ and
    // app.py's /api/index-compare/* handlers) ----

    let lastIndexCompareResult = null;
    let lastIndexCompareGroundTruthLabel = "";
    let lastIndexCompareRecordType = "";

    function icCandidateEntries() {
      const entries = [];
      document.querySelectorAll("#ic-candidate-files .extra-file-row").forEach((row) => {
        const fileInput = row.querySelector("[data-ic-file]");
        const file = fileInput && fileInput.files[0];
        if (!file) return;
        const labelInput = row.querySelector("[data-ic-label]");
        const label = (labelInput && labelInput.value.trim()) || ("Candidate " + (entries.length + 1));
        entries.push({ file: file, label: label, slot: "candidate_" + entries.length });
      });
      return entries;
    }

    function setIndexCompareReportButtonAvailable(available) {
      const wrap = document.getElementById("ic-report-actions");
      const button = document.getElementById("ic-download-report-button");
      if (wrap) wrap.hidden = !available;
      if (button) button.disabled = !available;
    }

    function renderIndexCompareMapping(needsMapping, recordTypes) {
      const area = document.getElementById("ic-mapping-area");
      if (!area) return;
      area.innerHTML = "";
      area.hidden = false;
      needsMapping.forEach((entry) => {
        // `worksheet` is the currently-selected sheet for this candidate --
        // `let`, not `const`, since a multi-worksheet workbook (see the
        // selector below) can change which one this closure should use.
        // Previously always entry.worksheets[0], so a workbook whose real
        // index wasn't its first sheet (e.g. a first sheet of instructions/
        // metadata) could never be mapped at all -- see reviews/CODEX_REVIEW.md
        // finding L-7 / reviews/HUMAN_DECISIONS.md.
        let worksheet = entry.worksheets[0];
        const panel = document.createElement("div");
        panel.className = "ic-mapping-panel";
        panel.dataset.slot = entry.slot;
        panel.dataset.sheetName = worksheet.name;

        const title = document.createElement("p");
        title.className = "hint";
        panel.appendChild(title);

        const recordTypeSelect = document.createElement("select");
        recordTypeSelect.className = "ic-mapping-record-type";
        const fieldsContainer = document.createElement("div");
        fieldsContainer.className = "ic-mapping-fields";

        function updateTitleForWorksheet() {
          title.textContent =
            '"' + worksheet.name + '" doesn\'t match a known layout -- pick its record type to map columns, then run again.';
        }

        // Only shown when the workbook actually returned more than one
        // worksheet -- the common single-sheet case stays exactly as
        // before, no extra control to notice or skip past.
        if (entry.worksheets.length > 1) {
          const worksheetRow = document.createElement("label");
          worksheetRow.textContent = "Worksheet";
          const worksheetSelect = document.createElement("select");
          worksheetSelect.innerHTML = entry.worksheets
            .map((ws, index) => '<option value="' + index + '">' + escapeHtml(ws.name) + "</option>")
            .join("");
          worksheetSelect.addEventListener("change", () => {
            worksheet = entry.worksheets[Number(worksheetSelect.value)];
            panel.dataset.sheetName = worksheet.name;
            updateTitleForWorksheet();
            // A different worksheet has its own (possibly nonexistent)
            // header layout -- any record-type choice and field mapping
            // made against the previous sheet no longer applies.
            recordTypeSelect.value = "";
            fieldsContainer.innerHTML = "";
          });
          worksheetRow.appendChild(worksheetSelect);
          panel.appendChild(worksheetRow);
        }

        updateTitleForWorksheet();

        recordTypeSelect.innerHTML =
          '<option value="">Select a record type\u2026</option>' +
          recordTypes.map((rt) => '<option value="' + rt.value + '">' + escapeHtml(rt.label) + "</option>").join("");
        panel.appendChild(recordTypeSelect);
        panel.appendChild(fieldsContainer);

        recordTypeSelect.addEventListener("change", async () => {
          fieldsContainer.innerHTML = "";
          if (!recordTypeSelect.value) return;
          const response = await fetch("/api/index-compare/suggest-mapping", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              record_type: recordTypeSelect.value,
              header_row1: worksheet.header_row1,
              header_row2: worksheet.header_row2,
            }),
          });
          const data = await response.json();
          if (!response.ok || data.error) return;
          const columnOptions = worksheet.header_row2
            .map((columnLabel, index) => {
              const groupLabel = worksheet.header_row1[index] || "";
              const text = (groupLabel ? groupLabel + " / " : "") + (columnLabel || "(blank)");
              return '<option value="' + index + '">' + escapeHtml(text) + "</option>";
            })
            .join("");
          data.fields.forEach((field, index) => {
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
          });
        });

        area.appendChild(panel);
      });
    }

    function collectIndexCompareMappings() {
      const mappings = {};
      document.querySelectorAll(".ic-mapping-panel").forEach((panel) => {
        // Scoped to .ic-mapping-record-type specifically, not just "the
        // first select in this panel" -- a multi-worksheet panel now has
        // its own worksheet-picker <select> ahead of this one.
        const recordType = panel.querySelector(".ic-mapping-record-type").value;
        if (!recordType) return;
        const mapping = {};
        panel.querySelectorAll("[data-field]").forEach((fieldSelect) => {
          mapping[fieldSelect.dataset.field] = fieldSelect.value === "" ? null : Number(fieldSelect.value);
        });
        mappings[panel.dataset.slot] = {
          record_type: recordType,
          sheet_name: panel.dataset.sheetName,
          mapping: mapping,
        };
      });
      return mappings;
    }

    let lastIndexCompareReportBlob = null;

    async function buildIndexCompareReportBlob(result, groundTruthLabel, recordType) {
      const response = await fetch("/api/index-compare/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ result: result, ground_truth_label: groundTruthLabel, record_type: recordType }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "Report generation failed.");
      }
      return response.blob();
    }

    async function runIndexCompare() {
      const button = document.getElementById("ic-run-button");
      const status = document.getElementById("ic-status");
      const mappingArea = document.getElementById("ic-mapping-area");

      const groundTruthFile = document.getElementById("ic-ground-truth-file").files[0];
      const groundTruthLabel = (document.getElementById("ic-ground-truth-label").value || "").trim() || "Ground truth";
      if (!groundTruthFile) {
        if (status) status.textContent = "Upload a 100% Corrected index to compare candidates against.";
        return;
      }
      const candidateEntries = icCandidateEntries();
      if (!candidateEntries.length) {
        if (status) status.textContent = "Add at least one candidate index to compare.";
        return;
      }

      const body = new FormData();
      body.append("ground_truth_file", groundTruthFile);
      body.append("ground_truth_label", groundTruthLabel);
      candidateEntries.forEach((entry, index) => {
        body.append("candidate_file_" + index, entry.file);
        body.append("candidate_label_" + index, entry.label);
      });

      const mappings = collectIndexCompareMappings();
      Object.keys(mappings).forEach((slot) => {
        body.append(slot + "_mapping", JSON.stringify(mappings[slot]));
      });

      button.disabled = true;
      if (status) status.textContent = "Comparing...";
      lastIndexCompareReportBlob = null;
      setIndexCompareReportButtonAvailable(false);
      try {
        const response = await fetch("/api/index-compare/analyze", { method: "POST", body: body });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || "Comparison failed.");
        if (data.needs_mapping) {
          renderIndexCompareMapping(data.needs_mapping, data.record_types);
          if (status) status.textContent = "Some files need a column mapping before comparing -- fill them in above and run again.";
          return;
        }
        if (mappingArea) {
          mappingArea.hidden = true;
          mappingArea.innerHTML = "";
        }
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
      } catch (error) {
        if (status) status.textContent = escapeHtml(error.message || "Comparison failed.");
      } finally {
        button.disabled = false;
      }
    }

    async function downloadIndexCompareReport() {
      const status = document.getElementById("ic-status");
      const button = document.getElementById("ic-download-report-button");
      if (!lastIndexCompareReportBlob) return;
      button.disabled = true;
      try {
        const url = URL.createObjectURL(lastIndexCompareReportBlob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "index-comparison-report.docx";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      } catch (error) {
        if (status) status.textContent = error.message || "Download failed.";
      } finally {
        button.disabled = false;
      }
    }

    // ---- Info-button popups (see tm_info_button_html() in test_mode.py) ----
    // Mirrors Prompt Builder's own wireInfoButtons()/closeAllInfoPanels()
    // (static/prompt-builder.js) under Test Mode's own class names.

    function closeAllTmInfoPanels(except) {
      document.querySelectorAll(".tm-info-panel").forEach((panel) => {
        if (panel === except) return;
        panel.hidden = true;
        const btn = document.querySelector('.tm-info-btn[aria-controls="' + panel.id + '"]');
        if (btn) btn.setAttribute("aria-expanded", "false");
      });
    }

    function wireTmInfoButtons() {
      document.addEventListener("click", (event) => {
        const btn = event.target.closest(".tm-info-btn");
        if (btn) {
          // preventDefault() here also stops the click from being treated
          // as a click on the enclosing <summary> -- these buttons sit
          // inside a collapsible section's <summary> (next to its title),
          // and without this, opening the info popup would also toggle the
          // section open/closed.
          event.preventDefault();
          const panel = document.getElementById(btn.getAttribute("aria-controls"));
          const wasOpen = panel && !panel.hidden;
          closeAllTmInfoPanels();
          if (panel && !wasOpen) {
            panel.hidden = false;
            btn.setAttribute("aria-expanded", "true");
          }
          return;
        }
        if (!event.target.closest(".tm-info-panel")) closeAllTmInfoPanels();
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeAllTmInfoPanels();
      });
    }

    let lastCompareResults = null;
    let lastCorrectedLabel = "";

    function setReportButtonAvailable(available) {
      const wrap = document.getElementById("compare-report-actions");
      const button = document.getElementById("download-report-button");
      if (wrap) wrap.hidden = !available;
      if (button) button.disabled = !available;
    }

    async function runCompare() {
      const button = document.getElementById("run-compare-button");
      const status = document.getElementById("compare-file-status");
      const container = document.getElementById("compare-results");
      const correctedFile = document.getElementById("corrected-file-input").files[0];
      const correctedLabelInput = document.getElementById("corrected-label-input");
      const correctedLabel = (correctedLabelInput && correctedLabelInput.value.trim()) || "100% corrected reference";
      if (!correctedFile) {
        if (status) status.textContent = "Upload the 100% Corrected DOCX before comparing.";
        return;
      }

      const body = new FormData();
      body.append("corrected_file", correctedFile);

      let extraCount = 0;
      document.querySelectorAll("#extra-model-files .extra-file-row").forEach((row) => {
        const fileInput = row.querySelector("[data-extra-file]");
        const file = fileInput && fileInput.files[0];
        if (!file) return;
        const labelInput = row.querySelector("[data-extra-label]");
        const label = (labelInput && labelInput.value.trim()) || ("Uploaded model " + extraCount);
        body.append("extra_model_file_" + extraCount, file);
        body.append("extra_model_label_" + extraCount, label);
        extraCount += 1;
      });

      if (extraCount === 0) {
        if (status) status.textContent = "Add at least one model DOCX to compare.";
        return;
      }

      button.disabled = true;
      if (status) status.textContent = "Comparing...";
      container.innerHTML = "";
      setReportButtonAvailable(false);
      try {
        const response = await fetch("/api/test-mode/compare", { method: "POST", body });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || "Comparison failed.");
        renderCompareResults(data.results);
        lastCompareResults = data.results;
        lastCorrectedLabel = correctedLabel;
        setReportButtonAvailable(true);
        if (status) status.textContent = "";
      } catch (error) {
        container.innerHTML = '<p class="hint">' + escapeHtml(error.message || "Comparison failed.") + "</p>";
        if (status) status.textContent = "";
      } finally {
        button.disabled = false;
      }
    }

    async function downloadCompareReport() {
      const status = document.getElementById("compare-file-status");
      const button = document.getElementById("download-report-button");
      if (!lastCompareResults || !lastCompareResults.length) return;
      button.disabled = true;
      if (status) status.textContent = "Building report...";
      try {
        const response = await fetch("/api/test-mode/compare-report", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ results: lastCompareResults, corrected_label: lastCorrectedLabel }),
        });
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || "Report generation failed.");
        }
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
      } catch (error) {
        if (status) status.textContent = error.message || "Report generation failed.";
      } finally {
        button.disabled = false;
      }
    }

    // Shows the chosen filename next to the .file-picker translatable
    // stand-in button (static/base.css) -- see file_picker_html()'s own
    // docstring (pages/__init__.py) for why this never needs to restore
    // the placeholder text itself. Delegated on document so it also
    // covers rows added later by "Add another" (addExtraFileRow()/
    // addIndexCandidateRow() above), with nothing extra to wire up.
    document.addEventListener("change", (event) => {
      const input = event.target;
      if (!input || input.tagName !== "INPUT" || input.type !== "file") return;
      const picker = input.closest(".file-picker");
      const nameEl = picker && picker.querySelector(".file-picker-name");
      if (nameEl && input.files && input.files.length) nameEl.textContent = input.files[0].name;
    });

    window.addEventListener("DOMContentLoaded", () => {
      const profileSelect = document.querySelector('[name="profile_id"]');
      if (profileSelect) {
        profileSelect.addEventListener("change", () => {
          updateRunButton(false);
          resetPreflight();
          hideSettingsAlert();
        });
      }
      document.querySelectorAll('[name="api_key_gemini"], [name="api_key_claude"]').forEach((input) => {
        input.addEventListener("input", () => {
          updateRunButton(false);
          resetPreflight();
          hideSettingsAlert();
        });
      });
      document.querySelectorAll('[name="order"]').forEach((input) => {
        input.addEventListener("change", () => {
          setOrderHint();
          resetPreflight();
        });
      });
      document.querySelectorAll('[name="file_type"]').forEach((input) => {
        input.addEventListener("change", resetPreflight);
      });
      document.querySelectorAll('[name="model_a"], [name="model_b"], [name="zoom_a"], [name="zoom_b"]').forEach((input) => {
        input.addEventListener("change", () => {
          syncModelSelects();
          // Which provider's key is required can change with the model
          // selection (e.g. switching Model A from Gemini to Claude), so
          // the Run button's enabled/tooltip state needs to be recomputed.
          updateRunButton(false);
          resetPreflight();
        });
      });
      syncModelSelects();
      setOrderHint();
      const confirmRunButton = document.getElementById("confirm-run-button");
      if (confirmRunButton) {
        confirmRunButton.addEventListener("click", (event) => {
          event.preventDefault();
          runConfirmed = true;
          completionAlertShown = false;
          if (runForm) runForm.requestSubmit(confirmRunButton);
        });
      }
      const confirmOffPeakButton = document.getElementById("confirm-run-offpeak-button");
      if (confirmOffPeakButton) {
        confirmOffPeakButton.addEventListener("click", (event) => {
          event.preventDefault();
          runConfirmed = true;
          completionAlertShown = false;
          // requestSubmit(submitter) posts to the button's own formaction
          // (/test-mode/run-offpeak) instead of the form's /test-mode/run.
          if (runForm) runForm.requestSubmit(confirmOffPeakButton);
        });
      }
      const closeAlertButton = document.getElementById("settings-alert-close");
      if (closeAlertButton) {
        closeAlertButton.addEventListener("click", hideSettingsAlert);
      }
      const refreshStatusButton = document.getElementById("refresh-status-button");
      if (refreshStatusButton) {
        refreshStatusButton.addEventListener("click", refreshStatus);
      }
      const resetButton = document.getElementById("reset-button");
      if (resetButton) {
        resetButton.addEventListener("click", () => {
          resetPreflight();
          hideSettingsAlert();
          refreshStatus();
        });
      }
      const browseSourceButton = document.getElementById("browse-source-button");
      if (browseSourceButton) {
        browseSourceButton.addEventListener("click", pickSourceFolder);
      }
      const openOutputsFolderButton = document.getElementById("open-outputs-folder-button");
      if (openOutputsFolderButton) {
        openOutputsFolderButton.addEventListener("click", openOutputsFolder);
      }
      const sourceFolderManualButton = document.getElementById("source-folder-manual-button");
      if (sourceFolderManualButton) {
        sourceFolderManualButton.addEventListener("click", setSourceFolderManually);
      }
      const addExtraFileButton = document.getElementById("add-extra-file-button");
      if (addExtraFileButton) {
        addExtraFileButton.addEventListener("click", addExtraFileRow);
      }
      const runCompareButton = document.getElementById("run-compare-button");
      if (runCompareButton) {
        runCompareButton.addEventListener("click", runCompare);
      }
      const downloadReportButton = document.getElementById("download-report-button");
      if (downloadReportButton) {
        downloadReportButton.addEventListener("click", downloadCompareReport);
      }
      const addIcCandidateButton = document.getElementById("ic-add-candidate-button");
      if (addIcCandidateButton) {
        addIcCandidateButton.addEventListener("click", addIndexCandidateRow);
      }
      const icRunButton = document.getElementById("ic-run-button");
      if (icRunButton) {
        icRunButton.addEventListener("click", runIndexCompare);
      }
      const icDownloadReportButton = document.getElementById("ic-download-report-button");
      if (icDownloadReportButton) {
        icDownloadReportButton.addEventListener("click", downloadIndexCompareReport);
      }
      wireTmInfoButtons();
      const runForm = document.querySelector('form[action="/test-mode/run"]');
      if (runForm) {
        runForm.addEventListener("submit", handleProfileEditsBeforeSubmit);
        runForm.addEventListener("submit", confirmReset);
      }
      renderRunRows(initialRuns);
      updateRunButton(running);
      updateRunStatus(running, TM_INITIAL_DATA.offPeak);
      if (running) {
        window.setTimeout(refreshStatus, 1500);
      }
    });
