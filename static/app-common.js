// Shared browser-side helpers for the Transcribe and Test Mode pages
// (app.py's page() and test_mode_page()) -- extracted after both pages'
// inline <script> blocks turned out to define 12 functions with byte-
// identical bodies. See docs/DESIGN.md's "Codebase structure" section.
//
// These all read/write DOM elements or module-level `let` variables
// (settingsAlertReturnFocus, runConfirmed, preflightComplete) declared in
// each page's own remaining inline script -- safe because top-level `let`/
// `const` in one classic <script> tag is visible to script tags that run
// later in the same document (verified directly: not an ES-module import,
// just normal script-to-script global scope sharing), and none of these
// functions are called until a later user action, by which point every
// script on the page has already run. Loaded via a plain (non-deferred)
// <script src> placed immediately before each page's inline script, so
// load order can never matter here even if that changes later.

function playAlertSound() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const context = new AudioContext();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(660, context.currentTime);
    gain.gain.setValueAtTime(0.001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.18, context.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.28);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.3);
  } catch (error) {
    return;
  }
}

function showSettingsAlert(message, title = "Run settings needed") {
  const alert = document.getElementById("settings-alert");
  const titleNode = document.getElementById("settings-alert-title");
  const messageNode = document.getElementById("settings-alert-message");
  if (!alert || !messageNode) return;
  settingsAlertReturnFocus = document.activeElement;
  if (titleNode) titleNode.textContent = title;
  messageNode.textContent = message;
  alert.hidden = false;
  playAlertSound();
  const closeButton = document.getElementById("settings-alert-close");
  if (closeButton) closeButton.focus();
  // Setting textContent directly (above) bypasses i18n.js's DICTIONARY
  // entirely -- a plain assignment, not something it walks and translates
  // on its own -- so every alert shown this way used to display in English
  // regardless of the selected language, same bug as updateRunStatus()'s
  // title label (see its own comment in this file). tbRefreshLanguage()
  // (i18n.js) re-applies whatever language is currently active, including
  // a no-op in English; it covers `title` and any `message` that exactly
  // matches a DICTIONARY entry. A `message` built from several variable
  // parts (e.g. missingRunSettingMessage()/apiKeyMismatchMessage() in
  // pages/transcribe.py and pages/test_mode.py) can't be a single DICTIONARY
  // key, so those are pre-translated at the point they're assembled instead
  // -- see DYNAMIC_LINE_PATTERNS in i18n.js -- and arrive here already in
  // the right language, same as any other message.
  if (typeof window.tbRefreshLanguage === "function") window.tbRefreshLanguage();
}

function hideSettingsAlert() {
  const alert = document.getElementById("settings-alert");
  if (alert) alert.hidden = true;
  if (settingsAlertReturnFocus && typeof settingsAlertReturnFocus.focus === "function") {
    settingsAlertReturnFocus.focus();
  }
  settingsAlertReturnFocus = null;
}

function resetPreflight() {
  runConfirmed = false;
  preflightComplete = false;
  const confirmButton = document.getElementById("confirm-run-button");
  const runButton = document.getElementById("run-button");
  const settings = document.getElementById("run-confirmation-settings");
  if (confirmButton) confirmButton.disabled = true;
  if (runButton) runButton.disabled = false;
  if (settings) settings.hidden = true;
}

function applySourceFolder(path) {
  const display = document.getElementById("source-folder-display");
  if (!display) return;
  display.textContent = path;
  display.dataset.selected = "true";
  resetPreflight();
}

async function pickSourceFolder() {
  const button = document.getElementById("browse-source-button");
  if (!button) return;
  button.disabled = true;
  try {
    const response = await fetch("/api/pick-source-folder", { method: "POST" });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "Couldn't open the folder picker.");
    if (data.canceled) return;
    applySourceFolder(data.source_folder);
  } catch (error) {
    showSettingsAlert(error.message || "Couldn't open the folder picker.");
  } finally {
    button.disabled = false;
  }
}

async function openOutputsFolder() {
  const button = document.getElementById("open-outputs-folder-button");
  if (!button) return;
  button.disabled = true;
  try {
    const response = await fetch("/api/open-outputs-folder", { method: "POST" });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "Couldn't open the outputs folder.");
  } catch (error) {
    showSettingsAlert(error.message || "Couldn't open the outputs folder.");
  } finally {
    button.disabled = false;
  }
}

async function setSourceFolderManually() {
  const button = document.getElementById("source-folder-manual-button");
  const input = document.getElementById("source-folder-manual-input");
  if (!button || !input) return;
  const path = input.value.trim();
  if (!path) {
    showSettingsAlert("Paste a folder path first.");
    return;
  }
  button.disabled = true;
  try {
    const response = await fetch("/api/set-source-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "Couldn't use that path.");
    applySourceFolder(data.source_folder);
    input.value = "";
  } catch (error) {
    showSettingsAlert(error.message || "Couldn't use that path.");
  } finally {
    button.disabled = false;
  }
}

function updateRunStatus(running) {
  const status = document.getElementById("run-status");
  const settings = document.getElementById("run-confirmation-settings");
  const title = document.querySelector("#run-confirmation .run-confirmation-title");
  if (!status) return;
  status.hidden = !running;
  if (settings && running) settings.hidden = true;
  if (title) {
    // Setting textContent directly bypasses i18n.js's DICTIONARY entirely
    // (a plain assignment, not something it walks and translates on its
    // own) -- this used to leave this label stuck in English forever after
    // the very first call, even with Italian selected, since this runs on
    // every page load (from the DOMContentLoaded handler in
    // transcribe.py/test_mode.py) *after* i18n.js's own initial pass
    // already ran and correctly translated the server-rendered text.
    // tbRefreshLanguage() (i18n.js) is exposed for exactly this "content
    // added/changed after the initial pass" case and re-applies whatever
    // language is currently active, including a no-op in English.
    title.textContent = running ? "Progress:" : "Confirm settings:";
    if (typeof window.tbRefreshLanguage === "function") window.tbRefreshLanguage();
  }
}

function updateDeleteButton(running) {
  const deleteButton = document.getElementById("profile-delete-button");
  if (!deleteButton) return;
  deleteButton.disabled = Boolean(running) || !document.querySelector('[name="profile_id"]').value;
}

function confirmProfileDelete(event) {
  if (!event.submitter || event.submitter.id !== "profile-delete-button") return;
  const profileId = document.querySelector('[name="profile_id"]').value;
  const profile = profiles[profileId];
  const label = profile ? profile.label : "the selected profile";
  if (!window.confirm(`${label} will be permanently deleted. This cannot be undone.`)) {
    event.preventDefault();
  }
}

function confirmReset(event) {
  if (!event.submitter || event.submitter.id !== "reset-button") return;
  if (!window.confirm("Reset All clears the source folder, run settings, and current output. Continue?")) {
    event.preventDefault();
  }
}
