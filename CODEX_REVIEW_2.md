# Independent follow-up review of audit 8

Customizable Transcriber 0.5.6 · November 22, 2026

**13 of 26 prior findings are resolved, 12 remain open, and one requires a human decision.** Two high-severity failures remain. A restricted XLS request can include a neighboring record, and a provider response that ended early can be recorded as complete. Three additional findings concern publishing translation files and retaining the profile instructions a user approved.

## Review basis

The current repair response identifies the November 22 audit, its two decisions, and checkpoint `79a7acc34dbb9d435a3b256659a4f92a34a4c1c5`. The matching documents are [the prior review](reviews/CODEX_REVIEW_8.md), [Claude’s response](reviews/CLAUDE_RESPONSE_8.md), and [the decision record](reviews/HUMAN_DECISIONS_8.md). The unnumbered documents in `reviews/` concern earlier work. HEAD remains at the checkpoint. The review covered the working-tree diff across 50 tracked files, the 14 new test files outside that diff, and the callers and consumers of the changed code.

Claude marked all 26 findings resolved and none DISAGREE. I separately assessed the explicit Gemini exception under M-5. The release, installer, credential-storage and transcript-provenance choices are addressed under M-10, M-11, L-4 and L-3. HD-1 is the only outstanding product decision.

## Prior findings

### HIGH

**H-1 — STILL_OPEN. Restricted XLS requests can include an unselected record.** The unmatched-number and numbered Index cases now work. The boundary parser still requires digits immediately before the filename extension, with an optional closing parenthesis. In an ordinary synthetic transcript, selecting page 001 also selected the following `Appendix.jpg` text in both extraction and preflight. Language detection uses the same extraction helper. A blank range with whole-document mode off also selected both numbered pages in that helper. This can send records outside the user’s selection to the provider. See `xls_conversion/ai_parser.py:354–364, 952–969, 1024–1061, 1328–1340`.

**Correction.** Split on every record heading first, then determine each block’s eligibility independently. Reject an empty restricted range before building any provider sample. Test numbered and unnumbered neighbors through detection, preflight and conversion. **Claude can correct automatically. Human judgment is unnecessary.**

**H-2 — RESOLVED. A second tab can no longer substitute another source folder.** The submitted folder is checked and pinned before dispatch. Transcribe and Test Mode workers consume the pinned value, and the off-peak Transcribe handler passes its resolved path directly. Stale and forged-selection tests passed. The separate profile-snapshot gap is N-3. See `run_support.py:714–751`, `handlers/transcribe_offpeak.py:150–166`, and `tests/test_source_folder_binding.py`.

**H-3 — RESOLVED. Dotted source names no longer overwrite earlier translations.** Exclusive creation and appending the extension preserve the whole stem and prevent reuse of existing destinations. Repeated names and pre-existing outputs have regression coverage. N-1 and N-2 cover failures introduced by the new publishing code. See `transcript_translation.py:1061–1106` and `tests/test_transcript_translation.py`.

**H-4 — RESOLVED. Repeated record headings retain distinct translations.** A record’s document position and its entry position participate in the key through chunking, response lookup and assembly. A duplicate response ID generates an entry-level failure. See `transcript_translation.py:194–201, 331–335, 772–783, 819–851` and `tests/test_transcript_translation.py`.

**H-5 — STILL_OPEN. Text returned with an incomplete terminal status can count as a complete page.** Blank and output-token-limited replies now receive appropriate handling. With the installed Claude SDK’s `model_context_window_exceeded` and `refusal` statuses, a mocked batch result containing text produced no error and zero incomplete pages in both cases. The real-time Claude branch uses the same success assumption. Gemini similarly accepts nonempty text with non-success reasons other than `MAX_TOKENS`. A researcher can receive a partial transcription or refusal in a successful record. See `customizable_transcriber/core.py:852–864, 933–949, 1460–1473` and `batch_transcription.py:474–493, 589–605`.

**Correction.** Classify terminal reasons explicitly for each adapter, preserve partial text with its actual reason, and count blocked, incomplete and unknown outcomes consistently in exports, summaries and ledger events. Exercise nonempty refusal and context-limit fixtures in both modes. **Claude can correct automatically. Human judgment is unnecessary.**

