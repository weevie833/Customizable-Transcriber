# Independent Software Engineering and Security Review

Review date: 2026-09-10

Scope: the complete current repository, including the Python HTTP application, browser JavaScript, XLSX/DOCX readers and writers, AI-provider integrations, profile/settings persistence, tests, build tooling, dependency manifests, and CI configuration. Source code was not modified.

Diagnostics performed:

- `pytest tests/`: 170 passed.
- Offline JavaScript parser regression harness: passed (6 entries).
- `pip check`: no broken installed requirements.
- `pip-audit` against `requirements.txt` and `requirements-dev.txt`: no known vulnerabilities at review time.
- `npm audit` against `profiles/worksheets/package-lock.json`: no known vulnerabilities at review time.
- Ruff: 109 findings, including 20 unused imports, 32 broad exception catches, and several high-complexity functions.
- Bandit: no high-severity results; reported uses of `ElementTree`, subprocesses, and test-only `exec`. The untrusted DOCX parser has explicit size and DTD/entity guards, so the generic `ElementTree` warning was not treated as an independently exploitable issue.
- Branch-aware Python coverage: 67% overall; `app.py` 43%, `customizable_transcription/core.py` 56%, and `xls_conversion/ai_parser.py` 56%. Browser JavaScript is not covered by this measurement and has no automated browser test suite.
- Current-tree and Git-history secret-pattern scans found no committed API keys or private keys.

## CRITICAL

No critical findings.

## HIGH

### H-1. The loopback server has CSRF protection but no client authentication or authorization boundary

1. **Description:** Any process or operating-system user able to connect to the machine's loopback interface can bootstrap the CSRF cookie with a GET and then call every read/write endpoint. The random cookie proves that a request came through the app, but it is issued to every caller and therefore is not authentication.
2. **Files and locations:** `app.py:142-145`, `app.py:1548-1613`, `app.py:1615-1813`, and `app.py:3115-3122`; the resulting capabilities include profile mutation/deletion, settings changes, output/status reads, and AI-backed Prompt Builder preflight calls. `SECURITY.md:33-41` declares a single-local-user threat model.
3. **Why it matters:** On a shared machine, another local account/process can read current generated output, obtain profile content, delete or overwrite user profiles, change the selected source folder, stop jobs, and potentially consume a stored `.env` API key indirectly through endpoints that permit provider fallback. Host/Origin/SameSite controls protect against ordinary remote web pages and DNS rebinding, but they do not protect against a local HTTP client. The impact includes confidentiality loss, destructive state changes, and provider charges.
4. **Recommended correction:** Generate a separate authentication capability at launch and require it on every route, including GETs; deliver it only to the launched browser/user (for example through a one-time launch URL followed by a protected session). Consider refusing to run in shared/server contexts unless an authenticated mode is configured. Keep the current Host/Origin/CSRF controls as additional defenses.
5. **Automation:** **Requires a human decision.** The maintainer must decide whether shared-host isolation is supported or explicitly unsupported and choose a usable authentication/session design. Implementation and tests can then be automated.

## MEDIUM

### M-1. Batch source files are selected by extension without size, content, or resolved-path validation

1. **Description:** Recursive batch discovery accepts any regular path ending in `.jpg`, `.jpeg`, `.png`, or `.pdf`; later provider code reads the entire file into memory. It neither verifies magic bytes nor sets a per-file size ceiling, and a file symlink may resolve outside the folder the user selected.
2. **Files and locations:** `customizable_transcription/core.py:270-287`, `customizable_transcription/core.py:534-623`, and `customizable_transcription/core.py:696-756`. By contrast, the single-upload path performs type sniffing and request-size checks at `app.py:282-311` and `app.py:2193-2228`.
3. **Why it matters:** A large or sparse mislabeled file can exhaust memory when `read_bytes()` or base64 encoding runs. A mislabeled file or outward-pointing symlink can also transmit bytes the user did not intend to send to Google or Anthropic. The extension-only batch policy behaves differently from the safer upload policy.
4. **Recommended correction:** Before every provider call, reject symlinks or require `resolved_path.is_relative_to(resolved_source_root)`, apply a documented per-file byte limit, and validate the actual JPEG/PNG/PDF signature. Re-check immediately before opening to reduce time-of-check/time-of-use exposure and stream where the SDK permits it.
5. **Automation:** **Partly automatic; human decision required** for whether intentional in-folder symlinks should remain supported and for the appropriate file-size limit.

