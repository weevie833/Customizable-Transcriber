# Codex Independent Code and Security Review

Review date: 2026-09-16

Reviewed revision: `e420b3f` (`main`)

Scope: the complete tracked repository, including Python and JavaScript source, HTML/CSS, configuration, workflows, dependency manifests, tests, documentation, and a Git-history secret scan. The repository contained 135 tracked files and approximately 26,512 lines of Python/JavaScript.

## Executive result

| Severity | Count |
|---|---:|
| CRITICAL | 0 |
| HIGH | 1 |
| MEDIUM | 3 |
| LOW | 3 |
| INFORMATIONAL | 4 |

The application has strong localhost request defenses, bounded upload parsing, file-type checks, archive-expansion limits, output escaping, exact direct dependency pins, concurrency guards, and a substantial offline test suite. The unresolved findings are concentrated in the newer Off-Peak batch path. In particular, the application can report a provider batch as cancelled even when cancellation failed and the paid provider job is still running.

## Review basis and diagnostics

- `pytest -q`: **228 passed**. The live-server tests required permission to bind loopback sockets; after that permission was granted, the complete suite passed.
- Python bytecode compilation: **passed** for all application and test modules.
- `node --check`: **passed** for all tracked JavaScript application and parser files.
- Offline parser regression harness: **passed**, 6 entries.
- `pip check`: **passed**, no broken installed requirements.
- `pip-audit -r requirements.txt`: **no known vulnerabilities found**.
- `npm audit --audit-level=high` in `profiles/worksheets/`: **0 vulnerabilities**.
- Ruff: **118 findings**: 40 `BLE001`, 23 `I001`, 12 `PLR0402`, 8 `TRY004`, 7 `UP012`, 6 `PLW1510`, 5 `DTZ005`, 4 `F401`, and 13 across other rules.
- Current-tree and Git-history credential-pattern scans found no credible committed API keys, private keys, or tracked `.env` file. Matches were documentation, placeholders, or test fixtures.

No source code was modified during this review. Only this report and `HUMAN_DECISIONS.md` were replaced.

## CRITICAL

No critical findings.

## HIGH

### H-1 — Off-Peak cancellation can falsely report success while the provider job continues

1. **Description:** Both provider cancellation helpers suppress every exception. The orchestration loop then exits whenever the local `cancelled` flag is set, even if the immediately following provider status is non-terminal or the status check fails. It finally reports `Off-peak batch cancelled` and releases the shared run slot without confirming the provider accepted or completed cancellation.
2. **Files and locations:** `batch_transcription.py:240-248`, `batch_transcription.py:336-340`, `batch_transcription.py:411-440`, `batch_transcription.py:487-499`, `batch_transcription.py:525-543`; the current behavior is explicitly exercised by `tests/test_offpeak_batch.py:391-435`.
3. **Why it matters:** A Gemini or Claude batch may continue processing and accruing charges after the UI says it was cancelled. The application may also write an output full of `No result was returned` errors, forget the active provider job, and allow another run to start. Because job state is not persisted, a restart removes the only in-app record of the still-running job.
4. **Recommended correction:** Separate `cancellation_requested` from `cancellation_confirmed`; classify benign “already terminal” responses rather than swallowing all errors; continue polling until the provider reaches a terminal state; use a bounded cancellation-confirmation deadline; and report `cancellation unconfirmed` with the provider job ID and recovery instructions if confirmation cannot be obtained. Persisting the non-secret provider/job identifier would permit recovery after restart.
5. **Automatic or human:** **Human decision required.** The false-success behavior can be corrected safely, but the cancellation deadline, recovery UX, and whether to reverse the existing no-persistence policy are product decisions. See HD-1 in `HUMAN_DECISIONS.md`.

## MEDIUM

### M-1 — Off-Peak ignores the selected processing order

1. **Description:** The Off-Peak handler validates and records `oldest`/`newest`, but does not pass it to the worker. The worker calls `source_files()` without `reverse_order`, so Off-Peak always uses the default oldest-to-newest ordering.
2. **Files and locations:** `handlers/transcribe_offpeak.py:76-109`, `handlers/transcribe_offpeak.py:115-149`, `batch_transcription.py:160-168`, `batch_transcription.py:367-390`, `customizable_transcription/core.py:335-352`; UI promise at `pages/transcribe.py:167-170`.
3. **Why it matters:** The confirmation UI can say `Newest-to-oldest` while the generated Markdown/DOCX is in the opposite order. This is a direct data-integrity and apparent-intent failure, especially for chronological archival material and records spanning adjacent images.
4. **Recommended correction:** Pass the normalized order (or a `reverse_order` boolean) into `run_off_peak_job()`, forward it to `source_files()`, and add tests proving both orders produce the promised provider request/result ordering.
5. **Automatic or human:** **Safe to correct automatically.** The UI and real-time path already define the intended semantics.

### M-2 — Off-Peak materializes an unbounded aggregate batch in memory

