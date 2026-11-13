# Claude Response to CODEX_REVIEW.md (2026-09-16 review, `e420b3f`)

Every finding below was independently re-verified against the actual source
before anything was changed (not taken on Codex's word) — each was traced to
the exact lines named, and reproduced where reproducible (e.g. the loop
condition that let a single post-cancel poll failure short-circuit straight
to "cancelled" was confirmed by reading the pre-fix control flow directly,
not inferred from the report). Two findings (H-1, M-2) carried real product
tradeoffs Codex correctly flagged as `HUMAN_DECISION_REQUIRED`; both were
put to the user directly, with the recommended option chosen for each (see
HD-1/HD-2 below). Every other finding was safe to fix without a new
decision and was fixed in this pass. No exceptions or disagreements with
Codex's own severity/bucket labels this round.

**Validation performed for every fix:** `pytest -q` → **248 passed** (up
from Codex's reported 228; 21 new regression tests added, 1 pre-existing
test removed — see L-1 below for why — 0 tests weakened). `py_compile`
across every touched module. `ruff check .` → 118 findings (was 117 after
the safe M-1/M-3/L-2 fixes alone, +1 `DTZ005` from a new `datetime.now()`
call that matches this file's own existing, already-accepted convention —
see M-3 below; net unchanged from Codex's own reported 118 baseline). For
H-1 specifically, the exact pre-fix bug (a single post-cancel poll failure,
or a cancellation that simply never reaches a terminal provider state,
being reported as a clean "cancelled" success) was reproduced as a failing
test against the pre-fix code before the fix was written, then confirmed
fixed — not just asserted fixed from reading the diff. No live provider
calls were made anywhere in this pass; every Gemini/Claude client is a
fake, matching this test suite's existing convention.

---

## CRITICAL

No findings.

## HIGH

### H-1 — Off-Peak cancellation can falsely report success while the provider job continues

**RESOLVED**, following **HD-1**'s recommended choice (confirmed with the
user): persist non-secret job metadata, and never report an outcome until
the provider actually confirms it.

Two independent bugs were confirmed and fixed, not one:

1. The poll loop's exit condition was `if terminal or cancelled: break` —
   so the very first poll *after* Stop was pressed ended the loop
   regardless of whether that poll's own result was terminal. A job still
   `JOB_STATE_RUNNING` would be reported as "cancelled" on the spot.
2. A poll *failure* right after Stop (`except Exception: if cancelled:
   break`) was treated identically — a transient network blip immediately
   after clicking Stop was enough to report false success, with no retry
   at all (contrast with an *uncancelled* run, which already tolerated
   transient poll failures).

Fix (`batch_transcription.py`, `run_off_peak_job()`):

- The loop now only exits on `if terminal: break` (a real terminal state,
  whatever it turns out to be). A poll failure after cancellation goes
  through the exact same bounded transient-retry-with-backoff path an
  uncancelled run already used (`_is_transient_poll_error()`,
  `MAX_CONSECUTIVE_POLL_FAILURES`) — no more special-cased shortcut.
- A new bounded **cancellation-confirmation deadline**
  (`CANCELLATION_CONFIRMATION_TIMEOUT_SECONDS = 600`, 10 minutes — the
  same duration `MAX_CONSECUTIVE_POLL_FAILURES` already uses for its own
  "give up and say so" bound) starts the moment Stop is first detected. If
  the job still hasn't reached a terminal state by then (polls succeeding
  but the job just isn't stopping, or polls failing but not enough to hit
  the failure-count bound), the run ends with a `status_unknown` outcome —
  "Off-peak batch cancellation could not be confirmed after 10 minutes —
  job {id} may still be running (and billing)... check the provider's own
  console" — never "cancelled."
- Once a terminal state *is* reached, the result is reported honestly, not
  just as "cancelled because Stop was pressed": a new `_batch_was_cancelled()`
  helper checks the job's own terminal state (Gemini
  `JOB_STATE_CANCELLED`; Claude's `canceled` count) before choosing the
  wording. If the job actually finished (e.g. `SUCCEEDED`) before the
  cancel request took effect, the summary says exactly that — real,
  complete results still exist and are still written; this isn't reported
  as a cancellation that didn't happen.