### M-2. “Process all” bypasses the documented image-count limit and AI endpoints have no server-side job/cost control

1. **Description:** Typed ranges are capped at 5,000 images, but `process_all=True` obtains marker numbers through `all_image_numbers()` without applying `MAX_IMAGES_PER_REQUEST`. XLS preflight and conversion then make sequential provider calls inside request threads, with no shared run lock, cancellation, or concurrency quota.
2. **Files and locations:** `xls_conversion/ai_parser.py:871-908`, `xls_conversion/ai_parser.py:977-1008`, `xls_conversion/ai_parser.py:1206-1264`, and `xls_conversion/ai_parser.py:1495-1701`; HTTP entry points are `app.py:1949-2049`. Client confirmation at `xls_conversion/app.js:484-497` is advisory and can be bypassed by direct requests.
3. **Why it matters:** A large document or repeated concurrent requests can run thousands of billable AI calls, occupy server threads for a very long time, and continue after the browser request is abandoned. This is both a resource-exhaustion and unexpected-cost risk.
4. **Recommended correction:** Enforce the same hard server-side count cap for explicit ranges and `process_all`; add a bounded job queue/concurrency limit, cancellation, request ownership, and a server-validated maximum estimated call count. Reject new XLS AI jobs when the quota is exhausted.
5. **Automation:** **Requires a human decision** on acceptable call/cost limits and whether XLS work should become a background job; the enforcement itself can then be implemented automatically.

### M-3. The advertised saved `.env` key workflow is rejected by the primary user flows

1. **Description:** The key-loading layer supports `.env` fallback, and the README says users may save a key once instead of pasting it each run. However, Transcribe, Test Mode, and XLS preflight/conversion enforce non-empty browser fields before the fallback can be used. Browser JavaScript enforces the same requirement.
2. **Files and locations:** `README.md:76-97`, `customizable_transcription/core.py:146-179`, `app.py:1836-1843`, `app.py:1955-1965`, `app.py:1997-2005`, `app.py:2584-2589`, `pages/transcribe.py:229-271`, `pages/test_mode.py:191-245`, and `xls_conversion/app.js:500-511,629-644`.
3. **Why it matters:** A documented setup option does not work for the application's central workflows. Users can reasonably store a key on disk based on the documentation and still be blocked, while code paths retaining fallback behavior become inconsistently tested and understood.
4. **Recommended correction:** Choose one policy: allow a blank submitted key to use the provider-specific environment value and indicate only that a key is configured (never reveal it), or remove fallback from the runtime and documentation. Make error messages provider-neutral.
5. **Automation:** **Requires a human product/security decision** because enabling stored keys changes the local authorization and persistence risk; the selected policy can then be applied consistently.

### M-4. Profile persistence prevents corruption but permits lost updates and creation collisions

1. **Description:** Atomic temp-file replacement ensures valid JSON, but profile read/modify/write operations are not serialized and do not use revision checks. Two tabs can update the same profile with last-writer-wins behavior; two simultaneous creates can both select the same available ID before either writes it.
2. **Files and locations:** `profiles_store.py:46-68`, `profiles_store.py:228-230`, `profiles_store.py:325-427`, and request handlers `app.py:2150-2191`, `app.py:2282-2446`. The Transcribe and Test locks protect run state, not the shared profile store.
3. **Why it matters:** Concurrent browser tabs or request threads can silently discard a user's changes. Atomic replacement avoids a truncated file but does not provide transaction isolation or conflict detection.
4. **Recommended correction:** Add one profile-store lock covering ID allocation and mutations, plus an optimistic revision/version token so stale browser tabs receive a conflict instead of overwriting newer content. If multiple app processes are supported, use an OS-level file lock or transactional store.
5. **Automation:** **Requires a human decision** on single-process versus multi-process support and the desired conflict UX. A process-local lock alone is safe to add automatically but does not fully resolve stale-edit loss.

### M-5. Test Mode's multi-batch key and failure behavior does not match its apparent isolation intent

