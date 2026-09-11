# Human Decisions Required

Extracted from `CLAUDE_RESPONSE.md`: every finding marked `HUMAN_DECISION_REQUIRED`
(12 of the 17 findings in `CODEX_REVIEW.md`; the other 5 — M-6, L-1, L-3, L-4,
and the informational I-1 — were resolved or required no action and are not
repeated here). No source code was modified to produce this file.

Findings are ordered so that decisions affecting other findings' resolution
come first, followed by decisions that are independent of the rest. Within
each entry, "blocks other findings" is my own analysis of dependency, not a
claim that appears verbatim in `CODEX_REVIEW.md`.

## Decisions recorded — 2026-09-10

**Addressing CODEX_REVIEW_2.md finding N-1**: this file originally shipped
as an options/recommendations memo with no record of which option was
actually chosen for any of the 12 items — a real gap an independent
reviewer correctly flagged, since "Claude implemented its own
recommendation" and "the user approved a specific option" are not
distinguishable without one. Every decision below was made by the user
(weevie833@gmail.com), interactively, in chat, on 2026-09-10, in response
to the options this file itself lists — Claude did not select any option
on its own authority. The table records the option selected and the
resulting action; each numbered section below carries the same decision
inline, near its own options and rationale.

| # | Finding | Option selected | Resulting action |
|---|---|---|---|
| 1 | H-1 | Single-user machine only | Documented explicitly in `SECURITY.md` as out of scope. No code change. |
| 2 | M-3 | (Resolved by investigation before a choice was needed) | Code was already correct for the documented split (batch tools require paste; Preflight Test/Detect Languages honor `.env`) — README/`PRIVACY.md` corrected to describe it accurately. *Note: `CODEX_REVIEW_2.md` finding M-3 later found `detect_xls_languages()` itself didn't actually honor `.env` end-to-end — a real bug in the implementation of this already-selected policy, fixed separately (see that finding's own response in `CLAUDE_RESPONSE_2.md`), not a reopened decision.* |
| 3 | M-5a | Per-provider key scoping | Implemented: separate Gemini/Claude key fields, server validates only providers actually in use. |
| 3 | M-5b | Continue, isolate per-run failures | Implemented: each queued run's failure is caught and recorded against that run only. |
| 4 | M-2 | Small concurrency guard | Implemented: shared `xls_ai_lock` rejects a second concurrent XLS AI request with a 409. |
| 5 | L-2 | Extract to static assets | Implemented: all inline `<script>`/`<style>` moved to `/static/*.js`/`*.css`; CSP `unsafe-inline` removed from both directives. |
| 6a | L-8 (app.py split) | Yes, split further | Not yet implemented — flagged as a separate follow-up task (spawned task, pending). |
| 6b | L-8 (exception audit) | Yes, audit them | Done: all ~39 broad `except Exception` catches audited; all found deliberate/correct; none narrowed; missing rationale comments added. |
| 6c | L-8 (lint in CI) | Yes, informational/non-blocking | Implemented: Ruff added to CI as a non-blocking `lint` job. |
| 7 | M-7 | Leave as-is for now | No action; revisit later. |
| 8 | L-5 | Pin the two floor-only packages only | Implemented: `cryptography`/`pyasn1` exact-pinned. *(The CI-tooling pin gap `CODEX_REVIEW_2.md` separately found — unpinned `ruff`/`pip-audit` — was fixed as part of that follow-up review, consistent with this same "pin what's floating" policy, not a new decision.)* |
| 9a | M-1 (size limit) | Tighter ceiling (~25–50MB) | Implemented: `MAX_BATCH_IMAGE_BYTES = 50_000_000`. |
| 9b | M-1 (symlinks) | Reject all symlinks | Implemented: any symlink, or a file reached through a symlinked directory, is rejected. |
| 10 | M-4 | Leave last-writer-wins as-is | No action; accepted as a known limitation. |
| 11 | L-6 | Keep as documented reference-only | No code change; `xls_conversion/README.md` corrected to accurately state only `baptism-parser.js` is tested (a factual documentation gap `CODEX_REVIEW_2.md` separately found, fixed under this same decision). |
| 12 | L-7 | Add a plain worksheet selector | Implemented: `renderIndexCompareMapping()` shows a worksheet `<select>` only when a workbook has more than one sheet. |

---

## 1. H-1 — Loopback server has CSRF protection but no client authentication/authorization boundary

**Codex's concern:** Any local process or OS account able to reach
`127.0.0.1:8765` can bootstrap the CSRF cookie with a plain GET and then call
every read/write endpoint. The cookie proves a request came through this
app's own browser flow, not that the caller is an authorized *user* — so on
a shared machine, another local account could read generated transcriptions,
read/delete/overwrite saved profiles, change the selected source folder, or
stop a running job.

**Why a human decision is required:** `SECURITY.md` already declares a
single-local-user threat model, but the actual code doesn't enforce anything
that distinguishes "this app's own user" from "any other process on this
machine." Closing that gap means either accepting the current scope as
final (a documentation decision) or building a real authentication boundary
(a new feature with session-lifecycle and usability consequences). Both are
legitimate; neither is implied by the existing code or docs strongly enough
to pick without the maintainer's input on who actually uses this machine.

**Concrete decision:** Does this app need to defend against another local
OS account/process on the same machine, or is single-user-per-machine an
acceptable, permanent constraint?

**Options:**
- **(a) Keep single-user scope, document it explicitly.** Update
  `SECURITY.md` to state plainly that another local account on the same
  machine is *not* defended against (only cross-site/browser-based attacks
  and DNS rebinding are in scope), closing the gap by making it an
  intentional, disclosed limitation rather than a silent one.
