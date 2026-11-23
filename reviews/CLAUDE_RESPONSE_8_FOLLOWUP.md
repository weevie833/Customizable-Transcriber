# Response to CODEX_REVIEW_2.md (follow-up to review 8)

Checkpoint: 79a7acc, plus the uncommitted review-8 repairs, which this pass keeps. Nothing is committed or pushed. CODEX_REVIEW_2.md stays at the repository root as supplied and is unchanged. `.gitattributes` now export-ignores `/CODEX_REVIEW*.md`, so the file can't reach the download ZIP if it is ever committed.

The 13 items the review verified are unchanged: H-2, H-3, H-4, M-1, M-5 (Gemini batch policy), M-6, M-8, M-9, M-10, M-12, L-2, L-3 (folder-name-only headers) and I-1. H-3's output publishing was rebuilt for N-1/N-2. Its no-overwrite and whole-stem guarantees are kept and still tested.

## Decisions taken (M-15 / HD-1)

- **Q1.** A lone given name with no surname and no year is **not** identity evidence. Answer: "No (Recommended)".
- **Q2.** Counts go on the **completion screen and in the report**. Order-only matches are labelled as a subset of Matched. Answer: "Both places (Recommended)".

## Disposition

| Item | Disposition | Verification |
|---|---|---|
| H-1 | Fixed | 15 tests |
| H-5 | Fixed | 9 tests |
| M-2 | Fixed | 7 tests |
| M-3 | Fixed (the earlier explanation is corrected below) | 9 tests |
| M-4 | Fixed | 4 tests, plus 5 updated |
| M-7 | Fixed | test |
| M-11 | Fixed. The Mac script is tested for real; Windows is checked in source and by a new CI step | 4 tests plus CI steps |
| M-13 | Fixed | 4 tests |
| M-14 | Fixed for supported configurations. Intel Mac is flagged | 2 tests plus a lock resolve check |
| M-15 | Implemented as decided | 6 tests plus a browser check |
| L-1 | Fixed | 10 cases |
| L-4 | Fixed | 4 tests |
| L-5 | Fixed | 9 tests |
| N-1 | Fixed | 7 tests |
| N-2 | Fixed | 2 tests |
| N-3 | Fixed. Also fixes a double save | 3 tests |

### H-1: restricted XLS requests could include an unselected record

- `collect_image_markers()` (`xls_conversion/ai_parser.py`) now finds every `START OF RECORD:` heading first, then reads the image number out of it.
- A heading with no readable number is kept as a boundary but marked excluded. So is an Index heading.
- So neither one can merge into the record before it.
- `split_image_blocks()` refuses a blank range unless Process all is on, and takes only the requested numbers.
- Tests are in `tests/test_image_block_selection.py`. They go through split, requested-number detection, preflight and parse, with mocked providers. They cover:
  - unnumbered headings;
  - a heading with text before the number;
  - the Index heading;
  - a blank range;
  - Process all.

### H-5: text returned with an incomplete terminal status counted as a complete page

- New leaf module `customizable_transcriber/stop_reasons.py`. One table per provider maps every stop reason to complete, truncated, incomplete or blocked:
  - Claude: `end_turn` and `stop_sequence` are complete, `max_tokens` is truncated, `refusal` is blocked, and anything else is incomplete.
  - Gemini: `STOP` is complete, `MAX_TOKENS` is truncated, the safety and recitation family is blocked, and anything else, including no reason at all, is incomplete.
- These paths all go through `stop_reasons.finish()`:
  - real-time Gemini and Claude (`core.py`);
  - both batch collectors (`batch_transcription.py`);
  - the ledger (`usage_ledger.record_call` now writes an `outcome` field).
- Incomplete text is kept with an `[INCOMPLETE: ... stop reason ...]` notice and counted in the run summary ("N incomplete"). Blocked or empty replies fail the page.
- Tests are in `tests/test_incomplete_provider_output.py`:
  - each provider and each outcome, real-time and batch;
  - the document notice;
  - the summary count;
  - the ledger outcome.