1. **Description:** Test Mode stores one key for slot A and one for slot B across every queued batch. A queue that changes provider in the same slot is impossible to run because one key cannot satisfy both providers. In addition, a validation or setup failure for one run is caught outside the run loop and aborts all remaining independent runs.
2. **Files and locations:** `app.py:1436-1544`, especially the loop and outer exception at `app.py:1473-1539`; queue validation/key assignment at `app.py:2584-2630`; UI fields at `pages/test_mode.py:1198-1201`.
3. **Why it matters:** The code comments describe each queued run as independent and explicitly discuss queues mixing Gemini and Claude, but queue ordering/provider selection can make the configuration unsatisfiable, and one unavailable model prevents unrelated later comparisons from completing. Users may pay for early runs yet receive an incomplete comparison set.
4. **Recommended correction:** Associate credentials by provider (or by queued run) rather than by A/B position. Catch validation/run failures per run, record that run's failure, and continue with unaffected runs unless the user chose fail-fast behavior.
5. **Automation:** **Requires a human UX decision** on provider-key entry and fail-fast versus continue semantics; implementation can then be automated.

### M-6. Test Mode DOCX output omits metadata that the architecture says every output contains

1. **Description:** Normal Transcribe output passes native language, translations, record type, model, and profile label into `write_docx()`. Test Mode passes only native language and translations.
2. **Files and locations:** Normal call at `app.py:1407-1416`; Test Mode call at `app.py:1505-1511`; metadata writer at `app.py:1189-1305`; stated invariant at `docs/DESIGN.md:47-49` ("Every DOCX").
3. **Why it matters:** Test artifacts lose the model/profile provenance needed for trustworthy comparison and may omit record-type metadata used by XLS Conversion. The filename contains some model information, but that is weaker and can be renamed.
4. **Recommended correction:** Pass the same `record_type`, `model`, and `profile_label` values in Test Mode, and add a regression test that opens generated DOCX XML and verifies all declared metadata.
5. **Automation:** **Safe to automate** if the documented “Every DOCX” invariant is authoritative.

### M-7. Automated coverage is weak around the highest-risk orchestration and all browser state machines

1. **Description:** The test suite is substantial for several pure functions, but measured coverage is low for the HTTP/application orchestration and AI extraction modules; there is no automated browser suite for the large inline/static JavaScript state machines.
2. **Files and locations:** `tests/`, `.github/workflows/tests.yml:17-49`, `app.py` (43% measured coverage), `customizable_transcription/core.py` (56%), `xls_conversion/ai_parser.py` (56%), `pages/test_mode.py`, `static/prompt-builder.js`, and `xls_conversion/app.js`. Existing Node coverage exercises only `xls_conversion/baptism-parser.js` through `xls_conversion/tests/harness.js`.
3. **Why it matters:** Key handling, preflight invalidation, queue behavior, concurrent requests, downloads, browser rendering, and error recovery can regress while 170 tests remain green. Several issues in this review sit precisely in unexecuted branches.
4. **Recommended correction:** Add end-to-end HTTP tests for every route and failure branch; add Playwright or equivalent tests for Transcribe, Test Mode, Prompt Builder, and XLS Conversion; test file-size/symlink boundaries, profile conflicts, process-all caps, stored-key policy, cancellation, and output metadata. Add coverage thresholds focused on production modules rather than aggregate test code.
5. **Automation:** **Partly automatic.** Test scaffolding and coverage enforcement are safe to automate, but maintainers must define expected behavior for the ambiguous workflows above and decide how live-provider calls are contract-tested.

## LOW

### L-1. Dynamic HTML and the primary output download are cacheable

1. **Description:** JSON/status responses usually send `Cache-Control: no-store`, but dynamic HTML pages and `/download` do not. Those pages embed saved profile content and current state; the download contains generated transcription data.
2. **Files and locations:** `app.py:3057-3085`; compare with `app.py:3087-3094` and `app.py:2721-2741`.
3. **Why it matters:** Browser caches/history may retain sensitive archival text, local paths, status messages, or profile reference content beyond the running session, contrary to the more careful no-store treatment on adjacent endpoints.
4. **Recommended correction:** Send `Cache-Control: no-store` on dynamic HTML, generated downloads, error responses containing local details, and profile exports. Static versioned assets may use a separate cache policy.
5. **Automation:** **Safe to automate.** Add response-header regression tests.

### L-2. The Content Security Policy permits all inline scripts and styles

