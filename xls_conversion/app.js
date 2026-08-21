(function () {
  const LABELS = {
    battesimi: "Church Battesimi",
    matrimoni: "Church Matrimoni",
    morti: "Church Morti",
    civil_birth: "Civil Birth",
    civil_marriage: "Civil Marriage",
    civil_death: "Civil Death",
  };

  const AI_READY = new Set(["battesimi", "matrimoni", "morti", "civil_birth", "civil_marriage", "civil_death"]);

  let sourceFilename = "";
  let sourceText = "";
  let cachedResult = null;
  let preflightPassed = false;
  let exportResult = null;

  const sourceFile = document.getElementById("sourceFile");
  const fileDetail = document.getElementById("fileDetail");
  const geminiModel = document.getElementById("geminiModel");
  const geminiApiKey = document.getElementById("geminiApiKey");
  const imageRange = document.getElementById("imageRange");
  const preflightButton = document.getElementById("preflightButton");
  const convertButton = document.getElementById("convertButton");
  const ignoreButton = document.getElementById("ignoreButton");
  const resetButton = document.getElementById("resetButton");
  const xlsxProgress = document.getElementById("xlsxProgress");
  const preflightResults = document.getElementById("preflightResults");
  const processStatus = document.getElementById("processStatus");
  const message = document.getElementById("message");
  const outputPanel = document.getElementById("outputPanel");
  const downloadButton = document.getElementById("downloadButton");
  const downloadCsvButton = document.getElementById("downloadCsvButton");
  const recordType = document.getElementById("recordType");

  sourceFile.addEventListener("change", uploadSource);
  recordType.addEventListener("change", handleSettingsChange);
  imageRange.addEventListener("input", handleSettingsChange);
  geminiModel.addEventListener("change", handleSettingsChange);
  geminiApiKey.addEventListener("input", handleApiKeyInput);
  preflightButton.addEventListener("click", runPreflight);
  convertButton.addEventListener("click", convertWithAi);
  ignoreButton.addEventListener("click", convertWithAi);
  resetButton.addEventListener("click", reset);
  downloadButton.addEventListener("click", () => downloadOutput("xlsx"));
  downloadCsvButton.addEventListener("click", () => downloadOutput("csv"));

  function selectedRecordType() {
    return recordType.value;
  }

  async function uploadSource() {
    const file = sourceFile.files[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".docx")) {
      setMessage("Upload a Microsoft Word DOCX file.", true);
      sourceFile.value = "";
      return;
    }

    setBusy(true);
    setMessage("Reading DOCX transcription...");
    fileDetail.textContent = file.name;

    try {
      const body = new FormData();
      body.append("source_file", file);
      const response = await fetch("/api/xls-conversion/upload", {
        method: "POST",
        body,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The DOCX file could not be read.");

      sourceFilename = data.filename;
      sourceText = data.text;
      fileDetail.textContent = data.filename;
      if (!geminiApiKey.value.trim()) {
        setMessage("DOCX loaded. Paste a Gemini API key before running Preflight Check.");
      } else if (!imageRange.value.trim()) {
        setMessage("DOCX loaded. Select an image range before running Preflight Check.");
      } else {
        setMessage("DOCX loaded. Choose the record type and run Preflight Check.");
      }
    } catch (error) {
      clearSource();
      setMessage(error.message || String(error), true);
    } finally {
      setBusy(false);
    }
  }

  async function runPreflight() {
    if (!sourceText) {
      setMessage("Upload a DOCX file before running preflight.", true);
      return;
    }
    if (!geminiApiKey.value.trim()) {
      setMessage("Paste a Gemini API key before running preflight.", true);
      geminiApiKey.focus();
      return;
    }
    if (!imageRange.value.trim()) {
      setMessage("Select an image range before running preflight.", true);
      imageRange.focus();
      return;
    }
    if (!AI_READY.has(selectedRecordType())) {
      setMessage(`AI preflight for ${LABELS[selectedRecordType()]} is not configured yet.`, true);
      return;
    }

    setBusy(true);
    setMessage(`Gemini is reviewing the selected ${LABELS[selectedRecordType()]} image range for English translations...`);
    try {
      const response = await fetch("/api/xls-conversion/preflight", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          record_type: selectedRecordType(),
          text: sourceText,
          image_range: imageRange.value.trim(),
          model: geminiModel.value,
          gemini_api_key: geminiApiKey.value.trim(),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Preflight failed.");

      cachedResult = data;
      preflightResults.value = formatPreflightResults(cachedResult);
      preflightPassed = cachedResult.ok;
      convertButton.disabled = !preflightPassed;
      ignoreButton.disabled = preflightPassed;

      if (preflightPassed) {
        setMessage(
          `Preflight passed. Gemini found English translations for all ${cachedResult.entries_reviewed} reviewed entries.`
        );
      } else {
        setMessage(preflightFailureMessage(cachedResult), true);
      }
    } catch (error) {
      cachedResult = null;
      preflightPassed = false;
      convertButton.disabled = true;
      ignoreButton.disabled = true;
      setMessage(error.message || String(error), true);
    } finally {
      setBusy(false);
    }
  }

  function preflightFailureMessage(result) {
    const codes = new Set((result.issues || []).map((issue) => issue.code));
    const alerts = [];

    if (codes.has("requested_image_not_found")) {
      alerts.push(
        'Review the results. "Requested image not found" means that an image number was skipped, likely because it was a duplicate or not relevant. Check the transcription before proceeding.'
      );
    }
    if (codes.has("english_translation_missing")) {
      alerts.push(
        "Review the results. If an entry is missing an English translation, check the transcription before proceeding."
      );
    }

    return (
      alerts.join(" ") ||
      "Preflight found a problem in the selected image range. Review the results before continuing."
    );
  }

  async function convertWithAi(event) {
    const outputFormat = "xlsx";
    if (!cachedResult) {
      setMessage("Run preflight before converting.", true);
      return;
    }
    if (!AI_READY.has(selectedRecordType())) {
      setMessage(`AI extraction for ${LABELS[selectedRecordType()]} is not configured yet.`, true);
      return;
    }
    const apiKey = geminiApiKey.value.trim();
    if (!apiKey) {
      setMessage("Paste a Gemini API key before converting.", true);
      geminiApiKey.focus();
      return;
    }

    if (exportResult) {
      downloadOutput(outputFormat);
      return;
    }

    const showXlsxProgress = outputFormat === "xlsx";
    setXlsxProgress(showXlsxProgress);
    setBusy(true);
    setMessage(`Extracting ${LABELS[selectedRecordType()]} records with ${geminiModel.options[geminiModel.selectedIndex].text}...`);
    try {
      const response = await fetch("/api/xls-conversion/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          record_type: selectedRecordType(),
          text: sourceText,
          image_range: imageRange.value.trim(),
          image_overrides: "",
          model: geminiModel.value,
          gemini_api_key: apiKey,
          preflight_token: cachedResult.preflight_token,
          ignore_preflight: event.currentTarget === ignoreButton,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "AI extraction failed.");

      exportResult = data;
      outputPanel.hidden = false;
      appendAiResults(data);
      downloadOutput(outputFormat);
      setMessage(
        `${outputFormat.toUpperCase()} created. ${data.rows.length} record(s) extracted with ${data.model}.`
      );
      outputPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      setMessage(error.message || String(error), true);
    } finally {
      setXlsxProgress(false);
      setBusy(false);
    }
  }

  function appendAiResults(result) {
    const lines = ["", "AI extraction:"];
    lines.push(`- Model: ${result.model}`);
    lines.push(`- Records created: ${result.rows.length}`);
    if (result.missing_images?.length) {
      lines.push(`- No AI records returned for image(s): ${formatImageList(result.missing_images)}`);
    }
    (result.exception_log || []).forEach((item) => lines.push(`- ${item}`));
    preflightResults.value += lines.join("\n");
  }

  function downloadOutput(format) {
    if (!exportResult) return;
    const base = sourceFilename.replace(/\.docx$/i, "") || "transcription";
    const filename = `${base}-${selectedRecordType()}.${format}`;
    const blob =
      format === "xlsx"
        ? base64Blob(
            exportResult.xlsx_base64,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          )
        : new Blob([exportResult.csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function base64Blob(value, type) {
    const bytes = Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
    return new Blob([bytes], { type });
  }

  function formatPreflightResults(result) {
    const lines = [
      `Requested images: ${formatImageList(result.expected_images)}`,
      `Images reviewed: ${result.reviewed_images.length ? formatImageList(result.reviewed_images) : "none"}`,
      `Entries reviewed: ${result.entries_reviewed}`,
      `English translations found: ${result.translations_found}`,
    ];
    lines.push("");

    if (result.issues.length) {
      lines.push("Problems:");
      result.issues.forEach((issue) => {
        const entry = issue.entry_identifier ? `, entry ${issue.entry_identifier}` : "";
        lines.push(`- Image ${issue.image_number}${entry}: ${issue.message}`);
        if (issue.evidence) lines.push(`  Evidence: ${issue.evidence}`);
      });
    } else {
      lines.push("Problems: None");
    }

    return lines.join("\n");
  }

  function formatImageList(images) {
    if (images.length <= 12) return images.join(", ");
    return `${images.slice(0, 12).join(", ")} and ${images.length - 12} more`;
  }

  function invalidatePreflight() {
    cachedResult = null;
    preflightPassed = false;
    exportResult = null;
    convertButton.disabled = true;
    ignoreButton.disabled = true;
    preflightResults.value = "";
    outputPanel.hidden = true;
    if (sourceText) {
      setMessage("Settings changed. Run Preflight Check again.");
    }
  }

  function handleSettingsChange() {
    invalidatePreflight();
    setBusy(false);
  }

  function setBusy(isBusy) {
    const aiReady = AI_READY.has(selectedRecordType());
    const apiKeyEntered = Boolean(geminiApiKey.value.trim());
    const imageRangeEntered = Boolean(imageRange.value.trim());
    sourceFile.disabled = isBusy;
    preflightButton.disabled = isBusy || !sourceText || !apiKeyEntered || !imageRangeEntered || !aiReady;
    convertButton.disabled = isBusy || !preflightPassed || !aiReady || !apiKeyEntered;
    ignoreButton.disabled = isBusy || !cachedResult || preflightPassed || !aiReady || !apiKeyEntered;
    resetButton.disabled = isBusy;
  }

  function setXlsxProgress(isVisible) {
    xlsxProgress.hidden = !isVisible;
    convertButton.setAttribute("aria-busy", String(isVisible));
  }

  function handleApiKeyInput() {
    setBusy(false);
    if (!sourceText) return;
    if (geminiApiKey.value.trim() && imageRange.value.trim()) {
      setMessage("Gemini API key entered. Run Preflight Check when ready.");
    } else if (geminiApiKey.value.trim()) {
      setMessage("Gemini API key entered. Select an image range before running Preflight Check.");
    } else {
      setMessage("Paste a Gemini API key before running Preflight Check.", true);
    }
  }

  function setMessage(text, isError = false) {
    message.textContent = text;
    processStatus.classList.toggle("error", isError);
  }

  function clearSource() {
    sourceFilename = "";
    sourceText = "";
    fileDetail.textContent = "No file selected";
    preflightButton.disabled = true;
  }

  function reset() {
    sourceFile.value = "";
    recordType.value = "battesimi";
    imageRange.value = "";
    geminiModel.value = "gemini-3.6-flash";
    geminiApiKey.value = "";
    clearSource();
    invalidatePreflight();
    setXlsxProgress(false);
    setMessage("Upload a DOCX file to begin.");
  }
})();