### MEDIUM

**M-1 — RESOLVED. Recognizable wrong-provider keys are rejected locally.** Client creation, XLS calls and caches, translation and off-peak submission check the key shape before the relevant provider request. The tests cover both directions. See `customizable_transcriber/core.py:269–298, 484–490`, `batch_transcription.py:838–849`, `handlers/transcribe_translate.py:117–120`, and `tests/test_key_provider_mismatch.py`.

**M-2 — STILL_OPEN. Provider-originated text can still reach persistent errors.** The batch collector passes through an item’s raw error message. The sanitizer trusts its opening words and preserves the *entire* message for several prefixes. A synthetic provider message beginning “Request was” survived verbatim. The result is written to the transcript and its first 200 characters can reach the ledger. The real-time formatter also returns raw text for unrecognized non-SDK exceptions, which can include local paths. See `batch_transcription.py:453–477, 674, 1117` and `customizable_transcriber/core.py:678–716, 1416–1420`.

**Correction.** Carry a typed internal error category separately from external detail. Render durable messages from that category and safe fields, including for unexpected exceptions. Test the actual document and ledger sinks with a provider message that shares a friendly prefix. **Claude can correct automatically. Human judgment is unnecessary.**

**M-3 — STILL_OPEN. A partially unreadable recovery file can still lose records.** Per-job keys fix the original collision for well-formed jobs, including legacy Transcribe records. A valid JSON map containing one malformed entry is nevertheless considered readable. A temporary Transcribe file containing one good entry and a second entry with a plain-string job reference lost the second entry when a third was saved. Test Mode uses the same filtering pattern. It can erase the remaining evidence needed to reconcile a provider job. Also, contrary to the response’s explanation, the first persistence call shown in the worker follows the provider’s returned job ID. See `app_state.py:221–250, 275–282, 365–414` and `batch_transcription.py:915–934`.

**Correction.** Preserve unknown entries losslessly or set aside the original bytes under a collision-free name before rewriting. Apply this to both save and single-job clear. Keep valid sibling entries available and add mixed-validity restart tests. **Claude can correct automatically. Human judgment is unnecessary.**

**M-4 — STILL_OPEN. An acknowledged Stop can precede a billable off-peak submission.** Reset and queue edits now make their principal state transitions under a lock, and setup no longer clears a newly set stop flag. The default Transcribe worker checks Stop before submission only when supplied with Test Mode’s optional submission lock. With an already-stopped sink and no lock, the worker reached a stubbed submission helper. Both modes can also spend time preparing images after their last check. See `handlers/transcribe_offpeak.py:122–129, 150–168` and `batch_transcription.py:367–397, 507–547, 815–858, 905–926`.

**Correction.** Honor cancellation on worker entry and during preparation. Coordinate the last pre-send check and the transition to submitting for both providers. Keep the existing reconciliation path when Stop arrives after dispatch. Add a deterministic test that stops between preparation and the mocked provider call. **Claude can correct automatically. Human judgment is unnecessary.**

**M-5 — RESOLVED under the maintainer’s Gemini decision.** Claude requests are checked against a conservative 250 MB encoded-size budget including repeated prompt text and framing. Gemini retains the expressly approved 500 MB raw limit, halved with zoom. The maintainer recorded one successful ten-image Gemini run at about 35 MB encoded. That establishes acceptance at that size only. Zoom crops are Gemini-only, and a connection loss during submission still has an unknown billing outcome. See `batch_transcription.py:289–324, 831–867, 905–906`, `tests/test_offpeak_envelope.py`, and `reviews/CLAUDE_RESPONSE_8.md:109–118`.

**M-6 — RESOLVED. Test Mode compares the same transcription body across input formats.** Generated header and preamble text are removed before scoring. The DOCX-versus-Markdown self-comparison returns zero error and the regression suite retains register text after the first record heading. See `test_mode/comparison.py:34–68, 90` and `tests/test_comparison_metadata_strip.py:28–46`.