- Non-secret job metadata (provider, model, job id, submission timestamp,
  status) is now persisted to `app_state.OFF_PEAK_JOB_FILE`
  (`~/Library/Application Support/Customizable Transcription/
  off_peak_job.json`, and the Windows/Linux equivalents) at every stage —
  written `running` right after submission, updated
  `cancellation_requested` when Stop is first detected, updated
  `status_unknown` on an unconfirmed cancellation or any other fatal
  error, and **cleared** once a job is fully resolved (there is nothing
  left to recover once results are written). **The API key is never
  written to this file, or anywhere else this app persists to disk** — per
  HD-1's explicit constraint.
- On app startup, `app_state.surface_stale_off_peak_job()` (wired into
  `main()`) reads this file; if a job from a previous session is still
  unresolved (the app crashed, was closed, or a confirmation genuinely
  timed out), it's surfaced into the existing log/summary UI — "An
  off-peak batch job from a previous session may still be unresolved:
  provider X, job id Y, submitted Z, last known status W... check the
  provider's own console... click Reset All to dismiss." Dismissal reuses
  the existing Reset All flow (`reset_ui_state()` now also calls
  `clear_off_peak_job_state()`), rather than a new UI control.

**Deliberately not built: automatic reconnect-and-resume polling after a
restart.** HUMAN_DECISIONS.md's HD-1 left this as an open sub-question
("reconnect/recover after restart, or only provide the job ID for manual
provider-console recovery?"). The question put to the user described the
recommended option as keeping the job ID "visible even after an app
restart" — manual recovery, not silent automatic resumption — and that's
what was built. A real auto-resume would need a live API key to poll with,
which this app never persists (by the same HD-1 constraint), so it could
only ever be a "paste your key again to resume watching" flow at best —
a real feature in its own right, not a natural extension of this fix. Left
as a candidate follow-up, not implemented speculatively.

**One deliberate simplification vs. HD-1's literal 6-state list**
(`running` / `cancellation requested` / `cancellation confirmed` /
`completed` / `failed` / `status unknown`): `completed`, `cancellation
confirmed`, and `failed` are all represented the same way — by **deleting**
the persisted file — rather than as three more distinct status strings.
Once a job is fully resolved (results written, or a fatal error already
reported to the user in this same process), there's nothing a future
restart would need to show; a status string nobody will ever read isn't
worth a fourth/fifth/sixth branch. `running`, `cancellation_requested`, and
`status_unknown` are the three states that can actually still be on disk
when the app starts back up, and those are the three implemented.

**Files:** `batch_transcription.py`, `app_state.py`, `app.py` (wires
`surface_stale_off_peak_job()` into `main()`).

**Tests added:** `tests/test_offpeak_batch.py` —
`test_run_off_peak_job_cancellation_tolerates_a_transient_poll_failure_then_confirms`,
`test_run_off_peak_job_cancellation_that_never_confirms_is_not_reported_as_success`
(reproduces the exact false-success shape, asserts the summary is never the
old "cancelled" text, and that `status_unknown` was persisted),
`test_run_off_peak_job_reports_unconfirmed_when_cancellation_never_reaches_a_terminal_state`
(the "polls keep succeeding but the job just never stops" case, driven by a
fake monotonic clock),
`test_run_off_peak_job_reports_honestly_when_it_finishes_before_cancellation_takes_effect`,
`test_run_off_peak_job_persists_running_state_before_the_first_poll` (also
asserts the API key never appears in the persisted file), and the existing
success test now also asserts the persisted file is gone afterward.
`tests/test_app_state_sandboxing.py` — round-trip, Reset-All-clears, and
`surface_stale_off_peak_job()` tests for the new persistence functions,
matching this file's existing pattern for `APP_SETTINGS_FILE`.
`tests/conftest.py`'s `sandboxed_user_data` fixture now also patches
`app_state.OFF_PEAK_JOB_FILE`, following the exact same
patch-the-module-that-actually-owns-it discipline its own docstring already
documents (confirmed necessary: `write_off_peak_job_state()` etc. are
defined in `app_state.py` and always read `app_state`'s own global,
regardless of what `app.py`'s re-exported copy is patched to).

## MEDIUM

### M-1 — Off-Peak ignores the selected processing order

**RESOLVED.** `handlers/transcribe_offpeak.py` now passes `reverse_order:
order != "oldest"` through to `run_off_peak_job()`, which threads it into
`validated_images()` → `source_files(..., reverse_order=...)` — the same
switch the real-time `/run` path already used. The confirmation UI's
"Newest-to-oldest" promise now actually determines the submitted batch's
request order (and therefore the output's entry order).

**Tests added:** `test_validated_images_honors_reverse_order`,
`test_run_off_peak_job_honors_newest_first_order` (end-to-end, spies on
`submit_gemini_batch`'s actual image order), and
`test_run_offpeak_forwards_newest_first_order_to_the_job` (HTTP layer,
`order=newest` → `reverse_order is True` reaching the spawned job) plus a
`reverse_order is False` assertion added to the existing `order=oldest`
reservation test.

### M-2 — Off-Peak materializes an unbounded aggregate batch in memory

**RESOLVED**, following **HD-2**'s recommended choice (confirmed with the
user): reject an oversized batch up front, before any file is read.

`batch_transcription.py`'s `validated_images()` now enforces two caps
before submission:

- `MAX_BATCH_IMAGE_COUNT = 1000` — checked first, cheaply (`len(files)`),
  before touching the filesystem at all.
- `MAX_BATCH_AGGREGATE_BYTES = 2_000_000_000` (~2GB) — the sum of every
  source file's own size (Claude's ~1.33x base64 expansion on top of this
  is accepted as the cost of using that provider, not folded into the
  number itself, so both providers are held to the same "how many
  original-file bytes can this batch contain" limit). Accumulated
  alongside the existing per-file `validate_batch_source_file()` calls
  (which already `stat()` every file), so no file is `stat()`'d twice and
  no file's *contents* are ever read before the batch is accepted or
  rejected — matching the recommendation's own "before any file body is
  read" framing.

Exceeding either raises a clear `BatchSubmissionError` naming the actual
count/size and suggesting the folder be split.

**These two numbers are directional defaults, not measured against this
app's real workloads** — reasonable starting points for a local
single-user tool on a typical consumer-machine memory budget, explicitly
documented as such in the code's own comment. If real batches turn out to
run close to either limit, or a real host-memory budget is known, they're
two constants to adjust, not a design to rework.

**Not implemented, and deliberately out of scope for this fix:** the
validation/read TOCTOU race the finding also named (a file could change
between the `.stat()` check and the actual read inside `submit_*_batch()`).
This app's own threat model (see finding I-1: single trusted local user,
already an accepted, previously-decided constraint) has no adversary for
this race to matter to — only a user modifying their own in-progress
source folder mid-run, a self-inflicted edge case, not a security boundary.
Left as-is rather than adding re-validation-immediately-before-read
complexity for a scenario with no real attacker in this app's own
documented deployment model.

**Tests added:** `test_validated_images_rejects_over_item_count_cap`,
`test_validated_images_rejects_over_aggregate_byte_cap`,
`test_validated_images_accepts_a_batch_within_both_caps`.

### M-3 — Background provider calls rely on SDK-default timeouts and cannot honor Stop while blocked

**RESOLVED**, for the part of this finding specific to Off-Peak's own
client construction — see the scope note below for the one part
deliberately left as-is.

`batch_transcription.py` previously constructed one `genai.Client`/
`anthropic.Anthropic` per job with no timeout at all — every submission,
poll, cancel, and result-collection call relied on whatever the installed
SDK version's own internal default happened to be, which was never a
deliberate choice this app made and could silently change on a dependency
bump. Fixed with two explicit, bounded timeout tiers, each backed by its
own client:

- **Heavy** (`BATCH_SUBMIT_TIMEOUT_SECONDS`, = `core.py`'s existing
  `BATCH_REQUEST_TIMEOUT_SECONDS`, 600s): submission (uploads every
  image's full bytes in one request) and result collection (downloads
  every response) — genuinely large transfers, given the same generous
  bound the real-time per-image path already uses.
- **Light** (`BATCH_STATUS_TIMEOUT_SECONDS = 60`): polling and
  cancellation — small, fixed-size requests. A hung connection here is now
  caught in under a minute instead of potentially hanging for the SDK's
  own undocumented default, keeping Stop (which this loop only checks
  between polls) responsive.

A timeout during submission or result collection now raises a clear,
specific `BatchSubmissionError`/`RuntimeError` naming the elapsed time and
configured bound, rather than surfacing as a raw SDK exception or a
misleading "already retried N times" message from a different code path.
A timeout during **polling** — which Gemini's SDK lets escape as a bare
`httpx.TimeoutException` rather than wrapping it in `genai_errors.APIError`
the way Claude's SDK does (confirmed: `xls_conversion/ai_parser.py` and
`handlers/profiles.py` already catch `httpx.TimeoutException` directly for
this exact reason) — now goes through the loop's normal bounded
transient-retry treatment via a new `_is_transient_poll_error()` helper,
instead of aborting the whole job on a single timeout the way Gemini's
(previously unhandled) timeout used to.

**Scope note / one point not changed, with reasoning:** the finding also
named `run_support.py`'s real-time-run and Test Mode API-key checks
(`validate_api_key_with_retry()` calls in `run_job()`/`run_test_job()`) as
omitting the explicit timeout their own per-image calls use. That omission
is pre-existing, deliberate, and already documented in `make_client()`'s
own comment: those two callers run inside a background job thread with its
own progress log and Stop support, so an SDK-default timeout was judged
acceptable there, unlike a single foreground request with nothing else to
fall back on (Prompt Builder's Preflight Test, which *does* pass an
explicit timeout). Off-Peak's own client construction had no such
documented rationale for omitting a timeout — it simply never set one — so
that's the gap this fix closes. Revisiting the real-time/Test Mode
key-check design would be a second, separate, undecided scope change; not
folded into this fix.

**Tests added:**
`test_run_off_peak_job_uses_explicit_heavy_and_light_gemini_timeouts`,
`test_run_off_peak_job_submission_timeout_produces_a_clear_error`,
`test_run_off_peak_job_tolerates_a_gemini_poll_timeout` (the specific
previously-broken Gemini-timeout-during-poll case),
`test_run_off_peak_job_collect_results_timeout_produces_a_clear_error`.

## LOW

### L-1 — Off-Peak regression tests omit the paths where current defects occur

**RESOLVED**, as a direct consequence of fixing H-1/M-1/M-2/M-3 above —
every path L-1 named now has coverage (see each finding's own "Tests
added" list). One additional, explicit action this finding called for:
**the one test that "deliberately treats a post-cancel poll failure as
successful local completion"** (`test_run_off_peak_job_cancellation_
survives_a_poll_failure`) has been **removed**, not just left passing
by coincidence — it asserted the exact bug H-1 fixed. It's replaced by
`test_run_off_peak_job_cancellation_tolerates_a_transient_poll_failure_then_confirms`
(the same transient-failure-then-recovery scenario, but now asserting the
*correct*, confirmed outcome) and
`test_run_off_peak_job_cancellation_that_never_confirms_is_not_reported_as_success`
(a poll that never recovers, asserting the old bug's exact false-success
text never appears).

### L-2 — Gemini prompt caches are not cleaned up when XLS extraction exits early

**RESOLVED.** Both `preflight_generic()`'s and `parse_generic()`'s
per-image/per-block loops in `xls_conversion/ai_parser.py` now run inside
`try/finally`, with the existing best-effort `delete_gemini_prompt_cache()`
call moved into the `finally` block. `parse_generic()`'s own comment used
to justify *not* doing this by naming the exact scenario ("an index==0
failure re-raises out of this function before reaching it") as an accepted
minor cost — confirming, once tested, that it was a real gap worth
closing, not a hypothetical one. `delete_gemini_prompt_cache()` was already
fully best-effort (silently swallows its own failures), so this can never
turn a real failure into a different, more confusing one.

**Tests added:** `tests/test_prompt_caching.py` —
`test_preflight_generic_deletes_gemini_cache_even_when_the_loop_raises`,
`test_parse_generic_deletes_gemini_cache_even_when_the_first_image_raises`
(the latter reproduces the exact scenario the old comment named).

### L-3 — Advisory-only lint has accumulated a large, noisy baseline

**RESOLVED — by decision, not by code change.** HUMAN_DECISIONS.md already
lists "Lint remains informational/non-blocking in CI" under "Previously
resolved constraints retained," and Codex's own write-up says no new
decision is required for this finding. No lint-gate or baseline change was
made. `ruff check .` is 118 findings, identical to Codex's own reported
count — the one new `DTZ005` finding this pass introduced (a
`datetime.now()` call in the new `submitted_at_iso = ...` line, matching
this same file's own pre-existing, already-accepted `_log_timestamp()`
pattern) is offset by one finding no longer present after the M-1/M-3/L-2
mechanical fixes, so the net count Codex would see on a re-review is
unchanged.

## INFORMATIONAL

### I-1 — Authentication is intentionally absent under a single-user threat model

**RESOLVED — by decision, not by code change.** Previously decided by the
maintainer; no new decision required, and this pass didn't touch the
security-boundary code. (Referenced directly in M-2's own scope reasoning
above.)

### I-2 — Direct dependencies are pinned and current audits are clean, but the build is not fully immutable

**RESOLVED — by decision, not by code change.** Previously accepted risk;
no new decision required.

### I-3 — Approximately 2,500 lines of parser code are outside the live application

**RESOLVED — by decision, not by code change.** Previously decided by the
maintainer (retain as documented reference code); no new decision
required.

### I-4 — Automated coverage is strong at the Python/HTTP level but has no browser end-to-end suite

**RESOLVED — by decision, not by code change.** Previously decided by the
maintainer (defer browser automation); no new decision required. This
pass added 21 new Python/HTTP-level regression tests, consistent with the
documented "continue adding HTTP/module regression tests for every defect"
fallback this finding itself names.

---

## Summary of files changed

- `batch_transcription.py` — M-1 (`reverse_order` plumbing), M-2 (aggregate
  capacity caps), M-3 (explicit heavy/light timeouts,
  `_is_transient_poll_error()`), H-1 (honest cancellation confirmation,
  bounded deadline, `_batch_was_cancelled()`, job-state persistence calls).
- `app_state.py` — H-1 (`OFF_PEAK_JOB_FILE`, `write_off_peak_job_state()`,
  `clear_off_peak_job_state()`, `read_off_peak_job_state()`,
  `surface_stale_off_peak_job()`; `reset_ui_state()` now also clears it).
- `app.py` — H-1 (`surface_stale_off_peak_job()` wired into `main()`).
- `handlers/transcribe_offpeak.py` — M-1 (`reverse_order` forwarded to the
  job thread).
- `xls_conversion/ai_parser.py` — L-2 (`try/finally` around both cache
  lifecycles in `preflight_generic()`/`parse_generic()`).
- `tests/test_offpeak_batch.py` — new/replaced tests for M-1, M-2, M-3,
  H-1 (see each finding above).
- `tests/test_app_state_sandboxing.py` — new tests for the H-1 persistence
  functions.
- `tests/test_prompt_caching.py` — new tests for L-2.
- `tests/conftest.py` — `sandboxed_user_data` now also patches
  `app_state.OFF_PEAK_JOB_FILE` (required once H-1's persistence existed at
  all, or every `run_off_peak_job()` test would have written to the real
  per-user data directory).

CLAUDE STATUS: RESOLVED