1. **Description:** Source validation limits each file to 50 MB but imposes no image-count or aggregate-byte ceiling. Gemini retains every image byte payload in a request list; Claude additionally base64-encodes every file and retains the expanded strings. Validation and reading are separate passes, so a file can also change after the size/symlink check.
2. **Files and locations:** `customizable_transcription/core.py:93-99`, `customizable_transcription/core.py:313-332`, `batch_transcription.py:160-168`, `batch_transcription.py:175-203`, `batch_transcription.py:273-312`.
3. **Why it matters:** A legitimate-looking folder containing many individually valid files can exhaust RAM before provider submission. For example, 100 files at the allowed maximum represent 5 GB of raw input; Claude base64 expansion alone raises that to roughly 6.7 GB before object overhead. Abrupt process termination can lose current state and leave partially submitted provider work difficult to identify.
4. **Recommended correction:** Enforce provider-aware maximum item count and aggregate bytes before reading file bodies; revalidate/open files at consumption time to reduce the validation/read race; reject oversize batches with a clear estimate; and use provider file-upload or streaming facilities instead of retaining every payload when supported.
5. **Automatic or human:** **Human decision required** for capacity and scale expectations. Implementation is straightforward after limits or a streaming design are selected. See HD-2 in `HUMAN_DECISIONS.md`.

### M-3 — Background provider calls rely on SDK-default timeouts and cannot honor Stop while blocked

1. **Description:** Off-Peak constructs both SDK clients without explicit timeouts, so submission, polling, cancellation, and result retrieval depend on SDK-version defaults. The real-time and Test Mode API-key checks also omit the explicit timeout that their actual image calls use. Stop events are only examined before or after a blocking provider call, not during it.
2. **Files and locations:** `batch_transcription.py:392-399`, `batch_transcription.py:415-489`, `run_support.py:499-529`, `run_support.py:624-637`, `customizable_transcription/core.py:396-424`, `customizable_transcription/core.py:427-453`. The existing explicit batch timeout is `customizable_transcription/core.py:85-99`.
3. **Why it matters:** Network stalls can make the application appear stuck and delay cancellation for the SDK's full default timeout. Default behavior can also change when dependencies are upgraded, producing inconsistent failure handling across otherwise similar code paths.
4. **Recommended correction:** Configure explicit per-call timeouts for all provider clients, with separate sensible bounds for submission/result transfer versus lightweight status/cancel calls; pass an explicit timeout to background API-key validation; surface timeout failures distinctly; and keep provider job IDs visible when a status call times out.
5. **Automatic or human:** **Safe to correct automatically** using the existing timeout policy as the baseline, with tests that simulate timed-out submit, poll, cancel, results, and key-validation calls.

## LOW

### L-1 — Off-Peak regression tests omit the paths where current defects occur

1. **Description:** The Off-Peak tests cover happy-path submission, status retries, and a successful cancel call, but do not test selected `newest` ordering, aggregate capacity, explicit client timeouts, cancellation API failure, or a non-terminal status after a cancellation request. One test deliberately treats a post-cancel poll failure as successful local completion.
2. **Files and locations:** `tests/test_offpeak_batch.py:58-136`, `tests/test_offpeak_batch.py:391-479`, `tests/test_offpeak_batch.py:518-587`.
3. **Why it matters:** The suite passes while H-1 and M-1 remain deterministic defects. New code in the highest-cost external integration path is therefore less protected than its test count suggests.
4. **Recommended correction:** Add focused mocked regression cases for cancellation failure/non-terminal transitions, both processing orders, aggregate limits, file mutation between validation and read, and timeouts on every provider operation.
5. **Automatic or human:** **Safe to correct automatically** once HD-1 and HD-2 define the desired behavior.

### L-2 — Gemini prompt caches are not cleaned up when XLS extraction exits early

1. **Description:** The XLS preflight and generic parsing flows delete a created Gemini cache only after their processing loops. An exception that leaves the function early skips deletion; the code intentionally relies on the provider TTL instead.
2. **Files and locations:** `xls_conversion/ai_parser.py:1295-1307`, `xls_conversion/ai_parser.py:1309-1389`, `xls_conversion/ai_parser.py:1682-1700`, `xls_conversion/ai_parser.py:1702-1829`; cleanup helper at `customizable_transcription/core.py:969-978`.
3. **Why it matters:** Failed or cancelled work can retain paid/provider-side cache resources until expiry. This is bounded by the one-hour TTL and is not a data-corruption issue, but it is avoidable resource and cost leakage.
4. **Recommended correction:** Put loop execution in `try/finally` and call the already best-effort cleanup helper from `finally` whenever a cache was created.
5. **Automatic or human:** **Safe to correct automatically.** The helper already suppresses cleanup-only failures.

### L-3 — Advisory-only lint has accumulated a large, noisy baseline

