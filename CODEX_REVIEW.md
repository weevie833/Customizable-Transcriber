# Codex Independent Code and Security Re-Review

Review date: 2026-09-20

Reviewed revision: `a4e3328` (`main`)

Scope: the complete repository, not only recent changes. This included 145 tracked files and approximately 28,735 lines of Python/JavaScript, plus HTML/CSS, generated DOCX/ZIP assets, configuration, workflows, dependencies, tests, documentation, and Git history. The nine commits after the prior reviewed revision (`e420b3f`) were examined in detail.

## Executive result

| Severity | Count |
|---|---:|
| CRITICAL | 0 |
| HIGH | 2 |
| MEDIUM | 3 |
| LOW | 3 |
| INFORMATIONAL | 4 |

The previously reported Off-Peak cancellation, ordering, timeout, cache-cleanup, and unbounded-batch defects were substantially addressed, and the repository retains strong localhost request protections, input/archive bounds, output escaping, profile-path validation, concurrency controls, and dependency hygiene. The principal remaining risks are ambiguous paid-batch submission and destructive AI-assisted continuation merging. Four product/data-policy choices are isolated in `HUMAN_DECISIONS.md`.

## Review basis and diagnostics

- `.venv/bin/pytest -q`: **274 passed in 24.65s**. Loopback-binding permission was required for live HTTP tests.
- Python bytecode compilation: **passed** for all application and test modules.
- `node --check`: **passed** for all tracked JavaScript files.
- Offline parser regression harness: **passed**, 6 entries parsed with expected fields.
- `.venv/bin/pip check`: **passed**, no broken installed requirements.
- `.venv/bin/pip-audit -r requirements.txt -r requirements-dev.txt`: **no known vulnerabilities found**.
- `npm audit --audit-level=high` in `profiles/worksheets/`: **0 vulnerabilities**.
- Generated worksheet DOCX and ZIP integrity checks: **passed**; expected EN/IT bundle members were present.
- Ruff: **120 findings**: 41 `BLE001`, 23 `I001`, 13 `PLR0402`, 8 `TRY004`, 7 `UP012`, 6 `DTZ005`, 6 `PLW1510`, 3 `ISC004`, 3 `S110`, 3 `F401`, and 7 across other rules; 49 are mechanically fixable.
- Current-tree and Git-history credential-pattern scans found no credible committed API key, private key, or tracked `.env` file. The local `.env` is ignored.
- `git diff --check`: **passed** before the reports were replaced.

No application source code was modified. Only this report and `HUMAN_DECISIONS.md` were replaced.

## CRITICAL

No critical findings.

## HIGH

### H-1 — A timed-out Off-Peak submission can create an untracked or duplicate paid job

1. **Description:** The application learns and persists the provider job ID only after the batch-create response returns. If the provider accepts the batch but the response is lost or times out, `job_id` remains unknown and no recovery state is written. The displayed error explicitly tells the user to try again. The pinned Anthropic SDK also has transport retries enabled by default, while this create call supplies no application-level idempotency or reconciliation identifier.
2. **Files and locations:** `batch_transcription.py:302-330`, `batch_transcription.py:391-435`, `batch_transcription.py:548-566`; error-path coverage at `tests/test_offpeak_batch.py:907-937`; dependency at `requirements.txt:2`.
3. **Why it matters:** The first request may already be running and billing even though the app reports submission failure. An SDK retry or the encouraged manual retry can create a second paid batch. Because neither job ID is known locally, cancellation/status recovery is impossible through the app and a crash in the response-to-persistence window has the same effect.
4. **Recommended correction:** Persist a non-secret `submitting` record before the network call with a unique run identifier, provider, timestamp, request count, and request fingerprint. Use a provider-supported idempotency key when available; otherwise disable automatic retries for the non-idempotent create call, give Gemini a unique display name, and treat response timeout as **outcome unknown** rather than “try again.” Add provider-list/dashboard reconciliation before permitting resubmission, or require explicit user acknowledgement that the prior job was checked.
5. **Automatic or human:** **Human decision required.** The safe error wording and pre-submit record are automatic, but the supported recovery/reconciliation workflow and whether resubmission may proceed without provider confirmation are product decisions. See HD-1.

### H-2 — Continuation merging can silently erase previously extracted record fields

