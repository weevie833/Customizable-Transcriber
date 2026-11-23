Independent security and best-practices review
Reviewed November 23, 2026. Customizable Transcriber 0.5.6, commit a102d4448e0e70bc4493dab16ad9e103f30b02c9.

Remediation priority. No critical or high-severity vulnerabilities were identified in the core server, handlers, storage, or frontend modules reviewed under the documented single-user loopback deployment model (SECURITY.md). Three medium-severity defense-in-depth and concurrency issues should be addressed first: bounding actual decompressed bytes in .docx/.xlsx zip-bomb checks (M-1), preventing profile saves on /transcribe from clobbering an active background run's state (M-2), and suppressing the CSRF Set-Cookie header on rejected 400/403 security responses (M-3).
CRITICAL
No critical finding identified under the documented single-user, loopback deployment model.
HIGH
No high-severity finding identified in the reviewed modules.
MEDIUM
M-1. DOCX and XLSX zip-bomb checks trust declared ZIP header sizes rather than actual decompressed bytes
	•	Location. http_utils.py (extract_docx_text), index_compare/reader.py (_check_zip_bomb_safety).
	•	Evidence and impact. Both ingestion guards inspect ZipInfo.file_size from the archive's central directory before calling archive.read(info) or openpyxl.load_workbook(). Because file_size is an untrusted metadata field declared by the archive creator, a crafted .docx or .xlsx can declare a small file_size while actually decompressing to gigabytes during read, bypassing MAX_DOCX_XML_BYTES, _MAX_ZIP_ENTRY_BYTES, and _MAX_ZIP_TOTAL_BYTES.
	•	Recommended correction. Stream-read archive.open(info) in bounded chunks up to MAX_DOCX_XML_BYTES + 1 in extract_docx_text() and reject immediately if actual decompressed bytes exceed the cap. Apply the same bounded streaming check across all entries in _check_zip_bomb_safety() before passing the buffer to openpyxl.load_workbook(). Add regression tests with a crafted ZIP whose declared file_size underreports its decompressed length.
	•	Disposition. Safe to correct automatically.
M-2. Saving a profile on /transcribe clobbers an active background run's state
	•	Location. handlers/profiles.py (ProfilesHandlerMixin.save_profile).
	•	Evidence and impact. save_profile() acquires lock and unconditionally overwrites state["summary"], state["log"] = [message], and state["download"] = "" (both on success and in its except block) without checking state["running"]. Saving or updating a profile from /transcribe while a transcription or translation job is active wipes the live progress log and download reference.
	•	Recommended correction. Check state["running"] under lock. Either reject profile saves while a run is active (matching delete_prompt_builder_profile()) or avoid mutating state["summary"], state["log"], and state["download"] when state["running"] is True. Add a concurrency test covering a profile save while state["running"] is True.
	•	Disposition. Safe to correct automatically.
M-3. The CSRF cookie is emitted on rejected 400 and 403 security-error responses
	•	Location. app.py (Handler.end_headers, Handler._send_security_error).
	•	Evidence and impact. Handler.end_headers() unconditionally emits Set-Cookie: ct_token=...; Path=/; SameSite=Strict; HttpOnly on every response, including 400/403 rejections from _send_security_error(). While SameSite=Strict and HttpOnly prevent cross-site scripts from reading the token, rejected security-check responses should not mint or refresh request tokens.
	•	Recommended correction. Set a per-request flag (for example, self._suppress_csrf_cookie = True in _send_security_error()) and skip Set-Cookie in end_headers() when set, or emit Set-Cookie only on normal 200 responses. Verify in tests that 400/403 responses from _security_check() carry no Set-Cookie header.
	•	Disposition. Safe to correct automatically.
LOW
L-1. Non-constant-time CSRF comparison and mode enforcement on pre-existing secret files
	•	Location. app.py (Handler._security_check, load_request_token), profiles_store.py (migrate_saved_keys_file).
	•	Evidence and impact. _security_check() compares the cookie token with != rather than secrets.compare_digest(). In addition, load_request_token() and migrate_saved_keys_file() pass 0o600 to os.open(), which only sets permission bits when creating a new file; if request-token or USER_DATA_DIR / ".env" already exists with looser permissions (for example, after a backup restore or manual copy), appending or truncating leaves the broader mode unchanged on POSIX systems.
	•	Recommended correction. Use secrets.compare_digest(_cookie_token(...) or "", CSRF_TOKEN) in _security_check(). On POSIX, explicitly call os.chmod(path, 0o600) after writing or appending to request-token and USER_DATA_DIR / ".env".
	•	Disposition. Safe to correct automatically.
