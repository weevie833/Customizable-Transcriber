"""Transcribe page ("/transcribe", the app's original page() function).
Split out of app.py as part of the app.py-modularization pass -- see
CLAUDE.md."""

from __future__ import annotations

import html

from customizable_transcription.core import MODELS
from pages import FOOTER_HTML, json_for_inline_script
from profiles_store import load_profile, profile_options_html, profiles_for_browser
from app_state import load_source_folder, lock, state

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

    if profile_id:
        active_profile = load_profile(profile_id)
        if active_profile.get("kind") == "custom" and not any((role_context, reference_context, output_format)):
            role_context = active_profile.get("role_context", "")
            reference_context = active_profile.get("reference_context", "")
            output_format = active_profile.get("output_format", "")

    source_folder = load_source_folder()
    source_folder_display = html.escape(str(source_folder)) if source_folder else "No folder selected"
    source_folder_selected = "true" if source_folder else "false"
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
    pdf_checked = "checked" if file_type == "pdf" else ""
    profile_options = profile_options_html(profile_id)
    profile_data_json = json_for_inline_script(profiles_for_browser())
    download_disabled_class = "" if download else " disabled-link"
    download_aria_disabled = "false" if download else "true"

    return f"""<!doctype html>
<html lang="en">
  <head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Customizable Transcription</title>
  <script src="/static/i18n.js" defer></script>
  <script src="/static/app-common.js"></script>
  <script>
    document.addEventListener("click", function (event) {{
      const link = event.target.closest("a.download");
      if (link && link.getAttribute("aria-disabled") === "true") {{
        event.preventDefault();
      }}
    }});

    async function refreshStatus() {{
      const response = await fetch("/status", {{ cache: "no-store" }});
      if (!response.ok) return;
      const status = await response.json();
      const translateStatus = window.tbTranslateStatusText || function (text) {{ return text; }};
      document.getElementById("summary").textContent = translateStatus(status.summary || "");
      document.getElementById("output").textContent = "Output: " + (status.output || "");
      document.getElementById("log").textContent = translateStatus(status.log || "");
      updateRunButton(status.running);
      updateRunStatus(status.running);
      document.getElementById("stop-button").disabled = !status.running;
      updateDownloadControl(status.download);

      if (status.completed) {{
        showCompletionAlert();
      }}

      if (status.running) {{
        window.setTimeout(refreshStatus, 1500);
      }}
    }}

    const profiles = {profile_data_json};
    let originalProfileFields = null;
    let runConfirmed = false;
    let preflightComplete = false;
    let completionAlertShown = false;

    const downloadHelpText = "The DOCX file will be downloaded to wherever your browser saves downloaded files. Check your browser's Downloads button for download history.";

    function updateDownloadControl(available) {{
      const link = document.getElementById("download-link");
      if (!link) return;
      link.classList.toggle("disabled-link", !available);
      link.setAttribute("aria-disabled", available ? "false" : "true");
      link.tabIndex = available ? 0 : -1;
    }}

    function showCompletionAlert() {{
      if (completionAlertShown) return;
      completionAlertShown = true;
      showSettingsAlert("Scroll down and review the Progress Console and click the Download Document button.", "Batch completed");
    }}

    function profileFields() {{
      return {{
        role_context: document.querySelector('[name="role_context"]').value,
        reference_context: document.querySelector('[name="reference_context"]').value,
        output_format: document.querySelector('[name="output_format"]').value,
      }};
    }}

    function setProfileFields(profileId) {{
      const profile = profiles[profileId];
      if (!profile) {{
        document.querySelector('[name="role_context"]').value = "";
        document.querySelector('[name="reference_context"]').value = "";
        document.querySelector('[name="output_format"]').value = "";
        document.querySelector('[name="new_profile_name"]').value = "";
        document.querySelector('[name="profile_action"]').value = "use";
        originalProfileFields = profileFields();
        updateRunButton(false);
        updateDeleteButton(false);
        return;
      }}
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
    }}

    function normalizeProfileName(name) {{
      return name.trim().toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^[.-]+|[.-]+$/g, "") || "custom-profile";
    }}

    function profileMatchingName(name) {{
      const normalizedName = normalizeProfileName(name);
      const loweredName = name.trim().toLowerCase();
      return Object.values(profiles).find((profile) =>
        profile.id === normalizedName || (profile.label || "").trim().toLowerCase() === loweredName
      );
    }}

    function suggestedVersionName(name) {{
      let counter = 2;
      let candidate = `${{name}} ${{counter}}`;
      while (profileMatchingName(candidate)) {{
        counter += 1;
        candidate = `${{name}} ${{counter}}`;
      }}
      return candidate;
    }}

    function resolveDuplicateProfileName(event, newName) {{
      const duplicate = profileMatchingName(newName);
      const duplicateAction = document.querySelector('[name="duplicate_profile_action"]');
      if (duplicateAction) duplicateAction.value = "";
      if (!duplicate) return true;

      if (window.confirm(`A profile named "${{duplicate.label}}" already exists. Choose OK to replace it, or Cancel to create a new version.`)) {{
        document.querySelector('[name="profile_id"]').value = duplicate.id;
        document.querySelector('[name="new_profile_name"]').value = "";
        document.querySelector('[name="profile_action"]').value = "update";
        if (duplicateAction) duplicateAction.value = "replace";
        return true;
      }}

      const versionName = window.prompt("Name for the new profile version:", suggestedVersionName(newName));
      if (!versionName || !versionName.trim()) {{
        event.preventDefault();
        return false;
      }}
      document.querySelector('[name="new_profile_name"]').value = versionName.trim();
      document.querySelector('[name="profile_action"]').value = "create";
      return true;
    }}

    function fieldsChanged() {{
      const current = profileFields();
      return originalProfileFields && (
        current.role_context !== originalProfileFields.role_context ||
        current.reference_context !== originalProfileFields.reference_context ||
        current.output_format !== originalProfileFields.output_format
      );
    }}


    function canRun() {{
      const profileSelected = Boolean(document.querySelector('[name="profile_id"]').value);
      const apiKeyEntered = Boolean(document.querySelector('[name="gemini_api_key"]').value.trim());
      return profileSelected && apiKeyEntered;
    }}

    let settingsAlertReturnFocus = null;

    function missingRunSettingMessage() {{
      const missing = [];
      const sourceFolderDisplay = document.getElementById("source-folder-display");
      if (!sourceFolderDisplay || sourceFolderDisplay.dataset.selected !== "true") {{
        missing.push("choose a source folder");
      }}
      if (!document.querySelector('[name="gemini_api_key"]').value.trim()) {{
        missing.push("paste a Gemini API key");
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

    function updateRunButton(running) {{
      const runButton = document.getElementById("run-button");
      if (!runButton) return;
      const confirmButton = document.getElementById("confirm-run-button");
      const profileSelected = Boolean(document.querySelector('[name="profile_id"]').value);
      const apiKeyEntered = Boolean(document.querySelector('[name="gemini_api_key"]').value.trim());
      const sourceFolderDisplay = document.getElementById("source-folder-display");
      const sourceFolderSelected = Boolean(sourceFolderDisplay && sourceFolderDisplay.dataset.selected === "true");
      runButton.disabled = Boolean(running);
      if (confirmButton && running) confirmButton.disabled = true;
      if (running) {{
        runButton.title = "A transcription process is already running.";
      }} else if (!sourceFolderSelected) {{
        runButton.title = "Choose a source folder before running transcription.";
      }} else if (!apiKeyEntered) {{
        runButton.title = "Paste your Gemini API key before running transcription.";
      }} else if (!profileSelected) {{
        runButton.title = "Select a prompt profile before running transcription.";
      }} else {{
        runButton.title = "Check selected settings before transcription.";
      }}
    }}

    function selectedRunSettings() {{
      const selectedOrder = document.querySelector('[name="order"]:checked');
      const selectedFileType = document.querySelector('[name="file_type"]:checked');
      const profileId = document.querySelector('[name="profile_id"]').value;
      const profile = profiles[profileId];
      const orderLabel = selectedOrder && selectedOrder.value === "oldest" ? "Oldest-to-newest" : "Newest-to-oldest";
      const fileTypeLabel = selectedFileType ? selectedFileType.value.toUpperCase() : "Not selected";
      const profileLabel = profile ? profile.profile_label || profile.label : "Select a Profile";
      return {{ orderLabel, fileTypeLabel, profileLabel }};
    }}

    function runPreflightCheck() {{
      const panel = document.getElementById("run-confirmation");
      if (!panel) return;
      const settings = selectedRunSettings();
      document.getElementById("confirm-order").textContent = settings.orderLabel;
      document.getElementById("confirm-file-type").textContent = settings.fileTypeLabel;
      document.getElementById("confirm-profile").textContent = settings.profileLabel;
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
        ? "Oldest-to-newest shows the oldest record at the top of the output document with newer entries following afterwards as you scroll."
        : "Newest-to-oldest shows the most recent record at the top of the output document with older entries following afterwards as you scroll.";
    }}

    function handleProfileEditsBeforeSubmit(event) {{
      if (event.submitter && event.submitter.id === "reset-button") return;
      if (event.submitter && event.submitter.id === "profile-delete-button") return;
      if (event.submitter && event.submitter.id === "run-button") {{
        const missingMessage = missingRunSettingMessage();
        if (missingMessage) {{
          event.preventDefault();
          resetPreflight();
          showSettingsAlert(missingMessage);
          return;
        }}
        event.preventDefault();
        runPreflightCheck();
        return;
      }}
      if (event.submitter && event.submitter.id === "confirm-run-button" && !preflightComplete) {{
        event.preventDefault();
        showSettingsAlert("Please run the preflight check before starting transcription.");
        return;
      }}
      if (event.submitter && event.submitter.id === "confirm-run-button") {{
        runConfirmed = false;
        preflightComplete = false;
      }}
      const newName = document.querySelector('[name="new_profile_name"]').value.trim();
      const action = document.querySelector('[name="profile_action"]');
      if (event.submitter && event.submitter.id === "profile-save-button") {{
        if (newName) {{
          action.value = "create";
          resolveDuplicateProfileName(event, newName);
          return;
        }}
        // Always overwrites the currently loaded profile in place -- no
        // confirm dialog. This button is now specifically the destructive-
        // update action; "Save as New Profile" (below) is the explicit way
        // to keep the original instead. Previously this asked "Replace X?
        // Choose Cancel to save a new version" and then, on Cancel, opened a
        // second prompt() that silently created a duplicate profile if
        // accepted -- easy to trigger by mistake, since Cancel reads as
        // "cancel the save," not "keep both versions." Dropped per the
        // profile-save-protocol review in CLAUDE.md: a user who clicks Save
        // Profile does not need the prior version kept as a fallback.
        action.value = "update";
        return;
      }}
      if (event.submitter && event.submitter.id === "profile-save-new-button") {{
        action.value = "create";
        if (newName) {{
          resolveDuplicateProfileName(event, newName);
          return;
        }}
        const profileId = document.querySelector('[name="profile_id"]').value;
        const profile = profiles[profileId];
        const suggested = suggestedVersionName(profile ? (profile.profile_label || profile.label) : "Custom Profile");
        const versionName = window.prompt("Name for the new profile:", suggested);
        if (!versionName || !versionName.trim()) {{
          event.preventDefault();
          return;
        }}
        document.querySelector('[name="new_profile_name"]').value = versionName.trim();
        resolveDuplicateProfileName(event, versionName.trim());
        return;
      }}
      if (newName) {{
        action.value = "create";
        resolveDuplicateProfileName(event, newName);
        return;
      }}
      if (!fieldsChanged()) {{
        action.value = "use";
        return;
      }}
      // Reached by editing profile fields and then clicking Run (Confirm
      // and run) without an explicit Save first -- always overwrites the
      // loaded profile in place, same reasoning as "profile-save-button"
      // above (this used to confirm()/prompt() here too, with the same
      // silent-duplicate risk on Cancel). Type a name in the "Save new
      // custom profile as" field and use "Save as New Profile" instead if
      // you want to keep the original.
      action.value = "update";
    }}

    window.addEventListener("DOMContentLoaded", () => {{
      const profileSelect = document.querySelector('[name="profile_id"]');
      if (profileSelect) {{
        setProfileFields(profileSelect.value);
        profileSelect.addEventListener("change", () => {{
          setProfileFields(profileSelect.value);
          resetPreflight();
          hideSettingsAlert();
        }});
      }}
      const apiKeyInput = document.querySelector('[name="gemini_api_key"]');
      if (apiKeyInput) {{
        apiKeyInput.addEventListener("input", () => {{
          updateRunButton(false);
          resetPreflight();
          hideSettingsAlert();
        }});
      }}
      document.querySelectorAll('[name="order"]').forEach((input) => {{
        input.addEventListener("change", () => {{
          setOrderHint();
          resetPreflight();
        }});
      }});
      document.querySelectorAll('[name="file_type"]').forEach((input) => {{
        input.addEventListener("change", resetPreflight);
      }});
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
      const downloadLink = document.getElementById("download-link");
      if (downloadLink) {{
        downloadLink.addEventListener("click", (event) => {{
          if (downloadLink.getAttribute("aria-disabled") === "true") event.preventDefault();
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
      const runForm = document.querySelector('form[action="/run"]');
      if (runForm) {{
        runForm.addEventListener("submit", handleProfileEditsBeforeSubmit);
        runForm.addEventListener("submit", confirmProfileDelete);
        runForm.addEventListener("submit", confirmReset);
      }}
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
    input[type="file"] {{
      display: none;
    }}
    .section-divider {{
      border: none;
      border-top: 1px solid #d9d4c8;
      margin: 18px 0;
    }}
    .check {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 14px;
      font-weight: 500;
    }}
    .check input {{
      appearance: none;
      width: 16px;
      height: 16px;
      margin: 0;
      border: 1.5px solid #4b5563;
      border-radius: 2px;
      background: transparent;
    }}
    .check input:checked {{
      background: #255c99;
      border-color: #255c99;
      box-shadow: inset 0 0 0 3px #fff;
    }}
    details.manual-override-section {{
      margin: 20px -18px -18px;
      padding: 14px 18px;
      border-top: 1px solid #d9d4c8;
      border-radius: 0 0 8px 8px;
      background: #f4f5f6;
    }}
    details.manual-override-section summary {{
      cursor: pointer;
      list-style: none;
      font-weight: 700;
      font-size: 15px;
      padding: 2px 0;
    }}
    details.manual-override-section summary::-webkit-details-marker {{
      display: none;
    }}
    details.manual-override-section summary::before {{
      content: "\\25B8";
      margin-right: 8px;
      color: #255c99;
      display: inline-block;
      transition: transform 0.12s ease;
    }}
    details.manual-override-section[open] summary::before {{
      transform: rotate(90deg);
    }}
    details.manual-override-section .profile-work-area {{
      margin: 14px 0 0;
      padding: 0;
      border-top: none;
      border-radius: 0;
      background: none;
    }}
    #download-wrap {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    @media (max-width: 720px) {{
      main {{
        width: min(100% - 28px, 980px);
        padding-top: 20px;
      }}
      .row, .run-options, .profile-select-row, .profile-save-row {{ grid-template-columns: 1fr; }}
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
      <h1>Transcribe</h1>
    </div>
    <div class="header-nav-row">
      <nav class="site-nav" aria-label="Primary navigation">
        <a class="nav-link nav-home" href="/" aria-label="Home" title="Home">🏠</a>
        <a class="nav-link" href="/prompt-builder">Prompt Builder</a>
        <a class="nav-link" href="/transcribe" aria-current="page">Transcribe</a>
        <a class="nav-link" href="/xls-conversion">XLSX Conversion</a>
        <a class="nav-link" href="/test-mode">Test Mode</a>
      </nav>
      <div class="lang-toggle" role="group" aria-label="Language / Lingua">
        <button type="button" class="lang-flag" data-lang="en" aria-pressed="true" title="English" aria-label="English">🇺🇸</button>
        <button type="button" class="lang-flag" data-lang="it" aria-pressed="false" title="Italiano" aria-label="Italiano">🇮🇹</button>
      </div>
    </div>
  </header>
  <form method="post" action="/run">
    <div class="path-control">
      <label>Source folder</label>
      <div class="path-control-row">
        <button id="browse-source-button" type="button" class="button-tiny">Browse&hellip;</button>
        <div class="path-display" id="source-folder-display" data-selected="{source_folder_selected}">{source_folder_display}</div>
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
        <button id="profile-delete-button" class="danger" type="submit" formaction="/delete-profile" formmethod="post" disabled>Delete Profile</button>
      </div>
      <input type="hidden" name="profile_action" value="use">
      <input type="hidden" name="duplicate_profile_action" value="">
    </label>
    <p class="hint">Use the Prompt Builder page to create prompts, or bypass the Prompt Builder and place your prompt in the sections below. Manual prompts cannot be edited in the Prompt Builder.</p>
    <div class="actions run-actions">
      <div class="run-button-stack">
        <button id="run-button" type="submit" disabled>Preflight Check</button>
        <button id="confirm-run-button" type="submit" disabled>Confirm and run</button>
      </div>
      <span id="run-confirmation" class="run-confirmation">
        <span class="run-confirmation-title">Confirm settings:</span>
        <span id="run-confirmation-settings" class="run-confirmation-settings" hidden>
          <span>Order: <strong id="confirm-order"></strong></span>
          <span>File type: <strong id="confirm-file-type"></strong></span>
          <span>Prompt Profile: <strong id="confirm-profile"></strong></span>
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
  <section class="panel">
    <h2 class="panel-title">Progress Console</h2>
    <div id="summary" class="summary" role="status" aria-live="polite">{escaped_summary}</div>
    <div class="actions">
      <form method="post" action="/stop">
        <button id="stop-button" class="danger" type="submit" {stop_disabled}>Stop</button>
      </form>
      <a id="download-link" class="download{download_disabled_class}" href="/download" download aria-disabled="{download_aria_disabled}">Download Document</a>
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