**M-7 — STILL_OPEN. Computing the comparison budget can itself require quadratic work.** Before the budget is charged, each dated truth row constructs a fresh list of same-year and undated candidates merely to get its length. For a large single-year workbook, the application can copy the candidate bucket once per truth row before it can refuse the comparison. This is a source-level complexity finding. See `index_compare/align.py:118–146, 286–302` and the admitted worksheet dimensions in `index_compare/reader.py:34–35`.

**Correction.** Charge bucket cardinalities using integer counts, stop as soon as the budget is exceeded, and iterate candidate groups without concatenating them. Add a low-budget test that checks the work done before rejection. **Claude can correct automatically. Human judgment is unnecessary.**

**M-8 — RESOLVED. Page-zoom advice now checks files and bounds preview geometry.** File admission precedes analysis. Pixel, aspect and minimum-width checks precede thumbnail processing. The page-zoom suite passed. See `run_support.py:189–216`, `customizable_transcriber/page_zoom.py:113–145`, and `tests/test_page_zoom.py`.

**M-9 — RESOLVED. DOCX declaration handling works across supported XML encodings.** The parser’s declaration callbacks reject forbidden declarations before content extraction. The encoding regression cases passed. See `http_utils.py:217–264` and `tests/test_docx_security.py`.

**M-10 — RESOLVED. Release publication requires signing and notarization checks.** Release mode with all signing inputs absent exited 2 before building. The workflow validates the stapled disk image and mounted application before upload. This verifies the gate and its ordering. An actual signed release was outside local verification. See `mac/build.sh:31–48, 106–124` and `.github/workflows/mac-release.yml:75–101`.

**M-11 — STILL_OPEN. A retry after an interrupted package update can destroy the last working environment.** An ordinary pip or smoke-test failure restores the backup within the same invocation. If that invocation ends with a partial live `venv` and a good `venv-old`, the next invocation deletes the good backup and saves the partial directory over it. An isolated run of the actual Mac start script with that disk state and a failing stub interpreter restored the partial directory and deleted the last-working marker. The Windows script has the same sequence. Both discard backups without checking completion of all marker writes. See `Start Customizable Transcriber (Mac).command:95–111` and `Start Customizable Transcriber (Windows).bat:82–101, 166–172`.

**Correction.** Recover an outstanding update before rotating backups. Keep the last verified environment until imports and marker writes succeed. Test interrupted updates followed by both successful and failed retries, using platform-specific temporary runtimes. **Claude can correct automatically. Human judgment is unnecessary.**

**M-12 — RESOLVED. Worksheet names containing quotation marks round-trip through XLSX.** The writer encodes the sheet-name XML attribute with `quoteattr`. The quoted-title regression passed. See `xls_conversion/spreadsheet_export.py:180–185` and `tests/test_sheet_name_sanitization.py`.

**M-13 — STILL_OPEN. A corrupt user override can silently select the shipped profile.** Reserved names and missing IDs now receive appropriate handling. The merged loader reads shipped files first and skips malformed user JSON. In a temporary store with a shipped profile and a corrupt override of the same ID, exact lookup returned the shipped profile. The run can consequently use different archival instructions while displaying the expected ID. Invalid UTF-8 in a profile can also interrupt enumeration. See `profiles_store.py:188–203, 292–325, 374–385`.

**Correction.** For execution and editing, resolve the highest-priority file for the selected ID and validate that file directly. Report a damaged override without falling through. Isolate encoding failures in the browser’s profile listing. Test corrupt overrides of shipped profiles. **Claude can correct automatically. Human judgment is unnecessary.**

**M-14 — STILL_OPEN for manual setup. The audited checkout environment itself is repaired.** All 35 installed runtime pins matched `requirements.lock`, `pip check` passed, and the environment-wide advisory scan was clean. The prior review also called for manual installations to use the reviewed runtime baseline. The published manual command still installs the eight direct pins in `requirements.txt`, leaving other transitive versions to the resolver. See `README.md:82–99`, `requirements.txt`, `requirements.lock`, and `reviews/CODEX_REVIEW_8.md:141–146`.

