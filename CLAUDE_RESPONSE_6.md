# Claude Response to SECURITY_REVIEW_4.md (revision `628adf2`)

Each finding was checked against the source before changing anything. No
disagreements with the reviewer's severities. No live provider calls were made.

**Validation:** `pytest -q` -> **325 passed** (324 + 1 new). `pip-audit` (both
`requirements.txt` and the installed environment) -> **No known vulnerabilities
found** (was 17: 3 `urllib3`, 14 `pip`). `ruff check .` -> 75 findings, unchanged
informational baseline (no new ones). `xls_conversion/tests/run_parser_test.py`
passes. `node --check` passes on every tracked JS file.

## Section 3 / 6 — `urllib3` CVEs (PYSEC-2026-4175/4176/4177) and `pip` CVEs

**RESOLVED.** `requirements.txt` now exact-pins `urllib3==2.8.0` with a comment in
the same style as the `cryptography`/`pyasn1` pins (L-5). `pip` was upgraded in
`.venv` (environment-only; not a repo change). Audit re-run clean.

## SEC-4-02 (Low) — Gemini reasoning-cap gate hardcoded to `gemini-3`

**RESOLVED.** `customizable_transcription/core.py`: new `_CAPPABLE_GEMINI_PREFIXES =
("gemini-3", "gemini-4")`, used by `_gemini_thinking_is_cappable()`, which gates both
the thinking-level cap and the `MAX_TOKENS` truncation retry. The same hardcoded
check in `xls_conversion/ai_parser.py` (`call_gemini_json`'s thinking config, found
while grepping) was widened identically so the two stay in sync. A prefix tuple was
chosen over dynamic feature detection: the SDK exposes `ThinkingLevel` globally, not
per model, so it cannot tell a model that supports it from one that does not. Test:
`test_gemini_thinking_cappable_covers_3_and_4_but_not_25` (3.x and 4.x true;
`gemini-2.5-pro` and Claude false); the existing 2.5-pro no-retry test is unchanged.

## SEC-4-01 (Medium) / HD-4 — Off-Peak in-memory payloads

**RESOLVED by documentation; no code change.** The reviewer's premise that nothing
bounds the batch is out of date: review round 5 (M-2) already added
`MAX_BATCH_AGGREGATE_BYTES` = 500 MB (halved with Page zoom) and
`MAX_BATCH_IMAGE_COUNT` = 1,000, enforced by `validated_images()` from `stat()`
metadata before any file is read, plus the 50 MB per-file cap. Worst case is roughly
1-1.5 GB resident for Claude (base64 copy), so a 100-200 scan batch is either within
the envelope or rejected up front with a split-the-folder message. Disk-staged /
chunked-JSONL submission was not built (only relevant to multi-GB batches); recorded
in `docs/DESIGN.md` ("Off-Peak memory envelope") and a status note under HD-4 in
`HUMAN_DECISIONS.md`, which stays open for measured per-provider limits.

## Section 5 — prior findings tracking

H-1, H-2, M-1, M-2, M-3, L-2 verified resolved by the reviewer; no action. L-5 is
now closed by the `urllib3` pin above.

## Files changed

`requirements.txt`, `customizable_transcription/core.py`,
`xls_conversion/ai_parser.py`, `tests/test_provider_error_messages.py`,
`docs/DESIGN.md`, `HUMAN_DECISIONS.md`, `CLAUDE_RESPONSE_6.md`.

CLAUDE STATUS: RESOLVED
