# Codex Third Independent Review

## Scope and baseline

This review re-read `CODEX_REVIEW.md`, `CODEX_REVIEW_2.md`, `CLAUDE_RESPONSE.md`, `CLAUDE_RESPONSE_2.md`, and `HUMAN_DECISIONS.md`; inspected the complete current repository; and compared the current tree at `bf95338` with the pre-audit checkpoint `7327924` (`main`/`origin/main`). The working tree was clean before this report was created.

The current delta is 65 files, 8,861 insertions, and 5,071 deletions. The largest post-review change is the second-stage `app.py` split into `handlers/`, `http_utils.py`, and `run_support.py`. This review therefore checked both the earlier security/correctness repairs and whether the extraction lost routes, changed behavior, duplicated state, or bypassed the central HTTP security checks.

## Diagnostic results

- `pytest -q`: **196 passed** in 21.13 seconds.
- Coverage run: **77% total** (5,901 statements, 1,346 missed). The most relevant current figures are `app.py` 62%, `handlers/index_compare.py` 87%, `handlers/transcribe_run.py` 77%, `run_support.py` 78%, `customizable_transcription/core.py` 71%, and `xls_conversion/ai_parser.py` 61%.
- Python bytecode compilation of production and test code: passed.
- Node syntax checks for every repository JavaScript file: passed.
- Offline baptism-parser regression harness: passed, 6 entries parsed.
- `pip check`: no broken requirements.
- `pip-audit` against `requirements.txt` and `requirements-dev.txt`: no known vulnerabilities.
- `npm audit --audit-level=high` in `profiles/worksheets`: 0 vulnerabilities.
- Bandit 1.8.6: no high-severity result; 3 medium and 22 low results. The medium results were reviewed and are not actionable findings: the `ElementTree.fromstring` call is preceded by decompressed-size and DTD/entity guards, while the two B608 results are HTML f-strings rather than SQL.
- Ruff 0.16.7: **101 informational findings**. These are mainly the deliberately retained broad HTTP-boundary catches, import ordering, and subprocess-style warnings. Three reported `app.py` imports are compatibility/test re-exports actually used by the suite. This remains non-blocking exactly as selected in `HUMAN_DECISIONS.md`; no demonstrated security, correctness, or integrity defect was derived from the output.
- Structural extraction check: all 50 pre-split `Handler` methods still exist, one intentional dispatch helper (`run_transcription`) was added, no method names collide across the mixins, and the extracted `/run` implementation is AST-identical to the pre-split body. All 44 pre-split top-level helpers remain; the only AST differences are documentation wording.
- Live browser smoke review against the current server: `/`, `/prompt-builder`, `/transcribe`, `/xls-conversion`, `/test-mode`, `/getting-started`, and `/privacy` all rendered their expected level-one heading without an application error.
- `git diff --check 7327924..HEAD`: passed. `.env` is not tracked, and a targeted source scan found no embedded API key or private-key material.

## Prior finding disposition

