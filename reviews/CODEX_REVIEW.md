# Codex Independent Code and Security Re-Review

Review date: 2026-11-13

Reviewed revision: `2aaddbd` (`main`, matching `origin/main`)

Scope: the complete repository, not only recent changes. The review covered 176 tracked files and approximately 34,427 lines of Python/JavaScript, plus HTML/CSS, installer scripts, generated DOCX/ZIP assets, configuration, workflows, dependencies, documentation, Git history, and the untracked workspace file noted below. Changes since the prior security review were examined in detail, especially corrected-transcript translation, year checking, Prompt Builder import/delete behavior, the package rename, PDF removal, and the new Windows/macOS installers.

## Executive result

| Severity | Count |
|---|---:|
| CRITICAL | 0 |
| HIGH | 1 |
| MEDIUM | 2 |
| LOW | 2 |
| INFORMATIONAL | 4 |

The application retains strong localhost request hardening, archive/file bounds, path validation, output escaping, atomic profile writes, run-slot controls, and provider-error handling. Prior Off-Peak submission and continuation-merge findings are resolved. The main new risk is the Windows installer shipping a security-stale Python interpreter and both installers being unable to upgrade an existing embedded interpreter. CSV formula neutralization and translation request sizing also have reproducible gaps.

## Review basis and diagnostics

- `.venv/bin/pytest -q -r fEsxX`: **408 passed, 1 skipped in 29.02s**. The skipped shortcut-creation test is Windows-CI-only. Loopback access was required for live HTTP tests.
- Python bytecode compilation: **passed** for application and test modules.
- `node --check`: **passed** for all tracked JavaScript files.
- Offline XLS parser regression harness: **passed**, 6 entries parsed with expected fields.
- `.venv/bin/python -m pip check`: **passed**, no broken installed requirements.
- `.venv/bin/python -m pip_audit -r requirements.lock -r requirements-dev.txt`: **no known package vulnerabilities found**.
- `npm audit --audit-level=high` in `profiles/worksheets/`: **0 vulnerabilities**.
- macOS installer `bash -n`: **passed**.
- Generated worksheet DOCX/ZIP integrity checks: **passed**; all expected English and Italian bundle members were present.
- Ruff: **90 findings**: 47 `BLE001`, 10 `DTZ005`, 8 `TRY004`, 7 `ISC004`, 6 `PLW1510`, 3 `S110`, 2 `F401`, 2 `RUF059`, and one each across five other rules. Three are marked safely fixable.
- Current-tree and Git-history credential-pattern scans found no credible committed API key, private key, tracked `.env`, `.pem`, or `.key` file.
- `git diff --check` and `git fsck --no-dangling`: **passed** before these reports were replaced.
- Isolated probes reproduced the CSV control-character bypass and confirmed that XLSX cells are emitted as inline strings rather than formulas.

No application source code was modified. Only this report and `reviews/HUMAN_DECISIONS.md` were replaced.

## CRITICAL

No critical findings.

## HIGH

### H-1 — The Windows installer ships a security-stale Python and installed runtimes never upgrade