1. **Description:** Both continuation merge paths remove the existing row and replace it wholesale with the AI's newly returned row. The confirmation gate only checks whether the new row's `notes` says it continues from the prior image; it does not verify that known dates, names, relationships, or other fields survived. Only notes, source-image bookkeeping, and in one path two locator fields receive special preservation.
2. **Files and locations:** `xls_conversion/ai_parser.py:1637-1650`, `xls_conversion/ai_parser.py:1818-1859`, `xls_conversion/ai_parser.py:1898-1933`, `xls_conversion/ai_parser.py:1998-2029`; tests at `tests/test_continuation_merge.py:39-117` and `tests/test_continuation_fragment_split.py:69-97` verify row replacement but not preservation of every prior non-empty field.
3. **Why it matters:** A model can comply with the continuation-note instruction while omitting or changing fields extracted from the departure image. The spreadsheet then silently loses historical data that was previously present, with no exception or conflict log. This is especially dangerous because the merge is intended to improve integrity and the resulting row appears complete and authoritative.
4. **Recommended correction:** Merge field-by-field under explicit invariants. At minimum, a blank continuation value must never erase a prior non-empty value; stable identity/date/locator fields should be preserved or conflicts logged for review. Retain both original rows or fail the merge when invariants are violated. Add tests covering omitted fields, conflicting non-empty values, multiple returned rows, and all six record schemas.
5. **Automatic or human:** **Human decision required.** Blank-never-erases is safe to implement automatically, but the policy for conflicting non-empty values—preserve the first extraction, trust the context-aware merge, or require review—changes data semantics. See HD-2.

## MEDIUM

### M-1 — Prompt Builder preflight compares only the main text and ignores structured example data

1. **Description:** Example rows now contain `date`, `text`, optional baptism/church-wedding blocks, and an optional next-image continuation. The full prompt correctly serializes all applicable parts, but preflight sends only `.text` as `example_entry`. The server then describes that partial string to the critique model as the known-100%-accurate example.
2. **Files and locations:** `static/prompt-builder.js:258-299`, `static/prompt-builder.js:1578-1598`; `handlers/profiles.py:68-145`, `handlers/profiles.py:248-298`; current tests only submit a flat string at `tests/test_prompt_builder_preflight.py:70-77`.
3. **Why it matters:** Preflight cannot validate the new Date format or same-image Baptism/Church Wedding Record blocks, and its critique can misclassify structured-output differences. Sending the existing full serializer unchanged is also unsafe because the continuation belongs to the next image, not necessarily the one uploaded for preflight.
4. **Recommended correction:** Define a dedicated preflight ground-truth serializer. For a one-image preflight, include Date, Main entry, and any side-column block visible on that image, but explicitly exclude next-image continuation data. Alternatively, support paired image uploads and compare the continuation separately. Add JavaScript/HTTP tests asserting the exact multipart ground truth.
5. **Automatic or human:** **Human decision required** because preflight's image/example scope must be defined before the serializer can be corrected. See HD-3.

### M-2 — The 2 GB Off-Peak aggregate cap still permits process-level memory exhaustion

1. **Description:** The former unbounded behavior is now capped, but the chosen 2,000,000,000-byte raw-input limit is explicitly an unmeasured directional default. Gemini retains the inlined request payloads in one list; Claude retains base64 strings of approximately 2.67 GB at the maximum, before Python/object/HTTP serialization overhead and the rest of the process.
2. **Files and locations:** `batch_transcription.py:238-261`, `batch_transcription.py:264-330`, `batch_transcription.py:397-435`; tests validate threshold enforcement but not peak resident memory at `tests/test_offpeak_batch.py:166-223`.
3. **Why it matters:** A formally valid batch can still exhaust memory or trigger severe swapping on an ordinary 8 GB machine. The bound prevents unlimited growth but does not yet establish a safe operating envelope, particularly for Claude's base64 expansion and transient serialization copies.
4. **Recommended correction:** Measure peak memory for each provider and derive provider-specific limits from a documented minimum supported host. Until measured, use a materially conservative cap and clear split-batch guidance. For larger workloads, use provider file staging/streaming rather than retaining all payloads in memory.
5. **Automatic or human:** **Human decision required** for the supported minimum host and maximum legitimate batch. See HD-4.

### M-3 — Real-time and Test Mode key validation still cannot be stopped promptly