- The fake used in `tests/test_batch_file_content_sniffing.py` now returns `STOP`.

### M-2: provider text in persistent errors

- Batch item errors are now typed (`ItemError`, in `batch_transcription.py`). Only errors the app wrote itself are shown as written. A raw provider message is replaced by the generic sentence, even one that starts with a friendly prefix like "Request was". The full detail goes to the live Progress Console only.
- In durable mode, `humanize_provider_error()` (`core.py`) changed:
  - It returns the exception text only for a `SafeMessageError`, which the app raises for its own fixed messages.
  - For SDK errors it gives a summary.
  - For anything else it says "An unexpected error stopped this image (TypeName)...".
- Tests are in `tests/test_error_text_sanitization.py`. They check the transcript document and the ledger record, using a provider message with a friendly prefix and a local path.

### M-3: a partly unreadable recovery file lost records

`app_state.py` now reads the raw map, keeps every entry including malformed ones, and rewrites from it:

- on save and on single-job clear;
- for Transcribe and for Test Mode.

Valid sibling entries are still used. A file that isn't a JSON object is set aside under a timestamp plus uuid name before rewriting. Startup surfacing reports how many entries couldn't be read.

Tests are in `tests/test_offpeak_recovery_records.py`. They cover:

- mixed valid and invalid entries surviving a save, a clear and a restart;
- setting aside a non-object file;
- a set-aside name that never collides.

**Correction to reviews/CLAUDE_RESPONSE_8.md.** That response implied the job record is written before the provider returns a job id. That is wrong. The first write happens after `create` returns the id (`batch_transcription.py`, in `_validate_and_submit`). An outcome-unknown timeout is still reported as "check the dashboard before retrying", as decided in review 5. No persisted record exists for that window.

### M-4: an acknowledged Stop could precede a billable submission

- `submit_gemini_batch()` and `submit_claude_batch()` take `should_stop` and `before_send` callbacks. They check Stop at these points:
  - on entry;
  - before each image is prepared;
  - one last time right before `create`.
- `before_send` is the sink's `begin_submission()`. Under the state lock, it either refuses because Stop is set, or marks the job as submitting. Both Transcribe and Test Mode sinks have it; Test Mode counts concurrent runs.
- A stop before sending ends with "Stopped before this off-peak batch was submitted." This works with or without Test Mode's submit lock.
- Stop pressed while sending now says the batch will be cancelled once the provider confirms it. The existing reconciliation path runs as before.
- Tests:
  - `tests/test_offpeak_stop_before_submit.py` stops between preparation and the mocked provider call, for both providers and both modes, and on entry.
  - In `tests/test_offpeak_batch.py`, five cancellation tests used to set Stop before submission. They now set it right after the mocked submission, which the new rule requires.

### M-7: computing the comparison budget was itself quadratic

`_score_identity_pairs()` (`index_compare/align.py`) changed:

- It charges the budget per truth row, using integer group sizes.
- It stops at the first row that would go over.
- It walks the candidate groups without building concatenated lists.

`test_budget_rejection_does_no_list_copies_or_comparisons` checks that a rejected budget makes no comparison calls and no list copies.

### M-11: a retry after an interrupted update could destroy the last working environment

Both start scripts now write `Runtime/update-pending.txt`, containing `python` or `venv`, before touching anything. On the next start, an outstanding marker is recovered first: the backup is restored, including the old build marker for a Python update. This happens before the up-to-date check and before any backup is rotated. Backups are removed only after:

- the import check passed;
- every marker write succeeded;
- the pending marker was removed.

Tests and checks:

- **Mac:** `tests/test_installer_interrupted_update.py` runs the real `.command` with a stub interpreter. It covers an interrupted update followed by a failed retry and by a successful retry, for both venv and Python updates.
- **Windows:** the `.bat` carries the same logic, with CRLF kept. It was inspected in source only. New interrupted-update steps in the `windows-install` and `mac-install` CI jobs run a failed retry, then a successful one. They haven't run on GitHub yet; those jobs only run weekly, on manual dispatch or on a tag.

