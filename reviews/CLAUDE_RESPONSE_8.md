# Response to Codex review 8

Reviewed against `reviews/CODEX_REVIEW_8.md` and `reviews/HUMAN_DECISIONS_8.md` (0.5.6, commit `79a7acc`). I checked every finding against the source before changing anything. Nothing has been committed or pushed.

**Validation for the whole set** (run after the last change):
- `.venv/bin/python -m pytest -q`: 634 passed, 1 skipped. The skip is the existing Windows-only bash test.
- `.venv/bin/ruff check . --select F,E9`: clean.
- `node --check` on every file in `static/*.js` and on `xls_conversion/app.js`: clean.
- `bash -n` on `mac/launcher.sh`, the Mac `.command` and `install-mac.sh`: clean.
- `python3 xls_conversion/tests/run_parser_test.py`: PASS.
- `.github/workflows/tests.yml` parses as YAML.
- Not run: real provider calls (no paid requests were made), the Windows installer, and the signed release workflow.

Summary:
- 26 findings RESOLVED.
- 0 DISAGREE.
- 0 HUMAN_DECISION_REQUIRED. The decisions taken with the maintainer were M-5 (Gemini part), M-10, M-11, M-15/HD-1, L-3/HD-2 and L-4.

---

## HIGH

### H-1. A restricted image range can send the entire transcript. RESOLVED
Confirmed. When a range matched no marker, `split_image_blocks` fell back to the whole document. Excluded Index markers were also dropped before boundaries were computed, so an excluded page's text leaked into the block before it.
- **Changes** (`xls_conversion/ai_parser.py`):
  - `collect_image_markers` now keeps Index markers and flags them `excluded`. They still act as block boundaries, but they are never selected.
  - `split_image_blocks` returns the whole document only for an explicit whole-document request on a document with no markers.
  - A range that matches nothing, or a range applied to an unmarked document, raises an actionable error before any API call.
- **Tests:** `tests/test_image_block_selection.py` checks:
  - the exact outbound text for a missing range;
  - an excluded page between two records;
  - an unmarked document, with and without whole-document mode.

### H-2. A confirmed run can upload another tab's source folder. RESOLVED
Confirmed. The handlers re-read the shared `app_settings.json` folder at submit time.
- **Changes:**
  - `pages/transcribe.py` and `pages/test_mode.py` now carry the displayed folder in a hidden `source_folder` field. `static/app-common.js` keeps that field in sync when the user picks a folder.
  - `run_support.bind_source_folder()` rejects a submission whose folder no longer matches the saved one ("The source folder changed after this page was loaded…"). It then pins the resolved folder on the form.
  - `run_job`, `run_test_job`, `run_off_peak_job` and `run_test_off_peak_job` use that pinned value through `resolved_source_folder()`. The handlers involved are `handlers/transcribe_run.py`, `transcribe_offpeak.py` and `test_mode_run.py`.
- **Note:** the worker still loads the profile by id. That lookup is now exact (see M-13), so a missing profile fails rather than being substituted.
- **Tests:** `tests/test_source_folder_binding.py` covers the two-tab case for real-time, off-peak and Test Mode runs.

### H-3. A period in the filename can make translation overwrite a transcript. RESOLVED
Confirmed. `with_suffix` replaced everything after the last period in a name such as `Nati.1823`.
- **Changes** (`transcript_translation.py`):
  - `output_paths` appends the extension to the full basename.
  - `_reserve_output` creates the destination exclusively, adding `-2`, `-3` and so on, so an existing file is never overwritten.
  - `_publish` writes through a temp file and `os.replace`. If the write fails, it removes its own empty placeholder.
- **Tests:** `tests/test_transcript_translation.py` covers dotted names, a repeated translation, and pre-existing sentinel outputs. The sentinels are unchanged after both runs.