- **(b) Add a real authentication boundary.** E.g., a one-time launch
  token embedded in the URL the app prints/opens at startup, followed by a
  server-side session the browser must present on every subsequent request.

**Security/integrity implications:**
- (a) Leaves the actual capability gap unchanged — another local account can
  still reach every endpoint — but removes the false impression that CSRF
  protection implies user-level authorization. No new attack surface.
- (b) Closes the gap for real, but a session-issuance mechanism is itself
  new attack surface (token leakage via shell history/process list/browser
  history, session-fixation-style bugs, a forgotten-to-invalidate token
  after the app restarts) that must be built and reviewed carefully — a
  half-built auth layer can be worse than none if it creates a false sense
  of security.

**Compatibility/usability implications:**
- (a) Zero behavior change for any existing user or workflow.
- (b) Changes what "open the app" means for every user, including the
  single-user majority this app is built for today: a bookmarked
  `http://127.0.0.1:8765/` would stop working on its own, browser restarts
  or a second browser/profile would need re-authentication, and any
  external tooling or scripts that currently hit the HTTP API directly
  would break until updated to carry the new credential.

**Claude's recommendation:** Option (a) is the lower-risk default *if* this
app is not actually intended to run on shared/multi-user machines — it costs
nothing to implement, matches the threat model `SECURITY.md` already states,
and avoids the real risk of shipping a partially-correct auth layer. I can't
recommend (b) over (a) without knowing whether shared-machine use is an
actual requirement; if it is, (b) is necessary and (a) alone would be
inadequate.

**Decision selected (2026-09-10, by the user in chat):** Option (a) —
single-user machine only. `SECURITY.md` now states this explicitly as an
accepted, out-of-scope limitation; no authentication layer was built.

**Blocks other findings:** Yes — directly informs **M-3** (whether a blank
API-key field may fall back to a stored `.env` key has a materially
different risk profile depending on whether another local account can reach
this server), and loosely informs **M-5** (how test-mode credentials should
be scoped/protected). Resolve this first.

---

## 2. M-3 — Advertised `.env` key workflow is rejected by the primary user flows

**Codex's concern:** The README documents saving an API key once via `.env`
as an alternative to pasting it every run, and `api_key()`/`claude_api_key()`
do support that fallback — but Transcribe, Test Mode, and XLS Conversion all
require a non-empty pasted key field before that fallback code path is ever
reached, so the documented workflow doesn't actually work for any of the
app's three main tools.

**Why a human decision is required:** Fixing the mismatch means picking a
policy (silently allow a blank field to use the stored key, or drop the
fallback and its documentation), and the "allow it" option has a real
authorization/security dimension that depends directly on H-1's outcome — a
stored key silently usable by whoever opens the browser is a materially
different risk on a single-user machine than on one the maintainer intends
to keep multi-account-safe.

