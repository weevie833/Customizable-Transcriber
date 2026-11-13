# Response to CODEX_REVIEW_2.md

Every finding below was independently re-verified against the actual source
before any action was taken. `CODEX_REVIEW_2.md` is a follow-up to
`CODEX_REVIEW.md`/`CLAUDE_RESPONSE.md`/`HUMAN_DECISIONS.md`, and it correctly
identified two real, concrete bugs in the prior repair (M-2, M-3), one real
CI regression the prior repair introduced (L-5), one documentation accuracy
gap (L-6), and one real process gap in how this whole exercise was tracked
(N-1: `HUMAN_DECISIONS.md` never recorded which options were actually
selected). All five are fixed below. The remaining `HUMAN_DECISION_REQUIRED`
items (M-4, M-7, L-8) were, in fact, already decided by the user interactively
in the session that produced the prior repair — `CODEX_REVIEW_2.md` had no way
to know that, since the decisions were never written back into
`HUMAN_DECISIONS.md` (exactly what N-1 flags). Fixing N-1 makes that
traceable for future review passes.

**Validation performed after all changes:** `pytest tests/` → 193 passed (up
from 191 reported in `CODEX_REVIEW_2.md`; 2 new regression tests added,
0 removed). The offline `xls_conversion/tests/run_parser_test.py` harness
still passes. `py_compile` across every touched module succeeds. Node
`--check` on every touched/loaded JS file passes. `pip check` clean after
the new `requirements-dev.txt` pins. A live browser smoke check confirmed
the fixed `xls_conversion/app.js` is served correctly with no console
errors. Every new/changed test was verified to fail against the pre-fix
code (via a manual revert-test-restore cycle, not `git stash`, after an
earlier `git stash` attempt on `app.py` proved risky against this
session's large accumulated diff) before the fix was applied.

---

## Prior-finding disposition (from CODEX_REVIEW_2.md's own table)

### H-1, M-1, M-5, M-6, L-1, L-2, L-3, L-4, L-7, I-1 — RESOLVED

Independently re-verified: agree with `CODEX_REVIEW_2.md`'s own assessment.
No further action.

### M-2 — STILL_OPEN → RESOLVED

**Verified the finding is real:** `all_image_numbers_capped()` caps the
*deduplicated* count of marker numbers, but `split_image_blocks()` (which
`parse_generic()`'s loop actually iterates, one AI call per entry) emits
one block per marker *occurrence* — not per distinct number. A
transcription containing the same marker repeated past
`MAX_IMAGES_PER_REQUEST` times would pass the deduped-count check while
still producing that many blocks/AI calls. Confirmed by temporarily
reverting the fix and reproducing exactly this with a synthetic
5,001-times-repeated marker.

**What was changed:**
- `xls_conversion/ai_parser.py`: `parse_generic()` now checks
  `len(blocks) > MAX_IMAGES_PER_REQUEST` (the actual unit that drives
  AI-provider call count) immediately after `split_image_blocks()` computes
  them, before the per-block loop starts. This applies to both the
  `process_all` and explicit-range paths, since the same repeated-marker
  issue affects both (a range's own dedup only bounds distinct numbers,
  not occurrences).
- `xls_conversion/app.js`: `estimateImageCount()`'s `process_all` branch
  now counts marker *occurrences* instead of deduplicating into a `Set`,
  so the "Estimated: ~N images" display and the large-run confirmation
  dialog no longer understate a repeated-marker document's real cost.
- Files changed: `xls_conversion/ai_parser.py`, `xls_conversion/app.js`.
- New test: `tests/test_image_range.py::test_repeated_marker_numbers_still_hit_the_block_cap`
  — builds a transcript with the same marker repeated `MAX_IMAGES_PER_REQUEST + 1`
  times, confirms `all_image_numbers_capped()` alone would NOT catch it
  (proving the premise), then confirms `parse_generic()` rejects it before
  calling the (mocked) AI function at all. Confirmed to fail on the
  pre-fix code, pass on the fix.

### M-3 — STILL_OPEN → RESOLVED

**Verified the finding is real:** `validate_api_key_with_retry()` already
resolves a blank pasted key to a configured `.env` key internally (via
`make_client()`'s own `(override or "").strip() or api_key(project_dir)`
fallback) and validates *that* resolved key. But `detect_xls_languages()`
then called `detect_languages()` with the *original*, still-blank
`api_key_value` — which immediately raised "Paste an API key before
detecting languages." even though validation had just succeeded using a
real `.env`-sourced key. Confirmed this is genuinely a bug in the
*implementation* of an already-decided policy (documented in
`HUMAN_DECISIONS.md`'s M-3 entry, now dated and recorded — see the N-1
section below), not a case where the policy itself needed to be decided
again: Prompt Builder's Preflight Test — the other tool this same
`.env`-honoring policy applies to — does not have this bug, since it
passes `api_key_override` straight into `make_client()` once and reuses
the resulting client, never re-checking the original value a second time.

**What was changed:**
- `app.py`: `detect_xls_languages()` now resolves the effective key the
  same way `critique_prompt_gap()` already does elsewhere in this file
  (`api_key_value or (claude_api_key(...) if claude else api_key(...))`)
  and passes *that* to `detect_languages()`, instead of the original
  possibly-blank pasted value.
- `xls_conversion/app.js`: `setBusy()`'s `detectLanguagesButton.disabled`
  no longer requires `apiKeyEntered` (Preflight/Convert/Ignore still do —
  that friction is deliberate and unchanged, per this project's own prior
  M-3 resolution). `runLanguageDetection()`'s redundant client-side blank-key
  early-return (which would have blocked the request even with the button
  enabled) was removed. A click with genuinely no key configured anywhere
  still fails cleanly with a clear server-side error.
- Files changed: `app.py`, `xls_conversion/app.js`.
- New test:
  `tests/test_xls_conversion_preflight_key_check.py::test_detect_languages_honors_a_blank_key_via_env_fallback`
  — mocks `validate_api_key_with_retry` (success) and `api_key()` (returns
  a known fake key), sends a blank `gemini_api_key`, and confirms
  `detect_languages()` actually receives the resolved key, not the blank
  value. Confirmed to fail on the pre-fix code, pass on the fix.

### M-4, M-7, L-8 — HUMAN_DECISION_REQUIRED → decisions recorded (see N-1)

These were already decided by the user interactively during the session
that produced the prior repair (`M-4`: leave last-writer-wins as-is;
`M-7`: leave coverage as-is for now; `L-8`: split `app.py` further — yes,
deferred as a follow-up task; audit exception catches — done; lint in
CI — yes, informational). `CODEX_REVIEW_2.md` could not have known this,
since `HUMAN_DECISIONS.md` never recorded it — see N-1 below, now fixed.
No new decision was made or changed as part of this response; the
dispositions above are exactly what was already implemented.

### L-5 — REGRESSION_INTRODUCED → RESOLVED

**Verified the finding is real:** the prior repair's new `lint` CI job ran
`pip install ruff` with no version pin, and the pre-existing
`dependency-audit` job ran `pip install pip-audit` the same way — both
unreviewed executables landing in CI on every run, the exact class of risk
this file's own exact-pinning convention (already applied to `pytest`)
exists to avoid.

**What was changed:** Added `ruff==0.16.7` and `pip-audit==2.10.1` to
`requirements-dev.txt` (current latest of each, confirmed via `pip index
versions`), matching the existing `pytest` pin's own convention and
rationale comment. Both CI jobs now install from `requirements-dev.txt`
instead of a bare `pip install <tool>`. Also fixed the one Ruff finding
`CODEX_REVIEW_2.md` flagged directly (an unused `import os` in
`tests/test_batch_source_file_limits.py`).
- Files changed: `requirements-dev.txt`, `.github/workflows/tests.yml`,
  `tests/test_batch_source_file_limits.py`.
- Verified: `pip install -r requirements-dev.txt` installs cleanly with no
  conflicts (`pip check` passes); `ruff --version` confirms `0.16.7` is
  what actually runs.
- **Not done, matching the original decision's own scope:** full
  transitive-dependency lock file and GitHub Actions SHA-pinning remain
  the maintainer's explicitly-recorded choice not to adopt (see
  `HUMAN_DECISIONS.md`'s L-5 entry) — pinning the two newly-floating CI
  tools is the same "pin what's floating" policy already selected, not an
  expansion of it.

### L-6 — STILL_OPEN → RESOLVED

**Verified the finding is real:** `xls_conversion/README.md` stated the
three dormant regex parsers "are exercised only by the offline regression
tests under `xls_conversion/tests/`" — but a direct search of
`xls_conversion/tests/harness.js` and `run_parser_test.py` confirms only
`baptism-parser.js` is ever loaded or referenced; `matrimony-parser.js` and
`morti-parser.js` have zero execution path or test coverage anywhere in
the repo. `docs/DESIGN.md`'s own mention of this topic was already
accurate (it only discusses `baptism-parser.js` and makes no claim about
the other two).

**What was changed:** Corrected `xls_conversion/README.md` to state
plainly that only `baptism-parser.js` is tested, and that
`matrimony-parser.js`/`morti-parser.js` are unmaintained reference code
with no coverage and no execution path. This is a documentation
correction under the already-recorded L-6 decision (keep as documented
reference-only) — not a reopening of whether to archive or revive the
parsers.
- Files changed: `xls_conversion/README.md`.

## New findings

### N-1 — HUMAN_DECISIONS.md records no decisions → RESOLVED

**Verified the finding is entirely correct:** `HUMAN_DECISIONS.md` shipped
as a pure options/recommendations memo. Multiple source comments and this
project's own prior response cited it as authority for implemented
choices, but nothing in the file itself distinguished a user-approved
selection from Claude's own recommendation being implemented
unilaterally — a real, material gap for exactly the categories the review
names (authentication scope, stored-key behavior, stale-write data loss,
dependency policy, non-enforcing quality gates).

**What was changed:** `HUMAN_DECISIONS.md` now opens with a dated
"Decisions recorded — 2026-09-10" section: a summary table naming the
option selected and resulting action for all 12 original items, explicit
that every decision was made by the user in chat (not invented or assumed
by Claude), plus notes on the two cases where a decision's *implementation*
was later found to have a bug (M-3, L-6) versus being reopened. Each of
the 12 numbered sections in the file also got its own inline
"**Decision selected (2026-09-10, by the user in chat):**" entry, placed
right after Claude's own recommendation and before the "Blocks other
findings" line, so a reader scanning any one entry sees the actual outcome
without needing the summary table. No approvals were invented — every
entry reflects what was actually chosen in this session's own
conversation history.
- Files changed: `HUMAN_DECISIONS.md`.

---

## Summary of files changed

- `xls_conversion/ai_parser.py` — M-2 (block-count cap enforced against
  actual blocks, not deduped numbers)
- `xls_conversion/app.js` — M-2 (accurate occurrence-based estimate), M-3
  (Detect Languages no longer client-gated on a pasted key)
- `app.py` — M-3 (effective-key resolution for Detect Languages)
- `requirements-dev.txt` — L-5 (ruff/pip-audit exact-pinned)
- `.github/workflows/tests.yml` — L-5 (both CI jobs install from
  requirements-dev.txt)
- `xls_conversion/README.md` — L-6 (corrected parser test-coverage claim)
- `HUMAN_DECISIONS.md` — N-1 (decisions recorded throughout)
- `tests/test_image_range.py` — M-2 test
- `tests/test_xls_conversion_preflight_key_check.py` — M-3 test
- `tests/test_batch_source_file_limits.py` — L-5 (unused-import cleanup)

No changes were committed or pushed.

---

CLAUDE STATUS: READY_FOR_REVIEW