| Finding | Status | Verification summary |
|---|---|---|
| H-1 | RESOLVED | `SECURITY.md` accurately records the human-selected single-user-machine threat model. Central Host validation still covers all requests; Origin and CSRF validation still cover all state-changing requests after the handler split. |
| M-1 | RESOLVED | Batch inputs still reject symlinks, enforce the 50 MB ceiling, and verify file signatures before provider submission. The regression suite remains green. |
| M-2 | RESOLVED | XLS AI requests retain the single-request concurrency guard. `parse_generic()` now caps the actual post-split block/call count before provider calls, and the browser estimate counts marker occurrences. The repeated-marker regression test passes. |
| M-3 | RESOLVED | The selected policy is implemented: batch operations require a pasted key, while Prompt Builder Preflight and XLS Detect Languages may use `.env`. Detect Languages now resolves and passes the effective provider-specific key end-to-end; its blank-field regression test passes. |
| M-4 | RESOLVED | Atomic writes and creation locks remain in place. `HUMAN_DECISIONS.md` now explicitly records acceptance of last-writer-wins for stale multi-tab edits, so no unmade decision remains. |
| M-5 | RESOLVED | Test Mode retains provider-scoped Gemini/Claude keys and per-run failure isolation. Its mixed-provider and failure-continuation tests pass after the module split. |
| M-6 | RESOLVED | Test Mode still writes record type, model, and profile metadata into generated DOCX files, with regression coverage. |
| M-7 | RESOLVED | The human decision to defer browser automation and a coverage threshold is now recorded. Coverage improved from 67% to 77%; this review did not find a new correctness defect hidden by the accepted test policy. |
| L-1 | RESOLVED | Dynamic HTML, JSON, and generated downloads retain `Cache-Control: no-store`. |
| L-2 | RESOLVED | CSP still excludes `unsafe-inline`; executable assets remain external and dynamic data remains in escaped inert JSON islands. The current pages loaded successfully in a live browser smoke pass. |
| L-3 | RESOLVED | `.env` loading remains restricted to the two provider key names and does not overwrite process-environment values. |
| L-4 | RESOLVED | Syntactically valid non-object profile JSON continues to be skipped safely. |
| L-5 | RESOLVED | `cryptography`, `pyasn1`, Ruff, and pip-audit are exact-pinned. CI installs the pinned development requirements. Mutable action tags and unlocked transitives remain an explicitly accepted narrow-policy limitation, not an unrecorded decision. Current Python and npm audits are clean. |
| L-6 | RESOLVED | Documentation now accurately states that only `baptism-parser.js` is tested and that the other two dormant parsers are unmaintained reference code, matching the selected retention policy. |
| L-7 | RESOLVED | The multi-sheet Index Compare mapping UI retains the selected plain worksheet selector and clears mappings when the selected sheet changes. |
| L-8 | RESOLVED | The selected second modularization pass is complete: `app.py` is now 663 lines and cross-cutting routing/security remains central, while feature handlers and shared run/HTTP logic are separated. The broad-catch rationale and informational lint policy are recorded and implemented. The new sandbox-binding tests cover the principal imported-`Path` alias risk created by the split. |
| I-1 | RESOLVED | Previously noted defensive controls remain present; the current test, dependency, syntax, security, and browser diagnostics found no new critical/high issue. |
| N-1 | RESOLVED | `HUMAN_DECISIONS.md` now records the selected option, resulting action, date, and decision owner for every prior decision item. |

## New findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

None.

### LOW

#### N-2 — HUMAN_DECISION_REQUIRED: Index Compare's pre-inspection endpoint has no client execution path

- **Affected files:** `handlers/index_compare.py:60-91`; `app.py:476-478`; `static/test-mode.js:378-608`; `tests/test_index_compare_http.py:100-130`.
- **Technical reason:** `inspect_index_file()` says it is called client-side immediately after each XLSX file is selected so mapping can be requested before the user presses Run. No production JavaScript calls `/api/index-compare/inspect`; the only callers are its two HTTP tests. The actual UI first discovers mapping requirements through `/api/index-compare/analyze` after Run is pressed. The current user-visible flow still works, but the endpoint, route, tests, and docstring maintain a second parsing surface for behavior the client never invokes, and the implementation differs from its stated intent.
- **Why it matters:** This is dead production API code and misleading maintenance documentation. Future changes can spend effort preserving an endpoint under the false assumption that it supports an immediate-preflight UX, while the real UI behavior remains delayed until comparison starts.
- **Recommended correction:** Decide which UX is intended. If mapping-on-Run is correct, remove the unused route/method and its endpoint-only tests and update the explanatory text. If immediate inspection is desired, wire file-input change handlers to the endpoint, render or retain the returned mapping state, and add a browser-level regression test for that interaction.
- **Claude can safely address automatically:** **Partly.** Removal or wiring is straightforward after the intended UX is selected; the wiring option needs browser-state tests.
- **Human judgment required:** **Yes.** Choosing immediate pre-inspection versus the current mapping-on-Run interaction is a product/UX decision.

### INFORMATIONAL

None beyond the diagnostic observations above.

OVERALL STATUS: HUMAN_DECISION_REQUIRED
