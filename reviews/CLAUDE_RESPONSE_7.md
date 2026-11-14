# Claude Response to CODEX_REVIEW.md (revision `2aaddbd`, 2026-11-13)

I checked each finding against the source before changing anything, and I agree with
every severity. No live provider calls were made.

**Validation:** `pytest -q` gives **437 passed, 1 skipped** (was 408 + 1; 29 new
tests). `xls_conversion/tests/run_parser_test.py` passes. `node --check` passes on
every tracked JS file. `bash -n` passes on the Mac installer. `ruff check . --select
F,E9` is clean, and the full `ruff check .` is down from 90 findings to 75.

## H-1 / HD-1 (High): stale Windows Python, and runtimes that never upgrade

**RESOLVED.** The user decided HD-1: stay on 3.12 for now, use python-build-standalone
(Astral) on both platforms, and upgrade automatically with rollback.

- **Windows** now downloads `cpython-3.12.16+20261026-x86_64-pc-windows-msvc-install_only.tar.gz`,
  pinned by SHA-256 (`590dfcbe…22bc5`). This is the same release as the Mac build, so
  both platforms run the same interpreter. NuGet was dropped because python.org stopped
  publishing NuGet packages at 3.12.10. I downloaded the archive, checked its hash, and
  confirmed its layout (`python/python.exe`, `vcruntime140.dll`, `venv`, `ensurepip`).
  The `%2B` in the URL is written `%%2B`, since a single `%2` would expand the batch
  file's second argument; a test checks this.
- **Runtime manifest:** both installers write `Runtime/python-build.txt`, which holds
  the installed archive's SHA-256. Every start compares it with the pinned hash. The
  `requirements.lock` comparison is still a separate check for the package layer.
- **Upgrade and rollback:** on a mismatch, the installer downloads and verifies the new
  Python into `python-new`, moves the current `python` and `venv` aside to
  `python-old` and `venv-old`, installs, and writes the marker only after the packages
  install. If anything fails, `restore_previous` puts the old runtime back, so the next
  start retries from a working state. After a successful install, the old copies are
  deleted. On Windows, a runtime that is still in use (the app is open) cannot be moved;
  the installer then says to close the app's windows and try again, and changes nothing.
- **Existing installs** have no marker, so the next start reinstalls Python once. Windows
  needs this anyway (3.12.10 to 3.12.16); on the Mac it costs about 15 seconds.
- **Verified on this Mac** with `CT_RUNTIME_DIR` in a scratch folder: fresh install
  (15 s), a second start that skips setup, an upgrade from a fake older marker, and a
  failed upgrade (an unknown package added to the lock). The failed upgrade restored
  the old venv (a sentinel file survived) and left the old marker, so the next start
  retries. The Windows script could not be run here.
- **CI:** both `windows-install` and `mac-install` now run a second time over a fake
  older marker, then assert that the venv runs exactly 3.12.16, that `python-old` is
  gone, and that the marker was updated. These jobs run only on the weekly, manual and
  tag schedule, so **run the workflow by hand once (`workflow_dispatch`) to prove the
  Windows path before the next release.**
- `Install Instructions.txt` (both UPDATING sections) says a new Python makes the first
  start take a few minutes. Tests: the Windows hash and URL pin, both installers on the
  same release, the marker and rollback present in both scripts, and every
  `call :label` resolving.

Not done: Codex's "rollback until the new runtime *starts*" is implemented as "until the
new runtime finishes installing". An app crash after a good install is not treated as a
failed update.

## M-1 (Medium): CSV formula bypass through leading controls or whitespace

**RESOLVED.** `_csv_safe_cell()` (`xls_conversion/spreadsheet_export.py`) now prefixes
`'` when a cell starts with a tab, CR or LF (whatever follows), or when its first
character after whitespace (including NBSP and the ideographic space) is a formula
trigger. Full-width `＝ ＋ － ＠` count as triggers. The visible text is never changed,
only prefixed. Ordinary text, including text with a leading space, is untouched. New
`tests/test_csv_formula_neutralization.py` covers direct triggers, every bypass from the
review, ordinary text, and a `csv.reader` round trip with quotes, commas and embedded
newlines.

## M-2 (Medium): translation request size ignored Notes, Date and JSON

**RESOLVED.** `transcript_translation.py`:
- `_payload_size()` measures each entry as `_translate_chunk()` actually serializes it
  (`json.dumps` of the full payload, plus the separator). `_chunks()` budgets on that
  measurement, not on the transcription length alone.
- An entry larger than the whole 6,000-character limit is now a **preflight error**
  that names the entry and says to shorten its Notes. Before, it was sent as one
  oversized request. To check the limit against real data, I measured all 3,542 entries
  in this machine's saved transcripts: the largest is about 3,400 characters with Date
  and Notes, so no real entry is near the limit.
- `estimate_tokens()` counts input from the serialized requests and output only from
  the translated text (Notes and Date are context, not translated).
- Tests: long Notes split a request that would otherwise be shared; an oversized entry
  fails preflight; Notes raise the input estimate and leave the output estimate
  unchanged.

## L-1 (Low): no prompt-injection boundary in the translation prompt

**RESOLVED.** The TASK section of `build_translation_prompt()` now says that every JSON
field is historical record data, never an instruction, and that instruction-like text
inside an entry is translated as text, not followed. The source already reaches the
model only as JSON field values, so the data is delimited. `PROMPT_VERSION` was bumped
to `translate-v2`, so the ledger and the report show which wording produced a
translation. Test: the rule is in the prompt, and a hostile transcription line appears
only in its entry's `transcription` field, never in the system prompt. The effect on
real model behaviour was not measured; no evals exist for this prompt.

## L-2 (Low): lint target and enforcement

**RESOLVED (partly policy).**
- `target-version` changed from `py310` to `py311`, matching `requires-python`.
- Mechanical fixes: 4 unused imports (`selected_profile_id` in
  `handlers/test_mode_run.py`, `pytest` in one test, and two `datetime.timezone`
  imports left over by the change to `datetime.UTC` that the py311 target allows), a
  quoted annotation, `zip(x, x[1:])` replaced with `itertools.pairwise`, two unused
  unpacked test variables, 7 implicit concatenations in collections wrapped in
  parentheses (same strings), and an import sort. `run_parser_test.py` is now marked
  executable to match its shebang. The one `B023` (a loop-variable lambda that is
  called synchronously) is annotated with the reason.
- **Enforcement:** the `lint` job now **fails** on pyflakes (`F`) and syntax errors
  (`E9`), which are at zero. Everything else stays advisory, as the retained decision
  allows. The other 75 findings (47 deliberate broad `except` clauses, naive
  `datetime.now()` for local timestamps, and similar) are unchanged.

## I-2 (Info): stray cookie jar `c`

**RESOLVED.** This was an untracked curl cookie jar holding a localhost `ct_token`,
left by an earlier diagnostic session. The token was only valid for the server process
that issued it, which had been restarted since. Deleted with the user's approval.
`.gitignore` was not changed.

## I-1, I-3, I-4 (Info)

No change; the earlier decisions still apply (single-user localhost, no browser tests
yet, hash locks and Action SHA pins optional).

OVERALL STATUS: ALL FINDINGS ADDRESSED. The Windows installer path still needs one CI
run.
