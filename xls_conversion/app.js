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

  // Threshold used by confirmLargeRunIfNeeded() -- see the "Cost safeguard"
  // section of the multi-language plan. Picked so a normal single-language,
  // modest-range run never sees a confirm dialog.
  const LARGE_RUN_THRESHOLD = 15;

  let sourceFilename = "";
  let sourceText = "";
  let detectedLanguages = []; // [{language, role}]
  let languageRuns = {}; // language -> {role, cachedResult, preflightPassed, exportResult}
  let combinedXlsxBase64 = null;

  const sourceFile = document.getElementById("sourceFile");
  const uploadBox = document.getElementById("uploadBox");
  const fileDetail = document.getElementById("fileDetail");
  const geminiModel = document.getElementById("geminiModel");
  const geminiApiKey = document.getElementById("geminiApiKey");
  const imageRange = document.getElementById("imageRange");
  const processAll = document.getElementById("processAll");
  const detectLanguagesSection = document.getElementById("detectLanguagesSection");
  const detectLanguagesButton = document.getElementById("detectLanguagesButton");
  const detectedLanguagesEl = document.getElementById("detectedLanguages");
  const outputModeFieldset = document.getElementById("outputModeFieldset");
  const languageChoicesEl = document.getElementById("languageChoices");
  const scopeEstimateEl = document.getElementById("scopeEstimate");
  const preflightButton = document.getElementById("preflightButton");
  const convertButton = document.getElementById("convertButton");
  const ignoreButton = document.getElementById("ignoreButton");
  const resetButton = document.getElementById("resetButton");
  const xlsxProgress = document.getElementById("xlsxProgress");
  const preflightResults = document.getElementById("preflightResults");
  const processStatus = document.getElementById("processStatus");
  const message = document.getElementById("message");
  const outputPanel = document.getElementById("outputPanel");
  const downloadRowsEl = document.getElementById("downloadRows");
  const recordType = document.getElementById("recordType");

  // Single source of truth for the model list lives in app.py's MODELS dict
  // -- Transcribe/Test Mode/Prompt Builder build their <select> from it
  // server-side, but this page is a static asset with no Python templating,
  // so it used to keep its own hand-typed copy of the same list. That copy
  // drifted (a model app.py had was missing here, or vice versa); fetching
  // it at load time instead means there is exactly one place to update.
  let defaultModelId = "";

  async function loadModelOptions() {
    try {
      const response = await fetch("/api/models", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const models = Array.isArray(data.models) ? data.models : [];
      if (!models.length) throw new Error("empty model list");
      geminiModel.innerHTML = "";
      models.forEach(({ id, label }) => {
        const option = document.createElement("option");
        option.value = id;
        option.textContent = label;
        geminiModel.appendChild(option);
      });
      defaultModelId = typeof data.default === "string" && data.default ? data.default : models[0].id;
      geminiModel.value = defaultModelId;
    } catch (err) {
      setMessage("Could not load the model list from the server. Reload the page to try again.", true);
    }
  }
  loadModelOptions();

  sourceFile.addEventListener("change", uploadSource);
  ["dragenter", "dragover"].forEach((eventName) => {
    uploadBox.addEventListener(eventName, (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!sourceFile.disabled) uploadBox.classList.add("dragover");
    });
  });
  ["dragleave", "dragend", "drop"].forEach((eventName) => {
    uploadBox.addEventListener(eventName, (event) => {
      event.preventDefault();
      event.stopPropagation();
      uploadBox.classList.remove("dragover");
    });
  });
  uploadBox.addEventListener("drop", (event) => {
    if (sourceFile.disabled) return;
    const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    sourceFile.files = transfer.files;
    uploadSource();
  });
  recordType.addEventListener("change", handleSettingsChange);
  imageRange.addEventListener("input", handleSettingsChange);
  processAll.addEventListener("change", () => {
    imageRange.disabled = processAll.checked;
    handleSettingsChange();
  });
  geminiModel.addEventListener("change", handleSettingsChange);
  geminiApiKey.addEventListener("input", handleApiKeyInput);
  detectLanguagesButton.addEventListener("click", runLanguageDetection);
  outputModeFieldset.addEventListener("change", (event) => {
    if (event.target && event.target.name === "outputMode") {
      enforceLanguageLimitForCurrentMode();
      handleLanguageSelectionChange();
    }
  });
  languageChoicesEl.addEventListener("change", (event) => {
    if (event.target && event.target.type === "checkbox") {
      handleLanguageChoiceChange(event);
    }
  });
  preflightButton.addEventListener("click", runPreflight);
  convertButton.addEventListener("click", convertWithAi);
  ignoreButton.addEventListener("click", convertWithAi);
  resetButton.addEventListener("click", reset);

  function selectedRecordType() {
    return recordType.value;
  }

  // Reads the "Record type: <label>" line from the header box Prompt
  // Builder-produced transcriptions now carry (see docs/DESIGN.md's
  // "Profile storage" section). Matched against this page's own <option> text rather
  // than a separate label->key table, so the two can't drift out of sync.
  // Scoped to the first ~1000 characters (the box is always at the very top)
  // so nothing an entry's own text happens to contain can match instead.
  // Silently does nothing when absent or unrecognized -- this is a
  // convenience, not a requirement, and the dropdown stays fully editable.
  function applyDeclaredRecordType(text) {
    const sample = (text || "").slice(0, 1000);
    const match = sample.match(/^Record type:\s*(.+?)\s*$/m);
    if (!match) return null;
    const declaredLabel = match[1].trim();
    const option = Array.from(recordType.options).find(
      (opt) => opt.textContent.trim() === declaredLabel
    );
    if (!option) return null;
    recordType.value = option.value;
    recordType.dispatchEvent(new Event("change"));
    return declaredLabel;
  }

  // Reads "Native-language transcription:"/"Translations produced:" from the
  // same header box -- when present, this is a free, instant, deterministic
  // substitute for the AI-based Detect Languages call, not just a shortcut to
  // it: no API key or model needed, since it's plain text parsing. Detect
  // Languages stays available as the (paid) fallback for any DOCX without a
  // box -- this never fires an AI call on its own. Returns the detected
  // language names for messaging, or null when no box was found.
  function applyDeclaredLanguages(text) {
    const sample = (text || "").slice(0, 1000);
    const nativeMatch = sample.match(/^Native-language transcription:\s*(.+?)\s*$/m);
    if (!nativeMatch) return null;
    const native = nativeMatch[1].trim();
    if (!native) return null;

    const languages = [{ language: native, role: "transcription" }];
    const translationsMatch = sample.match(/^Translations produced:\s*(.+?)\s*$/m);
    if (translationsMatch) {
      const raw = translationsMatch[1].trim();
      if (raw && raw.toLowerCase() !== "none") {
        raw.split(",").forEach((language) => {
          const trimmed = language.trim();
          if (trimmed) languages.push({ language: trimmed, role: "translation" });
        });
      }
    }

    detectedLanguages = languages;
    renderDetectedLanguages();
    renderLanguageChoices();
    updateScopeEstimate();
    return languages.map((entry) => entry.language);
  }

  function selectedOutputMode() {
    const checked = outputModeFieldset.querySelector('input[name="outputMode"]:checked');
    return checked ? checked.value : "single";
  }

  function requiredLanguageCount(mode) {
    return mode === "single" ? 1 : 2;
  }

  function selectedLanguages() {
    return Array.from(languageChoicesEl.querySelectorAll('input[type="checkbox"]:checked')).map(
      (el) => el.value
    );
  }

  function languageRole(language) {
    const found = detectedLanguages.find((entry) => entry.language === language);
    return found ? found.role : "translation";
  }

  function roleLabel(role) {
    return role === "transcription" ? "original-language transcription" : "translation";
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

      const detectedRecordType = applyDeclaredRecordType(sourceText);
      const detectedLanguageNames = applyDeclaredLanguages(sourceText);
      detectLanguagesSection.hidden = Boolean(detectedLanguageNames);
      const notes = [];
      if (detectedRecordType) {
        notes.push(`Source material set to "${detectedRecordType}" from the document's own header.`);
      }
      if (detectedLanguageNames) {
        notes.push(`Language(s) detected from the document's own header: ${detectedLanguageNames.join(", ")}.`);
      }
      const noteText = notes.length ? ` ${notes.join(" ")}` : "";

      if (!geminiApiKey.value.trim()) {
        setMessage(`DOCX loaded.${noteText} Paste an API key before running Preflight Check.`);
      } else if (!imageRange.value.trim() && !processAll.checked) {
        setMessage(`DOCX loaded.${noteText} Select an image range before running Preflight Check.`);
      } else if (detectedLanguageNames) {
        setMessage(`DOCX loaded.${noteText} Choose an output mode and language(s), then run Preflight Check.`);
      } else {
        setMessage(`DOCX loaded.${noteText} Detect languages, then run Preflight Check.`);
      }
    } catch (error) {
      clearSource();
      setMessage(error.message || String(error), true);
    } finally {
      setBusy(false);
    }
  }

  async function runLanguageDetection() {
    if (!sourceText) {
      setMessage("Upload a DOCX file before detecting languages.", true);
      return;
    }
    if (!geminiApiKey.value.trim()) {
      setMessage("Paste an API key before detecting languages.", true);
      geminiApiKey.focus();
      return;
    }
    if (!imageRange.value.trim() && !processAll.checked) {
      setMessage("Select an image range, or check Process all, before detecting languages.", true);
      imageRange.focus();
      return;
    }

    setBusy(true);
    setMessage("Detecting languages present in the transcription...");
    try {
      const response = await fetch("/api/xls-conversion/detect-languages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: sourceText,
          image_range: imageRange.value.trim(),
          process_all: processAll.checked,
          model: geminiModel.value,
          gemini_api_key: geminiApiKey.value.trim(),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Language detection failed.");

      detectedLanguages = data.languages || [];
      renderDetectedLanguages();
      renderLanguageChoices();
      updateScopeEstimate();

      if (detectedLanguages.length) {
        setMessage(
          `Detected ${detectedLanguages.length} language(s). Choose an output mode and language(s) below.`
        );
      } else {
        setMessage("No languages were confidently detected. Check the transcription before continuing.", true);
      }
    } catch (error) {
      setMessage(error.message || String(error), true);
    } finally {
      setBusy(false);
    }
  }

  function renderDetectedLanguages() {
    detectedLanguagesEl.innerHTML = "";
    detectedLanguages.forEach((lang) => {
      const chip = document.createElement("span");
      chip.className = "language-chip";
      chip.textContent = `${lang.language} (${roleLabel(lang.role)})`;
      detectedLanguagesEl.appendChild(chip);
    });
  }

  function renderLanguageChoices() {
    languageChoicesEl.innerHTML = "";
    languageRuns = {};
    combinedXlsxBase64 = null;
    detectedLanguages.forEach((lang, index) => {
      const label = document.createElement("label");
      label.className = "radio-option";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = lang.language;
      input.checked = index === 0;
      label.appendChild(input);
      label.appendChild(document.createTextNode(` ${lang.language} (${roleLabel(lang.role)})`));
      languageChoicesEl.appendChild(label);
    });
    updateOutputModeAvailability();
  }

  function updateOutputModeAvailability() {
    const multiCapable = detectedLanguages.length >= 2;
    outputModeFieldset.disabled = detectedLanguages.length === 0;
    outputModeFieldset.querySelectorAll('input[name="outputMode"]').forEach((radio) => {
      if (radio.value !== "single") {
        radio.disabled = !multiCapable;
      }
    });
    if (!multiCapable) {
      const singleRadio = outputModeFieldset.querySelector('input[name="outputMode"][value="single"]');
      if (singleRadio) singleRadio.checked = true;
    }
    enforceLanguageLimitForCurrentMode();
  }

  function enforceLanguageLimitForCurrentMode() {
    const limit = requiredLanguageCount(selectedOutputMode());
    const checked = Array.from(languageChoicesEl.querySelectorAll('input[type="checkbox"]:checked'));
    checked.slice(limit).forEach((cb) => {
      cb.checked = false;
    });
  }

  function handleLanguageChoiceChange(event) {
    const limit = requiredLanguageCount(selectedOutputMode());
    const checked = Array.from(languageChoicesEl.querySelectorAll('input[type="checkbox"]:checked'));
    if (checked.length > limit) {
      const toUncheck = checked.find((cb) => cb !== event.target);
      if (toUncheck) toUncheck.checked = false;
    }
    handleLanguageSelectionChange();
  }

  function handleLanguageSelectionChange() {
    invalidatePreflight();
    updateScopeEstimate();
    setBusy(false);
  }

  function estimateImageCount() {
    if (!sourceText) return 0;
    if (processAll.checked) {
      const numbers = new Set();
      const pattern = /(?:^|\n)\s*(?:---\s*)?START OF RECORD:\s*.*?_(\d+)\.[A-Za-z0-9]+/gi;
      let match = pattern.exec(sourceText);
      while (match) {
        numbers.add(match[1]);
        match = pattern.exec(sourceText);
      }
      return numbers.size;
    }
    return countImageRangeClientSide(imageRange.value.trim());
  }

  // Mirrors the server's parse_image_range() caps (xls_conversion/ai_parser.py)
  // so a typo like "1-1000000000" gets an instant, capped estimate here
  // instead of the tab looping toward a billion Set insertions. Counts
  // arithmetically -- never materializes the individual image numbers, since
  // this is only ever used for the on-screen "Estimated: ~N images" figure;
  // the actual range string is what's sent to the server, which does its own
  // real (and also capped) expansion and de-duplication.
  const MAX_IMAGE_RANGE_SPAN_ESTIMATE = 5000;
  const MAX_IMAGES_PER_REQUEST_ESTIMATE = 5000;

  function countImageRangeClientSide(value) {
    const singles = new Set();
    let rangeTotal = 0;
    (value || "").split(",").forEach((part) => {
      const trimmed = part.trim();
      if (!trimmed) return;
      const rangeMatch = trimmed.match(/^(\d+)\s*-\s*(\d+)$/);
      if (rangeMatch) {
        const start = parseInt(rangeMatch[1], 10);
        const end = parseInt(rangeMatch[2], 10);
        if (end < start) return;
        rangeTotal += Math.min(end - start + 1, MAX_IMAGE_RANGE_SPAN_ESTIMATE);
      } else if (/^\d+$/.test(trimmed)) {
        singles.add(trimmed);
      }
    });
    return Math.min(singles.size + rangeTotal, MAX_IMAGES_PER_REQUEST_ESTIMATE);
  }

  function currentLanguageCountForEstimate() {
    const selectedCount = selectedLanguages().length;
    return selectedCount || requiredLanguageCount(selectedOutputMode());
  }

  function updateScopeEstimate() {
    const imageCount = estimateImageCount();
    if (!imageCount) {
      scopeEstimateEl.textContent = "";
      return;
    }
    const languageCount = currentLanguageCountForEstimate();
    const totalCalls = imageCount * languageCount;
    scopeEstimateEl.textContent = `Estimated: ~${imageCount} image(s) × ${languageCount} language(s) = ~${totalCalls} AI calls for preflight, and again for conversion.`;
  }

  function isLargeRun() {
    const imageCount = estimateImageCount();
    const languageCount = currentLanguageCountForEstimate();
    return imageCount * languageCount > LARGE_RUN_THRESHOLD || languageCount >= 2;
  }

  function confirmLargeRunIfNeeded(actionLabel) {
    if (!isLargeRun()) return true;
    const imageCount = estimateImageCount();
    const languageCount = currentLanguageCountForEstimate();
    return window.confirm(
      `This will process approximately ${imageCount} image(s) × ${languageCount} language(s) = ` +
        `~${imageCount * languageCount} AI calls for ${actionLabel}. Continue?`
    );
  }

  async function runPreflight() {
    if (!sourceText) {
      setMessage("Upload a DOCX file before running preflight.", true);
      return;
    }
    if (!geminiApiKey.value.trim()) {
      setMessage("Paste an API key before running preflight.", true);
      geminiApiKey.focus();
      return;
    }
    if (!imageRange.value.trim() && !processAll.checked) {
      setMessage("Select an image range before running preflight.", true);
      imageRange.focus();
      return;
    }
    if (!AI_READY.has(selectedRecordType())) {
      setMessage(`AI preflight for ${LABELS[selectedRecordType()]} is not configured yet.`, true);
      return;
    }
    const languages = selectedLanguages();
    if (!languages.length) {
      setMessage("Detect languages and choose at least one before running preflight.", true);
      return;
    }
    if (!confirmLargeRunIfNeeded("preflight")) return;

    setBusy(true);
    languageRuns = {};
    outputPanel.hidden = true;
    combinedXlsxBase64 = null;
    let allPassed = true;
    const resultSections = [];
    const failureAlerts = [];

    for (let i = 0; i < languages.length; i += 1) {
      const language = languages[i];
      const role = languageRole(language);
      setMessage(`Preflight: ${language} (${i + 1}/${languages.length})...`);
      try {
        const response = await fetch("/api/xls-conversion/preflight", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            record_type: selectedRecordType(),
            text: sourceText,
            image_range: imageRange.value.trim(),
            process_all: processAll.checked,
            model: geminiModel.value,
            gemini_api_key: geminiApiKey.value.trim(),
            target_language: language,
            target_role: role,
            filename: sourceFilename,
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `Preflight failed for ${language}.`);

        languageRuns[language] = { role, cachedResult: data, preflightPassed: data.ok, exportResult: null };
        resultSections.push(`=== ${language} ===\n${formatPreflightResults(data)}`);
        if (!data.ok) {
          allPassed = false;
          failureAlerts.push(preflightFailureMessage(data));
        }
      } catch (error) {
        languageRuns[language] = { role, cachedResult: null, preflightPassed: false, exportResult: null };
        resultSections.push(`=== ${language} ===\n${error.message || String(error)}`);
        allPassed = false;
        failureAlerts.push(`${language}: ${error.message || String(error)}`);
      }
    }

    preflightResults.value = resultSections.join("\n\n");
    outputPanel.hidden = true;

    if (allPassed) {
      setMessage(`Preflight passed for ${languages.join(", ")}.`);
    } else {
      setMessage(failureAlerts.join(" ") || "Preflight found a problem. Review the results before continuing.", true);
    }
    setBusy(false);
  }

  function preflightFailureMessage(result) {
    const codes = new Set((result.issues || []).map((issue) => issue.code));
    const alerts = [];

    if (codes.has("requested_image_not_found")) {
      alerts.push(
        'Review the results. "Requested image not found" means that an image number was skipped, likely because it was a duplicate or not relevant. Check the transcription before proceeding.'
      );
    }
    if (codes.has("target_material_missing")) {
      alerts.push(
        `Review the results. If an entry is missing its ${result.target_language || "selected-language"} material, check the transcription before proceeding.`
      );
    }
    if (codes.has("record_type_filename_mismatch")) {
      alerts.push(
        "The selected Source Material doesn't appear to match the uploaded filename. Double-check the record type before converting."
      );
    }

    return (
      alerts.join(" ") ||
      "Preflight found a problem in the selected image range. Review the results before continuing."
    );
  }

  function allLanguagesPassed() {
    const languages = selectedLanguages();
    return (
      languages.length > 0 &&
      languages.every((lang) => languageRuns[lang] && languageRuns[lang].preflightPassed)
    );
  }

  function hasAnyPreflightResult() {
    const languages = selectedLanguages();
    return languages.some((lang) => languageRuns[lang] && languageRuns[lang].cachedResult);
  }

  function allLanguagesConverted() {
    const languages = selectedLanguages();
    return (
      languages.length > 0 &&
      languages.every((lang) => languageRuns[lang] && languageRuns[lang].exportResult)
    );
  }

  async function convertWithAi(event) {
    const languages = selectedLanguages();
    if (!languages.length || !languages.every((lang) => languageRuns[lang])) {
      setMessage("Run preflight before converting.", true);
      return;
    }
    if (!AI_READY.has(selectedRecordType())) {
      setMessage(`AI extraction for ${LABELS[selectedRecordType()]} is not configured yet.`, true);
      return;
    }
    const apiKey = geminiApiKey.value.trim();
    if (!apiKey) {
      setMessage("Paste an API key before converting.", true);
      geminiApiKey.focus();
      return;
    }

    if (allLanguagesConverted()) {
      // Already converted (Convert clicked again with nothing new to do) --
      // just re-show the existing download buttons, no auto-download and no
      // completion alert (nothing new actually finished just now).
      renderDownloadRows();
      outputPanel.hidden = false;
      return;
    }

    if (!confirmLargeRunIfNeeded("conversion")) return;

    const ignorePreflight = event.currentTarget === ignoreButton;
    setXlsxProgress(true);
    setBusy(true);
    try {
      for (let i = 0; i < languages.length; i += 1) {
        const language = languages[i];
        const run = languageRuns[language];
        setMessage(
          `Extracting ${language} records (${i + 1}/${languages.length}) with ${geminiModel.options[geminiModel.selectedIndex].text}...`
        );
        const response = await fetch("/api/xls-conversion/parse", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            record_type: selectedRecordType(),
            text: sourceText,
            image_range: imageRange.value.trim(),
            image_overrides: "",
            process_all: processAll.checked,
            model: geminiModel.value,
            gemini_api_key: apiKey,
            preflight_token: run.cachedResult ? run.cachedResult.preflight_token : "",
            ignore_preflight: ignorePreflight,
            target_language: language,
            target_role: run.role,
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `AI extraction failed for ${language}.`);
        run.exportResult = data;
        appendAiResults(language, data);
      }

      if (selectedOutputMode() === "two-tabs" && languages.length === 2) {
        setMessage("Combining both languages into one workbook...");
        const combineResponse = await fetch("/api/xls-conversion/combine", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            record_type: selectedRecordType(),
            sheets: languages.map((lang) => ({
              language: lang,
              rows: languageRuns[lang].exportResult.rows,
            })),
          }),
        });
        const combineData = await combineResponse.json();
        if (!combineResponse.ok) throw new Error(combineData.error || "Combining the workbook failed.");
        combinedXlsxBase64 = combineData.xlsx_base64;
      }

      outputPanel.hidden = false;
      renderDownloadRows();
      const totalRecords = languages.reduce(
        (sum, lang) => sum + (languageRuns[lang].exportResult.rows || []).length,
        0
      );
      setMessage(`Conversion complete for ${languages.join(", ")}. ${totalRecords} record(s) extracted.`);
      outputPanel.scrollIntoView({ behavior: "smooth", block: "start" });
      showCompletionAlert();
    } catch (error) {
      setMessage(error.message || String(error), true);
    } finally {
      setXlsxProgress(false);
      setBusy(false);
    }
  }

  function appendAiResults(language, result) {
    const lines = ["", `AI extraction (${language}):`];
    lines.push(`- Model: ${result.model}`);
    lines.push(`- Records created: ${result.rows.length}`);
    if (result.missing_images?.length) {
      lines.push(`- No AI records returned for image(s): ${formatImageList(result.missing_images)}`);
    }
    (result.exception_log || []).forEach((item) => lines.push(`- ${item}`));
    preflightResults.value += lines.join("\n");
  }

  function renderDownloadRows() {
    downloadRowsEl.innerHTML = "";
    const languages = selectedLanguages();
    languages.forEach((language) => {
      const run = languageRuns[language];
      if (!run || !run.exportResult) return;

      const xlsxBtn = document.createElement("button");
      xlsxBtn.type = "button";
      xlsxBtn.className = "success";
      xlsxBtn.textContent = languages.length > 1 ? `Download ${language} XLSX` : "Download XLSX";
      xlsxBtn.addEventListener("click", () => downloadOutput(language, "xlsx"));
      downloadRowsEl.appendChild(xlsxBtn);

      const csvBtn = document.createElement("button");
      csvBtn.type = "button";
      csvBtn.className = "success";
      csvBtn.textContent = languages.length > 1 ? `Download ${language} CSV` : "Download CSV";
      csvBtn.addEventListener("click", () => downloadOutput(language, "csv"));
      downloadRowsEl.appendChild(csvBtn);
    });

    if (combinedXlsxBase64) {
      const combinedBtn = document.createElement("button");
      combinedBtn.type = "button";
      combinedBtn.className = "success";
      combinedBtn.textContent = "Download Combined XLSX (2 tabs)";
      combinedBtn.addEventListener("click", downloadCombined);
      downloadRowsEl.appendChild(combinedBtn);
    }
  }

  function downloadOutput(language, format) {
    const run = languageRuns[language];
    if (!run || !run.exportResult) return;
    const base = sourceFilename.replace(/\.docx$/i, "") || "transcription";
    const languageSuffix = selectedLanguages().length > 1 ? `-${language}` : "";
    const filename = `${base}-${selectedRecordType()}${languageSuffix}.${format}`;
    const blob =
      format === "xlsx"
        ? base64Blob(
            run.exportResult.xlsx_base64,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          )
        : new Blob([run.exportResult.csv], { type: "text/csv;charset=utf-8" });
    triggerDownload(blob, filename);
  }

  function downloadCombined() {
    if (!combinedXlsxBase64) return;
    const base = sourceFilename.replace(/\.docx$/i, "") || "transcription";
    const filename = `${base}-${selectedRecordType()}-combined.xlsx`;
    const blob = base64Blob(
      combinedXlsxBase64,
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    );
    triggerDownload(blob, filename);
  }

  function triggerDownload(blob, filename) {
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
    const materialLabel = result.target_language ? `${result.target_language} material found` : "Target material found";
    const lines = [
      `Entries reviewed: ${result.entries_reviewed}`,
      `${materialLabel}: ${result.target_material_found}`,
    ];
    lines.push("");

    if (result.issues.length) {
      lines.push("Problems:");
      result.issues.forEach((issue) => {
        const entry = issue.entry_identifier ? `, entry ${issue.entry_identifier}` : "";
        const location = issue.image_number ? `Image ${issue.image_number}${entry}` : "General";
        lines.push(`- ${location}: ${issue.message}`);
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
    languageRuns = {};
    combinedXlsxBase64 = null;
    convertButton.disabled = true;
    ignoreButton.disabled = true;
    preflightResults.value = "";
    outputPanel.hidden = true;
    downloadRowsEl.innerHTML = "";
    if (sourceText) {
      setMessage("Settings changed. Run Preflight Check again.");
    }
  }

  function invalidateLanguageDetection() {
    detectedLanguages = [];
    detectedLanguagesEl.innerHTML = "";
    languageChoicesEl.innerHTML = "";
    outputModeFieldset.disabled = true;
    const singleRadio = outputModeFieldset.querySelector('input[name="outputMode"][value="single"]');
    if (singleRadio) singleRadio.checked = true;
    scopeEstimateEl.textContent = "";
    detectLanguagesSection.hidden = true;
  }

  function handleSettingsChange() {
    // Detected languages (AI or box-declared) describe the uploaded DOCX
    // itself, not the record type/range/process-all/model chosen to run it
    // with -- those don't change what languages are actually in the
    // document, so they must NOT wipe the detection results (this used to
    // call invalidateLanguageDetection() here, which meant checking
    // "Process all" -- or any other setting -- silently discarded whatever
    // Detect Languages or the drop-time box parse had already found).
    // Preflight/Convert results genuinely do go stale on any of these,
    // since they're keyed to the exact run configuration server-side.
    invalidatePreflight();
    setBusy(false);
  }

  function setBusy(isBusy) {
    const aiReady = AI_READY.has(selectedRecordType());
    const apiKeyEntered = Boolean(geminiApiKey.value.trim());
    const imageRangeEntered = Boolean(imageRange.value.trim()) || processAll.checked;
    const hasLanguages = selectedLanguages().length > 0;
    sourceFile.disabled = isBusy;
    detectLanguagesButton.disabled = isBusy || !sourceText || !apiKeyEntered || !imageRangeEntered || !aiReady;
    preflightButton.disabled =
      isBusy || !sourceText || !apiKeyEntered || !imageRangeEntered || !aiReady || !hasLanguages;
    convertButton.disabled = isBusy || !allLanguagesPassed() || !aiReady || !apiKeyEntered || !hasLanguages;
    ignoreButton.disabled =
      isBusy || !hasAnyPreflightResult() || allLanguagesPassed() || !aiReady || !apiKeyEntered || !hasLanguages;
    resetButton.disabled = isBusy;
  }

  function setXlsxProgress(isVisible) {
    xlsxProgress.hidden = !isVisible;
    convertButton.setAttribute("aria-busy", String(isVisible));
  }

  function handleApiKeyInput() {
    setBusy(false);
    if (!sourceText) return;
    if (geminiApiKey.value.trim() && (imageRange.value.trim() || processAll.checked)) {
      setMessage("API key entered. Detect languages, then run Preflight Check when ready.");
    } else if (geminiApiKey.value.trim()) {
      setMessage("API key entered. Select an image range before detecting languages.");
    } else {
      setMessage("Paste an API key before running Preflight Check.", true);
    }
  }

  function setMessage(text, isError = false) {
    message.textContent = text;
    processStatus.classList.toggle("error", isError);
  }

  // On-screen + sonic alert when a conversion finishes, matching Transcribe/
  // Test Mode's own showCompletionAlert() (pages/transcribe.py, pages/
  // test_mode.py) -- a user who stepped away while a long conversion ran
  // (up to ~10 minutes for a large
  // transcript, per GETTING_STARTED) has no way to notice the on-page status
  // text change on its own. showSettingsAlert()/playAlertSound() are the
  // same shared functions those two pages use, loaded here from static/
  // app-common.js. Unlike those pages, there's no `completionAlertShown`
  // guard here -- this only ever fires once per convertWithAi() call that
  // actually just finished a real conversion (the "already converted, Convert
  // clicked again" early-return path above doesn't call this), so there's
  // nothing to dedupe against.
  function showCompletionAlert() {
    showSettingsAlert(
      "Scroll down and review the Spreadsheet output panel, then click Download to save your file(s).",
      "Conversion completed"
    );
  }

  function clearSource() {
    sourceFilename = "";
    sourceText = "";
    fileDetail.textContent = "No file selected";
    preflightButton.disabled = true;
    invalidateLanguageDetection();
  }

  function reset() {
    if (!window.confirm("Reset clears the loaded source file, your selections, and any results. Continue?")) return;
    sourceFile.value = "";
    recordType.value = "battesimi";
    imageRange.value = "";
    imageRange.disabled = false;
    processAll.checked = false;
    if (defaultModelId) geminiModel.value = defaultModelId;
    geminiApiKey.value = "";
    clearSource();
    invalidatePreflight();
    setXlsxProgress(false);
    setMessage("Upload a DOCX file to begin.");
  }
})();