1. **Description:** Actual image calls use the explicit 600-second application timeout, but the initial API-key validation in Real-time and Test Mode passes no timeout. Comments justify this with background progress and Stop support, yet the Stop event is not checked during the blocking validation call; it can only take effect after the SDK returns.
2. **Files and locations:** `customizable_transcription/core.py:396-453`, `customizable_transcription/core.py:561-572`; callers at `run_support.py:523-530` and `run_support.py:633-638`. Prompt Builder correctly passes an explicit timeout at `handlers/profiles.py:269-277`.
3. **Why it matters:** A network stall can leave the UI on “Checking API key...” and make Stop appear ineffective for the SDK's full default duration. Relying on dependency defaults also makes this behavior less explicit and can change on dependency upgrades.
4. **Recommended correction:** Pass a short explicit key-check timeout (the existing 60- or 90-second policy is a suitable baseline), catch/report timeout distinctly, and add tests for both Real-time and Test Mode validation stalls. True mid-call cancellation would require an async/cancellable transport; the bounded timeout is the practical minimum.
5. **Automatic or human:** **Safe to correct automatically.** Existing timeout constants and foreground preflight behavior define a compatible policy.

## LOW

### L-1 — Failed Off-Peak state persistence is silent while the UI promises recovery

1. **Description:** `write_off_peak_job_state()` suppresses every `OSError` and returns no success indicator. The cancellation-unknown message then states unconditionally that the job ID “is saved and will be shown again,” even when disk-full, permissions, or filesystem failure prevented that write.
2. **Files and locations:** `app_state.py:192-219`; callers and promise at `batch_transcription.py:588-596`, `batch_transcription.py:694-705`, `batch_transcription.py:780-786`.
3. **Why it matters:** The user may close the app believing recovery metadata is durable, then permanently lose the only local job identifier while the provider job continues.
4. **Recommended correction:** Return a success/failure result (or raise a persistence-specific exception after retaining live state), log the failure, and change the UI to instruct the user to copy the visible job ID immediately when persistence failed. Treat malformed persisted JSON similarly rather than silently ignoring it.
5. **Automatic or human:** **Safe to correct automatically.** It changes error reporting, not the chosen recovery policy.

### L-2 — The lint baseline remains too noisy to act as a regression control

1. **Description:** Ruff reports 120 findings and the CI lint job is explicitly `continue-on-error`. Broad exception catches, silent exception handlers, unused imports, and a loop-variable closure warning are mixed with intentional style exceptions.
2. **Files and locations:** `pyproject.toml:21-33`, `.github/workflows/tests.yml:104-125`; representative silent handlers at `batch_transcription.py:367-375`, `batch_transcription.py:463-467`, and `app_state.py:199-209`.
3. **Why it matters:** New correctness/security warnings do not fail CI and are hard to distinguish from the accepted baseline. L-1 is itself represented by silent-handler warnings, demonstrating that the output contains actionable signals.
4. **Recommended correction:** Fix the 49 mechanical findings, annotate intentional exceptions narrowly, and enforce either a selected correctness/security ruleset or a no-new-findings baseline while leaving purely stylistic rules advisory.
5. **Automatic or human:** **Partly automatic.** Mechanical cleanup is safe; changing the CI gate remains the maintainer's previously accepted policy choice.

### L-3 — Documentation overstates continuation-note determinism

1. **Description:** User documentation says continuation notes are written by the app, not the model. In implementation, the model must first recognize the split and emit one of the expected phrases; the application only normalizes a matching phrase and adds the neighboring filename. If the model omits the note, no preset is created and XLS merge logic never activates.
2. **Files and locations:** Claims at `README.md:225-232`, `docs/DESIGN.md:419-430`, `xls_conversion/README.md:37-49`; actual detection/normalization at `static/prompt-builder.js:431-451` and `customizable_transcription/core.py:1015-1089`.
3. **Why it matters:** Maintainers and users may believe split detection is deterministic and fail to review missed continuations. A model omission can leave duplicate/truncated spreadsheet rows without an application warning.
4. **Recommended correction:** State precisely that the model detects/flags the split and the app standardizes the note. Consider a validation warning when adjacent record boundaries look inconsistent or when a run ends with a likely incomplete entry, while acknowledging that deterministic visual detection is not currently implemented.
5. **Automatic or human:** **Safe to correct automatically** for documentation. Adding heuristic detection would require separate design and testing.

