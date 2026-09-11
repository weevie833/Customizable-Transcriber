# Codex Follow-up Independent Review

## Scope and baseline

This review compared the complete current repository and its uncommitted working-tree changes with commit `7327924` (`HEAD`, also `main`/`origin/main`), the only committed pre-repair baseline present. It read `CODEX_REVIEW.md`, `CLAUDE_RESPONSE.md`, and `HUMAN_DECISIONS.md`, reviewed the current implementation (including untracked repair files), and exercised the changed security, orchestration, persistence, document, and browser-facing paths.

`HUMAN_DECISIONS.md` contains the decision questions, options, and Claude recommendations, but it does not record which options the human selected. Where the implementation makes the apparent choice unambiguous, this review evaluates that implemented policy. Where accepting the remaining risk is itself the only possible resolution, the finding remains `HUMAN_DECISION_REQUIRED` until the decision is recorded.

## Diagnostic results

- `pytest -q`: **191 passed** in 20.55 seconds.
- Coverage run: **67% total**; `app.py` 59%, `app_state.py` 72%, `customizable_transcription/core.py` 71%, `profiles_store.py` 59%, `xls_conversion/ai_parser.py` 61%, `test_mode/comparison.py` 41%, and `test_mode/report_docx.py` 44%.
- Python bytecode compilation of production and test code: passed.
- Node syntax checks for all repository JavaScript: passed.
- Offline regex-parser regression harness: passed, 6 entries parsed.
- `pip check`: no broken requirements.
- `pip-audit`: no known vulnerabilities in the current Python requirement sets.
- `npm audit`: 0 vulnerabilities in `profiles/worksheets`.
- Bandit: no high-severity result. Its two medium results were reviewed: protected `ElementTree.fromstring` use and the intentional isolated `exec` in the offline test harness did not establish new actionable vulnerabilities.
- Ruff 0.16.6: **92 findings**. The new lint job is non-blocking; one finding is a newly added unused import in `tests/test_batch_source_file_limits.py` and the remainder is mostly import ordering/style and existing broad-catch debt.
- Browser smoke review: `/`, `/transcribe`, `/prompt-builder`, `/test-mode`, `/xls-conversion`, `/getting-started`, and `/privacy` all loaded. The remaining inline script elements are non-executable `application/json` data islands; executable scripts and styles load from same-origin static assets.
- `git diff --check`: passed. `.env` is not tracked, and a targeted key/private-key scan found no matching source file.

## Prior finding disposition