**Correction.** Use the tested runtime lock for manual installations on supported configurations. Where platform markers or a documented interpreter need different dependencies, validate the applicable lock for that configuration. Add a check keeping setup instructions and their tested inputs aligned. **Claude can correct automatically within the existing support policy. Human judgment is unnecessary.**

**M-15 — HUMAN_DECISION_REQUIRED. Matching changed as approved, but weak identity evidence and on-screen disclosure need clarification.** Conflicting named, dated, unlocated rows now remain missing and extra. Same-page order-only pairs are counted in the DOCX. The matcher also accepted two unlocated rows containing only the given name “Paolo,” with no surname or year, as one identity match and zero order-only matches. Years constrain matches only when both are present. The decision record asks for a screen and report outcome, while the existing UI deliberately exposes comparison results only by download. See `index_compare/align.py:65–71, 118–148, 290–302`, `index_compare/report_docx.py:193–216`, `static/test-mode.js:609–624`, `CLAUDE.md:33–35`, and `reviews/HUMAN_DECISIONS_8.md:5–13`.

**Correction and decision.** Confirm whether a single name without a date qualifies as identity evidence and whether report-only disclosure satisfies HD-1. My recommendation is to leave lone given-name matches unresolved and show matched, order-only, missing and extra counts in the on-screen completion message. Align the matcher, text and acceptance tests with the confirmed rule. **Claude can implement the chosen policy automatically after clarification. Human judgment is required for those two choices.**

### LOW

**L-1 — STILL_OPEN. The macOS launcher uses a weaker identity check than the Python launcher.** Python requires HTTP 200 and the expected top-level JSON property. The Mac shell pipeline accepts a matching substring anywhere in a response body. Its curl flags also admit 3xx bodies, and the grep expression rejects some valid JSON whitespace. A different local service can be opened, or the correct service can be reported as a conflict. This is a source-traced discrepancy. See `mac/launcher.sh:88–98` and `launch.py:61–76`.

**Correction.** Require status 200 and parse a bounded JSON object with the expected top-level ID. Exercise the shell launcher with valid JSON whitespace, redirects, unrelated and malformed responses. **Claude can correct automatically. Human judgment is unnecessary.**

**L-2 — RESOLVED. Wrong-shaped JSON settings no longer break load, save or reset.** A common reader validates the mapping, the folder reader checks its value type, and recovery works for malformed inputs. See `app_state.py:162–212` and `tests/test_app_state_sandboxing.py`.

**L-3 — RESOLVED. Both transcript headers follow HD-2.** The maintainer chose folder name only, with full provenance available locally and no full-path export option. Real-time and off-peak writers use the basename, and Word is built from that body. Header tests passed. The distinct error-text disclosure is covered by M-2. See `customizable_transcriber/core.py:1373`, `batch_transcription.py:1105–1109`, and `tests/test_source_folder_header.py`.

**L-4 — STILL_OPEN. Replacing an app folder can still discard an effective saved credential.** The runtime combines the user-data and app-folder files per key. Both Mac migration helpers skip the entire old file whenever the destination exists. A user-data file containing only the Gemini key and an old app file supplying the Claude key work together until replacement deletes the latter. A failed copy also logs a note and permits deletion to proceed. The startup copier likewise skips an existing destination. The checkout’s local permissions are now 0600. See `customizable_transcriber/core.py:189–205`, `profiles_store.py:206–225`, `install-mac.sh:32–36, 99–118`, and `mac/launcher.sh:58–63, 115–122`.

**Correction.** Respect the approved no-overwrite rule. When the old file still supplies a credential, preserve a private recoverable copy or retain the old folder and give an actionable migration message. On copy error, prevent deletion of the only copy. Test split keys and failed migration through replacement using dummy values. **Claude can correct automatically. Human judgment is unnecessary.**

**L-5 — STILL_OPEN. Preflight and extraction interpret the same approved role differently.** The cache case-folds the role while the prompt builders compare case-sensitively. A local probe approved `transcription`, validated the same token with `Transcription`, and obtained the translation instruction instead. The ordinary UI sends lowercase values. Unsupported marker overrides are now correctly refused. See `handlers/xls_conversion.py:56–95, 151–180` and `xls_conversion/ai_parser.py:57–86, 255–266, 2423–2427, 2453–2458`.

