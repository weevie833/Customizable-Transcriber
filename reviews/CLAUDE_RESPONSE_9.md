# Response to GEMINI_REVIEW_9.md

Review: reviews/GEMINI_REVIEW_9.md (Gemini, 2026-11-23, commit a102d44; text extracted from the supplied DOCX, which stays on the Desktop unchanged). Every finding was checked against the code before any change. Nothing is committed or pushed.

## Disposition

| Item | Verdict on checking | Disposition | Tests |
|---|---|---|---|
| M-1 | Not reproducible | No code change; behaviour now tested | 3 |
| M-2 | Real, narrow | Fixed | 1 |
| M-3 | True, harmless in practice (Low) | Fixed | 2 |
| L-1 | Accurate; the `.env` half partly overstated | Fixed | 3 |
| L-2 | Accurate, needs a hand-edited profile file | Fixed | 2 |
| L-3 | Accurate (defence in depth) | Fixed | 4 |
| L-4 | One real cosmetic bug; the rest is hardening | Fixed | browser check |
| L-5 | Accurate (advice only, runs already exact) | Fixed | 1 |
| L-6 | Accurate | Fixed | 2 |
| I-1 | Accurate | Fixed | 3 |
| I-2 | Wording and the up-front key check: accurate | Fixed; `.env` alignment not changed | 3 |
| I-3 | Low value | Not changed | - |
| I-4 | Optional | Not changed | - |

All 24 new tests are in `tests/test_gemini_review_9.py` and go through the real entry points (live server, real handlers) with synthetic files and temp dirs. No provider is called. Run against the previous source, 19 of them fail. The 5 that pass there are deliberate: the three M-1 tests document existing behaviour, the non-ASCII-token test guards the new comparison, and the export-filename test confirms a valid id is unchanged.

## Notes per item

**M-1 (zip bombs).** I built a DOCX whose headers declare 1,000 bytes for a 20 MB `word/document.xml`. Python's `zipfile` stops reading at the declared size (`ZipExtFile` counts down from `file_size`). The read then fails its CRC check, so it is rejected with nothing expanded. openpyxl reads through the same `zipfile`, so `index_compare/reader.py` behaves the same way and reports "Could not read this file as an XLSX workbook." The existing guards are correct as they are. The tests pin this down for both readers and for `zipfile` itself.

**M-2.** `save_profile()` now checks `state["running"]` under the lock. During a run, the save result (or the error) is added to the run's log, and the summary, log and download link are left alone. The Save buttons were already disabled when Transcribe renders during a run. The gaps were a Translate run (started by fetch, with no reload) and a second tab. The run itself is unaffected either way, because workers use the approved profile snapshot (CODEX_REVIEW_2 N-3).

**M-3.** `_send_security_error()` sets a per-request flag, and `end_headers()` then skips `Set-Cookie`. The flag is reset at the top of `_security_check()`, because a keep-alive connection reuses the handler. A test sends a rejected request and then a valid one on the same connection, and the cookie comes back on the second. In practice this was harmless: every later request from a rejected host is rejected too.

**L-1.** The token is compared with `secrets.compare_digest` on bytes. A str compare raises `TypeError` for non-ASCII input, which would have been a 500, and a test covers that case. A new `restrict_to_owner()` in `profiles_store.py` sets mode 0600 on POSIX (best effort; a no-op on Windows). It runs on an existing request-token file when it is read and after it is written, and on an existing `USER_DATA_DIR/.env`. Gemini was right that `migrate_saved_keys_file()` appends to an existing `.env` without fixing its mode. It never creates one with a loose mode.

**L-2.** `_read_profile_file()` treats a file whose id fails `_VALID_PROFILE_ID` as not a profile. It is skipped in listings and reported by `load_profile_exact()`. All 19 real profiles on this Mac pass the check. The export filename also goes through `safe_filename()`.

**L-3.** A new `app_state.output_file()` returns the path only for an existing file inside `USER_OUTPUTS_DIR`, resolved at call time, so the test sandbox applies. `/download`, `/test-mode/download/<run>` and `/download-translation-report` serve only through it. One existing test (`test_download_endpoint_is_not_cacheable`) served a file from a temp dir; it now uses the sandboxed outputs folder.

**L-4.**
- `runIndexCompare()` no longer escapes text it assigns to `textContent`. This was the real bug: an `&` showed as `&amp;`.
- `escapeHtml()` in `test-mode.js` now also escapes `"`, because `innerHTML` alone leaves quotes. That makes `rt.value` safe in the `<option value>` it builds.
- `addSimpleRow()` escapes its placeholder with a new `pbAttr()`. I kept the markup route rather than setting the property, because `addRow()` copies the placeholder into `aria-label` and the translation pass reads both.
- The six `option[value="..."]` selectors use `CSS.escape()`.

The values involved were app constants or validated profile ids. In the browser, Prompt Builder's "Add another term" row still gets its placeholder and `aria-label`, and Prompt Builder and Test Mode load with no console errors.

**L-5.** `/api/page-zoom-check` and `/api/offpeak-cost-estimate` use `load_profile_exact()`. An unknown id now gives no page layout instead of another profile's layout. The test seeds a two-page profile, which the old fallback would have reported, and fails on the old code.

**L-6.** `parse_post_form()` turns a `UnicodeDecodeError` into "The form submission isn't valid UTF-8 text." `parse_multipart_form()` takes a `max_bytes` argument, and profile import passes 2 MB (`MAX_PROFILE_IMPORT_BYTES`; the largest real profile is about 100 KB). The refusal comes from Content-Length, before the body is read.

**I-1.** The banner's install line is pinned to the offered release tag (`install_line_for(tag)`). Anything other than a plain `vX.Y.Z` tag falls back to the `main` line, so a strange tag can never reach the pasted shell command. `fetch_latest_tag()` accepts only an https redirect within github.com, or a relative one. The repo path is deliberately not checked, so a future repo rename (which GitHub redirects) can't silently stop update notices. README and Install Instructions still give the `main` line for first installs. That is unchanged.

**I-2.** Transcribe and XLS Conversion now say "Paste an API key ...". `/run` and `/run-offpeak` call `ensure_key_matches_model()` before the run slot is used, so a key for the wrong provider is refused before anything starts. Test Mode keeps "Paste a Gemini API key -- at least one queued run uses a Gemini model.", which is correct there because it has a key field per provider. **Not changed:** the `.env` fallback difference in XLS Conversion (language detection falls back to a saved key; preflight and convert require a pasted one). Aligning it means choosing a policy, so it is left for the user.

**I-3.** Not changed. The raw `self.path` comparisons only affect requests the app's own forms never make. The `--` guard isn't needed, because the paths passed to `open`/`xdg-open` are absolute folders the app controls.

**I-4.** Not changed. The CI gate stays at F,E9.

## Verification

- `pytest tests/`: 739 passed, 1 skipped (was 715 + 24 new).
- Ruff F,E9 gate: clean. The full advisory count is unchanged at 95 (with ruff 0.17.6), and the new test file has no findings.
- `node --check` on both edited scripts. `xls_conversion/tests/run_parser_test.py` passes.
- Browser (server restarted on 8765): Prompt Builder and Test Mode load with no console errors, and Prompt Builder's "Add another term" row was checked.
- Checked in source only: the POSIX file-mode fixes on Windows (a no-op there by design).