### H-4. Duplicate record headings assign one translation to two entries. RESOLVED
Confirmed. Entry ids were built from the record name and position, so two records named `Nati_002.jpg` collided.
- **Changes** (`transcript_translation.py`):
  - `Entry.record_index` holds the record's position in the document. Ids now have the form `"<record_index>/<record>#<position>"`, while labels still show the record name.
  - Chunks split on `record_index`.
  - A response that contains an id more than once is rejected.
- **Tests:** duplicate headings in the same chunk and in different chunks, plus a duplicate response id. Existing tests were updated to the new id format.

### H-5. Empty or truncated output can count as a successful page. RESOLVED
Confirmed for both providers, in real-time and batch modes.
- **Real-time** (`customizable_transcriber/core.py`): blank Claude text now raises. A token-limited response keeps its partial text and gets a fixed `TRUNCATION_MARKER` notice appended.
- **Batch** (`batch_transcription.py`): blank output is recorded as an item error. Max-tokens output keeps its text with the same notice appended.
- **Summaries:** run summaries now count incomplete pages (`count_incomplete`, `incomplete_summary_suffix`). The counting is in `run_support.py` and `batch_transcription.py`.
- No extra paid requests are made.
- **Tests:** `tests/test_incomplete_provider_output.py` covers blank, blocked and token-limited responses for each adapter.

## MEDIUM

### M-1. A recognizably wrong provider key is sent before the mistake is detected. RESOLVED
- **Changes:**
  - `core.key_provider_mismatch()` and `ensure_key_matches_model()` check the key's shape against the selected model. A Claude key starts with `sk-ant-`.
  - The check runs in `make_client` and before every provider client is built: the XLS AI calls and cache clients, the translation run and preflight, and off-peak submission.
- The check is local, so a wrong key is never sent to the other provider.
- **Tests:** `tests/test_key_provider_mismatch.py`. Test fixtures that used fake Claude keys now use the `sk-ant-` prefix.

### M-2. Raw exception text reaches the ledger and exported transcripts. RESOLVED
- **Changes:**
  - `core.safe_error_summary()` reduces an exception to its class name and HTTP status for usage-ledger events.
  - `humanize_provider_error(..., include_original=False)` gives a generic sentence for provider SDK errors. It is used for the `ERROR` lines in transcripts and for translation failure reasons.
  - Batch item errors write a fixed sentence to the document and the ledger (`safe_batch_item_error`). The raw text goes only to the live Progress Console, where it is useful to the operator.
- **Tests:** `tests/test_error_text_sanitization.py`.

### M-3. A second off-peak job erases the first job's recovery record. RESOLVED
Confirmed. Transcribe kept a single record. Test Mode keyed records by run id, so a reused run id replaced the earlier record.
- **Changes** (`app_state.py`):
  - `OFF_PEAK_JOB_FILE` now holds `{"format": "off-peak-jobs-v2", "jobs": {record_key: fields}}`.
  - An old single-record file is read as one entry, so no separate migration is needed and nothing is lost. The next write converts it.
  - `write_off_peak_job_state()` adds or updates only its own entry. `clear_off_peak_job_state(record_key)` removes only that entry. Reset All (`record_key=None`) remains the explicit dismissal and clears everything.
  - An unreadable file is renamed `off_peak_job.unreadable-<timestamp>.json` and logged, rather than overwritten. A single-job clear leaves an unreadable file alone. The Test Mode file follows the same rules.
  - At startup, every outstanding job is listed.
- **Sinks** (`batch_transcription.py`): each sink gets a record key unique to its job (a uuid; for Test Mode, `<run_id>#<uuid8>`).
- **Deviation from the recommendation:** records are keyed by a per-job key, not by provider job id. A record is first written before submission, when there is no provider id yet. The provider and job id are still fields in each record.
- `read_off_peak_job_state()` still returns the most recent record, so existing callers are unchanged.
- **Tests:** `tests/test_offpeak_recovery_records.py` covers:
  - two successive jobs where the second resolves;
  - a restart with two outstanding jobs;
  - a legacy-format file;
  - unreadable files for both modes;
  - a reused Test Mode run id.
  `tests/test_test_mode_offpeak.py` was updated for the new key.