1. **Description:** The global CSP contains both `script-src 'unsafe-inline'` and `style-src 'unsafe-inline'`.
2. **Files and locations:** `app.py:1554-1564`; large inline scripts/styles are generated in `pages/transcribe.py`, `pages/test_mode.py`, `pages/prompt_builder.py`, `pages/home.py`, and `app.py:1027-1160`.
3. **Why it matters:** Existing escaping appears deliberate, but an introduced HTML-injection bug would not be contained by CSP because injected inline script is allowed. This removes an important second layer against stored profile/UI data becoming executable.
4. **Recommended correction:** Move inline scripts/styles to static assets or use per-response nonces/hashes; remove `unsafe-inline` from `script-src`, then from `style-src` where feasible. Add a CSP regression test.
5. **Automation:** **Partly automatic.** Mechanical extraction is possible, but the breadth of generated-page JavaScript requires human review to avoid behavior regressions.

### L-3. The custom `.env` loader mutates arbitrary process environment variables and overrides existing values

1. **Description:** Every `KEY=value` line in `.env` is copied into `os.environ`, not only the two supported provider keys, and existing exported environment values are overwritten.
2. **Files and locations:** `customizable_transcription/core.py:146-179`; subprocesses resolved through environment `PATH` at `app.py:758-892` and network clients created at `customizable_transcription/core.py:331-359`.
3. **Why it matters:** Accidental or malicious `.env` entries such as proxy variables or `PATH` can change network routing and executable resolution. It also violates the common expectation that explicitly exported environment variables take precedence over a dotenv file.
4. **Recommended correction:** Parse only `GEMINI_API_KEY` and `ANTHROPIC_API_KEY`, do not overwrite already-set environment values, and avoid globally mutating `os.environ` when the values can be returned directly. Resolve OS helper executables defensively where practical.
5. **Automation:** **Safe to automate** after confirming the desired environment-precedence rule.

### L-4. A syntactically valid non-object profile can break all profile loading

1. **Description:** `load_custom_profiles()` catches unreadable/invalid JSON but passes any valid JSON value directly to dict-only normalization and `.get()` calls.
2. **Files and locations:** `profiles_store.py:233-275`, especially `profiles_store.py:251-267`; `normalize_profile_sections()` at `profiles_store.py:216-225`.
3. **Why it matters:** A file containing valid JSON such as `[]`, `null`, or a string can make every profile-dependent page fail rather than being skipped/quarantined. This is a fragile recovery path for manually copied, partially migrated, or externally synchronized profile files.
4. **Recommended correction:** Require a JSON object before normalization, validate the profile schema and field sizes, skip or quarantine invalid files, and surface a non-fatal warning naming the affected file.
5. **Automation:** **Safe to automate.** Preserve valid legacy object profiles and add malformed-profile tests.

### L-5. Python installs and CI actions are not fully reproducible or supply-chain pinned

1. **Description:** Direct Python packages are version-pinned, but transitive dependencies are not locked, two security floors have no upper/exact pin, and GitHub Actions use mutable major-version tags rather than commit SHAs.
2. **Files and locations:** `requirements.txt:1-12`, `requirements-dev.txt:1-9`, and `.github/workflows/tests.yml:30-38,60-75`. The npm build tree does have a lockfile with integrity hashes.
3. **Why it matters:** A fresh install or CI run can resolve a different transitive graph without a repository change, causing regressions or consuming a newly compromised release. Mutable action tags are a CI supply-chain exposure.
4. **Recommended correction:** Generate and review a cross-platform constraints/lock strategy with hashes where feasible, update it through Dependabot, and pin third-party actions to full commit SHAs with update comments.
5. **Automation:** **Requires a human dependency-policy decision** because Python platform/version compatibility affects the locking approach; lock and action updates can then be automated.

### L-6. The codebase retains approximately 2,500 lines of dormant regex parsers, two without regression coverage

