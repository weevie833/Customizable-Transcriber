/* Transcribe page ("/transcribe") script, extracted from pages/transcribe.py's
inline <script> block -- see CODEX_REVIEW.md finding L-2 / HUMAN_DECISIONS.md.
Content is unchanged from the inline block it replaced, except: (1) braces
are no longer doubled since this isn't inside an f-string anymore; (2) the
per-request dynamic values (profiles, running) are now read from the
transcribe-initial-data JSON data island (see json_data_island_html() in
pages/__init__.py) instead of being assigned directly by an executable
inline <script>. Not deferred (loaded via a plain <script src>, same as
before) since this script's own top-level statements run in document order
exactly where the inline block used to sit. */
    document.addEventListener("click", function (event) {
      const link = event.target.closest("a.download");
      if (link && link.getAttribute("aria-disabled") === "true") {
        event.preventDefault();
      }
    });

    async function refreshStatus() {
      const response = await fetch("/status", { cache: "no-store" });
      if (!response.ok) return;
      const status = await response.json();
      const translateStatus = window.tbTranslateStatusText || function (text) { return text; };
      document.getElementById("summary").textContent = translateStatus(status.summary || "");
      document.getElementById("output").textContent = "Output: " + (status.output || "");
      document.getElementById("log").textContent = translateStatus(status.log || "");
      updateRunButton(status.running);
      updateRunStatus(status.running, status.off_peak);
      document.getElementById("stop-button").disabled = !status.running;
      updateDownloadControl(status.download);

      if (status.completed) {
        showCompletionAlert();
      }

      if (status.running) {
        window.setTimeout(refreshStatus, 1500);
      }
    }

    const TR_INITIAL_DATA = JSON.parse(document.getElementById("transcribe-initial-data").textContent);
    const profiles = TR_INITIAL_DATA.profiles;
    const running = TR_INITIAL_DATA.running;
    const initialOffPeak = TR_INITIAL_DATA.off_peak;
    let originalProfileFields = null;
    let runConfirmed = false;
    let preflightComplete = false;
    let completionAlertShown = false;

    const downloadHelpText = "The DOCX file will be downloaded to wherever your browser saves downloaded files. Check your browser's Downloads button for download history.";

    function updateDownloadControl(available) {
      const link = document.getElementById("download-link");
      if (!link) return;
      link.classList.toggle("disabled-link", !available);
      link.setAttribute("aria-disabled", available ? "false" : "true");
      link.tabIndex = available ? 0 : -1;
    }

    function showCompletionAlert() {
      if (completionAlertShown) return;
      completionAlertShown = true;
      showSettingsAlert("Scroll down and review the Progress Console and click the Download Document button.", "Batch completed");
    }

    function profileFields() {
      return {
        role_context: document.querySelector('[name="role_context"]').value,
        reference_context: document.querySelector('[name="reference_context"]').value,
        output_format: document.querySelector('[name="output_format"]').value,
      };
    }

    function setProfileFields(profileId) {
      const profile = profiles[profileId];
      if (!profile) {
        document.querySelector('[name="role_context"]').value = "";
        document.querySelector('[name="reference_context"]').value = "";
        document.querySelector('[name="output_format"]').value = "";
        document.querySelector('[name="new_profile_name"]').value = "";
        document.querySelector('[name="profile_action"]').value = "use";
        originalProfileFields = profileFields();
        updateRunButton(false);
        updateDeleteButton(false);
        return;
      }
      document.querySelector('[name="role_context"]').value = profile.role_context || "";
      document.querySelector('[name="reference_context"]').value = profile.reference_context || "";
      document.querySelector('[name="output_format"]').value = profile.output_format || "";
      document.querySelector('[name="new_profile_name"]').value = "";
      document.querySelector('[name="profile_action"]').value = "use";
      const duplicateAction = document.querySelector('[name="duplicate_profile_action"]');
      if (duplicateAction) duplicateAction.value = "";
      originalProfileFields = profileFields();
      updateRunButton(false);
      updateDeleteButton(false);
    }

    function normalizeProfileName(name) {
      return name.trim().toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^[.-]+|[.-]+$/g, "") || "custom-profile";
    }

    function profileMatchingName(name) {
      const normalizedName = normalizeProfileName(name);
      const loweredName = name.trim().toLowerCase();
      return Object.values(profiles).find((profile) =>
        profile.id === normalizedName || (profile.label || "").trim().toLowerCase() === loweredName
      );
    }

    function suggestedVersionName(name) {
      let counter = 2;
      let candidate = `${name} ${counter}`;
      while (profileMatchingName(candidate)) {
        counter += 1;
        candidate = `${name} ${counter}`;
      }
      return candidate;
    }

    function resolveDuplicateProfileName(event, newName) {
      const duplicate = profileMatchingName(newName);
      const duplicateAction = document.querySelector('[name="duplicate_profile_action"]');
      if (duplicateAction) duplicateAction.value = "";
      if (!duplicate) return true;

      if (window.confirm(`A profile named "${duplicate.label}" already exists. Choose OK to replace it, or Cancel to create a new version.`)) {
        document.querySelector('[name="profile_id"]').value = duplicate.id;
        document.querySelector('[name="new_profile_name"]').value = "";
        document.querySelector('[name="profile_action"]').value = "update";
        if (duplicateAction) duplicateAction.value = "replace";
        return true;
      }

      const versionName = window.prompt("Name for the new profile version:", suggestedVersionName(newName));
      if (!versionName || !versionName.trim()) {
        event.preventDefault();
        return false;
      }
      document.querySelector('[name="new_profile_name"]').value = versionName.trim();
      document.querySelector('[name="profile_action"]').value = "create";
      return true;
    }

    function fieldsChanged() {
      const current = profileFields();
      return originalProfileFields && (
        current.role_context !== originalProfileFields.role_context ||
        current.reference_context !== originalProfileFields.reference_context ||
        current.output_format !== originalProfileFields.output_format
      );
    }


    function canRun() {
      const profileSelected = Boolean(document.querySelector('[name="profile_id"]').value);
      const apiKeyEntered = Boolean(document.querySelector('[name="gemini_api_key"]').value.trim());
      return profileSelected && apiKeyEntered;
    }

    let settingsAlertReturnFocus = null;

    function missingRunSettingMessage() {
      const missing = [];
      const sourceFolderDisplay = document.getElementById("source-folder-display");
      if (!sourceFolderDisplay || sourceFolderDisplay.dataset.selected !== "true") {
        missing.push("choose a source folder");
      }
      if (!document.querySelector('[name="gemini_api_key"]').value.trim()) {
        missing.push("paste a Gemini API key");
      }
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

    function updateRunButton(running) {
      const runButton = document.getElementById("run-button");
      if (!runButton) return;
      const confirmButton = document.getElementById("confirm-run-button");
      const offPeakButton = document.getElementById("confirm-run-offpeak-button");
      const profileSelected = Boolean(document.querySelector('[name="profile_id"]').value);
      const apiKeyEntered = Boolean(document.querySelector('[name="gemini_api_key"]').value.trim());
      const sourceFolderDisplay = document.getElementById("source-folder-display");
      const sourceFolderSelected = Boolean(sourceFolderDisplay && sourceFolderDisplay.dataset.selected === "true");
      runButton.disabled = Boolean(running);
      if (confirmButton && running) confirmButton.disabled = true;
      if (offPeakButton && running) offPeakButton.disabled = true;
      if (running) {
        runButton.title = "A transcription process is already running.";
      } else if (!sourceFolderSelected) {
        runButton.title = "Choose a source folder before running transcription.";
      } else if (!apiKeyEntered) {
        runButton.title = "Paste your Gemini API key before running transcription.";
      } else if (!profileSelected) {
        runButton.title = "Select a prompt profile before running transcription.";
      } else {
        runButton.title = "Check selected settings before transcription.";
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
      const orderLabel = selectedOrder && selectedOrder.value === "oldest" ? "Oldest-to-newest" : "Newest-to-oldest";
      const fileTypeLabel = selectedFileType ? selectedFileType.value.toUpperCase() : "Not selected";
      const profileLabel = profile ? profile.profile_label || profile.label : "Select a Profile";
      const zoomBox = document.querySelector('[name="zoom_pages"]');
      const zoomLabel = zoomBox && zoomBox.checked ? "On" : "Off";
      return { orderLabel, fileTypeLabel, profileLabel, zoomLabel };
    }

    function runPreflightCheck() {
      const panel = document.getElementById("run-confirmation");
      if (!panel) return;
      const settings = selectedRunSettings();
      document.getElementById("confirm-order").textContent = settings.orderLabel;
      document.getElementById("confirm-file-type").textContent = settings.fileTypeLabel;
      document.getElementById("confirm-profile").textContent = settings.profileLabel;
      const confirmZoom = document.getElementById("confirm-zoom");
      if (confirmZoom) confirmZoom.textContent = settings.zoomLabel;
      const settingsWrap = document.getElementById("run-confirmation-settings");
      const confirmButton = document.getElementById("confirm-run-button");
      const offPeakButton = document.getElementById("confirm-run-offpeak-button");
      const runButton = document.getElementById("run-button");
      if (settingsWrap) settingsWrap.hidden = false;
      if (confirmButton) confirmButton.disabled = false;
      if (offPeakButton) offPeakButton.disabled = false;
      if (runButton) runButton.disabled = true;
      preflightComplete = true;
      updateOffPeakCostEstimate();
      updatePageZoomAdvice();
      if (typeof window.tbRefreshLanguage === "function") window.tbRefreshLanguage();
    }

    async function updatePageZoomAdvice() {
      // Checks a few photos locally on the server (no API call) and says
      // whether Page zoom is likely to help -- see page_zoom_advice() in
      // run_support.py. Informational only, like the off-peak estimate.
      const adviceEl = document.getElementById("page-zoom-advice");
      if (!adviceEl) return;
      adviceEl.hidden = true;
      const fileType = document.querySelector('[name="file_type"]:checked');
      const zoomBox = document.querySelector('[name="zoom_pages"]');
      const params = new URLSearchParams({
        model: document.querySelector('[name="model"]').value || "",
        file_type: fileType ? fileType.value : "jpeg",
        profile_id: document.querySelector('[name="profile_id"]').value || "",
        zoom_pages: zoomBox && zoomBox.checked ? "on" : "",
      });
      try {
        const response = await fetch("/api/page-zoom-check?" + params.toString(), { cache: "no-store" });
        if (!response.ok) return;
        const data = await response.json();
        adviceEl.textContent = data.advice || "";
        adviceEl.hidden = !data.advice;
        // Fixed sentences with i18n.js DICTIONARY entries; a raw
        // .textContent assignment bypasses translation until refreshed.
        if (typeof window.tbRefreshLanguage === "function") window.tbRefreshLanguage();
      } catch (err) {
        // Best-effort only.
      }
    }

    async function updateOffPeakCostEstimate() {
      const estimateEl = document.getElementById("offpeak-cost-estimate");
      if (!estimateEl) return;
      const model = document.querySelector('[name="model"]').value;
      const fileType = document.querySelector('[name="file_type"]:checked');
      const profileId = document.querySelector('[name="profile_id"]').value;
      const params = new URLSearchParams({
        model: model || "",
        file_type: fileType ? fileType.value : "jpeg",
        profile_id: profileId || "",
      });
      try {
        const response = await fetch("/api/offpeak-cost-estimate?" + params.toString(), { cache: "no-store" });
        if (!response.ok) return;
        const data = await response.json();
        const estimateText = data.estimate_text || "";
        // Server-assembled text (variable image counts/token totals) --
        // bypasses i18n.js's DICTIONARY the same way showSettingsAlert()'s
        // assembled messages do, so it needs tbTranslateStatusText()'s
        // pattern-matching rather than a raw assignment (see i18n.js's
        // DYNAMIC_LINE_PATTERNS for the off-peak estimate's own patterns).
        estimateEl.textContent =
          typeof window.tbTranslateStatusText === "function" ? window.tbTranslateStatusText(estimateText) : estimateText;
        estimateEl.hidden = !estimateText;
      } catch (err) {
        // Best-effort only -- the estimate is informational, not load-bearing
        // for the run itself, so a failed fetch just leaves it hidden.
      }
    }

    function setOrderHint() {
      const selectedOrder = document.querySelector('[name="order"]:checked');
      const hint = document.getElementById("order-hint");
      if (!selectedOrder || !hint) return;
      hint.textContent = selectedOrder.value === "oldest"
        ? "Oldest-to-newest shows the oldest record at the top of the output document with newer entries following afterwards as you scroll."
        : "Newest-to-oldest shows the most recent record at the top of the output document with older entries following afterwards as you scroll.";
    }

    function handleProfileEditsBeforeSubmit(event) {
      if (event.submitter && event.submitter.id === "reset-button") return;
      if (event.submitter && event.submitter.id === "profile-delete-button") return;
      if (event.submitter && event.submitter.id === "run-button") {
        const missingMessage = missingRunSettingMessage();
        if (missingMessage) {
          event.preventDefault();
          resetPreflight();
          showSettingsAlert(missingMessage);
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
        showSettingsAlert("Please run the preflight check before starting transcription.");
        return;
      }
      if (isConfirmSubmit) {
        runConfirmed = false;
        preflightComplete = false;
      }
      const newName = document.querySelector('[name="new_profile_name"]').value.trim();
      const action = document.querySelector('[name="profile_action"]');
      if (event.submitter && event.submitter.id === "profile-save-button") {
        if (newName) {
          action.value = "create";
          resolveDuplicateProfileName(event, newName);
          return;
        }
        // Always overwrites the currently loaded profile in place -- no
        // confirm dialog. This button is now specifically the destructive-
        // update action; "Save as New Profile" (below) is the explicit way
        // to keep the original instead. Previously this asked "Replace X?
        // Choose Cancel to save a new version" and then, on Cancel, opened a
        // second prompt() that silently created a duplicate profile if
        // accepted -- easy to trigger by mistake, since Cancel reads as
        // "cancel the save," not "keep both versions." Dropped: a user who
        // clicks Save Profile does not need the prior version kept as a
        // fallback (see docs/DESIGN.md's "Additional notes" section).
        action.value = "update";
        return;
      }
      if (event.submitter && event.submitter.id === "profile-save-new-button") {
        action.value = "create";
        if (newName) {
          resolveDuplicateProfileName(event, newName);
          return;
        }
        const profileId = document.querySelector('[name="profile_id"]').value;
        const profile = profiles[profileId];
        const suggested = suggestedVersionName(profile ? (profile.profile_label || profile.label) : "Custom Profile");
        const versionName = window.prompt("Name for the new profile:", suggested);
        if (!versionName || !versionName.trim()) {
          event.preventDefault();
          return;
        }
        document.querySelector('[name="new_profile_name"]').value = versionName.trim();
        resolveDuplicateProfileName(event, versionName.trim());
        return;
      }
      if (newName) {
        action.value = "create";
        resolveDuplicateProfileName(event, newName);
        return;
      }
      if (!fieldsChanged()) {
        action.value = "use";
        return;
      }
      // Reached by editing profile fields and then clicking Run (Confirm
      // and run) without an explicit Save first -- always overwrites the
      // loaded profile in place, same reasoning as "profile-save-button"
      // above (this used to confirm()/prompt() here too, with the same
      // silent-duplicate risk on Cancel). Type a name in the "Save new
      // custom profile as" field and use "Save as New Profile" instead if
      // you want to keep the original.
      action.value = "update";
    }

    window.addEventListener("DOMContentLoaded", () => {
      const profileSelect = document.querySelector('[name="profile_id"]');
      if (profileSelect) {
        setProfileFields(profileSelect.value);
        profileSelect.addEventListener("change", () => {
          setProfileFields(profileSelect.value);
          // Choosing a profile applies its saved Page zoom default (Prompt
          // Builder). Only on a real change, not on page load, so a setting
          // the user changed for the current run survives a reload.
          const zoomBox = document.querySelector('[name="zoom_pages"]');
          const chosen = profiles[profileSelect.value];
          if (zoomBox && chosen) zoomBox.checked = Boolean(chosen.zoom_pages);
          resetPreflight();
          hideSettingsAlert();
        });
      }
      const apiKeyInput = document.querySelector('[name="gemini_api_key"]');
      if (apiKeyInput) {
        apiKeyInput.addEventListener("input", () => {
          updateRunButton(false);
          resetPreflight();
          hideSettingsAlert();
        });
      }
      document.querySelectorAll('[name="order"]').forEach((input) => {
        input.addEventListener("change", () => {
          setOrderHint();
          resetPreflight();
        });
      });
      document.querySelectorAll('[name="file_type"]').forEach((input) => {
        input.addEventListener("change", resetPreflight);
      });
      // Page zoom advice depends on the model and the checkbox, so either
      // change means the Preflight Check has to be run again.
      document.querySelectorAll('[name="zoom_pages"], [name="model"]').forEach((input) => {
        input.addEventListener("change", resetPreflight);
      });
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
          // form.requestSubmit(submitter) uses the submitter's own
          // formaction ("/run-offpeak") rather than the <form>'s default
          // action -- same <form> as the real-time Now button, just a
          // different button.
          if (runForm) runForm.requestSubmit(confirmOffPeakButton);
        });
      }
      const downloadLink = document.getElementById("download-link");
      if (downloadLink) {
        downloadLink.addEventListener("click", (event) => {
          if (downloadLink.getAttribute("aria-disabled") === "true") event.preventDefault();
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
      const runForm = document.querySelector('form[action="/run"]');
      if (runForm) {
        runForm.addEventListener("submit", handleProfileEditsBeforeSubmit);
        runForm.addEventListener("submit", confirmProfileDelete);
        runForm.addEventListener("submit", confirmReset);
      }
      updateRunButton(running);
      updateRunStatus(running, initialOffPeak);
      updateDeleteButton(running);
      if (typeof wireInfoButtons === "function") wireInfoButtons();
      if (running) {
        window.setTimeout(refreshStatus, 1500);
      }
    });