**Concrete decision:** Should a blank submitted API-key field be allowed to
fall back to a `.env`-configured key (with the UI only indicating "a key is
configured," never displaying it), or should the `.env` fallback be removed
entirely so the browser field is always authoritative?

**Options:**
- **(a) Allow blank-field fallback to `.env`,** with the UI showing a
  non-reversible "using saved key" indicator instead of ever echoing the key
  itself.
- **(b) Remove the `.env` fallback from the runtime** (`api_key()`/
  `claude_api_key()` stop reading `.env`) and correct the README/`.env.example`
  to describe the browser-paste flow as the only supported one.

**Security/integrity implications:**
- (a) Reintroduces exactly the shared-machine exposure H-1 discusses: any
  local account/browser session that reaches this server can now run a job
  under the *stored* key without ever seeing or typing it, which is a
  meaningfully lower bar than today's "must paste the actual key value."
  Should not be adopted independently of H-1's outcome.
- (b) No new exposure; simplest to reason about. The key only ever exists
  in the browser session that pasted it (or a `.env` file a user
  deliberately reads themselves to copy from).

**Compatibility/usability implications:**
- (a) Matches what the README already promises today — no doc rewrite
  needed for the workflow, just for the error/indicator copy. Restores a
  real convenience (not re-pasting a key every run) for solo users who
  already have `.env` set up.
- (b) Breaks the documented convenience entirely; anyone currently relying
  on a saved `.env` key (if any) would need to start pasting it every run.
  Requires README/`.env.example`/`GETTING_STARTED.html` edits to stop
  advertising a workflow that no longer exists.

**Claude's recommendation:** Decide this together with H-1, in the same
sitting. If H-1 resolves to "single-user scope is fine, document it," then
(a) is consistent and low-incremental-risk. If H-1 resolves to "add real
authentication," (a) should wait until that authentication exists, since
otherwise it's adding the exact exposure the new auth work is meant to
close. I can't recommend one over the other without that ordering being
settled first.

**Decision selected (2026-09-10, by the user in chat):** Investigation
(prompted by the user, following on from H-1's resolution) found the code
was already correct and consistent with option (a)'s underlying policy —
the batch tools already required a pasted key (deliberately, as a
cost-commitment gate the user explained is intentional) and the two
lightweight tools (Prompt Builder Preflight Test, XLS Conversion Detect
Languages) were already meant to honor `.env`. No option (a)/(b) choice
was actually needed; README/`PRIVACY.md` were corrected to describe this
split accurately instead. (`CODEX_REVIEW_2.md`'s own M-3 finding later
caught that `detect_xls_languages()`'s *implementation* of this
already-decided policy had a real bug — validation resolved a blank key
via `.env` but the actual detection call still used the original blank
value — fixed as a bug fix, not a reopened decision; see
`CLAUDE_RESPONSE_2.md`.)

**Blocks other findings:** No downstream findings depend on this one, but it
is itself blocked by **H-1**.

---

## 3. M-5 — Test Mode's key/failure handling doesn't match its documented independence

**Codex's concern:** Test Mode accepts exactly one API key per slot (A/B)
for an entire queue of runs, so a queue that mixes providers within the same
slot can never be satisfied by one key. Separately, `run_test_job()`'s
per-run loop sits inside one outer `try/except`, so a single run's setup
failure (e.g., a bad key) aborts every other *unrelated* queued run as one
fatal error — contradicting the function's own docstring, which states each
queued run is independent.

**Why a human decision is required:** Two different, non-mechanical
questions are bundled here: how credentials should actually be entered/
scoped in the UI (a form-design question with several equally valid shapes),
and whether a failure should abort the rest of the queue or let unaffected
runs continue (a fail-fast-vs-continue product choice with a real cost
trade-off: continuing after a bad key likely just repeats the same failure
for every other run using that same key).

**Concrete decision:**
1. Should API keys be entered per slot (current), per provider, or
   per-queued-run?
2. Should one run's failure abort the remaining queue (current,
   undocumented behavior), or should the queue continue and report each
   run's own outcome independently?

**Options:**
- **Credential scoping:** (a) keep per-slot (simplest UI, but structurally
  can't express a mixed-provider queue in one slot); (b) per-provider (one
  Gemini key + one Claude key, used by whichever runs need them, regardless
  of slot); (c) per-queued-run (most flexible, most form fields).
- **Failure handling:** (a) keep fail-fast (current); (b) catch each run's
  exception individually and continue, marking only that run as failed.

**Security/integrity implications:** Primarily a correctness/UX concern
rather than a security one. The one integrity-adjacent risk: continue-on-
error (failure option b) without a "same key, same failure" short-circuit
could hammer a provider with repeated doomed requests across every queued
run sharing that key — worth guarding against regardless of which failure
option is chosen.

**Compatibility/usability implications:**
- Credential scoping (b)/(c) let a user actually run the mixed-provider
  queues the code's own comments already contemplate; (a) silently forbids
  a configuration the UI doesn't otherwise block from being queued.
- Failure handling (b) means a user gets partial results (the runs that
  could complete) instead of losing an entire queue's progress to one bad
  key — generally the more forgiving choice for a paid, multi-run batch
  tool, but changes what "Fatal error" means in the UI and what the summary
  line reports.

**Claude's recommendation:** None with confidence — both halves are genuine
product/UX decisions (which credential-entry shape fits how users actually
queue comparisons; whether partial-completion or fail-fast better matches
the maintainer's expectations for a paid batch job) that I don't have enough
context to settle without assuming requirements not stated anywhere in the
repo.

**Decision selected (2026-09-10, by the user in chat):**
- M-5a (credential scoping): option (b), per-provider — one Gemini field,
  one Claude field, not tied to A/B slot. Implemented in `app.py`
  (`required_providers()`, `run_test()`) and `pages/test_mode.py`/
  `static/test-mode.js`.
- M-5b (failure handling): option (b), continue with per-run isolation.
  Implemented in `run_test_job()` — each run's own `try/except` now
  records that run's failure without aborting runs still queued after it.

**Blocks other findings:** No.

---

## 4. M-2 — "Process all" bypasses the documented image-count limit; no job/cost control (architectural remainder)

**Codex's concern:** Beyond the image-count cap (already fixed — see
`CLAUDE_RESPONSE.md`), XLS Conversion's preflight/parse/combine endpoints run
entirely synchronously inside the HTTP request thread, with no shared job
lock, cancellation, or concurrency quota — unlike `/run`/`/test-mode/run`,
which already have a background-job/state/lock/progress-log architecture.

**Why a human decision is required:** Turning a synchronous request handler
into a background job system is a genuine architectural change — it needs a
job-state model, a progress/status endpoint, a Stop control, and UI changes
to poll and render that state — not a bug fix. It also directly shapes what
**M-7**'s test strategy needs to cover (testing a synchronous handler vs. an
async job queue are different problems) and overlaps with **L-8**'s
"further split app.py" question, since building this job system is exactly
the kind of orchestration code L-8 is about.

**Concrete decision:** Should XLS Conversion's AI-backed endpoints
(preflight/parse/detect-languages/combine) be rearchitected as background
jobs with cancellation and a concurrency quota, matching `/run`'s existing
pattern — or is the current synchronous-per-request model acceptable given
this app's actual usage pattern (one user, one browser tab, one conversion
at a time)?

**Options:**
- **(a) Keep synchronous, but add a server-side concurrency guard** (e.g., a
  simple lock that rejects a second concurrent XLS AI request with a clear
  "a conversion is already running" error) — a much smaller change than a
  full job system.
- **(b) Build a full background-job architecture** matching `/run`, with
  polling, cancellation, and a job-history-style status surface.
- **(c) Leave as-is**, accepting that a very large document or a user
  opening two tabs can run long/expensive/concurrent AI batches with no
  server-side stop.

**Security/integrity implications:** (a)/(b) both bound unexpected AI-provider
cost and resource exhaustion from concurrent or abandoned requests; (c)
leaves that exposure open (a large document already produces thousands of
sequential calls even after the count cap fix, all inside one blocking
request with no way to cancel once started).

**Compatibility/usability implications:** (a) is close to invisible to a
normal single-tab user and only surfaces when a second concurrent attempt is
made. (b) changes the XLS Conversion page's interaction model noticeably
(the user would see progress/status instead of a single blocking request)
and is a larger, more visible UI change. (c) has no compatibility impact but
leaves the underlying resource/cost risk unaddressed.