### M-4. Reset, Stop and queue edits can race with a run reservation. RESOLVED
- **Changes:**
  - `reset_ui_state()` and `reset_test_ui_state()` now do the idle check, the stop-flag clear, the reset and the persistent cleanup under a single lock acquisition. They return whether they reset anything.
  - Run handlers clear the stop flag when they reserve a run. A Stop that arrives during setup releases the slot ("Stopped before … started.") instead of being lost. The translation run returns 409 in that case.
  - Queue add and remove check `running` and change the queue under the same lock.
- **Tests:** `tests/test_run_reservation_races.py`.

### M-5. Off-peak preflight can accept batches larger than the provider allows. RESOLVED (Claude: size check added; Gemini: kept as is after a real test, by the maintainer's decision)
- **Claude:** `batch_transcription.estimated_claude_batch_bytes()` estimates the request size: base64 images, including zoom crops, plus the repeated prompt and request framing. `check_claude_batch_envelope()` rejects anything over 250 MB, under Anthropic's 256 MB limit, before upload. The message explains how to split the batch.
  - **Tests:** `tests/test_offpeak_envelope.py`.
- **Gemini:** the review cites Google's guidance that inline batches should stay under 20 MB. Enforcing that would refuse nearly every real register. On 2026-11-22 the maintainer ran a real check:
  - **Run:** a Gemini 3.1 Pro off-peak batch of 10 Lappano PNGs (26.4 MB raw, about 35 MB encoded with prompts), job `batches/k0zmucb6…`.
  - **Result:** Google accepted it, and all 10 images came back `STOP` with no failures in 514 s (usage ledger `20261122-183749-905b15`).

  The 20 MB figure is therefore guidance, not an enforced limit, at least at that size. By the maintainer's decision the existing local cap stays (500 MB raw, 250 MB with Page zoom). A larger batch that Google does reject fails at submission with a reported error and nothing billed.

  Moving the Gemini adapter to Google's file-based batch input is recorded as an optional future improvement, not part of this round.

### M-6. Test Mode scores document metadata as transcription errors. RESOLVED
- **Change:** `test_mode/comparison.py` adds `strip_app_metadata()`, which removes the header box and preamble before the first `START OF RECORD`. It runs inside `strip_non_transcription_blocks()`, so both sides of the comparison are stripped the same way.
- **Tests:** `tests/test_comparison_metadata_strip.py`.

### M-7. Workbook comparison has no bound on matching work. RESOLVED
- **Change** (`index_compare/align.py`):
  - Identity keys are computed once, and candidates are bucketed by year.
  - A `_PairBudget` of `MAX_IDENTITY_PAIR_VISITS = 5_000_000` is charged before each comparison. Going over it raises `AlignmentTooLargeError` with a clear message instead of running without limit.
  - Normal-sized indexes are unaffected.
- **Tests:** `tests/test_index_compare_align.py` covers the budget and the unchanged pairing results.

### M-8. The page-zoom preview reads unchecked files and can enlarge its thumbnail. RESOLVED
- **Changes:**
  - `run_support.page_zoom_advice()` validates each file with the batch file check before analysing it.
  - `customizable_transcriber/page_zoom.py` never upscales and checks the header dimensions first. It rejects images over 120 MP or with an aspect ratio above 3:1, then draft-decodes to at least the profile width.
- **Regression check:** I compared old and new results on 300 real register photos. 299 were identical, and the one difference is a photo that is now draft-decoded at a slightly different size.
- **Tests:** `tests/test_page_zoom.py`.

### M-9. The DOCX declaration check depends on the XML byte encoding. RESOLVED
- **Change:** `http_utils._reject_xml_declarations` now parses with expat, using DOCTYPE, entity and notation handlers that raise. This catches declarations in UTF-16 and other encodings, which the old byte search missed.
- **Tests:** `tests/test_docx_security.py` adds UTF-16 and BOM cases.