1. **Description:** New Windows installations download Python `3.12.10`. Python `3.12.11` through `3.12.16` are security releases; the current `3.12.16` release fixes multiple CVEs, including ZIP decompression memory exhaustion, TLS, URL credential handling, Expat, and certificate-trust issues. Separately, both installers skip the Python download whenever their existing base interpreter is executable. They compare only `requirements.lock`, so replacing the application folder cannot upgrade an already-installed interpreter even if a later installer changes its Python URL and checksum.
2. **Files and locations:** `Start Customizable Transcriber (Windows).bat:9-15,19-31,38-58`; `Start Customizable Transcriber (Mac).command:11-16,36-69`; update instructions at `Install Instructions.txt:57-63,115-121`; installer CI at `.github/workflows/tests.yml:104-170`. Official release evidence: [Python 3.12.16 security release](https://www.python.org/downloads/release/python-31216/), [Python 3.12.15 security fixes](https://www.python.org/downloads/release/python-31215/), and [Python 3.12.11 security fixes](https://www.python.org/downloads/release/python-31211/).
3. **Why it matters:** A fresh Windows user receives an interpreter already superseded by six security releases. This application parses uploaded ZIP-based DOCX files and makes TLS network requests, so relevant standard-library attack surfaces are exercised. Existing Windows and macOS users would also remain pinned to an older runtime after a normal application update, creating a silent patching gap that `pip-audit` cannot detect because it audits packages, not CPython itself.
4. **Recommended correction:** Immediately replace the Windows runtime with a current security-patched build. Add a runtime manifest containing the expected implementation, version, build/source identifier, and archive digest; verify it on every start and stage an atomic runtime replacement when it differs. Keep the virtual-environment lock check as a separate package-layer check. Add clean-install and old-runtime-to-new-runtime CI scenarios, assert the executed interpreter version, and document the runtime update behavior.
5. **Automatic or human:** **Human decision required.** Removing `3.12.10` is mandatory, but the supported Python line, binary distributor, upgrade cadence, and rollback policy are platform/support choices. Once selected, the manifest and upgrade mechanism can be implemented mechanically. See HD-1.

## MEDIUM

### M-1 — Leading control/whitespace characters bypass CSV formula-injection protection

1. **Description:** `_csv_safe_cell()` neutralizes a cell only when its literal first character is `=`, `+`, `-`, or `@`. A value beginning with a tab, carriage return, newline, or spaces followed by a formula trigger is written unchanged. The isolated probe produced unchanged cells for `"\t=1+1"`, `"\r=1+1"`, `"\n=1+1"`, and `"  =1+1"` while direct `"=1+1"` was prefixed.
2. **Files and locations:** `xls_conversion/spreadsheet_export.py:77-105`; exports invoked at `xls_conversion/ai_parser.py:1684-1694`. There is no dedicated formula-neutralization regression test in `tests/`.
3. **Why it matters:** XLS Conversion accepts text originating in uploaded transcripts and AI responses. Spreadsheet applications can treat leading controls/whitespace as ignorable before formula detection, allowing crafted archival text or a compromised model response to become an evaluated CSV formula when the user opens the export. XLSX output is not affected because it explicitly emits inline-string cells.
4. **Recommended correction:** Neutralize based on the first meaningful character and explicitly cover tab, CR, LF, and other spreadsheet-recognized prefix characters. Apply the policy after normalizing prohibited controls but before CSV serialization, without stripping the user's visible content. Add round-trip tests for direct triggers, leading controls/whitespace, quotes, delimiters, multiline values, and safe ordinary text.
5. **Automatic or human:** **Safe to correct automatically.** The code already establishes formula neutralization as the intended policy; this only closes bypasses in that policy.

### M-2 — Translation request limits and token estimates omit fields that are actually sent

1. **Description:** Corrected-transcript translation caps each call at 6,000 source characters, but `_source_size()` counts only the transcription and optional Church Wedding Record. The actual JSON also includes `date`, all `notes`, identifiers, flags, language arrays, and serialization overhead. The preflight token estimate uses the same incomplete count. A DOCX can therefore contain a short transcription plus a very large Notes block, pass preflight as a small request, and be sent in one oversized API call.
2. **Files and locations:** limit and intent at `transcript_translation.py:74-77`; estimate at `transcript_translation.py:496-506`; actual payload at `transcript_translation.py:633-653`; incomplete size calculation and chunking at `transcript_translation.py:656-677`; UI claim at `static/transcribe-translate.js:113-118` and `README.md:231`; coverage at `tests/test_transcript_translation.py:271-277` checks only ordinary transcription sizes.
3. **Why it matters:** The stated timeout/cost guard can be bypassed by valid document content, causing unexpectedly large paid requests, provider context/size errors, timeouts, or memory pressure. Preflight can materially understate token use precisely when the omitted metadata is large.
4. **Recommended correction:** Size the exact serialized entry payload, or conservatively include every transmitted field plus JSON overhead. Reject a single entry that exceeds the per-call bound with a preflight error instead of sending it unsplit. Base the estimate on the serialized messages actually planned for each chunk, and add oversized-date/notes and multi-language regression tests.
5. **Automatic or human:** **Safe to correct automatically.** The existing 6,000-character policy already defines the intended operational bound.

## LOW

### L-1 — Translation source text lacks an explicit prompt-injection boundary

1. **Description:** The translation system prompt says to translate final corrected text faithfully, but it never explicitly says that instructions appearing inside the `transcription`, `date`, `notes`, or `church_wedding_record` fields are data and must be ignored. The XLS extraction prompt already contains that exact defensive rule for its own source blocks.
2. **Files and locations:** translation prompt at `transcript_translation.py:546-630`; source fields at `transcript_translation.py:633-653`; the stronger XLS rule at `xls_conversion/ai_parser.py:92-95`; prompt tests at `tests/test_transcript_translation.py:213-237` cover style choices but not adversarial embedded instructions.
3. **Why it matters:** A shared or malicious corrected DOCX could contain instruction-like text that changes the semantic translation while still returning valid IDs and JSON. Structural response validation would accept that corrupted translation. The likelihood is reduced because the normal input is user-corrected historical material and system-level instructions already emphasize faithful translation.
4. **Recommended correction:** Add an explicit system rule that every supplied field is untrusted historical data, never an instruction; delimit source data clearly; and add adversarial prompt-construction/response-validation tests. Continue treating model output as reviewable rather than authoritative.
5. **Automatic or human:** **Safe to correct automatically.** This reinforces the documented intent without changing translation semantics.

### L-2 — The lint signal remains non-enforcing and internally inconsistent

1. **Description:** Ruff reports 90 findings, including two unused imports and several silent/broad exception patterns, while CI deliberately ignores lint failure. The Ruff target is Python 3.10 even though the package declares Python 3.11 as the minimum. Intentional broad catches and one synchronous loop-lambda false positive are mixed with actionable findings.
2. **Files and locations:** `pyproject.toml:21-33`; `.github/workflows/tests.yml:175-186`; representative unused production import at `handlers/test_mode_run.py:44`; current diagnostic totals above.
3. **Why it matters:** New correctness and security-relevant warnings can be added without failing CI and are difficult to distinguish from accepted debt. The mismatched target also prevents linting from accurately representing the supported language baseline.
4. **Recommended correction:** Align Ruff to `py311`, remove the safely mechanical findings, annotate deliberate exceptions narrowly, and establish a no-new-findings baseline or enforce a selected correctness/security subset while leaving stylistic rules advisory.
5. **Automatic or human:** **Partly automatic.** Mechanical cleanup and target alignment are safe. Changing the CI gate remains a maintainer policy choice; the previously documented advisory-only decision can remain if a reliable no-new-findings mechanism is used.

## INFORMATIONAL

### I-1 — Authentication remains intentionally absent under a single-user localhost model

1. **Description:** Host, Origin, SameSite/HttpOnly cookie, and CSRF checks protect browser access and DNS rebinding, but any local process that can reach port 8765 can use the application. This is documented rather than accidental.
2. **Files and locations:** `app.py:65-123,306-377`; `SECURITY.md:30-56`; coverage in `tests/test_http_security.py`.
3. **Why it matters:** Another process running as the user could read outputs, alter settings/profiles, or initiate paid work. That is outside the current single-user threat model.
4. **Recommended correction:** Keep binding strictly to loopback and retain the documented deployment restriction. Add real session authentication before any LAN, proxy, multi-user, container-shared, or remote deployment.
5. **Automatic or human:** **Previously decided; no current human decision required.** Revisit only if deployment scope changes.

### I-2 — An untracked curl cookie jar containing a CSRF token is present in the workspace

1. **Description:** Untracked file `c` is a mode-`0644` Netscape cookie jar containing a localhost `ct_token`. It is absent from Git and history and appears to be a diagnostic artifact. The token is process-scoped and likely expired, but the file demonstrates that local auth-like material can be left behind.
2. **Files and locations:** workspace file `c`; `.gitignore:1-23` does not cover common cookie-jar artifacts.
3. **Why it matters:** If created while the corresponding server process is still active, another local account/process with read access could reuse the CSRF token. Under the documented single-user model the practical exposure is low, and it is not a committed secret.
4. **Recommended correction:** Delete the artifact after confirming it is no longer needed, use owner-only permissions for diagnostic cookie jars, and optionally ignore an explicitly named diagnostics directory rather than a broad single-letter pattern.
5. **Automatic or human:** **Human cleanup, not a source-code correction.** It was intentionally left untouched by this review.

### I-3 — Server-side tests are strong; browser behavior still has no automated execution

1. **Description:** The 409-test suite covers HTTP security, concurrency, archive handling, translation orchestration, year checks, installers' Python launcher, and data integrity. JavaScript receives syntax checking and the offline XLS parser harness, but no DOM/browser suite exercises the new translation panel, Prompt Builder import/delete without reload, dynamic state invalidation, or download flows.
2. **Files and locations:** `tests/`; client behavior in `static/transcribe-translate.js`, `static/prompt-builder.js`, `static/test-mode.js`, and `xls_conversion/app.js`; CI in `.github/workflows/tests.yml:31-170`.
3. **Why it matters:** Server contracts can pass while browser wiring, event handling, accessibility state, or multipart construction is broken. The new features materially expanded this unexecuted layer.
4. **Recommended correction:** Add a small Playwright smoke suite for translation preflight/run, Prompt Builder import/delete/save, and one XLS export flow, or extract the most important serializers/state transitions into Node-testable modules.
5. **Automatic or human:** **Previously deferred; no current human decision required.** Revisit as the client-side surface grows.

### I-4 — Package audits are clean, but supply-chain immutability is incomplete

1. **Description:** Runtime and development Python packages are exact-pinned, npm has a lockfile, downloaded interpreters have archive digests, and current audits are clean. Python package hashes are not locked, and GitHub Actions use mutable major tags such as `actions/checkout@v4`.
2. **Files and locations:** `requirements.lock`, `requirements-dev.txt`, `profiles/worksheets/package-lock.json`, `.github/workflows/tests.yml`, both start scripts.
3. **Why it matters:** A future clean install or CI run still trusts package-index responses and mutable Action tags. This is a defense-in-depth/reproducibility concern, distinct from H-1's current vulnerable interpreter.
4. **Recommended correction:** For stronger assurance, use hash-locked Python artifacts and pin Actions to reviewed commit SHAs with automated update PRs.
5. **Automatic or human:** **Previously accepted risk; no current human decision required.**

## Prior findings and architecture assessment

- Ambiguous Off-Peak submission is now reported as outcome-unknown; Claude create retries are disabled and Gemini receives a unique display name.
- Continuation merge invariants are applied in place before the persisted row is selected; blanks cannot erase prior values and conflicts preserve the original or reject identity mismatches.
- Prompt Builder preflight now uses a dedicated structured serializer, key checks have explicit bounds, and the Off-Peak aggregate cap is 500 MB.
- No confirmed material dead code was found. The legacy regex parsers remain intentionally retained as documented reference/regression code.
- The handler/module split, atomic profile store, bounded archive parsing, and central HTTP security checks are coherent and maintainable despite the remaining lint debt.

The repository is not eligible for PASS because the shipped Windows runtime currently omits known interpreter security fixes, and the CSV/request-sizing gaps warrant remediation.

OVERALL STATUS: HUMAN_DECISION_REQUIRED