**Claude's recommendation:** (a) is the smallest change that closes the
worst of the concurrency/cost exposure without committing to a UI redesign,
and could reasonably be adopted on its own regardless of what's decided for
(b). Whether the fuller (b) is worth the UI investment depends on how large
this app's users' documents actually get in practice — not something I can
infer from the code.

**Decision selected (2026-09-10, by the user in chat):** Option (a), small
concurrency guard. Implemented as `xls_ai_lock` (`app_state.py`), a single
shared lock across Parse/Preflight/Detect Languages guarded by
`_reserve_xls_ai_slot()` in `app.py` — a second concurrent request to any
of the three now gets a 409 instead of running alongside the first. The
fuller background-job rework (option b) was not built.

**Blocks other findings:** Yes — informs **M-7** (test strategy should
target the final architecture, not the current one) and overlaps with
**L-8** (both touch the same orchestration/handler code). Resolve before
M-7.

---

## 5. L-2 — Content Security Policy permits all inline scripts and styles

**Codex's concern:** The global CSP includes `script-src 'unsafe-inline'`
and `style-src 'unsafe-inline'`. Existing HTML-escaping appears deliberate,
but if a future HTML-injection bug were ever introduced, CSP would provide
no second layer of defense, since inline script execution is already
allowed by policy.

**Why a human decision is required:** Removing `unsafe-inline` requires
moving large inline `<script>`/`<style>` blocks (across `pages/transcribe.py`,
`pages/test_mode.py`, `pages/prompt_builder.py`, `pages/home.py`, and
`app.py`) to static assets, or adopting per-response nonces — either touches
every page-render function in the app. This is a mechanical-in-theory but
large-in-practice refactor with real regression risk (a missed inline
handler, a script that silently stops running), and it overlaps directly
with **L-8**'s open question about further splitting `app.py`'s page-render
functions — doing both in the same pass avoids rewriting the same code
twice.

**Concrete decision:** Should inline `<script>`/`<style>` be extracted to
static files (or switched to nonces) to remove `unsafe-inline` from the CSP,
and if so, should that work be sequenced together with L-8's broader
page-render restructuring?

**Options:**
- **(a) Extract to static assets.** Move inline JS/CSS into `/static/*.js`/
  `*.css` files (as `static/app-common.js`/`static/base.css` already do for
  shared code), removing `unsafe-inline` once nothing inline remains.
- **(b) Per-response nonces.** Generate a nonce per request, add it to the
  CSP header and to every inline `<script>`/`<style>` tag, keeping the
  content inline but making injected script (which wouldn't carry a valid
  nonce) unable to execute.
- **(c) Leave as-is,** relying on the existing escaping discipline
  (`json_for_inline_script()`, `html.escape()`) as the only defense.

**Security/integrity implications:** (a)/(b) both restore CSP as a genuine
second layer of defense against a future HTML/script-injection bug — the
exact scenario Codex's finding describes. (b) is a smaller code change than
(a) but must be threaded through every response correctly (a forgotten nonce
on one inline tag silently breaks that page); (a) is more invasive but
produces a simpler, static, auditable end state. (c) leaves the app exactly
as exposed as it is today to a future injection bug — no immediate
weakness, but no improvement either.

**Compatibility/usability implications:** (a)/(b) are both invisible to end
users if done correctly; the risk is entirely developer-facing (regression
risk during the refactor, e.g., a script that depends on load order breaking
when moved to an external file — this codebase has already hit this exact
issue once, per its own documented history with `static/app-common.js`).
(c) has zero risk of regression since nothing changes.

**Claude's recommendation:** If L-8's app.py-splitting work is going to
happen at all, do it together with (a) rather than sequentially — the two
touch the same functions and splitting first, then re-extracting inline
script separately, would mean touching every page-render function twice.
Whether to do either at all (vs. (c)) depends on how much refactoring risk
the maintainer is willing to accept for a defense-in-depth improvement
against a bug class (HTML injection) that hasn't been found in this app.

**Decision selected (2026-09-10, by the user in chat):** Option (a),
extract to static assets — after the user asked what the actual risk of
leaving it as-is was and was given a concrete answer (this app's own prior
script-injection bug, plus Prompt Builder's profile-import feature as a
realistic path for externally-authored content). Fully implemented:
`pages/transcribe.py`/`test_mode.py`/`prompt_builder.py`/`home.py`/
`privacy.py` and `app.py`'s `getting_started_page()` all moved their
inline `<script>`/`<style>` to new files under `static/`; per-request
dynamic data now flows through inert `<script type="application/json">`
data islands (`json_data_island_html()`); the CSP's `script-src`/
`style-src` dropped `'unsafe-inline'` entirely (`app.py`'s
`end_headers()`). Verified live in the browser on every page (zero CSP
console errors) and via a dedicated regression test
(`tests/test_http_security.py::test_csp_has_no_unsafe_inline`).

**Blocks other findings:** Yes — should be decided together with **L-8**
(shared code, shared risk of duplicated rework), and its outcome shapes what
**M-7** needs to test afterward. Resolve alongside L-8, before M-7.

---

## 6. L-8 — Routing/orchestration remains concentrated; static analysis absent from CI (architectural remainder)

**Codex's concern:** `app.py` combines routing, parsing, provider
orchestration, migrations, document generation, subprocess integration, and
most endpoint handlers in one file, with several high-complexity functions
and ~32 broad `except Exception` catches; no linter or security static
analyzer runs in CI.