### M-10. The macOS release workflow can publish without notarization. RESOLVED (approved by the maintainer)
Confirmed. With an empty notary secret, `mac/build.sh` quietly took its local path, and the tag job would then upload an unnotarized disk image.
- `mac/build.sh`: a new `CT_RELEASE=1` mode refuses to build when any of these is missing or empty, and names what is missing:
  - `CT_SIGN_IDENTITY`;
  - `NOTARY_KEY_ID`;
  - `NOTARY_ISSUER_ID`;
  - a `NOTARY_KEY_PATH` file containing a private key. The workflow writes this file even when the secret is empty, so its contents are checked.

  Local builds, where the variable is unset, are unchanged.
- `.github/workflows/mac-release.yml`:
  - the build step sets `CT_RELEASE: "1"`;
  - a new "Verify the disk image is notarized and stapled" step runs before artifact upload and the release attach. It runs `stapler validate` and `spctl` on the disk image, then mounts it and runs `stapler validate`, `spctl` and `codesign --verify --strict --deep` on the app inside.
- Validation:
  - `bash -n` passes and the workflow parses as YAML.
  - Locally, `CT_RELEASE=1` with no inputs, and with a key file that is not a .p8, both stop with the expected message.
  - The default local build still produces the app and the disk image.
- Not yet run on GitHub. A manual `workflow_dispatch` run (no tag, so nothing is published) will confirm the new verify step.

### M-11. A package-only installer update destroys the working venv first. RESOLVED (approved by the maintainer)
Confirmed in both installers. When the lockfile changes but Python doesn't, `venv --clear` ran on the live environment, and there was no backup to restore if the install failed.
- `Start Customizable Transcriber (Mac).command`:
  - Before a package-only reinstall, the working `venv` is moved to `venv-old`, and a flag records that a backup exists.
  - After `pip install`, an import check runs (`google.genai, anthropic, openpyxl, rapidfuzz, PIL, cryptography, certifi`). The `installed-requirements.txt` and `python-build.txt` markers are written only after it passes.
  - On any failure, `restore_previous` moves `venv-old` back to the exact path it came from, so the paths baked into the venv stay valid. Python-upgrade rollback is unchanged.
- `Start Customizable Transcriber (Windows).bat`: the same logic, as a new `:backup_venv` step and a venv-only branch in `:restore_previous`.
  - If the old venv can't be moved because the app is running, it stops at the existing "in use" message and changes nothing.
  - The file stays CRLF.
- `install-mac.sh` needs no change. When setup fails it restores the previous app folder, and the runtime it points to is now intact.
- `.github/workflows/tests.yml`: the `windows-install` and `mac-install` jobs gain a "failed package-only update" step. It appends an unknown package to the lock, expects the installer to fail, and then checks three things:
  - the old venv still imports;
  - no `venv-old` is left;
  - the installed-packages marker is unchanged.
- Validation on this Mac, against a real install in a temporary `CT_RUNTIME_DIR`, with real Python and PyPI downloads:
  - fresh install;
  - a pip failure, where the old venv was restored and the marker unchanged;
  - an install that passed pip but failed the import check (pillow removed), where the old venv was restored;
  - a valid lock change, where the new venv was installed and the marker updated;
  - an unchanged lock, which skipped setup.

  `bash -n`, `tests/test_launcher.py` and YAML parsing also pass.
- Windows: not run here. It will be checked by the next scheduled or manual `windows-install` CI run, which installs and tests without releasing anything.

### M-12. A quoted worksheet title produces an unreadable XLSX. RESOLVED
- **Change:** `xls_conversion/spreadsheet_export.py` now writes the sheet-name attribute with `quoteattr`.
- **Tests:** `tests/test_sheet_name_sanitization.py` round-trips titles containing double quotes, ampersands and non-ASCII text through openpyxl.