| Finding | Status | Verification summary |
|---|---|---|
| H-1 | RESOLVED | `SECURITY.md:43-56` explicitly makes other local OS users/processes out of scope and warns not to run on a shared machine. This is an accepted single-user threat model, not authentication. |
| M-1 | RESOLVED | `customizable_transcription/core.py:295-332,699-717,802-825` now rejects symlinked paths and files over 50 MB before reading, and content-sniffs JPEG/PNG/PDF before provider submission. Regression tests cover files, directory symlinks, limits, and signatures. |
| M-2 | STILL_OPEN | The new concurrency guard works, but the “Process all” cap can still be bypassed by repeated marker numbers. Details below. |
| M-3 | STILL_OPEN | The deliberately retained `.env` convenience still does not work for XLS “Detect Languages,” despite the new documentation saying it does. Details below. |
| M-4 | HUMAN_DECISION_REQUIRED | Creation collisions are locked and writes are atomic, but stale edits still silently overwrite newer edits. The source explicitly says that conflict behavior remains a product decision. Details below. |
| M-5 | RESOLVED | Test Mode now accepts provider-scoped Gemini/Claude keys (`pages/test_mode.py:164-172`, `app.py:2620-2665`) and isolates failures per run (`app.py:1428-1487`). Tests exercise mixed providers and continued execution after a failed run. |
| M-6 | RESOLVED | Test Mode passes record type, model, and profile label into DOCX generation (`app.py:1459-1470`), covered by `tests/test_test_mode_docx_metadata.py`. |
| M-7 | HUMAN_DECISION_REQUIRED | Python/HTTP coverage improved, but there is still no automated browser suite or CI coverage threshold. Details below. |
| L-1 | RESOLVED | Dynamic HTML and generated downloads now emit `Cache-Control: no-store` (`app.py:3106-3143`), with HTTP regression coverage. |
| L-2 | RESOLVED | CSP no longer allows `unsafe-inline` (`app.py:1546-1567`); executable inline assets were extracted and all primary pages loaded in the browser smoke review. JSON data islands use `</` escaping in `pages/__init__.py:20-64`. |
| L-3 | RESOLVED | The `.env` loader is restricted to the two provider-key names and does not overwrite an existing process environment value, covered by `tests/test_env_file_loading.py`. |
| L-4 | RESOLVED | `profiles_store.py:267-280` skips syntactically valid non-object JSON profiles, with regression coverage. |
| L-5 | REGRESSION_INTRODUCED | Two floor-only Python packages were exact-pinned, but the repair added another unpinned executable CI tool while the original transitive/action-tag risk remains. Details below. |
| L-6 | STILL_OPEN | All three dormant parsers remain, two remain untested, and the new documentation incorrectly says all are exercised by offline tests. Details below. |
| L-7 | RESOLVED | `static/test-mode.js:398-453` now renders a worksheet selector for multi-sheet workbooks, updates the selected sheet name, and clears mappings that belonged to the previous sheet. Backend multi-sheet tests pass. |
| L-8 | HUMAN_DECISION_REQUIRED | Page/profile extraction improved separation, but routing remains concentrated and the new static analysis is informational with 92 live findings. Details below. |
| I-1 | RESOLVED | The previously noted defensive controls remain present; dependency, syntax, security-header, document-ingestion, and test diagnostics completed without a new critical/high finding. |

## Unresolved prior findings

### M-2 — STILL_OPEN: repeated markers bypass the “Process all” cap

- **Affected files:** `xls_conversion/ai_parser.py:975-997,1000-1023,1499-1512,1584-1614`; `xls_conversion/app.js:423-465`; `tests/test_image_range.py:75-93`.
- **Technical reason:** `all_image_numbers()` de-duplicates marker numbers with `dict.fromkeys`, and `all_image_numbers_capped()` caps that unique-number count. `split_image_blocks(..., process_all=True)` does not de-duplicate and `parse_generic()` makes an AI call for each returned block. A synthetic transcription containing 5,001 `page_001.jpg` markers therefore reports one capped image but produces 5,001 blocks/calls. The browser estimate likewise counts marker numbers with a `Set`, so it understates the run. The server-side non-blocking XLS lock correctly prevents a second concurrent XLS AI request but does not repair this cap bypass or permit cancellation of an accepted long request.
- **Recommended correction:** Enforce `MAX_IMAGES_PER_REQUEST` against the actual block/call count after marker splitting and before any provider call. Make the client estimate use the same unit, and add a repeated-marker regression test. Keep the existing 5,000 limit unless the maintainer explicitly chooses a different value.
- **Claude can safely address automatically:** **Yes**, for enforcing the existing cap against actual blocks and adding tests.
- **Human judgment required:** **No** for the bypass fix. A different numeric limit or conversion to a cancellable background-job model remains a product decision.

### M-3 — STILL_OPEN: documented `.env` Detect Languages flow is impossible