1. **Description:** Ruff reports 118 findings, including 40 broad exception catches, 6 subprocess calls without an explicit `check` argument, 4 unused imports, 3 silent exception handlers, and one loop-variable closure warning. Some are intentional or false positives, but the clean and risky cases are mixed together and CI cannot regress because lint is `continue-on-error`.
2. **Files and locations:** `pyproject.toml:21-33`, `.github/workflows/tests.yml:51-72`; representative security-relevant findings at `batch_transcription.py:240-248` and `batch_transcription.py:336-340`.
3. **Why it matters:** A high-noise report makes meaningful new warnings easy to miss. The two silent cancellation handlers behind H-1 are already identified by Ruff, demonstrating that the advisory stream contains actionable defects.
4. **Recommended correction:** Triage the current baseline, add narrow `noqa` comments with rationale for intentional cases, correct safe mechanical findings, and make a selected security/correctness subset or a no-new-findings baseline enforceable in CI.
5. **Automatic or human:** **No new human decision required for this review.** The repository records an earlier decision to keep lint advisory-only. Mechanical cleanup is automatable; changing the gate remains an accepted maintainer policy choice.

## INFORMATIONAL

### I-1 — Authentication is intentionally absent under a single-user threat model

1. **Description:** Any local process able to connect to the loopback port can obtain the CSRF cookie and use the application. Host, Origin, and CSRF defenses protect the browser from cross-site requests; they are not user authentication.
2. **Files and locations:** `SECURITY.md:30-56`; central response protections at `app.py:300-342`; Host/Origin/CSRF checks at `app.py:352-375` and `app.py:506-509`.
3. **Why it matters:** On a shared or untrusted machine, another local account/process could read outputs, modify profiles/settings, or start and stop paid jobs.
4. **Recommended correction:** Continue enforcing the documented single-user deployment restriction. If that assumption changes, add real launch/session authentication before use on the shared machine.
5. **Automatic or human:** **Previously decided by the maintainer:** single-user machines only. No new decision is required unless the deployment model changes.

### I-2 — Direct dependencies are pinned and current audits are clean, but the build is not fully immutable

1. **Description:** Direct Python dependencies and developer tools are exact-pinned, and current Python/npm audits are clean. Some transitive Python packages remain resolver-selected, and GitHub Actions use mutable major tags such as `actions/checkout@v4` rather than commit SHAs.
2. **Files and locations:** `requirements.txt:1-17`, `requirements-dev.txt:1-18`, `profiles/worksheets/package-lock.json`, `.github/workflows/tests.yml:30-43`, `.github/workflows/tests.yml:60-68`, `.github/workflows/tests.yml:83-103`.
3. **Why it matters:** Future installations or CI runs are not perfectly reproducible and still trust upstream tag movement/resolution.
4. **Recommended correction:** For maximum supply-chain assurance, use a fully resolved Python lock with hashes and pin Actions to reviewed commit SHAs, with Dependabot updating them.
5. **Automatic or human:** **Previously accepted risk.** No new decision is required unless the maintainer wants reproducible/immutable builds.

### I-3 — Approximately 2,500 lines of parser code are outside the live application

1. **Description:** Three legacy regex parsers total 2,478 lines. None is used by the live XLS Conversion path; only the baptism parser has an offline harness, while the matrimony and morti parsers have no execution path or tests.
2. **Files and locations:** `xls_conversion/baptism-parser.js`, `xls_conversion/matrimony-parser.js`, `xls_conversion/morti-parser.js`; status documented at `xls_conversion/README.md:24-34`.
3. **Why it matters:** Dormant code increases repository search/audit burden and can mislead maintainers about the production architecture, although it creates no current runtime attack surface.
4. **Recommended correction:** Keep it explicitly marked reference-only, or move it to an archive/history location if its reference value no longer justifies keeping it in the active source tree.
5. **Automatic or human:** **Previously decided by the maintainer:** retain as documented reference code. No new decision is required.

### I-4 — Automated coverage is strong at the Python/HTTP level but has no browser end-to-end suite

1. **Description:** The 228-test suite exercises substantial parsing, HTTP security, concurrency, reports, and provider-error behavior. JavaScript receives syntax checks and one offline parser harness, but the browser state machines and user flows are not executed in a real DOM/browser in CI.
2. **Files and locations:** `tests/`, `static/*.js`, `xls_conversion/app.js`, `.github/workflows/tests.yml:17-49`.
3. **Why it matters:** DOM wiring, modal state, download behavior, translation refresh, and browser-only regressions can pass all current tests.
4. **Recommended correction:** Add a small Playwright smoke suite for the highest-risk flows when the project is ready to accept the dependency and CI cost; meanwhile continue adding HTTP/module regression tests for every defect.
5. **Automatic or human:** **Previously decided by the maintainer:** defer browser automation. No new decision is required.

## Overall assessment

The established application paths are substantially hardened and the dependency/test posture is better than typical for a local single-user tool. The Off-Peak path does not yet meet the same reliability standard: cancellation truthfulness, ordering, aggregate resource bounds, and explicit network failure behavior need remediation. Two choices are required before the safest implementation can be finalized; they are isolated in `HUMAN_DECISIONS.md`.

OVERALL STATUS: HUMAN_DECISION_REQUIRED
