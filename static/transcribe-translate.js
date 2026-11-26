/* Transcribe page: "Translate completed transcript" section
(pages/transcribe.py, handlers/transcribe_translate.py). The Preflight Check
reads the uploaded DOCX on the server and checks the API key with one tiny
request to the provider; Translate stays
disabled until a preflight of the current settings has passed. The run itself
reports through the Progress Console like a transcription run, so this script
hands off to transcribe.js's refreshStatus() once it starts. The translation
choices are made here; the prompt profile is only background on the register,
found from the document's header, so its picker stays hidden unless the user
asks for it or no profile was found. */
(function () {
  let preflightPassed = false;

  function el(id) {
    return document.getElementById(id);
  }

  function selectedLanguages() {
    return Array.from(document.querySelectorAll('[name="translate_language"]:checked')).map((box) => box.value);
  }

  function translateText(text) {
    return typeof window.tbTranslateStatusText === "function" ? window.tbTranslateStatusText(text) : text;
  }

  function checked(name) {
    const box = document.querySelector(`[name="${name}"]`);
    return box && box.checked ? "on" : "";
  }

  function selectedHonorifics() {
    const boxes = Array.from(document.querySelectorAll('[name="translate_honorific"]:checked')).map((box) => box.value);
    const other = document.querySelector('[name="translate_other_honorifics"]').value.split(",");
    return boxes.concat(other.map((value) => value.trim()).filter(Boolean));
  }

  function showProfilePicker() {
    el("translate-profile-wrap").hidden = false;
  }

  function requestBody() {
    const body = new FormData();
    const file = el("translate-source-file").files[0];
    if (file) body.append("source_file", file);
    body.append("languages", selectedLanguages().join(","));
    body.append("expand_abbreviations", checked("translate_expand_abbreviations"));
    body.append("convert_names", checked("translate_convert_names"));
    body.append("honorifics", selectedHonorifics().join(","));
    body.append("profile_id", document.querySelector('[name="translate_profile_id"]').value || "");
    body.append("model", document.querySelector('[name="model"]').value || "");
    body.append("api_key", document.querySelector('[name="gemini_api_key"]').value.trim());
    return body;
  }

  function setRunButtons(enabled) {
    el("translate-run-button").disabled = !enabled;
    const offPeak = el("translate-run-offpeak-button");
    if (offPeak) offPeak.disabled = !enabled;
  }

  function resetPreflight() {
    preflightPassed = false;
    setRunButtons(false);
  }

  function addList(container, heading, items, className) {
    if (!items || !items.length) return;
    const title = document.createElement("p");
    title.textContent = heading;
    if (className) title.className = className;
    container.appendChild(title);
    const list = document.createElement("ul");
    items.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = translateText(item);
      if (className) li.className = className;
      list.appendChild(li);
    });
    container.appendChild(list);
  }

  function addLine(container, text) {
    const line = document.createElement("p");
    line.textContent = translateText(text);
    container.appendChild(line);
  }

  function renderPreflight(data) {
    const box = el("translate-preflight-result");
    box.textContent = "";
    box.hidden = false;
    if (data.ok) {
      if (data.profile_label) {
        addLine(box, `Background: ${data.profile_label}` + (data.profile_detected ? " (named in the document)" : ""));
        if (el("translate-profile-wrap").hidden) {
          const change = document.createElement("button");
          change.type = "button";
          change.className = "button-tiny translate-change-profile";
          change.textContent = "Use a different profile";
          change.addEventListener("click", () => {
            showProfilePicker();
            change.remove();
          });
          box.appendChild(change);
        }
      } else {
        addLine(box, "Background: none");
        showProfilePicker();
      }
      if (data.api_key_valid) addLine(box, `API key: accepted by ${data.model_label}`);
      addLine(box, `Images: ${data.records}`);
      addLine(box, `Entries: ${data.entries}` + (data.fragments ? ` (${data.fragments} continue from the previous image)` : ""));
      Object.keys(data.to_translate || {}).forEach((lang) => {
        addLine(box, `To translate into ${lang}: ${data.to_translate[lang]}`);
        const already = (data.already_translated || {})[lang] || 0;
        if (already) addLine(box, `Already translated into ${lang}, skipped: ${already}`);
      });
      if (data.church_wedding_records) addLine(box, `Church Wedding Records to translate: ${data.church_wedding_records}`);
      const estimate = data.estimate || {};
      if (estimate.calls) {
        addLine(
          box,
          `Estimated use: about ${estimate.input_tokens} input tokens and ${estimate.output_tokens} output tokens in ${estimate.calls} request(s).`
        );
      }
    } else {
      addList(box, "Fix these before translating:", data.errors, "translate-error");
      if ((data.errors || []).includes("The selected prompt profile was not found.")) showProfilePicker();
    }
    addList(box, "Warnings:", data.warnings, "translate-warning");
    addList(box, "Your edits, accepted as written:", data.accepted_edits, "");
    if (data.ok) addLine(box, "Preflight passed. Click Translate, or Translate Off-Peak for roughly half the price.");
    if (typeof window.tbRefreshLanguage === "function") window.tbRefreshLanguage();
  }

  async function runPreflight() {
    resetPreflight();
    if (!el("translate-source-file").files[0]) {
      showSettingsAlert("Choose the corrected DOCX transcript first.");
      return;
    }
    const button = el("translate-preflight-button");
    button.disabled = true;
    const box = el("translate-preflight-result");
    box.textContent = "";
    box.hidden = false;
    addLine(box, "Reading the transcript and checking the API key...");
    if (typeof window.tbRefreshLanguage === "function") window.tbRefreshLanguage();
    try {
      const response = await fetch("/api/translate-transcript/preflight", { method: "POST", body: requestBody() });
      const data = await response.json();
      renderPreflight(data);
      preflightPassed = Boolean(data.ok);
      setRunButtons(preflightPassed);
    } catch (err) {
      renderPreflight({ ok: false, errors: ["The preflight check could not reach the app. Is it still running?"] });
    } finally {
      button.disabled = false;
    }
  }

  async function runTranslation(offPeak) {
    if (!preflightPassed) {
      showSettingsAlert("Please run the preflight check before translating.");
      return;
    }
    if (!document.querySelector('[name="gemini_api_key"]').value.trim()) {
      showSettingsAlert("Paste your API key in the API key field above.");
      return;
    }
    setRunButtons(false);
    const url = offPeak ? "/api/translate-transcript/run-offpeak" : "/api/translate-transcript/run";
    try {
      const response = await fetch(url, { method: "POST", body: requestBody() });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        showSettingsAlert(translateText((data.errors || ["The translation could not start."]).join(" ")));
        setRunButtons(true);
        return;
      }
      resetPreflight();
      completionAlertShown = false;
      refreshStatus();
      const progressHeading = document.querySelector(".panel .panel-title");
      if (progressHeading) progressHeading.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      showSettingsAlert("The translation could not start.");
      setRunButtons(true);
    }
  }

  window.addEventListener("DOMContentLoaded", () => {
    const form = el("translate-form");
    if (!form) return;
    form.addEventListener("submit", (event) => event.preventDefault());
    el("translate-preflight-button").addEventListener("click", runPreflight);
    el("translate-run-button").addEventListener("click", () => runTranslation(false));
    el("translate-run-offpeak-button").addEventListener("click", () => runTranslation(true));
    // Any change to what would be sent means the preflight must run again.
    form.addEventListener("change", (event) => {
      if (event.target.id === "translate-source-file") {
        const nameEl = event.target.closest(".file-picker").querySelector(".file-picker-name");
        const file = event.target.files[0];
        if (nameEl && file) nameEl.textContent = file.name;
      }
      resetPreflight();
      el("translate-preflight-result").hidden = true;
    });
    // The model and API key fields sit in the main form above, but the
    // preflight checked the key against that model, so a change to either
    // means running it again.
    const modelSelect = document.querySelector('[name="model"]');
    if (modelSelect) modelSelect.addEventListener("change", resetPreflight);
    const keyInput = document.querySelector('[name="gemini_api_key"]');
    if (keyInput) keyInput.addEventListener("input", resetPreflight);
  });
})();