- **Affected files:** `README.md:76-108`; `PRIVACY.md:70-87`; `xls_conversion/app.js:877-906`; `app.py:2058-2083`; `xls_conversion/ai_parser.py:323-349`; `tests/test_xls_conversion_preflight_key_check.py:83-99`.
- **Technical reason:** The revised documentation specifically promises `.env` fallback for XLS Conversion’s bounded “Detect Languages” call. The browser disables that button unless the password field is non-empty. If a blank request is sent directly, `validate_api_key_with_retry()` can resolve the saved key internally, but the handler then passes its original empty `api_key_value` to `detect_languages()`, which immediately raises “Paste an API key.” Existing tests cover a pasted bad key, not the advertised blank-field fallback.
- **Recommended correction:** Resolve the effective provider key once for this endpoint, use it for validation and language detection, allow the browser button when a configured provider key exists without exposing that key, and add an HTTP regression test for blank-field `.env` fallback. If saved-key use was not actually selected, remove the README/Privacy promise and require pasting consistently.
- **Claude can safely address automatically:** **Yes**, if the newly documented saved-key policy is authoritative.
- **Human judgment required:** **Yes**, only because `HUMAN_DECISIONS.md` does not record whether that policy was actually selected.

### M-4 — HUMAN_DECISION_REQUIRED: stale profile edits remain last-writer-wins

- **Affected files:** `profiles_store.py:40-53,399-455`; `pages/transcribe.py:204`; Prompt Builder profile-update UI.
- **Technical reason:** `_profile_write_lock` and atomic replacement prevent creation collisions, interleaved writes, and truncated JSON. They do not detect that a browser tab loaded an older version of a profile. A later save from that stale tab still silently replaces a newer save. `profiles_store.py:48-52` explicitly says last-writer-wins is preserved because revision/conflict behavior was not decided.
- **Recommended correction:** Either record that multi-tab editing is unsupported and last-writer-wins is accepted, or add a revision token checked on update and reject stale writes with a clear reload/save-as-new message.
- **Claude can safely address automatically:** **Partly**. Revision-token plumbing and tests are mechanical after the desired conflict policy is selected.
- **Human judgment required:** **Yes**, for whether stale writes are accepted and what conflict UX is desired.

### M-7 — HUMAN_DECISION_REQUIRED: browser and coverage policy remains unset

- **Affected files:** `.github/workflows/tests.yml`; `pyproject.toml:18-33`; `static/prompt-builder.js`; `static/test-mode.js`; `static/transcribe.js`; `xls_conversion/app.js`; current tests.
- **Technical reason:** The repair added valuable HTTP/orchestration tests and raised measured coverage in important Python modules, but the newly extracted browser state machines still have no automated browser tests. There is no CI coverage floor. The current 67% aggregate includes particularly low coverage in comparison/report generation, and the CSP refactor moved thousands of lines without adding an automated page-behavior gate. This review’s manual browser smoke check is not repeatable CI protection.
- **Recommended correction:** Record whether the intended decision was to defer browser automation. If not, add focused E2E smoke tests for initialization, preflight/confirm state, provider-key selection, XLS language detection, and multi-worksheet mapping; choose and enforce an incremental coverage threshold.
- **Claude can safely address automatically:** **Partly**. It can scaffold tests, but should not choose the browser framework, provider-mocking contract, or coverage threshold without direction.
- **Human judgment required:** **Yes**.

### L-5 — REGRESSION_INTRODUCED: repair adds another floating CI executable

- **Affected files:** `.github/workflows/tests.yml:30-39,60-71,82-93`; `requirements.txt:6-17`; `requirements-dev.txt`; dependency metadata.
- **Technical reason:** Exact-pinning `cryptography` and `pyasn1` correctly implements the narrow option described in `HUMAN_DECISIONS.md`. However, the new lint job executes `python -m pip install ruff` with no version pin on every run. The audit job similarly installs unpinned `pip-audit`, GitHub Actions still use mutable major tags, and no lock/hashes constrain transitives. The repair therefore introduced one more unreviewed executable dependency while only partially reducing the original risk.
- **Recommended correction:** At minimum exact-pin Ruff in a development/tooling requirements file and install it from there. Record whether the project accepts mutable Action tags and unlocked transitives or adopts SHA-pinned Actions plus a reviewed lock/update workflow.
- **Claude can safely address automatically:** **Yes** for moving Ruff to an exact pin after a version is selected; **no** for choosing the long-term supply-chain policy.
- **Human judgment required:** **Yes** for the full policy and maintenance workflow.