L-2. Unsanitized profile_id in Content-Disposition on profile export
	•	Location. profiles_store.py (export_profile_payload, _read_profile_file), handlers/profiles.py (export_prompt_builder_profile).
	•	Evidence and impact. export_profile_payload() constructs f"{profile_id}.tbprofile.json" directly from profile_id, which is then interpolated into Content-Disposition: attachment; filename="{filename}". Because _read_profile_file() reads profile_id = str(data.get("id") or path.stem) without validating it against _VALID_PROFILE_ID, a hand-edited JSON file in USER_PROFILES_DIR containing quotes or CR/LF in "id" could inject header characters.
	•	Recommended correction. Wrap profile_id with safe_filename(profile_id) when building the export filename, and validate profile_id with _validated_profile_id() inside _read_profile_file().
	•	Disposition. Safe to correct automatically.
L-3. Download endpoints do not assert USER_OUTPUTS_DIR confinement
	•	Location. handlers/transcribe_run.py (download), handlers/test_mode_run.py (test_download), handlers/transcribe_translate.py (download_translation_report).
	•	Evidence and impact. Each download handler reads a path string from in-memory run state (state["download"], test_state["runs"][run_id]["download"], state["report_download"]) and serves path.read_bytes() without verifying that the resolved path lies inside USER_OUTPUTS_DIR. Although these state values are currently populated only by server-side code, omitting the boundary check leaves no defense-in-depth guard against future regressions.
	•	Recommended correction. Verify path.resolve().is_relative_to(USER_OUTPUTS_DIR.resolve()) before reading and serving any download file, matching serve_static_asset() and delete_profile().
	•	Disposition. Safe to correct automatically.
L-4. Double-escaped error text and raw selector/attribute interpolation in frontend scripts
	•	Location. static/test-mode.js (runIndexCompare, renderIndexCompareMapping), static/prompt-builder.js (addSimpleRow, refreshPreflightExamplePicker, deleteSelectedProfile, importProfileFile, saveDraftBeforePreflight).
	•	Evidence and impact. In static/test-mode.js, runIndexCompare() assigns status.textContent = escapeHtml(error.message || "Comparison failed."), which double-escapes characters such as &, <, and > into literal HTML entities because .textContent already escapes text. In renderIndexCompareMapping(), rt.value is interpolated unescaped into <option value="...">. In static/prompt-builder.js, addSimpleRow() concatenates placeholder into an HTML attribute string, and several profile-list handlers interpolate profileId/id into querySelector('option[value="' + id + '"]') without CSS.escape(). |---|.textContent in runIndexCompare(). Build dynamic <option> and <input> elements with document.createElement() (or escape attribute values) and wrap selector values with CSS.escape().
	•	Disposition. Safe to correct automatically.
L-5. Read-only preflight endpoints use load_profile() fallback instead of exact lookup
	•	Location. app.py (/api/page-zoom-check, /api/offpeak-cost-estimate).
	•	Evidence and impact. Both GET endpoints resolve profile_id via load_profile(profile_id), which silently falls back to profiles[0] when profile_id does not match any existing profile. A stale or deleted profile_id from an open tab can therefore return page-zoom advice or off-peak estimates based on an unrelated profile's pageLayout.
	•	Recommended correction. Use load_profile_exact(profile_id) (catching lookup errors to fall back to page_layout = "") so an unknown ID never silently borrows another profile's layout.
	•	Disposition. Safe to correct automatically.
L-6. Uncaught UnicodeDecodeError in form parsing and oversized upload cap on profile import
	•	Location. http_utils.py (parse_post_form), handlers/profiles.py (import_prompt_builder_profile).
	•	Evidence and impact. parse_post_form() decodes the request body with .decode("utf-8") without catching UnicodeDecodeError (unlike parse_json_body(), which converts it into a clean RuntimeError). Separately, import_prompt_builder_profile() calls parse_multipart_form(), inheriting the 50 MB MAX_DOCX_BYTES ceiling for plain JSON profile imports.
	•	Recommended correction. Catch UnicodeDecodeError in parse_post_form() and raise a clear RuntimeError. Enforce a smaller size cap (for example, 1–2 MB) for JSON profile imports in import_prompt_builder_profile().
	•	Disposition. Safe to correct automatically.
