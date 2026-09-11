// playAlertSound()/showSettingsAlert()/hideSettingsAlert() (loaded from
// static/app-common.js, shared with Transcribe/Test Mode -- see that
// file's own comment) read/write this as a plain top-level `let`, not a
// window.* property -- this file is loaded via a plain (non-deferred)
// <script src> right after app-common.js, so a top-level `let` here is
// visible to app-common.js's functions the same way it is on those two
// pages' own per-page scripts.
//
// Extracted from an inline <script> tag in xls_conversion/index.html --
// see CODEX_REVIEW.md finding L-2 / HUMAN_DECISIONS.md: this is what lets
// the CSP drop 'unsafe-inline' from script-src.
let settingsAlertReturnFocus = null;
document.getElementById("settings-alert-close").addEventListener("click", hideSettingsAlert);