## INFORMATIONAL

### I-1 — Authentication remains intentionally absent under a single-user threat model

1. **Description:** Host, Origin, SameSite cookie, and CSRF checks protect against cross-site browser access and DNS rebinding, but any local process able to reach the loopback port can use the application. This is explicitly documented, not an accidental omission.
2. **Files and locations:** `SECURITY.md:30-56`; `app.py:300-375`, `app.py:377-509`.
3. **Why it matters:** On a shared or compromised workstation, another local account/process could read outputs, alter profiles/settings, or start paid work.
4. **Recommended correction:** Continue enforcing the documented single-user restriction. Add real launch/session authentication before any shared-machine, LAN, proxy, container, or remote deployment.
5. **Automatic or human:** **Previously decided:** single-user machines only. Revisit only if deployment scope changes.

### I-2 — Secret handling is repository-safe, but local `.env` permissions rely on the single-user assumption

1. **Description:** `.env` is ignored and absent from Git history; API keys pasted into batch flows are not persisted. The current local `.env` is mode `0644`, which is typical of manually created files and readable by other local accounts on many Unix systems.
2. **Files and locations:** `.gitignore:1`, `.env.example:1-2`, credential loaders in `customizable_transcription/core.py:302-327`; local filesystem mode observed during review.
3. **Why it matters:** This is acceptable only under the stated single-user threat model. If other OS users are in scope, stored provider credentials may be exposed.
4. **Recommended correction:** Document `chmod 600 .env` (or create it with owner-only permissions) and prefer pasted, non-persisted keys for higher-assurance use.
5. **Automatic or human:** **Previously accepted through the single-user constraint.** The documentation hardening is safe but not required under the current scope.

### I-3 — Dependency audits are clean, but builds are not fully immutable

1. **Description:** Direct Python and development dependencies are exact-pinned, npm uses a lockfile, and current audits are clean. Transitive Python resolution is not hash-locked and GitHub Actions use mutable major tags such as `actions/checkout@v4`.
2. **Files and locations:** `requirements.txt:1-17`, `requirements-dev.txt:1-18`, `profiles/worksheets/package-lock.json`, `.github/workflows/tests.yml:47-56`, `.github/workflows/tests.yml:83-94`, `.github/workflows/tests.yml:110-156`.
3. **Why it matters:** A future clean install or CI run is not fully reproducible and still trusts upstream tag movement and dependency resolution.
4. **Recommended correction:** For stronger supply-chain assurance, use a fully resolved hash-locked Python environment and pin Actions to reviewed commit SHAs with automated update PRs.
5. **Automatic or human:** **Previously accepted risk.** No new decision is required unless reproducible/immutable builds become a project goal.

### I-4 — Python/HTTP coverage is strong, but browser behavior remains unexecuted in CI

1. **Description:** The 274-test suite covers substantial parsing, HTTP security, concurrency, persistence, and provider failure behavior. JavaScript receives syntax checking and one offline parser harness, but Prompt Builder serialization, dynamic field visibility, multipart construction, translations, and browser navigation are not exercised in a DOM/browser.
2. **Files and locations:** `tests/`, especially the flat preflight fixture at `tests/test_prompt_builder_preflight.py:70-77`; browser logic in `static/prompt-builder.js`, `static/app-common.js`, `static/i18n.js`, `xls_conversion/app.js`; CI at `.github/workflows/tests.yml:38-102`.
3. **Why it matters:** M-1 passes all current tests because the browser's structured example object is never exercised end-to-end. Similar wiring/state regressions can remain invisible despite a green Python suite.
4. **Recommended correction:** Add a small Playwright smoke suite for Prompt Builder save/load/preflight and one XLS conversion flow, or at minimum extract browser serialization into testable JavaScript modules and run them under Node.
5. **Automatic or human:** **Previously decided:** browser automation is deferred. Revisit if recent Prompt Builder growth changes that cost/benefit decision.

## Overall assessment

The codebase is materially stronger than at the prior review: all 274 tests pass, dependency audits are clean, request/file defenses are well designed, and the earlier Off-Peak findings were addressed thoughtfully. It is not ready for a PASS because ambiguous batch submission can create untracked paid work, continuation merging can silently erase extracted data, and the structured preflight/capacity policies remain unresolved.

OVERALL STATUS: HUMAN_DECISION_REQUIRED