**Why a human decision is required:** The mechanical part (dead-import
cleanup) is already done — see `CLAUDE_RESPONSE.md`. What remains is (1)
further splitting `app.py`'s routing/handler code, which this repo's own
history shows needs careful, deliberate sequencing (a prior modularization
pass already caught two real cross-module sandboxing bugs from moving code
without fully tracing dependents); (2) auditing ~32 broad exception catches
individually to tell deliberate ones (this codebase has documented cases
where broadening a catch was an intentional fix, e.g. so one bad image
doesn't abort a whole batch) from accidental ones; and (3) deciding whether
to adopt Ruff/Bandit as enforced CI gates, which is an ongoing
process/tooling commitment, not a one-time change.

**Concrete decision:** How much further should `app.py` be split, should
that work be combined with L-2's inline-script extraction, should each of
the ~32 broad exception catches be individually reviewed and narrowed where
appropriate, and should Ruff/Bandit be adopted as enforced (failing) CI
checks going forward?

**Options:**
- **(a) Do nothing further** beyond the dead-import cleanup already applied;
  accept the current file organization and exception-handling style as a
  stable, working baseline.
- **(b) Continue the modularization** (further splitting `app.py`, ideally
  combined with L-2's work), and separately audit/narrow the broad
  exception catches one at a time.
- **(c) Adopt Ruff and/or Bandit as enforced CI gates** (with justified,
  documented suppressions for intentional patterns), independent of whether
  (b) happens.

**Security/integrity implications:** Broad `except Exception` catches can
mask a real bug as a generic "Fatal error" message, making some classes of
failure harder to diagnose; narrowing them (where they aren't deliberate)
improves error-message accuracy but risks reintroducing exactly the kind of
uncaught-exception failure mode this repo has fixed before if done
carelessly (see M-5's docstring-vs-behavior mismatch, itself caused by an
overly broad catch). CI-enforced static analysis (c) catches classes of bug
(unused imports masking a forgotten call, in one real case elsewhere in this
review) before merge rather than after.

**Compatibility/usability implications:** Entirely developer-facing; no
end-user impact either way. (b)/(c) both add ongoing maintenance overhead
(reviewing linter/security findings on every future change) that a
single-maintainer project should weigh deliberately rather than take on by
default.

**Claude's recommendation:** (c) — adopting Ruff at least as an informational
(non-blocking) CI check — is low-risk and would have caught the dead-import
drift this review already found; it doesn't require the larger, riskier (b)
to be worth doing. (b) is worth pursuing only if the maintainer has
bandwidth for the same kind of careful, dependency-traced work the prior
modularization pass required — not something to rush.

**Decision selected (2026-09-10, by the user in chat):** All three parts,
answered separately:
- Further app.py split: **yes**. Not yet implemented — deferred as its own
  follow-up (flagged via a spawned task, since it needs its own module-
  boundary design decisions per this file's own analysis above).
- Exception audit: **yes**. Done — all ~39 broad `except Exception`
  catches across `app.py`/`core.py`/`ai_parser.py`/`index_compare/
  reader.py` reviewed individually; all confirmed deliberate/correct
  (request-handler boundaries, background-job boundaries, per-item loop
  isolation, fail-safe untrusted-input parsing, or already-narrow-in-effect
  retry wrappers); none narrowed. Added the one missing rationale comment
  (`_cookie_token()`) and a class-level comment on `Handler` explaining the
  general pattern.
- Lint in CI: **yes, informational/non-blocking**. Implemented — the
  `lint` job in `.github/workflows/tests.yml` (`continue-on-error: true`).

**Blocks other findings:** Yes — its outcome (particularly whether `app.py`
is restructured further) shapes what **M-7**'s test suite needs to target,
and it should be sequenced with **L-2** to avoid duplicated rework. Resolve
alongside L-2, before M-7.

---

## 7. M-7 — Automated coverage is weak around orchestration and browser state machines

**Codex's concern:** Measured coverage is low for `app.py` (43%),
`customizable_transcription/core.py` (56%), and `xls_conversion/ai_parser.py`
(56%), and there is no automated browser-test suite for the large inline/
static JavaScript in `static/prompt-builder.js`/`xls_conversion/app.js`/
`pages/test_mode.py`.

**Why a human decision is required:** Closing this gap well requires
knowing the target architecture first (see M-2, L-2, L-8 above — testing a
synchronous handler that's about to become a background job, or inline
script that's about to move to a static file, means writing tests that get
thrown away or rewritten shortly after). It also requires committing to a
browser-automation framework (not currently a dependency), a CI coverage
threshold, and a policy for how (or whether) to contract-test real
provider calls — all ongoing tooling/process decisions with real
maintenance cost.

**Concrete decision:** Should this project adopt a browser-automation
framework (e.g., Playwright) for `static/prompt-builder.js`/
`xls_conversion/app.js`/Test Mode's JS state machines; should a coverage
threshold be enforced in CI (and at what level, and for which
modules); and how should live-provider-dependent code
(`ai_parser.py`'s semantic extraction, `core.py`'s transcription calls) be
tested — mocked contracts, a recorded-fixture/cassette approach, or
accepted as untestable-offline and covered only by the existing
Preflight/manual-test workflow?

**Options:**
- **(a) Adopt Playwright (or similar) now,** write E2E tests for the four
  main pages' JS state machines, and set a CI coverage floor for `app.py`/
  `core.py`/`ai_parser.py`.
- **(b) Defer browser-test tooling,** but expand Python-level HTTP tests
  (the pattern already established in `tests/test_http_security.py`/
  `tests/test_run_concurrency.py`) to cover more of the currently-untested
  orchestration paths, without committing to a new framework yet.
  This session's 12 new tests are a small step in this direction.
- **(c) Leave coverage as-is,** relying on manual verification (Preflight
  Test, Test Mode itself) as the primary quality gate for AI-extraction
  behavior, which can't be exercised offline regardless of framework choice.

**Security/integrity implications:** More coverage of orchestration paths
(concurrency, error handling, cancellation) reduces the chance that a future
change silently reintroduces a fixed defect — several of this review's own
findings (M-4's race, the earlier-documented deadlock/race in `/run`) were
found exactly this way. AI-extraction quality itself (`ai_parser.py`'s
semantic parsing) cannot be meaningfully covered by any offline framework
choice — that gap is inherent to using a live model, not a tooling
shortfall.

**Compatibility/usability implications:** Entirely developer-facing.
Adopting a browser-automation framework adds a new dependency and CI runtime
cost (E2E tests are slower than unit tests) but catches a class of
regression (JS state-machine bugs) that nothing else in this repo currently
catches at all.

**Claude's recommendation:** (b) is the lower-commitment path and builds
directly on this session's own additions; it doesn't foreclose (a) later.
I'd defer a firm recommendation on (a) specifically until M-2/L-2/L-8 are
settled, since the shape of what needs E2E coverage depends on their
outcome.

**Decision selected (2026-09-10, by the user in chat):** Option (c) —
leave coverage as-is for now; no browser-automation framework adopted, no
CI coverage threshold set. Asked again after M-2/L-2/L-8 were resolved
(as this entry's own dependency note required); same answer.

**Blocks other findings:** No, but it is blocked by **M-2**, **L-2**, and
**L-8** — resolve those first.

---

## 8. L-5 — Python installs and CI actions are not fully reproducible or supply-chain pinned

**Codex's concern:** Direct Python dependencies are exact-pinned, but
`cryptography`/`pyasn1` are floor-only (`>=`), there is no lock file for the
transitive dependency graph, and GitHub Actions are referenced by mutable
major-version tags (`@v4`/`@v5`) rather than pinned commit SHAs.

**Why a human decision is required:** Both fixes are legitimate supply-chain
hardening, but both are ongoing process commitments, not one-time patches:
a lock file needs a regeneration workflow (who runs it, how often, what
triggers a refresh), and SHA-pinned Actions need something (Dependabot or
manual review) to keep the pins current, or they silently go stale and stop
receiving fixes. This affects long-term maintenance burden for a
single-maintainer project.

**Concrete decision:** Should this project adopt a locked/hashed dependency
strategy (e.g., `pip-compile` output committed alongside `requirements.txt`)
and pin GitHub Actions to commit SHAs (with Dependabot configured to keep
them current)?

**Options:**
- **(a) Adopt full lock-file + SHA-pinning,** with Dependabot (already
  present in this repo for version-based updates) extended or supplemented
  to handle SHA-pin refreshes.
- **(b) Pin only the two floor-only packages** (`cryptography`, `pyasn1`) to
  exact versions, leaving the rest of the transitive graph unlocked, and
  leave GitHub Actions on mutable tags.
- **(c) Leave as-is,** relying on the existing scheduled `pip-audit`/`npm
  audit` CI job (already present) to catch known-vulnerable versions after
  the fact.

**Security/integrity implications:** (a) gives the strongest reproducibility
and supply-chain guarantee — the exact same dependency graph installs every
time, and a compromised new release of a transitive dependency can't be
silently pulled in without a corresponding lock-file change showing up in a
diff. (b) closes only the two floors Codex specifically flagged, leaving the
rest of the transitive graph free to drift. (c) already has some protection
(the existing scheduled audit job) but only detects a *known* vulnerability
after publication, not an unreviewed or novel supply-chain change.

**Compatibility/usability implications:** (a) adds a maintenance step (lock
file regeneration) to the normal dependency-update workflow, and SHA-pinned
Actions are harder to read/review at a glance in the workflow file (a
version tag like `@v4` is more legible than a 40-character SHA). (b)/(c) have
no workflow impact beyond what already exists.

**Claude's recommendation:** (a) is best practice, but given this is
described (in `SECURITY.md`) as a single-maintainer project with no formal
release process, the ongoing lock-file-regeneration burden should be weighed
against actual benefit — (b) alone would close the two specific gaps Codex
found with minimal ongoing cost, if the maintainer isn't ready to commit to
(a)'s process overhead.

**Decision selected (2026-09-10, by the user in chat):** Option (b) —
pin the two floor-only packages only. `cryptography`/`pyasn1` exact-pinned
in `requirements.txt`. Full lock-file adoption and Action SHA-pinning
(option a) not done. (A related, separately-found gap — the `lint`/
`dependency-audit` CI jobs installing `ruff`/`pip-audit` with no version
pin at all, from `CODEX_REVIEW_2.md` — was fixed under this same "pin
what's floating" policy: both now pinned in `requirements-dev.txt`.)

**Blocks other findings:** No.

---

## 9. M-1 — Batch source files selected by extension only; size/symlink policy (remainder)

**Codex's concern:** Beyond the content-type sniffing already fixed (see
`CLAUDE_RESPONSE.md`), batch source-file discovery still has no per-file
size ceiling and no symlink/path-containment check before a file is read
into memory and sent to an AI provider.

**Why a human decision is required:** An appropriate byte-size ceiling
depends on a fact about actual usage this session doesn't have access to —
how large a real archival scan legitimately gets for this app's users (a
high-resolution TIFF-quality JPEG scan can legitimately be tens of
megabytes; too aggressive a limit would reject real, valid source material).
Similarly, whether an in-folder symlink is an intentional way some users
organize a source folder (e.g., symlinking pages from another location) or
should always be rejected is a usage-pattern question, not a technical one.

**Concrete decision:** What per-file byte-size ceiling should batch source
discovery enforce, and should a symlinked file inside the selected source
folder be followed (current behavior) or rejected?

**Options — size limit:** (a) a generous ceiling (e.g., 100–200MB) that
only stops pathological/mislabeled files; (b) a tighter ceiling matched to
realistic scan sizes (e.g., 25–50MB, matching this app's existing
`MAX_DOCX_BYTES`); (c) no limit, relying on the (already-added) content-type
check alone.

**Options — symlinks:** (a) follow symlinks as today (simplest, matches
current behavior); (b) reject any symlink inside the source folder, erroring
per-file; (c) allow a symlink only if it resolves to a path still inside the
selected source folder (permits reorganizing via symlinks within one's own
folder, blocks pointing outside it).

**Security/integrity implications:** A size ceiling bounds memory use and
protects against a pathological/mislabeled file exhausting resources before
a request completes. Symlink option (c) prevents a folder that's been
tampered with (or carelessly constructed) from silently transmitting bytes
from outside the folder the user actually selected to an external AI
provider; (a) leaves that theoretical exposure open, (b) is safest but most
restrictive.

**Compatibility/usability implications:** A size limit set too low would
reject real, legitimate scans and surface as a confusing per-image failure
mid-batch; too high provides little real protection. Symlink option (b)
would break any user who currently (even unknowingly) has a symlinked file
in their source folder; (c) is more forgiving of legitimate in-folder
reorganization while still closing the escape-the-folder risk.

**Claude's recommendation:** Symlink option (c) (allow only if the resolved
path stays inside the source folder) is the most defensible default — it
closes the most concerning capability (transmitting bytes from outside a
user's chosen folder) without a compatibility cost for anyone not already
using external symlinks. I can't recommend a specific size number without
knowing this app's real-world scan sizes.

**Decision selected (2026-09-10, by the user in chat):**
- Size limit: tighter ceiling (~25–50MB). Implemented as
  `MAX_BATCH_IMAGE_BYTES = 50_000_000` (`customizable_transcription/core.py`),
  matching `app.py`'s existing `MAX_DOCX_BYTES`.
- Symlinks: **reject all symlinks** (stricter than the recommended option
  c) — after the user asked what a symlink actually is and was given a
  concrete explanation, they chose the simplest, most restrictive policy
  rather than the "allow if it stays inside the folder" middle ground.
  Implemented via `validate_batch_source_file()`/
  `_path_is_or_contains_symlink()`, which rejects a symlinked file and a
  file reached through a symlinked directory alike.

**Blocks other findings:** No.

---

## 10. M-4 — Profile persistence permits lost updates (stale-edit UX remainder)

**Codex's concern:** Beyond the write-lock already added (see
`CLAUDE_RESPONSE.md`, which closes the concurrent-*create*/mutation race),
two browser tabs that both loaded the same already-saved profile and edit it
independently still silently last-writer-wins — the second save overwrites
the first with no warning.

**Why a human decision is required:** Detecting and surfacing this kind of
conflict requires a revision/version token on each profile and a UI decision
about what happens when a stale save is detected (silently reload and
re-apply? Block the save and show a diff? Offer to overwrite anyway?) — a
UX design question, not a locking mechanism.

**Concrete decision:** Should profile saves detect a stale edit (the
profile changed on disk since this tab last loaded it) and, if so, what
should happen when one is detected?

**Options:** (a) leave last-writer-wins as-is, accepting that editing the
same profile from two tabs is an unsupported/rare workflow; (b) add a
revision token and silently refuse a stale save with an error directing the
user to reload; (c) add a revision token and offer a merge/overwrite choice
in the UI when a conflict is detected.

**Security/integrity implications:** Not a security concern — a data-loss/
correctness concern only, scoped to a single user's own profile content.

**Compatibility/usability implications:** (a) has no workflow impact.
(b) is a meaningful but backward-compatible addition — existing single-tab
users notice nothing; only genuine concurrent-edit conflicts newly surface
as an error instead of silently losing data. (c) is the most user-friendly
but requires the most new UI (a diff or merge view) for a scenario that may
be rare in practice for a single-user-per-machine tool.

**Claude's recommendation:** (b) is a reasonable middle ground if this is
worth doing at all — it prevents silent data loss with a small, mechanical
addition (a revision counter compared on save) and a plain error message,
without committing to a merge UI. Whether it's worth doing at all depends on
how often the maintainer's own users actually run two tabs against the same
profile — plausibly rare enough that (a) is an acceptable trade-off.

**Decision selected (2026-09-10, by the user in chat):** Option (a) —
leave last-writer-wins as-is. No revision token or conflict UI was added;
the concurrent-*create*-collision fix (the `_profile_write_lock` in
`profiles_store.py`) stands as the only concurrency work done here, and it
does not address the stale-edit scenario this decision is about.

**Blocks other findings:** No.

---

## 11. L-6 — Codebase retains ~2,500 lines of dormant regex parsers, two with no regression coverage

**Codex's concern:** `matrimony-parser.js`/`morti-parser.js` are not loaded
anywhere in the live UI and have no test coverage at all; only
`baptism-parser.js` (also dormant/not live) is exercised by the offline Node
harness. Dormant, production-adjacent code increases review surface and
risks silent decay.

**Why a human decision is required:** This is explicitly an open product
question already tracked in this repo's own project notes — whether
`baptism-parser.js`'s deterministic approach should ever be wired back into
the live UI as a free, offline first pass ahead of the AI extraction, or
whether all three dormant parsers should simply be archived/removed as
historical reference material. Neither answer is implied by the code itself.

**Concrete decision:** Should the three dormant regex parsers (a) be
formally archived/removed from the live repository (keeping them in git
history or a separate reference location only), (b) be kept as-is with
clear documentation that they are reference-only and never executed by the
live app, or (c) be revived as a real, wired-in offline pre-pass ahead of
the AI extraction path, with parity test coverage added for all three?

**Security/integrity implications:** Minimal directly — these files aren't
reachable from the live UI today. The main risk is indirect: reviewer
attention spent on dormant code, and the two untested variants
(`matrimony-parser.js`/`morti-parser.js`) silently drifting from what a
"working" version would look like if someone later assumes they're
maintained.

**Compatibility/usability implications:** (a) has no user-facing impact but
loses easy in-repo access to a fast, free, offline sanity check some
maintainers might value. (b) is the status quo. (c) would give users a free,
deterministic first-pass option alongside the paid AI extraction — a real
new feature, but one that needs the same regression-test investment
`baptism-parser.js`'s own harness already required, tripled across three
record types.

**Claude's recommendation:** (b) — document clearly, as this file's own
response already does, that these are reference-only and not live — is the
lowest-cost option if no one currently plans to build (c). Committing to (c)
only makes sense if the deterministic/free/offline value proposition is one
actual users have asked for; nothing in the repo suggests that yet.

**Decision selected (2026-09-10, by the user in chat):** Option (b) — keep
as documented reference-only. No parsers archived or revived.
(`CODEX_REVIEW_2.md` separately found `xls_conversion/README.md` itself
overstated this — claiming all three parsers "are exercised only by the
offline regression tests" when only `baptism-parser.js` actually is — a
factual documentation bug under this same decision, fixed by correcting
the README's wording, not by reopening the archive/revive/keep choice.)

**Blocks other findings:** No.

---

## 12. L-7 — Index Compare exposes multiple worksheets but the browser always maps only the first one

**Codex's concern:** `index_compare/reader.py` already returns every
worksheet in a workbook when automatic schema detection fails, but
`renderIndexCompareMapping()` (`pages/test_mode.py`) unconditionally uses
`entry.worksheets[0]` with no selector — a workbook whose first sheet is
instructions/metadata and whose *later* sheet holds the real index can never
be mapped correctly.

**Why a human decision is required:** The fix is a real (if small) UI
feature — a worksheet `<select>`, wiring its `change` event to re-render the
column-mapping panel for the newly chosen sheet, and new translatable copy —
not a one-line change. It also raises a UX question Codex itself flags:
should the app try to guess the most likely worksheet automatically (e.g.,
by re-running schema detection per sheet) as a convenience, or should it
always show a picker whenever more than one worksheet is returned?

**Concrete decision:** When a workbook returns multiple worksheets, should
the UI (a) always show an explicit worksheet selector before mapping, or
(b) attempt a best-guess default (e.g., the sheet with the most
rows/columns, or the one containing the most recognizable header text) while
still allowing the user to override it?

**Options:** (a) always prompt; (b) best-guess default + override; (c)
leave as-is (first worksheet only, no override).

**Security/integrity implications:** None directly — this is a correctness/
usability gap (silently mapping the wrong sheet's data), not a security
issue.

**Compatibility/usability implications:** (a) is the simplest to implement
correctly and never guesses wrong, but adds a click for every multi-sheet
workbook, including ones where the first sheet was actually already right.
(b) is more convenient when the guess is correct but risks silently mapping
the wrong sheet again if the heuristic is wrong — arguably no better than
today's hardcoded `[0]` in the worst case, unless the guess is paired with a
visible "did we get this right?" confirmation. (c) leaves the bug exactly as
Codex describes it.

**Claude's recommendation:** (a) is the safer default to implement first — a
plain selector with no guessing logic closes the actual reported bug
(inability to select a non-first sheet at all) without introducing a new
heuristic that could itself guess wrong. A best-guess convenience (b) could
be layered on top later if it proves worth the extra complexity.

**Decision selected (2026-09-10, by the user in chat):** Option (a), a
plain worksheet selector. Implemented in `renderIndexCompareMapping()`
(`static/test-mode.js`) — shown only when a workbook returns more than one
worksheet; `collectIndexCompareMappings()` updated to target the
record-type select specifically so it isn't confused by the added
worksheet select. No best-guess heuristic (option b) was added.

**Blocks other findings:** No.

---

## BLOCKING DECISIONS:

**[H-1, M-2, L-2, L-8]**

These four should be resolved before the remaining findings, because:
- **H-1** must be decided before **M-3** (explicitly linked — both concern
  what a stored/shared credential or session means for a shared machine),
  and informs **M-5**.
- **M-2** (XLS Conversion's job architecture) and **L-2** (CSP inline-script
  extraction, which overlaps with **L-8**'s app.py-restructuring question)
  together determine the app's near-future architecture in the areas
  **M-7**'s test-coverage strategy needs to target — deciding test strategy
  before these would risk building tests against code that's about to be
  restructured.
- **L-8** should be sequenced with **L-2** specifically to avoid touching
  the same page-render functions twice in two separate refactor passes.

The remaining findings (**M-1, M-4, M-5, M-7, L-5, L-6, L-7**) are
self-contained product/process decisions that do not need to wait on each
other or on the four above, except that **M-7** is best decided only after
**M-2/L-2/L-8** are settled.
