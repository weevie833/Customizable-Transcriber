# Response to CODEX_REVIEW.md

Every finding below was independently verified against the actual source (not
taken on Codex's word), and each recommended correction was evaluated for
regressions, compatibility problems, architectural impact, and product-decision
scope before any code was changed. Where a fix was safe and required no
product/architecture decision, it was implemented and tested. Where a finding
was valid but the fix required a decision this role isn't authorized to make
(a UX tradeoff, a security-posture/threat-model choice, a size/policy limit,
an architectural rewrite), the finding is marked `HUMAN_DECISION_REQUIRED` and
left unimplemented, sometimes with a smaller, decision-free sub-part already
resolved.

**Validation performed after all changes:** `pytest tests/` → 182 passed (up
from Codex's reported 170; 12 new regression tests added, 0 removed, 0
modified in ways that weaken a prior assertion). The offline
`xls_conversion/tests/run_parser_test.py` Node-driven harness still passes (6
entries). `py_compile` across every touched module succeeds. `ruff check
--select F401` dropped from 20 findings to 1 (an intentional, now-documented
re-export required by test sandboxing — see L-8). Every new/changed test was
also verified to actually fail against the pre-fix code (via `git stash` on
just that file) before the fix was applied, to confirm each test exercises
the real bug rather than passing vacuously.

---

## CRITICAL

No findings.

## HIGH

### H-1. Loopback server has CSRF protection but no client authentication/authorization boundary

**HUMAN_DECISION_REQUIRED**

Verified accurate: `_security_check()` (`app.py`) validates Host, Origin, and
a CSRF cookie, but the cookie is handed to *any* caller that GETs the server
first — it proves a request came through this app's own browser session, not
that the caller is an authorized user. `SECURITY.md` explicitly scopes this
app's threat model to "one local user," not a shared machine with multiple OS
accounts/processes reaching the same loopback port, so there is a real gap
between that documented scope and what the current controls actually enforce
against another local account.

**Decision needed:** whether this app should support (a) remaining
single-local-user only, with the gap explicitly documented as out of scope in
`SECURITY.md` (the CSRF/Host/Origin trio already fully defends the stated
scope), or (b) adding a real per-launch authentication boundary (e.g. a
one-time launch token/URL plus a protected session) for shared-machine use.
Option (b) is a genuine new feature (session issuance, expiry, UI changes to
every page load) with real usability tradeoffs (a bookmarked URL would stop
working, browser restarts would need re-authentication), not a bug fix — it
changes what "just open the app" means for every user, including the
single-user majority this app is built for today. I did not implement either
option unilaterally.

## MEDIUM

### M-1. Batch source files selected by extension only, no size/content/symlink validation

**HUMAN_DECISION_REQUIRED (partially resolved)**

Verified: `source_files()` (`customizable_transcription/core.py`) filters by
suffix only, with no magic-byte check, no per-file size ceiling, and no
symlink/path-containment check before the full file is read into memory and
base64-encoded for the provider call.

**Resolved now — content-type validation:** `transcribe_image()` now sniffs
the file's real leading bytes via the existing `sniff_file_type()` helper
(already used by the single-upload Preflight/DOCX paths) before sending
anything to a provider, and uses the *detected* type as the authoritative
MIME type rather than trusting the extension. A file that doesn't match a
supported JPEG/PNG/PDF signature — e.g. a mislabeled/renamed file the
extension-only folder scan can't distinguish — is now rejected with a clear
error, which `run_batch()`'s existing per-image `try/except` turns into one
failed image rather than corrupting the batch or forwarding
content mislabeled by extension to Google/Anthropic.
- Files changed: `customizable_transcription/core.py` (`transcribe_image()`,
  `_transcribe_image_gemini()`, `_transcribe_image_claude()` now take raw
  bytes instead of re-reading the path internally; `mimetypes` import
  removed as it's no longer used).
- New test: `tests/test_batch_file_content_sniffing.py` (2 tests, both
  confirmed to fail on the pre-fix code and pass after).

**Left as a human decision — size ceiling and symlink policy:** what
per-file byte limit is appropriate is a product fact I don't have (this
app's users are archivists working with real high-resolution scans; an
aggressive limit could reject legitimate source images, while too generous a
limit doesn't meaningfully bound memory use). Similarly, whether an
in-folder symlink is a supported, intentional way some users organize a
source folder, or should always be rejected, is a usage-pattern question,
not a technical one. Implementing either without that input risks breaking
real workflows or providing false security. Codex's own automation note
agrees ("Partly automatic; human decision required for... size limit").

### M-2. "Process all" bypasses the documented image-count limit; no job/cost control

**HUMAN_DECISION_REQUIRED (partially resolved)**

Verified both halves:
1. `parse_image_range()` enforces `MAX_IMAGES_PER_REQUEST` (5,000) on a typed
   range, but `all_image_numbers()` (used by "Process all") had no equivalent
   cap — a document with more image markers than that would simply run every
   one of them as sequential, billable AI calls inside the request thread.
2. `parse_xls_source`/`preflight_xls_source` and the functions they call
   (`xls_conversion/ai_parser.py`) run entirely synchronously within the
   HTTP request handler thread, with no shared job lock, cancellation, or
   concurrency quota — confirmed by reading both handlers directly; unlike
   `/run`/`/test-mode/run`, there is no background-job/state-machine
   architecture here at all.

**Resolved now — closing the cap inconsistency:** Added
`all_image_numbers_capped()`, which applies the exact same
`MAX_IMAGES_PER_REQUEST` ceiling "Process all" was silently exempt from, and
wired it into both `preflight_generic()` and `parse_generic()`'s
`process_all` branches. This is not a new policy choice — it applies a limit
this codebase's own maintainers already chose and already enforce on the
sibling code path, closing an inconsistency rather than introducing a new
threshold. A document whose real, already-transcribed content exceeds 5,000
images now gets the same clear, actionable error a huge typed range already
gets, instead of silently attempting an unbounded sequential run.
- Files changed: `xls_conversion/ai_parser.py`.
- New tests: `tests/test_image_range.py` (`test_process_all_within_cap_is_allowed`,
  `test_process_all_over_cap_is_rejected_not_silently_processed`).

**Left as a human decision — job architecture:** turning XLS Conversion's
synchronous request-thread model into a background job system with
cancellation and a concurrency quota (matching `/run`'s existing
state/lock/progress-log pattern) is a real architectural change with its own
UX (progress polling, a Stop button, job history) — not something to bolt on
silently. Codex's own note agrees this needs a decision on "whether XLS work
should become a background job."

### M-3. Advertised `.env` key workflow rejected by primary UI flows

**HUMAN_DECISION_REQUIRED**

Verified: `run_job()`/`run_test_job()`/XLS Conversion's handlers all require
a non-empty pasted key field before ever reaching `api_key()`/
`claude_api_key()`'s `.env`-fallback logic (`app.py:1830-1836` region and
equivalents) — a user who saved a key in `.env` per the README still cannot
run a job without pasting it again.

**Decision needed:** whether to (a) allow a blank submitted key to silently
use the provider's environment-configured key (only indicating "a key is
configured," never revealing it), or (b) remove the `.env` fallback from the
runtime and documentation entirely and make the browser field authoritative.
Option (a) has a real security/UX dimension on a shared machine (another
local user's browser session could unknowingly run a job under the first
user's stored key) that directly overlaps with H-1's own threat-model
question — the two should probably be decided together. I did not pick a
side.

### M-4. Profile persistence permits lost updates and creation collisions

**HUMAN_DECISION_REQUIRED (partially resolved)**

Verified: `atomic_write_text()` guarantees a well-formed file on disk but
provides no cross-request serialization — `save_custom_profile()`'s
id-collision-avoidance loop (checking `find_profile_path()`, then writing)
had a real TOCTOU window between two request threads (this app runs
`ThreadingHTTPServer`), and `update_profile()`/`update_full_profile()`/
`delete_profile()` all read-then-write with no lock either.

**Resolved now — closing the concurrent-create/mutation race:** Added one
process-local `_profile_write_lock` in `profiles_store.py`, covering the
full body of `save_custom_profile()`, `update_full_profile()`,
`update_profile()`, and `delete_profile()`. This guarantees two
near-simultaneous creates of the same name always land on two distinct ids
and two distinct files (never one silently overwriting the other before
either finishes), and that no mutation of one profile can interleave with
another mutation of the *same* profile mid-write. This is a pure
concurrency-correctness fix with no behavior change for the ordinary
single-request case, so no product decision was needed to add it.
- Files changed: `profiles_store.py`.
- New test: `tests/test_profile_store_concurrency.py` — reproduces the
  pre-fix collision deterministically (confirmed to fail on the unlocked
  code, pass on the locked code) by widening the check-then-write window
  with an injected delay.

**Left as a human decision — stale-edit/lost-update UX:** the lock above
does *not* add optimistic conflict detection for two browser tabs that both
loaded the same already-saved profile and edit it independently — the
second save still silently wins (last-writer-wins), by design, since
resolving that needs a revision/version token plus a conflict UI ("someone
else changed this profile, reload or overwrite?") — a UX decision, not a
locking mechanism. Codex's own note agrees a lock alone "does not fully
resolve stale-edit loss."

### M-5. Test Mode's key/failure handling doesn't match its documented independence

**HUMAN_DECISION_REQUIRED**

Verified both halves in `app.py`:
1. `run_test()` takes exactly one API key per slot (A/B) for the *entire*
   queue — a queue whose runs mix providers within the same slot cannot be
   satisfied by one key, confirmed by reading `resolve_run_batches()`/the
   key-matches-provider validation loop.
2. `run_test_job()`'s per-run loop (`for run_id, label, model, ... in
   run_specs`) sits inside one outer `try/except Exception` at the function
   level — a `validate_api_key_with_retry()` failure (or any other exception)
   on run N aborts every remaining queued run as one "Fatal error," even
   though the function's own docstring states each run is independent
   ("Nothing from one run... is read back into another run's prompt or
   config, so every run in the queue is unaffected by whatever the others
   produced").

**Decision needed:** (a) how credentials should actually be entered/scoped
(per-provider vs. per-slot vs. per-queued-run — a real form-design question),
and (b) whether a failed run should abort the rest of the queue (current,
undocumented behavior) or continue with the remaining runs reporting that one
run's own failure (fail-fast vs. continue-on-error is a product choice,
especially since continuing after a bad API key would likely just repeat the
same failure for every other run using that same key/slot — not free to get
"right" without knowing the intended UX). I did not change this behavior.

### M-6. Test Mode DOCX output omits model/profile/record-type metadata

**RESOLVED**

Verified: the normal Transcribe path's `write_docx()` call passes
`record_type`, `model`, and `profile_label`; Test Mode's call
(`run_test_job()`) passed only `native_language`/`translation_languages`,
contradicting `docs/DESIGN.md`'s stated "every DOCX" invariant and losing
provenance needed to trust a model comparison.

**What was changed:** `run_test_job()`'s `write_docx()` call now passes
`record_type`, `model`, and `profile_label`, exactly matching the normal
Transcribe path. `write_docx()`'s signature already defaulted these to `""`,
so this is a pure completion of an existing, optional parameter — no
signature or behavior change for any other caller.
- Files changed: `app.py`.
- New test: `tests/test_test_mode_docx_metadata.py` — calls `run_test_job()`
  directly with the AI provider stubbed out, then parses the real generated
  DOCX's `word/document.xml` to confirm the "AI model:", "Prompt profile:",
  and "Record type:" lines are present.

### M-7. Weak automated coverage around orchestration and browser state machines

**HUMAN_DECISION_REQUIRED**

Verified directionally: `app.py`/`pages/test_mode.py`/`static/prompt-builder.js`/
`xls_conversion/app.js` are large, and there is no browser-automation test
suite (Playwright or similar) anywhere in the repo — only the Node-based
`xls_conversion/tests/harness.js` (offline regex parser only) and the Python
`pytest` suite. This session added 12 new regression tests directly covering
5 of this review's own findings (M-1's content-sniffing, M-2's process-all
cap, M-4's write-lock race, M-6's DOCX metadata, L-1's cache headers, L-3's
env-file scoping, L-4's malformed-profile handling) — a real, if partial,
improvement in exactly the areas this finding calls out.

**Decision needed:** adopting a browser-automation framework (Playwright is
the obvious candidate but isn't currently a dependency), committing to a
coverage threshold enforced in CI, and deciding how (or whether) to
contract-test live-provider calls are all tooling/process decisions with
ongoing maintenance cost, not something to introduce unilaterally alongside
a code-review response.

## LOW

### L-1. Dynamic HTML and the primary download are cacheable

**RESOLVED**

Verified: every JSON/status response and both static-asset routes already
send `Cache-Control: no-store`; `respond()` (every dynamic HTML page) and
`download()` (the main Transcribe `.docx`/`.md` download) were the two
exceptions — `test_download()`, right next to `download()`, already had the
header, confirming this was an inconsistency rather than an intentional
design choice.

**What was changed:** Added `Cache-Control: no-store` to both `respond()`
and `download()`, matching every other response path in the file.
- Files changed: `app.py`.
- New tests: `tests/test_http_security.py`
  (`test_dynamic_html_pages_are_not_cacheable`,
  `test_download_endpoint_is_not_cacheable`).

### L-2. CSP allows `unsafe-inline` for scripts and styles

**HUMAN_DECISION_REQUIRED**

Verified: `end_headers()`'s CSP includes `script-src 'self' 'unsafe-inline'`
and `style-src 'self' 'unsafe-inline'`, and large inline `<script>`/`<style>`
blocks are generated across `pages/transcribe.py`, `pages/test_mode.py`,
`pages/prompt_builder.py`, `pages/home.py`, and `app.py`. Moving this content
to static assets or adopting per-response nonces touches every page-render
function in the app and is exactly the kind of "breadth of generated-page
JavaScript requires human review" work Codex itself flags as not safely
automatable. Not attempted here.

### L-3. `.env` loader mutates arbitrary environment variables, overrides existing values

**RESOLVED**

Verified: `load_env_file()` copied every `KEY=value` line in `.env` into
`os.environ` unconditionally, including unrelated variables (a stray
`PATH`/proxy override) and always overwrote an already-exported value.

**What was changed:** `load_env_file()` now copies only `GEMINI_API_KEY`/
`ANTHROPIC_API_KEY` (the only two keys `.env.example` documents and the only
two this app ever reads), and never overwrites a value already present in
`os.environ` — matching the common expectation (and python-dotenv's own
default) that an explicit export takes precedence over a dotenv file. This
precedence choice is a well-established default, not a novel policy, so I
applied it directly rather than treating it as an open decision.
- Files changed: `customizable_transcription/core.py`.
- New tests: `tests/test_env_file_loading.py` (3 tests).

### L-4. A syntactically valid non-object profile JSON file breaks all profile loading

**RESOLVED**

Verified and reproduced: `load_custom_profiles()` caught unreadable/invalid
JSON (`OSError`/`json.JSONDecodeError`) but not a syntactically valid
non-object value (`[]`, `null`, a bare string/number) — passing it into
`normalize_profile_sections()`'s dict-only `.get()` calls raised an unhandled
`AttributeError`, which (confirmed via direct reproduction) takes down every
profile-dependent page for the sake of one bad file.

**What was changed:** `load_custom_profiles()` now skips a file whose parsed
JSON isn't a `dict`, the same way it already skips an unparseable one,
instead of passing it downstream.
- Files changed: `profiles_store.py`.
- New test: `tests/test_profile_store_malformed_json.py` — confirmed to
  reproduce `AttributeError` on the pre-fix code and pass cleanly after.

### L-5. Python installs and CI actions not fully reproducible/pinned

**HUMAN_DECISION_REQUIRED**

Verified: `requirements.txt`'s direct dependencies are exact-pinned, but
`cryptography`/`pyasn1` are floor-only (`>=`), no lock file exists for the
transitive dependency graph, and `.github/workflows/tests.yml` references
GitHub Actions by mutable major-version tag (`@v4`/`@v5`) rather than a
pinned commit SHA. Adopting a lock-file strategy (and the regeneration
workflow that goes with it) and SHA-pinning actions (which then needs
Dependabot or an equivalent to keep the pins current) are real, ongoing
process changes with maintenance-burden tradeoffs a single maintainer should
choose deliberately, not something to impose silently. Not attempted here.

### L-6. ~2,500 lines of dormant regex parsers, two with no regression coverage

**HUMAN_DECISION_REQUIRED**

Verified: `matrimony-parser.js`/`morti-parser.js` are not loaded anywhere in
the live UI and have no test coverage; only `baptism-parser.js` is exercised
by the offline Node harness. This exact ambiguity is already tracked as an
open item in this repo's own project notes ("worth deciding whether
`baptism-parser.js` should be wired back into the live UI as a free,
deterministic first pass, or whether the dormant parsers should be archived")
— i.e., the maintainer has already flagged this as an undecided product
question, not an oversight. I did not remove or "formally support" any of
the three files.

### L-7. Index Compare only ever maps the first worksheet

**HUMAN_DECISION_REQUIRED**

Verified: `renderIndexCompareMapping()` (`pages/test_mode.py`) unconditionally
reads `entry.worksheets[0]`, even though `index_compare/reader.py` already
returns every worksheet a workbook has when schema detection fails. Adding a
worksheet selector is a real (if small) UI feature — a new `<select>`, wiring
its `change` event to re-render the column-mapping panel for the newly
chosen sheet, and new user-facing/translatable copy — not a one-line fix,
and Codex's own note ("minor UX review is advisable") agrees. Not
implemented here.

### L-8. Routing/orchestration concentrated; no lint/security static analysis in CI

**HUMAN_DECISION_REQUIRED (partially resolved)**

Verified: `app.py` was still large and unfocused in places, and Ruff (not
previously part of this repo's toolchain — installed temporarily for this
review, then removed again since adding it to the dependency/CI story is
part of the decision below) reported 109 findings.

**Resolved now — dead-import cleanup:** Removed 15 genuinely unused imports
(`html`, `os`, `timezone` in `app.py`; 6 unused `PROMPT_BUILDER_*` constants
and 5 unused `profiles_store` re-exports left over from the earlier
modularization pass, confirmed by grepping for any reference anywhere in the
codebase — including via `monkeypatch.setattr(ctapp, "NAME", ...)`-style
string-based test patching, not just direct attribute access; `typing.Callable`
and `google.genai.errors` in `xls_conversion/ai_parser.py`; one unused import
each in two test files). **One import Ruff also flagged
(`profiles_store.USER_PROFILES_DIR` in `app.py`) was deliberately kept and
annotated `# noqa: F401`**: it exists solely so
`tests/conftest.py`'s `sandboxed_user_data` fixture can
`monkeypatch.setattr(ctapp, "USER_PROFILES_DIR", ...)` — removing it would
have silently broken every test relying on that fixture's directory
sandboxing (confirmed by grepping for the exact `setattr(ctapp,
"USER_PROFILES_DIR"...)` call site before touching anything). This is exactly
the kind of blind "remove all unused imports" mistake the review's own
automation caveat warns against, and it's why I verified every candidate
individually rather than batch-applying Ruff's autofix.
Ruff's total finding count dropped from 109 to 89 as a direct result.
- Files changed: `app.py`, `xls_conversion/ai_parser.py`,
  `tests/test_http_security.py`, `tests/test_index_compare_http.py`.

**Left as a human decision:** splitting `app.py`'s remaining routing/handler
code further, addressing the ~32 broad `except Exception` catches (several
of which — per this repo's own documented history — were deliberately
widened on purpose, e.g. to keep one bad image from aborting a whole batch;
narrowing them requires knowing which ones are deliberate vs. accidental,
case by case), and adding Ruff/Bandit as enforced CI gates are all
process/architecture decisions with real ongoing cost, not mechanical
cleanup. Not attempted here.

## INFORMATIONAL

### I-1. Existing defensive controls and diagnostic baseline are strong

No correction requested or needed. Spot-checked several of the cited
controls (Host/Origin/CSRF, DOCX DTD/entity guards, XML/sheet-name
sanitization) directly in the source while investigating other findings, and
they match Codex's description. No action taken.

---

## Summary of files changed

- `app.py` — M-6 (Test Mode DOCX metadata), L-1 (Cache-Control), L-8 (dead
  imports)
- `customizable_transcription/core.py` — M-1 (content-type sniffing for
  batch files), L-3 (.env loader scoping/precedence)
- `profiles_store.py` — M-4 (profile-store write lock), L-4 (reject
  non-object profile JSON)
- `xls_conversion/ai_parser.py` — M-2 (process-all image-count cap), L-8
  (dead imports)
- `tests/test_http_security.py` — L-1 tests, L-8 dead-import cleanup
- `tests/test_image_range.py` — M-2 tests
- `tests/test_index_compare_http.py` — L-8 dead-import cleanup
- `tests/test_batch_file_content_sniffing.py` (new) — M-1 tests
- `tests/test_env_file_loading.py` (new) — L-3 tests
- `tests/test_profile_store_concurrency.py` (new) — M-4 tests
- `tests/test_profile_store_malformed_json.py` (new) — L-4 tests
- `tests/test_test_mode_docx_metadata.py` (new) — M-6 tests

No changes were committed or pushed, per instructions.

---

CLAUDE STATUS: HUMAN_DECISION_REQUIRED