### M-13: a corrupt user override silently selected the shipped profile

- `profiles_store.load_profile_exact()` validates the highest-priority file for the id directly. A damaged user copy now raises "...your saved copy is damaged..." instead of falling through to the shipped profile.
- `load_custom_profiles()` drops the shipped entry when its user override is damaged.
- Invalid UTF-8 is caught per file (`ProfileFileError`), so one bad file can't break the listing.
- Tests: `tests/test_profile_override_integrity.py`. The assertion in `tests/test_profile_reserved_ids.py` was updated.

### M-14: manual setup didn't use the tested lock

- README manual setup and Updating now use `pip install -r requirements.lock`, with a line on why.
- `requirements-dev.txt` now starts with `-r requirements.lock`.
- `test_setup_instructions_install_the_tested_lock` (`tests/test_launcher.py`) keeps the README's install commands pointed at the lock.
- The lock was resolved with binaries only (`pip install --dry-run --only-binary=:all:`) for Python 3.11 and 3.12 on Linux x86_64, macOS arm64 and Windows amd64.

**Flagged, not changed: Intel Macs.** cryptography 50.0.1 ships no Intel-Mac wheel. This was already true of `requirements.txt` before this pass, so manual setup there means a source build of cryptography. Whether to keep offering manual setup on Intel Macs is a support-policy decision.

### M-15: weak identity evidence and on-screen disclosure

Matcher changes, in `index_compare/align.py`:

- An unlocated pair now needs corroboration: both rows must have a surname, or both a year.
- This applies to the unlocated bucket and to the final identity pass.
- Located same-page given-name pairs and order-only pairs work as before.

Screen and report:

- Test Mode shows a counts table after Compare Indexes runs (`#ic-summary`, `static/test-mode.js` `renderIndexCompareSummary()`, Italian strings in `i18n.js`). Its columns are Candidate, Matched, "Matched by order only (part of Matched)", Missing, and Extra.
- The DOCX uses the same header, and says a shared given name alone is not enough.

Tests and checks:

- New tests in `tests/test_index_compare_align.py` (the "Paolo" case and its variants) and `tests/test_index_compare_report.py`.
- Three older align tests relied on given-name-only matching; they now supply surnames.
- In the browser, a real server result for a synthetic matrimoni pair rendered as Matched 2 / order-only 1 / Missing 1 / Extra 1, with no console errors.

### L-1: the Mac launcher's identity check was weaker than Python's

`health_is_ours` in `mac/launcher.sh` now requires all of these:

- HTTP 200 with redirects off;
- a response of 4 KB or less;
- a JSON object whose top-level `app` (read with `plutil`) is `customizable-transcriber`.

Ten launcher cases in `tests/test_launcher.py` (`test_signed_app_launcher_identity_check`) cover:

- a redirect;
- 404 and 500;
- the wrong app;
- a nested `app` key;
- a non-JSON body;
- an oversized body;
- the real app.

### L-4: replacing the app folder could discard a saved key

All three migration paths now merge per key, and never overwrite a key the user-data `.env` already has:

- `profiles_store.migrate_saved_keys_file`;
- the `keep_saved_keys` helper in `install-mac.sh` and `mac/launcher.sh`.

If the copy fails, the signed app keeps the installed copy and stops with a message. Tests are in `tests/test_saved_keys_location.py`. They cover split keys, a failed copy, and an end-to-end launcher run.

### L-5: preflight and extraction read the role differently

- `canonical_target_role()` (`ai_parser.py`) lowercases and strips the role. Anything other than `transcription` or `translation` is refused.
- It is applied at the request boundary in `handlers/xls_conversion.py`:
  - on parse and preflight;
  - on the approval cache save and its check.
