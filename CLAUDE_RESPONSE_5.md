# Claude Response to CODEX_REVIEW.md (2026-09-20 re-review, `a4e3328`)

Every finding below was independently re-verified against the actual source
before anything was changed. Each was traced to the exact lines named and its
mechanism reproduced or confirmed by reading the code (for example: the
Anthropic SDK's default `max_retries` is 2 and `submit_claude_batch()` passed
no override; `validate_api_key()` really was called with `timeout_seconds=None`
from `run_job()`/`run_test_job()`; `write_off_peak_job_state()` really swallowed
every `OSError` while the cancellation message promised the id "is saved";
the preflight really sent only `examples[i].text`). No exceptions or
disagreements with Codex's severity/bucket labels this round.

Four findings (H-1, H-2, M-1, M-2) carried real product tradeoffs Codex
correctly marked `HUMAN_DECISION_REQUIRED`. All four were put to the user
directly, with the recommended option chosen for each (HD-1..HD-4 below). All
other findings were safe to fix (or document) without a new decision and were
handled in this pass. No entry is left open.

**Validation performed for every fix:** `pytest -q` -> **297 passed** (up from
Codex's reported 274; 23 new tests, 0 weakened, 1 assertion tightened in
`test_run_off_peak_job_submission_timeout_produces_a_clear_error`).
`node --check` on every touched JavaScript file. The offline
`xls_conversion/tests/run_parser_test.py` still passes. `ruff check .` -> 72
findings (was 124 at the start of this pass). No live provider calls were made;
every Gemini/Claude client is a fake, matching this suite's convention. The
Prompt Builder preflight serialization (M-1) was additionally checked in a real
browser against a running copy of the app with `fetch` stubbed, capturing the
exact multipart `example_entry` that would be uploaded.

---

## CRITICAL

No findings.

## HIGH

### H-1 — A timed-out Off-Peak submission can create an untracked or duplicate paid job

**RESOLVED**, following **HD-1**'s lower-scope choice (confirmed with the user).

Confirmed as described: the job id is only known after the create response
returns; the pinned Anthropic SDK retries a failed/timed-out request twice by
default and `client.messages.batches.create(requests=...)` supplied no override;
Gemini's batch display name was the constant `"customizable-transcription-
offpeak"`; and the timeout message ended "Try again". Any of those could pay for
the same batch twice.

Decision (HD-1): take the lower-scope option, not the full `submitting` record +
reconciliation workflow. Recovery of a lost id stays manual (provider dashboard),
which is what the earlier accepted off-peak recovery decision already assumed.

What changed (`batch_transcription.py`):

- `submit_claude_batch()` now calls `client.with_options(max_retries=0)` for the
  create call - the SDK can no longer silently create a second batch.
- `submit_gemini_batch()` gives every batch a unique display name
  (`customizable-transcription-offpeak-<12 hex>`), so a lost-response job can be
  found in the provider's console.
- The submission error now catches `httpx.TimeoutException`,
  `httpx.RemoteProtocolError` and `anthropic.APIConnectionError` (Claude's own
  timeout is an `APIConnectionError` subclass and previously fell through to a
  generic error) and says **"Submission outcome unknown ... check your
  <Provider> account's batch list/dashboard ... BEFORE trying again"** instead
  of "Try again".
- Not done, by decision: no persisted `submitting` record, no acknowledgement
  gate, no automatic provider-list reconciliation.

Tests: `test_submit_claude_batch_tags_each_request_with_custom_id` now asserts
`max_retries=0` was applied; new `test_gemini_batches_get_a_unique_display_name`;
`test_run_off_peak_job_submission_timeout_produces_a_clear_error` asserts the
"outcome unknown / BEFORE trying again" wording and the absence of "Try again".

### H-2 — Continuation merging can silently erase previously extracted record fields

**RESOLVED**, following **HD-2**'s recommended choice ("original wins, conflict
logged").

Confirmed: both merge paths (`try_apply_merge()` for the forward/backward flag
paths, and the deterministic leading-fragment path) popped the previous row and
replaced it with the model's returned row; the only gate was that the new row's
notes said it continued, and only notes/source-image bookkeeping (plus two
locator fields in one path) were preserved. A merge call that dropped or altered
a field silently changed the spreadsheet.

Decision (HD-2): conservative field-level merge. A blank never erases a value;
a conflicting non-empty value keeps the original and is listed in the exception
log with both values; continuation-only facts fill blanks; if the merge returns
a different act/page/entry number it is not the same record and both rows are
kept. Warnings only - export is never blocked. Applied to every field of every
record type (no per-type immutable/append-only table; the uniform rule is the
conservative superset).