INFORMATIONAL
I-1. Pin the macOS update command to the resolved release tag and verify redirect host
	•	Location. update_check.py (INSTALL_LINE, fetch_latest_tag, update_status).
	•	Why it matters. INSTALL_LINE currently points to https://raw.githubusercontent.com/weevie833/Customizable-Transcriber/main/install-mac.sh piped to bash, which tracks the mutable main branch rather than the immutable release tag update_status() already resolved. Separately, fetch_latest_tag() extracts the tag from the Location header without confirming the redirect host is github.com.
	•	Recommended correction. Build install_line from the validated release tag (https://raw.githubusercontent.com/{REPO}/{tag}/install-mac.sh) and verify urllib.parse.urlparse(location).netloc == "github.com" (or a relative path) in fetch_latest_tag().
	•	Disposition. Safe to correct automatically.
I-2. Unify API key validation and .env fallback behavior across handlers
	•	Location. handlers/transcribe_run.py (run_transcription), handlers/transcribe_offpeak.py (run_off_peak), handlers/xls_conversion.py (parse_xls_source, preflight_xls_source, detect_xls_languages).
	•	Why it matters. run_transcription() raises "Paste a Gemini API key before running transcription." even when a Claude model is selected, and neither /run nor /run-offpeak calls ensure_key_matches_model() synchronously before spawning its worker thread (unlike /api/translate-transcript/run and /test-mode/run). In handlers/xls_conversion.py, detect_xls_languages() falls back to .env when no key is pasted, whereas preflight_xls_source() and parse_xls_source() require a pasted key.
	•	Recommended correction. Use provider-neutral missing-key wording on /transcribe, run ensure_key_matches_model() up front in /run and /run-offpeak, and align .env fallback policy across all three XLS Conversion AI endpoints.
	•	Disposition. Safe to correct automatically.
I-3. Normalize do_POST route matching and -- separators on OS launcher commands
	•	Location. app.py (Handler.do_POST), launch.py (_MAC_LAUNCHER_SCRIPT), handlers/settings.py (open_folder_in_file_manager).
	•	Why it matters. do_POST mixes urllib.parse.urlparse(self.path).path (for /api/*) with raw self.path == ... comparisons (for /run, /stop, /reset, and /prompt-builder/*), so any trailing query string on those routes returns 404. In launch.py and handlers/settings.py, passing -- before the path argument to /usr/bin/open and xdg-open hardens against paths starting with -.
	•	Recommended correction. Parse path = urllib.parse.urlparse(self.path).path once at the top of do_POST, and add -- before path arguments in open/xdg-open invocations.
	•	Disposition. Safe to correct automatically.
I-4. Expand Ruff CI checks to include security and bugbear subsets
	•	Location. pyproject.toml.
	•	Why it matters. CI currently fails only on pyflakes (F) and syntax errors (E9). Adding Ruff's bugbear (B) and security (S) rule subsets—even initially as informational warnings or a narrow enforced subset (S102, S301, S602)—helps prevent future regressions automatically.
	•	Recommended correction. Add an explicit Ruff rule configuration in pyproject.toml or CI once any intentional exceptions are marked with targeted noqa comments.
	•	Disposition. Optional maintainability improvement.
Scope and verification
	•	Reviewed directly from source: app.py, app_state.py, http_utils.py, launch.py, profiles_store.py, run_support.py, update_check.py, requirements.txt, pyproject.toml, SECURITY.md, customizable_transcriber/core.py, customizable_transcriber/usage_ledger.py, all modules in handlers/ (settings.py, profiles.py, transcribe_run.py, transcribe_offpeak.py, transcribe_translate.py, xls_conversion.py, index_compare.py, test_mode_run.py), index_compare/reader.py, xls_conversion/spreadsheet_export.py, pages/__init__.py, and frontend scripts (static/test-mode.js, static/prompt-builder.js, static/app-common.js, plus targeted innerHTML/subprocess/os.system searches across the repository).
	•	Not read in full in this pass: batch_transcription.py, transcript_translation.py, xls_conversion/ai_parser.py, xls_conversion/app.js, pages/home.py, pages/privacy.py, pages/prompt_builder.py, pages/test_mode.py, pages/transcribe.py, customizable_transcriber/page_zoom.py, static/transcribe.js, static/transcribe-translate.js, static/i18n.js, .github/workflows/, and the macOS/Windows installer and launcher scripts (install-mac.sh, Start Customizable Transcriber (Mac).command, Start Customizable Transcriber (Windows).bat, mac/).
	•	Evidence boundaries: This was a static source-code review; tests, linters, dependency advisory scans, and live provider calls were not executed during this pass.

OVERALL STATUS: CHANGES_REQUIRED