- `parse_records_with_ai` and `preflight_records_with_ai` apply it too.
- A blank role, which used to be read as translation, is now refused. The page always sends one.
- New tests in `tests/test_xls_preflight_binding.py`:
  - case variants are canonicalized;
  - unknown roles are refused;
  - an approval for `transcription` with a conversion sent as `Transcription` extracts with the transcription instruction, over HTTP;
  - an unknown role is refused before any key check or provider call.
- Three older tests in `tests/test_xls_conversion_preflight_key_check.py` sent no role. They now send `translation`.

### N-1: a failed publication left empty final documents

`transcript_translation.publish_outputs()` replaces the reserve-three-placeholders approach.

- **Staging.** Every output is written in full under a short temp name in the outputs folder.
- **Publishing.** Each output is published with `os.link`, which fails if the name already exists, so nothing is ever replaced. Where links aren't supported, it creates an exclusive placeholder and then runs `os.replace`; the placeholder is removed if the replace fails.
- **Name taken.** A name taken during publishing moves the whole set to the next `-N` suffix.
- **Any other failure.** Everything this call created is removed: temps and already-published finals.
- The three outputs now always share one suffix.

Tests are in `tests/test_transcript_translation.py`, through `run_translation_job` with mocked providers. They inject failures at:

- the Markdown write;
- the DOCX write;
- the report build;
- the report write;
- the third publish.

Each case leaves no files and no download link. Separate tests cover a race on a taken name and the no-hard-link fallback.

### N-2: long names failed only after paid processing

- `plan_output_names()` runs before the API-key check and the translation requests.
- It cuts the stem so the longest output name fits the folder's name limit (`PC_NAME_MAX`, at most 255). On Windows it also fits the 260-character path limit.
- Temp names are 20 characters, whatever the final name.
- An outputs path too long to hold any name fails up front.
- Tests:
  - A 200-character stem exports, with all three names at 255 bytes or less.
  - A folder too long to hold any name fails with no provider call and no files.

### N-3: the approved profile could change before the worker used it

- `run_job`, `run_test_job` and `run_test_off_peak_job` take the profile the handler validated. The Transcribe and Test Mode handlers pass a deep copy. Workers use `approved_profile()` and resolve from the form only when called without one.
- This also fixes a double save. Test Mode's worker re-resolved the form, so a run that created a new profile saved it twice, the second time as `-2`.
- Tests are in `tests/test_profile_snapshot.py`. The handler's thread start is replaced so the saved profile is edited after Run is accepted, before the worker starts. The tests then check:
  - Transcribe sends the approved prompt;
  - Test Mode sends the approved prompt to both runs;
  - a created profile is saved once.
- All three fail with the fix disabled.

## Verification (Python 3.12.0, macOS arm64)

- Full pytest: **715 passed, 1 skipped**. The skip creates a real Windows desktop shortcut.
- Ruff CI gate (`ruff check . --select F,E9`): passed. The full advisory Ruff count is 106. Most of it is pre-existing, mainly blind-except and the deliberate `noqa` re-exports in `app.py`.
- `bash -n` passed on the Mac `.command`, `install-mac.sh`, `mac/launcher.sh` and `mac/build.sh`.
- `node --check` passed on all `static/*.js` and `xls_conversion/app.js`.
- Both workflows parse as YAML.
- `python3 xls_conversion/tests/run_parser_test.py`: PASS.
- Export: a `git archive` of the working tree has 90 files. It includes `customizable_transcriber/stop_reasons.py` and excludes `reviews/` and the root review file.
- Server restarted on 8765. The Index Compare counts table was checked in the browser.

## Checked in source only

- The Windows `.bat` installer logic (M-11) and its new CI steps. None of the installer CI steps (both platforms) have run on GitHub yet.
- Intel Mac manual setup (M-14 flag).
- Real Developer ID signing and notarization of `mac/launcher.sh` changes (L-1, L-4). They are in the app only after a tagged release build.
- The H-5 classification against live provider replies. It was tested with fakes for each documented stop reason.

## Still open

- Intel Mac manual-setup support policy (M-14).
- The installer CI steps need one run (manual dispatch) to confirm them on Windows and Mac runners.