### M-13. A saved profile can disappear and another can be selected in its place. RESOLVED
- **Changes** (`profiles_store.py`):
  - `RESERVED_PROFILE_IDS = {"settings"}`. A profile named "Settings" now gets the id `settings-profile`.
  - The loader skips `settings.json` only when it has no profile fields, so an existing genuine profile with that name is recovered.
  - The new `load_profile_exact()` is used by the run handlers, and `run_support.selected_profile_id()` / `resolve_profile_for_run()` now require an exact match. The fallback in `load_profile()` remains for page rendering only.
- **Tests:** `tests/test_profile_reserved_ids.py` covers save, list and load consistency, plus a stale or corrupt selected profile.

### M-14. The checkout's environment has dependencies with known advisories. RESOLVED
- **Confirmed.** 14 packages in `.venv` were older than `requirements.lock`, all lower versions with no downgrades needed, and they included `certifi 2026.7.22` and `pyasn1 0.6.4`.
- **Change:** ran `pip install -r requirements.lock` in `.venv`. `pip-audit -r requirements.lock` reports no known vulnerabilities.
- The environment-wide `pip-audit` then flagged only pip-audit's own tooling dependencies: `filelock` 3.32.6 and `msgpack` 1.2.2. Neither is a runtime dependency or in any requirements file. I upgraded them to `filelock>=4.2.1` and `msgpack>=1.2.3`. `pip check` is clean, and the full environment audit is clean.
- No repository files changed for this finding.
- The server on port 8765, if it is running, should be restarted to pick up the updated packages.

### M-15. Unrelated rows with missing locators can be reported as a match. RESOLVED (HD-1: maintainer chose the recommended rule plus disclosure)
Confirmed. Rows with no locator shared a single bucket, and pairing by order paired whatever identity matching left over, even rows from different people and years.
- `index_compare/align.py`:
  - `_match_within_bucket()` takes a new `allow_positional` argument. `align_rows()` turns it off for the no-locator `""` bucket. Those rows now pair by name (and year) only, and anything left over counts as missing or extra.
  - Order-based pairing within a real page or act bucket is kept. That is what lets a badly misread name still be compared with the right entry on the same page.
  - Such pairs are counted in the new `AlignmentResult.position_only_pairs`.
- `index_compare/scoring.py` exposes `position_only_pairs` for each candidate.
- `index_compare/report_docx.py`:
  - the rows table gains a "Matched by order only" column;
  - a sentence under the table explains that rule and the no-locator rule.

  The report is the only place these counts appear; the page shows none of them.
- Tests:
  - `tests/test_index_compare_align.py` covers the Codex counterexample (Rossi 1800 vs Smith 1900 is no longer paired), shifted rows without locators (still paired by name), and a kept-and-counted same-page order pair.
  - `tests/test_index_compare_report.py` checks the new column and the explanation.
  - All Index Compare suites pass (50 tests).

## LOW

### L-1. The launchers can open an unrelated local service. RESOLVED
- **Changes:**
  - `app.py` adds `GET /api/health`, which returns `{"app": "customizable-transcriber", ...}`.
  - `launch.py` replaces `server_is_up` with `probe_server()`, which returns ours, other or none and does not follow redirects. When another service holds the port, the launcher exits with a port-conflict message instead of opening it.
  - `mac/launcher.sh` checks the app id the same way.
- **Tests:** `tests/test_health_endpoint.py` and `tests/test_launcher.py`. `bash -n` passes.

### L-2. Valid JSON of the wrong shape breaks the settings page. RESOLVED
- **Change:** `app_state._read_settings()` returns None unless the file is a JSON object. It also handles decode errors. Load, save and clear all go through it, so Reset All still works with a malformed file.
- **Tests:** `tests/test_app_state_sandboxing.py`.