What changed (`xls_conversion/ai_parser.py`): new `apply_merge_invariants()`
(and `_MERGE_IDENTITY_FIELDS`), called from both merge paths *before* the
previous row is popped, so a rejected merge leaves the original row untouched
and falls back to the existing "extract the whole block without merging" path.
Conflicts are appended to `exception_log` as `continuation merge conflict --
<field>: kept "<original>" (continuation returned "<new>")`. Notes keep using
`merge_notes()`.

Tests (`tests/test_continuation_merge_invariants.py`, new, 17 tests): blank never
erases and blanks fill, parametrized over **all six record types**; conflicting
value keeps the original and is reported (all six types); case/spacing-only
differences are not conflicts; different act number rejects; blank act number is
filled; and two end-to-end `parse_generic()` cases (merge that drops/alters
fields; merge returning a different act keeps both rows).

## MEDIUM

### M-1 — Prompt Builder preflight compares only the main text and ignores structured example data

**RESOLVED**, following **HD-3**'s recommended choice (one image; Date + Main +
side block; Continuation excluded).

Confirmed: `runPreflightTest()` sent `(examples[i]).text` as `example_entry` only,
so the Date line and Baptism/Church Wedding Record were never compared, while the
server described that string as the complete known-correct example.

What changed:

- `static/prompt-builder.js`: new `exampleAsPreflightText()` builds ground truth
  from Date, Main entry and the applicable Baptism / Church Wedding Record (using
  the existing labelled composition), with the Continuation deliberately cleared -
  it is the opening of the *next* image, which was not uploaded.
- `handlers/profiles.py`: the critique system prompt now explains the labelled
  parts, tells the model to compare each part with the matching block, and to
  ignore any continuation note in the output.
- `pages/prompt_builder.py` + `static/i18n.js`: a hint under the preflight text
  states the scope in the UI (English and Italian).

Verified in a live browser with `fetch` stubbed: with a Date, Main entry,
Baptism Record and Continuation filled in, the uploaded `example_entry` was
`Date:\n\n19 Luglio 1834 [...]\n\nMain entry:\n\nMAIN TEXT\n\nBaptism Record:\n\nBAPTISM TEXT`
- no continuation. Test: `test_preflight_critique_prompt_explains_labelled_example_parts`.
There is still no browser-level test in CI (see I-4); this was checked by hand.

### M-2 — The 2 GB Off-Peak aggregate cap still permits process-level memory exhaustion

**RESOLVED**, following **HD-4**'s recommended choice (conservative cap now,
manual splitting).

Confirmed: the 2,000,000,000-byte limit was an unmeasured default; Claude keeps
base64 copies (~1.33x) on top of the raw bytes plus request serialization.

Decision (HD-4): lower the in-memory cap to a conservative value and require
splitting larger folders; revisit with measured peak memory if too tight.
`MAX_BATCH_AGGREGATE_BYTES` is now **500,000,000** (500 MB of raw source files,
roughly 350-400 typical JPEGs). The existing rejection message already tells the
user to split by sub-folder/date range and states the limit. Not done, by
decision: memory measurement, provider-specific limits, provider-side file
staging/streaming. Test: `test_aggregate_cap_is_conservative`.

### M-3 — Real-time and Test Mode key validation still cannot be stopped promptly

**RESOLVED.** Safe fix, no decision needed.

Confirmed: `validate_api_key()` defaulted `timeout_seconds` to `None` (the SDK's
own default) and its comment assumed Stop could interrupt it; Stop is only
checked between calls.

What changed (`customizable_transcription/core.py`): new
`KEY_CHECK_TIMEOUT_SECONDS = 60`, now the default for `validate_api_key()` and
`validate_api_key_with_retry()` (so `run_job`, `run_test_job` and XLS
Conversion's key checks are all bounded; Prompt Builder still passes its own
90 s). A stall (`httpx.TimeoutException` / `anthropic.APITimeoutError`) is
re-raised as a plain `RuntimeError("The API key check did not finish within 60s
... Check your network connection and try again.")`, which is not classed as
transient, so it is not silently retried three times. True mid-call cancellation
still isn't possible (as Codex noted); the bounded timeout is the practical
minimum. Tests (`tests/test_key_check_timeout.py`): default timeout reaches the
client; a stalled check raises the clear error after exactly one attempt.

## LOW

### L-1 — Failed Off-Peak state persistence is silent while the UI promises recovery

**RESOLVED.** Safe fix.

Confirmed: `write_off_peak_job_state()` returned `None` and swallowed `OSError`;
the cancellation-unknown summary said the id "is saved and will be shown again"
unconditionally.