1. **Description:** `baptism-parser.js`, `matrimony-parser.js`, and `morti-parser.js` are not loaded by the live XLS Conversion UI. Only the baptism parser is exercised by the offline Node harness.
2. **Files and locations:** `xls_conversion/baptism-parser.js`, `xls_conversion/matrimony-parser.js`, `xls_conversion/morti-parser.js`, `xls_conversion/index.html:185-196`, `xls_conversion/tests/harness.js`, and explicit documentation at `docs/DESIGN.md:188-198`.
3. **Why it matters:** Dormant production-adjacent code increases review surface and creates ambiguity about the authoritative extraction path. The two untested variants can silently decay, making future reuse risky.
4. **Recommended correction:** Either remove/archive these parsers outside the runtime repository, or formally support them with an explicit entry point and parity tests for all three. Make the live AI path unmistakably authoritative in developer documentation.
5. **Automation:** **Requires a human decision** on whether these parsers are historical reference or supported fallback behavior.

### L-7. Index Compare exposes multiple worksheets but the browser always maps only the first one

1. **Description:** The server returns every candidate worksheet when schema detection fails, but the mapping UI unconditionally chooses `entry.worksheets[0]` and provides no worksheet selector.
2. **Files and locations:** `index_compare/reader.py:136-153,282-327`, `app.py:2832-2887`, and `pages/test_mode.py:456-470`.
3. **Why it matters:** A workbook whose first usable tab is instructions/metadata and whose later tab holds the index cannot be correctly mapped, even though the backend explicitly gathered the later sheet. Users may map and compare the wrong data or be unable to proceed.
4. **Recommended correction:** Render a worksheet selector when more than one worksheet is returned, refresh header/mapping choices when it changes, and submit the selected worksheet name. Add a multi-sheet HTTP/browser test.
5. **Automation:** **Safe to automate** if selection of a non-first worksheet is intended; minor UX review is advisable.

### L-8. Routing/orchestration remains highly concentrated and static quality checks are absent from CI

1. **Description:** `app.py` is 3,126 lines and combines routing, parsing, provider orchestration, migrations, document generation, native subprocess integration, background-job logic, and most endpoint handlers. Ruff reports 109 issues, including 20 unused imports and several functions with 39 branches or more than 100 statements; CI does not run a linter or security static analyzer.
2. **Files and locations:** `app.py` throughout, especially `Handler.do_POST()` at `app.py:1697-1933`; `customizable_transcription/core.py:696-763`; `xls_conversion/ai_parser.py:1484-1714`; `.github/workflows/tests.yml:17-82`; documentation describing `app.py` as “routing and the Handler class only” at `README.md:232-243`.
3. **Why it matters:** High-complexity orchestration makes security invariants and state transitions difficult to audit, encourages broad exception handling, and raises regression risk. Unused imports and stale architectural documentation indicate incomplete modularization.
4. **Recommended correction:** Split endpoint groups and service layers by feature, centralize response/error handling and request validation, remove dead imports, configure Ruff/Bandit (with justified suppressions), and enforce them in CI.
5. **Automation:** **Partly automatic.** Lint configuration and dead-import cleanup are safe to automate; architectural decomposition requires human sequencing and regression review.

## INFORMATIONAL

### I-1. Existing defensive controls and diagnostic baseline are strong in several areas

1. **Description:** The repository has explicit Host/Origin/CSRF defenses, output/profile path validation, DOCX/XLSX decompression limits, formula-injection mitigation, XML character sanitation, atomic text replacement, provider timeouts/retries, multi-OS CI, scheduled dependency audits, and focused regression tests for previously fixed security defects.
2. **Files and locations:** `app.py:121-218,246-430,1548-1613,2072-2148`; `profiles_store.py:40-88,135-158,511-539`; `index_compare/reader.py:16-134`; `xls_conversion/spreadsheet_export.py:22-105,281-321`; `.github/workflows/tests.yml`; `tests/test_docx_security.py`, `tests/test_http_security.py`, and `tests/test_index_compare_reader_security.py`.
3. **Why it matters:** These controls materially reduce common localhost-web, archive-bomb, traversal, XML, and spreadsheet-injection risks. All current tests passed, and current dependency/security scans found no known vulnerable locked package or committed credential.
4. **Recommended correction:** No correction is required for this item; retain these controls and add regression coverage when adjacent code changes.
5. **Automation:** **Not applicable.** Ongoing scheduled audits and tests are already automated.

## OVERALL STATUS

OVERALL STATUS: CHANGES_REQUIRED

PASS is not appropriate because unresolved authorization-boundary, resource/cost-control, file-ingestion, concurrency, correctness, and test-coverage issues warrant remediation.