### L-6 — STILL_OPEN: dormant-parser documentation overstates coverage

- **Affected files:** `xls_conversion/README.md:24-31`; `docs/DESIGN.md:211-222`; `xls_conversion/baptism-parser.js`; `xls_conversion/matrimony-parser.js`; `xls_conversion/morti-parser.js`; `xls_conversion/tests/harness.js:1-6`; `xls_conversion/tests/run_parser_test.py`.
- **Technical reason:** The live app uses only `ai_parser.py`. The offline harness requires only `baptism-parser.js`; repository reference searches and the passing offline test confirm that `matrimony-parser.js` and `morti-parser.js` still have no execution path or tests. The new README statement that the three parsers “are exercised only by the offline regression tests” is therefore false and can cause future maintainers to assume the two decaying parsers are validated.
- **Recommended correction:** Either explicitly document that only the baptism parser is tested and the other two are unmaintained reference code, add parity regression suites for both, or archive/remove all code not intended to be maintained.
- **Claude can safely address automatically:** **Yes** for correcting the factual documentation or adding tests once expected behavior is supplied; **no** for deciding to remove or revive the parsers.
- **Human judgment required:** **Yes** for the parsers’ lifecycle.

### L-8 — HUMAN_DECISION_REQUIRED: partial modularization and non-enforcing static analysis

- **Affected files:** `app.py` (3,175 lines); `pages/*.py`; `profiles_store.py`; `static/*.js`; `.github/workflows/tests.yml:51-71`; `pyproject.toml:21-33`.
- **Technical reason:** Extracting page rendering, profiles, CSS, and JavaScript is a meaningful maintainability improvement. Nevertheless, `app.py` still owns most routing/orchestration and is larger than the pre-audit file. Ruff is explicitly `continue-on-error`, currently reports 92 findings, and Bandit is not in CI. Thus static analysis reports drift but cannot stop it, and the architectural remainder has been reduced rather than eliminated.
- **Recommended correction:** Record acceptance of the current modular boundary and informational lint policy, or clean/baseline Ruff and make it enforcing. Further handler/orchestration extraction and Bandit adoption should be separately scoped, with tests around each moved boundary.
- **Claude can safely address automatically:** **Partly**. Mechanical Ruff cleanup can be reviewed and automated; architecture boundaries, suppressions, and enforcement policy require maintainer direction.
- **Human judgment required:** **Yes**.

## New findings

### LOW — NEW FINDING N-1: the human-decision artifact records no decisions

- **Affected files:** `HUMAN_DECISIONS.md:1-745`; source comments and documentation that cite it as authority, including `profiles_store.py:40-52`, `.github/workflows/tests.yml:51-55`, and `pyproject.toml:21-30`.
- **Technical reason:** The file is an options/recommendations memo, not a decision record: it contains no selected option, approver, date, or acceptance rationale for any of its 12 entries. Repairs and source comments claim choices were made “per HUMAN_DECISIONS.md,” but an independent reviewer cannot distinguish a human-approved risk acceptance from Claude implementing its own recommendation. This is particularly material for authentication scope, stored-key behavior, stale-write data loss, dependency policy, and non-enforcing quality gates.
- **Recommended correction:** Add a short, dated “Decision selected” and rationale/owner entry to every item, including explicitly accepted residual risk. Keep proposals separate from approved outcomes.
- **Claude can safely address automatically:** **No**. Claude can format recorded answers but must not invent approvals.
- **Human judgment required:** **Yes**.

## Conclusion

The repair pass resolves most concrete defects and introduces useful regression coverage, but the XLS call cap remains bypassable, the documented saved-key flow remains broken, and several accepted-risk choices are not actually recorded. No new critical or high-severity vulnerability was found.

OVERALL STATUS: CHANGES_REQUIRED