What changed: `write_off_peak_job_state()` (`app_state.py`) now returns
`True/False` and writes a run-log warning on failure ("could not save the
off-peak job record ... copy it from this log now"); the cancellation-unknown
summary (`batch_transcription.py`) says the id was saved only if it was, and
otherwise tells the user to copy it from the message. `surface_stale_off_peak_job()`
now reports an off-peak record that exists on disk but can't be read (corrupt or
unreadable), instead of silently forgetting it. Test:
`test_failed_job_state_write_is_reported_not_silent`.

### L-2 — The lint baseline remains too noisy to act as a regression control

**RESOLVED for the mechanical part; CI gate unchanged, by prior decision.**

Ran Ruff's safe autofixes (`ruff check . --fix`, no `--unsafe-fixes`): unsorted
imports, manual from-imports, unnecessary `.encode("utf-8")`, and unused
imports. Findings went **124 -> 72**. Two things worth recording:

- The autofix removed three imports from `app.py` that look unused but are
  deliberate re-exports the test suite reaches through `app.*`
  (`save_custom_profile`, `test_lock`, `test_state`); 10 tests failed until they
  were restored with explicit `# noqa: F401 -- re-exported for tests` comments,
  matching the file's existing convention. Anyone running `--fix` again on `app.py`
  should expect this.
- The remaining 72 are the intentionally broad handlers (`BLE001`), `TRY004`,
  `DTZ005` (already an accepted convention for this file), etc. Making Ruff a
  blocking CI gate remains the maintainer's previously accepted "informational"
  policy (`HUMAN_DECISIONS.md`, "Previously resolved constraints"), so the CI
  workflow was not changed.

### L-3 — Documentation overstates continuation-note determinism

**RESOLVED.** Documentation only.

Confirmed: the docs said the notes are "written by the app, not the model". In
fact the model must recognise the split and emit the fixed sentence; the app only
standardizes a matching sentence and adds the neighbour's name. Corrected in
`README.md`, `docs/DESIGN.md` and `xls_conversion/README.md` (and the local
`CLAUDE.md`/`HANDOFF.md`): the model detects the split, the app standardizes the
note, and a split the model misses is **not** marked or merged, so users should
spot-check pages where an entry runs off the bottom. The docs also now describe
the H-2 field-level merge guard. Heuristic visual detection remains
unimplemented (separate design).

## INFORMATIONAL

### I-1 — Authentication remains intentionally absent under a single-user threat model

**RESOLVED - by decision, not by code change.** Previously decided (single-user
machine only, documented in `SECURITY.md`). No change.

### I-2 — Secret handling is repository-safe, but local `.env` permissions rely on the single-user assumption

**RESOLVED - documentation hardening.** `README.md` now tells users to
`chmod 600 .env` and to prefer pasting the key on a shared computer. No code
change (`.env` is user-created).

### I-3 — Dependency audits are clean, but builds are not fully immutable

**RESOLVED - by decision, not by code change.** Previously accepted (exact
direct pins; hash-locked transitives and commit-SHA Actions not required).

### I-4 — Python/HTTP coverage is strong, but browser behavior remains unexecuted in CI

**RESOLVED - by decision, not by code change.** Browser automation remains
deferred. Noted in M-1: the preflight fix was verified in a real browser by hand,
which is exactly the gap this finding describes; the extracted-serializer or
Playwright option remains open if Prompt Builder keeps growing.

---

## Summary of files changed

- `batch_transcription.py` - H-1 (no SDK retry on create, unique Gemini display
  name, "outcome unknown" message, `uuid` import), M-2 (500 MB cap), L-1
  (honest "saved" wording).
- `app_state.py` - L-1 (`write_off_peak_job_state()` returns success and logs a
  failure; `surface_stale_off_peak_job()` reports an unreadable record).
- `xls_conversion/ai_parser.py` - H-2 (`apply_merge_invariants()`, wired into
  both merge paths).
- `customizable_transcription/core.py` - M-3 (`KEY_CHECK_TIMEOUT_SECONDS`, bounded
  key check with a plain timeout error, `httpx` import).
- `static/prompt-builder.js`, `handlers/profiles.py`, `pages/prompt_builder.py`,
  `static/i18n.js` - M-1 (preflight ground truth, critique-prompt wording, UI
  scope hint incl. Italian).
- `app.py` - L-2 (re-export imports restored with `noqa` after autofix); plus
  Ruff's safe autofixes across ~40 other modules/tests (import ordering etc.,
  no behavior change; full suite green).
- `README.md`, `docs/DESIGN.md`, `xls_conversion/README.md` - L-3, I-2.
- `tests/test_continuation_merge_invariants.py` (new), `tests/test_key_check_timeout.py`
  (new), `tests/test_offpeak_batch.py`, `tests/test_prompt_builder_preflight.py`
  - new/updated tests for H-1, H-2, M-1, M-2, M-3, L-1.

CLAUDE STATUS: RESOLVED