**Correction.** Validate a single canonical role at the request boundary, then pass that same value to caching, preflight and extraction. Cover case variants and unknown roles. **Claude can correct automatically. Human judgment is unnecessary.**

### INFORMATIONAL

**I-1 — RESOLVED. Legacy parser coverage is labeled accurately.** The CI step and XLS README identify the JavaScript fixture as legacy and point to tests for the active Python pipeline. The six-entry legacy fixture passed independently. See `.github/workflows/tests.yml`, `xls_conversion/README.md`, and `xls_conversion/tests/run_parser_test.py`.

## New findings

### NEW FINDING N-1 — MEDIUM. Failed translation publication leaves empty final documents

`transcript_translation.py:1061–1106, 1192–1214` reserves three final paths up front. Each publisher cleans up only its own placeholder. In a temporary directory, an ordinary write failure on the first output left both the final transcript DOCX and report DOCX present at zero bytes. A failure during reservation or assembly can likewise leave placeholders. The files resemble completed outputs in a persistent user folder. This behavior was introduced by the H-3 repair.

**Correction.** Track all reservations owned by the job and clean up every unpublished one on failure. Stage complete artifacts before exposing final names and retain protection against overwriting earlier files. Inject failures at reservation, assembly and each write. **Claude can correct automatically. Human judgment is unnecessary.**

### NEW FINDING N-2 — MEDIUM. A valid translation filename can fail only after paid processing

`transcript_translation.py:1081–1106, 1192–1214` appends a UUID and suffix to the full final filename for staging. With a valid 200-character ASCII source stem, the three final names were 239, 237 and 247 bytes on a filesystem permitting 255. Writing the first temporary output failed with a filename-too-long error. The provider loop has already finished by this point. The long temporary name is new in the H-3 repair.

**Correction.** Use short, independently generated temporary filenames in the destination directory. Budget final names for the filesystem’s component limit and validate them before dispatching paid work. Test near-limit filenames through successful export. **Claude can correct automatically. Human judgment is unnecessary.**

### NEW FINDING N-3 — MEDIUM. An approved prompt profile can change before the worker uses it

`handlers/transcribe_run.py:79–104, 144`, `handlers/test_mode_run.py:161–162, 226–229`, `run_support.py:314–339, 749–757, 861–866`, and `batch_transcription.py:1191–1195` resolve the profile in the handler, then resolve it again in the worker. Editing the same saved profile in between can change extraction instructions for a confirmed run. Exact-ID lookup protects against a different *ID*, but the contents under that ID are mutable. Transcribe’s off-peak handler already passes the resolved profile directly. This is a pre-existing issue identified while checking H-2, distinct from its repaired folder selection.

**Correction.** Pass the validated profile contents or built prompt and associated metadata in the job arguments. Add an interleaving test that edits the saved profile after reservation and checks the prompt actually dispatched. **Claude can correct automatically. Human judgment is unnecessary.**

## Verification

- Full pytest suite on Python 3.12.0 with local HTTP fixtures enabled: **634 passed, 1 skipped** in 37.86 seconds. The skip creates a real Windows desktop shortcut. The legacy six-entry parser check also passed.
- Ruff’s CI correctness gate (`F,E9`), JavaScript syntax, shell syntax, C launcher syntax, YAML parsing for both changed workflows, and the whitespace check with the repository’s Windows line endings accounted for all passed. Full advisory-only Ruff returned 98 diagnostics, compared with 84 recorded in the prior review. These include new test-code lint warnings. The project defines no type-checking gate.
- All 35 runtime pins matched the active environment. `pip check` found no broken requirements. A fresh environment-wide `pip-audit --local` query returned no known vulnerabilities. Credential inspection used file permissions and synthetic values.
- Focused checks used temporary files, pure functions, mock provider results, and an isolated Mac installer retry with a stub interpreter. No paid provider call, real Windows installation, production signing, notarization, or publication was performed. The maintainer’s Gemini result is attributed separately under M-5.

OVERALL STATUS: CHANGES_REQUIRED