### L-3. Downloadable transcripts include the absolute source path. RESOLVED (HD-2: maintainer chose folder name only)
Confirmed. Both writers put the full local path in the transcript header, and from there it reaches the Word document. Nothing in the app reads that line back; Test Mode's metadata strip matches it by its label only.
- `customizable_transcriber/core.py` (`run_batch`) and `batch_transcription.py` (`run_off_peak_job`) now write `Source folder: <folder name>`.
- The full path goes to the Progress Console instead:
  - real time: "Found N source file(s) in <path>.";
  - off-peak: a timestamped "Source folder: <path>" line.
- Each record still names its image file, so a transcript can still be traced to its images.
- No opt-in to include the full path, by the maintainer's choice.
- Tests:
  - `tests/test_source_folder_header.py` runs a real-time batch with a fake client. The header shows only the folder name, the parent folders never appear in the transcript, and the full path is logged.
  - `tests/test_offpeak_batch.py` asserts the same for the off-peak path.

### L-4. Replacing the app folder can discard saved credentials. RESOLVED (approved by the maintainer: user-data folder)
Confirmed. The optional `.env` sat in the app folder, which the Mac update paths replace and then delete.
- `customizable_transcriber/core.py`:
  - `saved_keys_files()` looks in `USER_DATA_DIR/.env` first (Application Support, AppData or XDG), then in the app folder's `.env`.
  - `api_key()` and `claude_api_key()` load both. The first value wins per key, and an exported environment variable still beats both files (`load_env_file()` never overwrites).
  - The opt-in policy is unchanged: only the single-image tools read saved keys.
- `profiles_store.migrate_saved_keys_file()`, called from `app.py` `main()` at startup:
  - copies an app-folder `.env` to `USER_DATA_DIR/.env` once, created with `O_EXCL` and mode 0600;
  - never overwrites an existing file, never deletes the original, never logs the contents.
- `install-mac.sh` and `mac/launcher.sh`: a `keep_saved_keys` helper runs before the installed copy is moved aside. It copies its `.env` to the data folder under `umask 077`, without overwriting, and prints only a note if the copy fails. `CT_DATA_DIR` overrides the location for tests.
- Windows updates are a manual folder replacement. The startup copy covers anyone who runs the new version once before deleting the old folder, and the README now tells new users to create the file in `%APPDATA%` from the start.
- Docs:
  - README setup step 5 now creates the file in the data folder with owner-only permissions on macOS and Linux;
  - `PRIVACY.md` describes the new location and the one automatic copy;
  - `PRIVACY.it.md` gained the matching paragraph. It had never mentioned the optional `.env` and still said keys are never written to a file.
- This checkout's `.env` was changed to mode 0600, at the maintainer's request.
- Tests: `tests/test_saved_keys_location.py` covers read order and per-key fallback, an exported variable winning, the one-time owner-only startup copy (never overwriting), and both Mac scripts' helper run under real bash (copy, mode 0600, no overwrite, called before replacement).

### L-5. XLS preflight approval omits inputs that change the extraction. RESOLVED
- **Changes** (`handlers/xls_conversion.py`):
  - The cached preflight approval now includes the normalized `target_role`. Changing the role after preflight requires a new preflight.
  - The UI never sends `image_overrides`, so conversion now refuses a non-empty value instead of silently using an unchecked marker mapping.
- **Tests:** `tests/test_xls_preflight_binding.py`.

## INFORMATIONAL

### I-1. The offline JavaScript regression job covers a retired parser. RESOLVED
- **Changes:**
  - In `.github/workflows/tests.yml`, the step is renamed "Legacy regex-parser fixture check (xls_conversion/tests/, not live extraction)", with a comment explaining what it covers.
  - `xls_conversion/README.md` now states that the suite is a legacy-fixture check and points to the Python suite under `tests/` for live-path regressions (for example `test_image_block_selection.py` and `test_continuation_fragment_split.py`).
- The reference files are kept.

---

STATUS: READY_FOR_REVIEW
