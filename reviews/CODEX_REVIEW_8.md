# Independent engineering and security review

Reviewed November 22, 2026. Customizable Transcriber 0.5.6, commit `79a7acc34dbb9d435a3b256659a4f92a34a4c1c5`.

**Remediation priority.** Two workflows can send a different set of records to an AI provider than the user selected. Translation can overwrite existing output or put one record's translation under another record. Off-peak processing can silently accept a missing or incomplete page. Address H-1 through H-5 before relying on these workflows for sensitive or authoritative records.

## CRITICAL

No critical finding identified under the documented single-user, loopback deployment model.

## HIGH

### H-1. A restricted image range can send the entire transcript to the provider

- **Location.** `xls_conversion/ai_parser.py:354–364, 951–965, 1016–1039, 1975–1979`, `xls_conversion/app.js:316–334`, `xls_conversion/index.html:102–110`.
- **Evidence and impact.** If none of the requested image numbers matches, the splitter returns the complete document as one unnamed block. Language detection sends that block as its sample, before conversion preflight. With pages 001 and 002 and only 003 selected, the mocked provider received the entire source. There is a second boundary error: an excluded “Index” heading is removed before block ends are calculated. The text of a following index page was included in selected page 001. Either case can disclose material the user excluded. The conversion path uses the same splitter.
- **Recommended correction.** Identify all record boundaries before filtering. An explicit range with zero matches should return an actionable error before any content-bearing API call. Permit a whole unmarked document only under an explicit whole-document selection. Test the exact outbound content for a missing range and for an excluded page between two records.
- **Disposition.** Safe to correct automatically.

### H-2. A confirmed run can upload another tab's source folder

- **Location.** `pages/transcribe.py:163–173`, `handlers/settings.py:164–191`, `handlers/transcribe_run.py:50–57, 132–133`, `run_support.py:703–709, 731–749, 811–821`, `handlers/transcribe_offpeak.py:67, 113`, `handlers/test_mode_run.py:138–165`, `batch_transcription.py:1108–1114`.
- **Evidence and impact.** The displayed folder is shared mutable settings. The run form does not identify the folder the user reviewed. The handler and worker can also read the setting at different times. In an isolated run through the real handler, folder A passed validation. After an ordinary settings change, the worker handed folder B to the mocked batch processor. A second tab can cause the same mismatch simply by changing folders before submission. Both directories can be perfectly valid, so file-type checks give no warning.
- **Recommended correction.** Bind the displayed folder or a server-issued selection identifier to the confirmation. Reject a stale selection before submission. Pass one validated job configuration, including the resolved folder and profile, to the worker. Exercise the two-tab case for ordinary runs, Test Mode and off-peak.
- **Disposition.** Safe to correct automatically.

### H-3. A period in the input filename can make translation overwrite an existing transcript

- **Location.** `transcript_translation.py:1040–1044, 1128–1145`, `run_support.py:689–695`.
- **Evidence and impact.** The timestamp is appended to the source stem, then `Path.with_suffix()` removes everything after the last period. Both `Register.1750.docx` and `Register.1751.docx` produced `Register.docx` and `Register.md` in the outputs directory. Those paths are opened for replacement. A previous translation or an unrelated file of that name can be lost. The reports retain distinct timestamps, obscuring which transcript each report describes.
- **Recommended correction.** Append each extension to the complete generated basename. Reserve fresh destinations without overwriting an existing file and publish completed artifacts from temporary files. Test repeated translation and two dotted names with pre-existing sentinel outputs.
- **Disposition.** Safe to correct automatically.

### H-4. Duplicate record headings silently assign one translation to two different entries

- **Location.** `transcript_translation.py:191–193, 280–285, 325–326, 462–483, 809–834, 890–905`.
- **Evidence and impact.** The response key consists of the displayed filename and an entry number that restarts at one for every record. A corrected or combined DOCX can repeat a heading. Preflight accepted two different source entries with the same key. When a mock returned “First.” and “Second.” for the respective entries, the assembled document contained “Second.” twice, “First.” zero times, and no reported failure.
- **Recommended correction.** Use a document-local record ordinal and entry ordinal for identity. Keep display names for labels. Reject duplicate or unexpected response identities and test both same-chunk and different-chunk cases.
- **Disposition.** Safe to correct automatically.

### H-5. Empty or truncated provider output can count as a successfully transcribed page

- **Location.** `batch_transcription.py:421–447, 527–552, 1034–1046, 1066–1085`, `customizable_transcriber/core.py:781–798, 865–875, 1327–1333`.
- **Evidence and impact.** The Gemini batch collector returned an empty success for one mocked item and an unmarked partial success for a token-limited item. The Claude collector also returned an empty success for a successful envelope with no text blocks. Finish reasons are captured for accounting but do not affect the batch output or failure count. Real-time Claude likewise lacks the blank-text check in real-time Gemini. A DOCX can omit part or all of a page while reporting zero failures.
- **Recommended correction.** Validate usable text and completion reasons consistently across providers and modes. Mark incomplete pages in both the document and the summary, preserving any useful partial text. This correction requires no additional paid requests. Cover blank, blocked and token-limited responses for each adapter.
- **Disposition.** Safe to correct automatically.

## MEDIUM

### M-1. Several paid workflows send a recognizably wrong provider key before detecting the mistake

- **Location.** `customizable_transcriber/core.py:233–248, 436–470`, `handlers/transcribe_run.py:51–57`, `batch_transcription.py:763–777`, `handlers/profiles.py:298–313`, `handlers/xls_conversion.py:135–157, 188–198, 232–236`, `handlers/transcribe_translate.py:63–78, 114–120`.
- **Evidence and impact.** These request paths select an SDK from the model and forward the pasted key. A wrong-provider credential has already been disclosed to the other provider by the time authentication fails. Test Mode and translation preflight already recognize mismatches locally. The translation run endpoint checks only that a key is present.
- **Recommended correction.** Apply the existing recognizable-mismatch check at the common credential-resolution boundary, including the separate batch clients, before constructing or calling an SDK. Leave unrecognized but potentially valid formats to their intended provider where appropriate. Assert that recognizable mismatches make zero outbound calls.
- **Disposition.** Safe to correct automatically.

### M-2. Raw exception text can reach the usage ledger and exported transcripts

- **Location.** `customizable_transcriber/core.py:550–559, 582–589, 635–653, 1334–1346`, `customizable_transcriber/usage_ledger.py:8–12, 329–346`, `app.py:805`, `PRIVACY.md:77–83`.
- **Evidence and impact.** Retry, cache and failed-image events persist parts of `str(exc)`. The user-facing error formatter also includes original exception text that can be written into Markdown and DOCX. An SDK or transport error that echoes request content can therefore put that content into persistent files despite the ledger's metadata-only contract. Inspection established the unfiltered path. No claim is made that a real credential was found in a log.
- **Recommended correction.** Persist allowlisted error categories, sanitized status codes and safe request identifiers. Keep raw exception bodies, headers and URLs out of durable and exported messages. Test with a fake exception containing synthetic sensitive text and assert its absence from all outputs.
- **Disposition.** Safe to correct automatically.

### M-3. Starting another off-peak job erases the recovery record of an unresolved job

- **Location.** `app_state.py:209–233, 246–283, 296–326`, `batch_transcription.py:660–682, 721–725, 979–997, 1083–1095`, `handlers/test_mode_run.py:182–192`.
- **Evidence and impact.** Transcribe stores a single recovery record. A worker can release its run slot with the old provider job still unresolved. In a temporary directory the sequence “first job unknown, second job running, second job completes” left no recovery record. The startup notice promises the ID will remain available until dismissal. Test Mode uses a separate map, but a restart or repeat with a reused run ID can replace its entry as well. Losing the ID makes a still-billable job harder to reconcile.
- **Recommended correction.** Key recovery entries by provider and provider job ID, migrate existing files, and remove only the resolved or explicitly dismissed entry. Preserve unreadable records for recovery. Test two successive jobs and restart with the first still outstanding.
- **Disposition.** Safe to correct automatically under the existing manual-recovery policy.

### M-4. Reset, Stop and queue edits can race with a run reservation

- **Location.** `handlers/transcribe_run.py:30–40, 114–116, 151–177`, `handlers/test_mode_run.py:53–72, 90–106, 205–224, 251–258`, `app_state.py:361–403`, `run_support.py:130–136`.
- **Evidence and impact.** Reset checks that the app is idle, releases the lock, then reacquires it elsewhere and writes `running = False`. A new reservation in between can be erased while its worker continues. Stop can be acknowledged during setup and then cleared at launch. A queue edit can pass its idle check before launch and commit after the queue snapshot, then be discarded when launch clears the queue. These are source-traced interleavings.
- **Recommended correction.** Commit each check and transition under the same lock. Initialize cancellation at reservation and have workers release only their own reservation. Coordinate persistent cleanup with the run it belongs to. Add deterministic interleaving tests for Reset/start, Stop/setup and queue/start.
- **Disposition.** Safe to correct automatically.

### M-5. Off-peak preflight can accept batches larger than the selected provider's request envelope

- **Location.** `batch_transcription.py:289–325, 335–372, 460–495, 753–758`.
- **Evidence and impact.** The local ceiling counts 500 MB of raw input, or 250 MB with zoom. Both adapters submit a single inline request containing images and repeated instructions. Base64 alone expands 200 MB of image bytes to roughly 267 MB. Anthropic limits the whole request to 256 MB. Google documents its inline method for batches under 20 MB. A normal register can pass local validation, consume substantial memory and upload time, then fail at submission. [Anthropic batch limits](https://platform.claude.com/docs/en/build-with-claude/batch-processing) · [Google inline batch guidance](https://aistudio.google.com/docs/batch-api#inline-requests)
- **Recommended correction.** Preflight a provider-specific bound on encoded image data, repeated prompts, zoom crops and request framing. For an oversized batch, explain how to split it before uploading. This fits the existing manual-splitting policy.
- **Disposition.** Safe to correct automatically.

### M-6. Test Mode scores document metadata as transcription errors

- **Location.** `handlers/test_mode_run.py:291–333`, `run_support.py:540–575, 646–655`, `test_mode/comparison.py:34–84`.
- **Evidence and impact.** The corrected reference and uploaded contestants are read from Word, including the generated header box. A selected completed run is read from its Markdown file, which lacks that box. Comparing a two-record DOCX to its own unchanged source body produced **84.23% character error and 87.04% word error**. Uploading the same DOCX on both sides produced zero. The magnitude depends on transcript length. The selection method alone can change a model's rank.
- **Recommended correction.** Extract the same transcription body on every comparison path. Remove recognized application metadata and provenance before scoring while preserving actual register text. A downloaded run used as its own corrected reference must score zero through either entry point.
- **Disposition.** Safe to correct automatically.

### M-7. Workbook comparison has no effective bound on matching work

- **Location.** `index_compare/reader.py:25–35, 113–122, 249–267`, `index_compare/align.py:74–104, 146–147, 179–184, 234–244`, `handlers/index_compare.py:143–151`.
- **Evidence and impact.** The reader accepts up to 100,000 rows per sheet. For missing or shared locators the matcher compares every truth row in a group with every candidate and retains each qualifying pair for sorting. Two ordinary 5,000-row indexes without page numbers imply up to 25 million pair visits. Common names can also make the stored pair list large. A file within the upload limits can exhaust a desktop process while it is serving other jobs.
- **Recommended correction.** Precompute identities, partition on available evidence, and enforce an overall candidate-pair budget before scoring or allocating pairs. Return an actionable narrowing request when the budget is exceeded. Verify the limit with small fixtures and a deliberately small test budget.
- **Disposition.** Safe to correct automatically.

### M-8. The page-zoom preview reads unchecked files and can enlarge its “thumbnail”

- **Location.** `app.py:466–486`, `run_support.py:187–207`, `customizable_transcriber/page_zoom.py:73–81, 115–132`, `customizable_transcriber/core.py:337–356`.
- **Evidence and impact.** The preview opens sampled paths with Pillow before applying the batch's file size and symlink checks. It can run while zoom is off to decide whether to suggest the option. Its grayscale resize fixes width at 800 and derives an uncapped height, so narrow images can be greatly enlarged. A selected folder can trigger a large local decode or allocation during preflight.
- **Recommended correction.** Apply source-file admission checks before preview decoding. Bound both decoded dimensions and thumbnail pixels, never upscale, and reject unsuitable aspect ratios. Test the sizing arithmetic and skipped-file behavior without allocating large images.
- **Disposition.** Safe to correct automatically.

### M-9. The DOCX declaration check depends on the XML byte encoding

- **Location.** `http_utils.py:225–250`, `tests/test_docx_security.py`.
- **Evidence and impact.** The reader searches raw bytes for DTD/entity declarations, then hands the document to an encoding-aware XML parser. The byte search does not enforce the same no-DTD policy across the encodings the parser accepts. The ZIP size limit remains valuable, but it does not establish this parser-level property. This is a static finding. No resource-exhaustion test was run.
- **Recommended correction.** Use a parser configured to forbid DTDs and entities independently of encoding, retaining the decompressed-size cap. Cover ordinary documents in each supported encoding and assert the declaration policy at the parser boundary.
- **Disposition.** Safe to correct automatically.

### M-10. The macOS release workflow can publish without notarization

- **Location.** `.github/workflows/mac-release.yml:70–80, 89–104`, `mac/build.sh:28–32, 88–93, 101–108`.
- **Evidence and impact.** If the notary key ID or issuer ID is empty, the build script takes its optional local-build path. The app can still be signed, but DMG signing, notarization, stapling and the final Gatekeeper assessments are skipped. The tag workflow can then upload that DMG under the official release filename. This describes the workflow behavior, not the state of any published artifact.
- **Recommended correction.** Require the signing identity and all notarization inputs in release mode. Make verification of the signed, stapled final artifact a prerequisite for upload. Preserve a separately explicit local development build mode.
- **Disposition.** Safe to correct automatically.

### M-11. A package-only installer update destroys the working virtual environment before the replacement succeeds

- **Location.** `Start Customizable Transcriber (Mac).command:31–38, 62–94`, `Start Customizable Transcriber (Windows).bat:39–45, 60–87` and its `:restore_previous` routine, `install-mac.sh:95–104`.
- **Evidence and impact.** Both installers back up the virtual environment on a Python-build change. With the same interpreter and a changed lockfile, both run `venv --clear` on the active environment before installing packages. If package installation fails, the rollback routine has no backup. Restoring the old application directory in the outer Mac installer leaves its runtime unusable until a successful reinstall.
- **Recommended correction.** Preserve the previous environment for a lockfile-only change as well. Install at the intended final path or otherwise account for absolute paths in virtual environments. Verify imports before committing the new markers. Add a failed-package-install rollback test on both platforms.
- **Disposition.** Safe to correct automatically.

### M-12. A quoted worksheet title produces an unreadable XLSX export

- **Location.** `xls_conversion/spreadsheet_export.py:9, 38–52, 180–184`, `xls_conversion/ai_parser.py:2426–2457`.
- **Evidence and impact.** The workbook writer inserts a sanitized title into a quoted XML attribute using a text-node escaping function. An ordinary double quote survives. A workbook created with the title `Latin "A"` had an invalid `xl/workbook.xml`. Multi-language export incorporates detected language labels into these titles.
- **Recommended correction.** Serialize the attribute with an XML writer or an attribute-quoting function. Round-trip workbooks with quotations, ampersands and non-ASCII labels through the production reader.
- **Disposition.** Safe to correct automatically.

### M-13. A saved profile can disappear and another profile can be selected in its place

- **Location.** `profiles_store.py:168–184, 262–281, 334–350, 366–399`, `run_support.py:292–300`.
- **Evidence and impact.** Saving a profile named “Settings” creates `settings.json`, which the loader always excludes as legacy configuration. The ID still passes the file-existence check. In a temporary store, save returned `settings`, the profile list omitted it, and loading that ID returned a different profile named “Demo.” A malformed selected profile can hit the same fallback. The resulting run can use the wrong archival instructions.
- **Recommended correction.** Reserve legacy filenames at ID allocation. Recover existing genuine profiles with that name by distinguishing profile data from legacy settings. Require exact successful lookup for execution and editing. Test save/list/load consistency and corrupt selected profiles.
- **Disposition.** Safe to correct automatically.

### M-14. The checkout's active environment contains dependencies with known advisories

- **Location.** Local `.venv`, `requirements.lock`, `requirements.txt`, `README.md:193–201`.
- **Evidence and impact.** Fourteen runtime distributions differ from the release lock. The active environment's advisory scan identified `certifi 2026.7.22` (PYSEC-2026-4320) and `pyasn1 0.6.4` (CVE-2026-119194 through CVE-2026-119197). The scanner emitted six rows, including one duplicate, for five distinct advisory IDs. The pinned versions `certifi 2026.10.23` and `pyasn1 0.6.5` passed the same scan. Launching from this checkout uses a different security baseline from the packaged release.
- **Recommended correction.** Rebuild this checkout's environment from the reviewed lockfile. For manual setup, use the same runtime lock as the installers and verify installed versions against it.
- **Disposition.** Safe to correct automatically. No installed package in the checkout was changed during the review.

### M-15. Unrelated rows with missing locators can be reported as a match

- **Location.** `index_compare/align.py:38–48, 90–103, 146–164, 229–244`, `index_compare/scoring.py:175–185`.
- **Evidence and impact.** Missing locators all enter one bucket. When identity matching rejects two rows, the positional fallback can still pair them. A truth row for Paolo Rossi in 1800 and a candidate for Anne Smith in 1900, both without locators, produced one match, zero missing and zero extra. This changes coverage counts and attributes field errors to people the evidence never linked.
- **Recommended correction.** Adopt an explicit rule for uncertain pairs. The recommended default counts them as unmatched. An optional reviewable positional pairing can support collections that guarantee source order. Cover conflicting years and shifted rows with missing locators.
- **Disposition.** Human decision required, HD-1.

## LOW

### L-1. The launchers can open an unrelated local service as the transcription app

- **Location.** `launch.py:46–66, 245–249`, `mac/launcher.sh:78–81`.
- **Evidence and impact.** The Python launcher treats any HTTP 200 on the app port as a running instance. The Mac launcher accepts any completed HTTP response, including error statuses. An ordinary port collision can open the wrong UI and tell the user the app is already running. This finding assumes no malicious local process.
- **Recommended correction.** Check an app-specific response on a dedicated health endpoint with redirects disabled. For an unrelated listener, report a port conflict before opening the browser. Test an unrelated 200, a redirect and a 404.
- **Disposition.** Safe to correct automatically.

### L-2. Valid JSON of the wrong shape can break the settings page and its own recovery actions

- **Location.** `app_state.py:161–206`, `pages/transcribe.py:75–77`, `pages/test_mode.py:63–65`.
- **Evidence and impact.** With an isolated settings file containing a JSON array, load raised `AttributeError`, save raised `TypeError`, and clear raised `TypeError`. The application assumes every syntactically valid JSON value is an object. The user can lose access to both pages and their folder controls.
- **Recommended correction.** Use a single settings reader that validates the top-level mapping and folder type and handles invalid encoding. Allow selection or reset to recover. Cover arrays, null and invalid UTF-8.
- **Disposition.** Safe to correct automatically.

### L-3. Downloadable transcripts include the operator's absolute source path

- **Location.** `customizable_transcriber/core.py:1300–1303`, `batch_transcription.py:1033–1036`, `run_support.py:646–655, 751–760`.
- **Evidence and impact.** A source-folder header containing the local path is written into Markdown and copied into the Word body. Sharing the finished document can reveal an account name, client name or private directory structure. The path also serves a legitimate local provenance purpose.
- **Recommended correction.** Choose the provenance displayed in shareable documents. Prefer a user-supplied collection label or relative paths in exports and retain absolute paths in local job details.
- **Disposition.** Human decision required, HD-2.

### L-4. Application-folder replacement can discard the optional saved credentials

- **Location.** `README.md:130–146, 193–201`, `customizable_transcriber/core.py:186–201`, `install-mac.sh:88–105`, `mac/launcher.sh:88–104`.
- **Evidence and impact.** Setup places the optional `.env` beside the application. The Mac update paths swap that directory for a fresh archive and delete the previous directory. Users who saved a key in the installed app folder can lose their only local copy. Separately, the ignored `.env` in this checkout has mode 0644, while the README specifies 0600. Actual access also depends on parent-directory permissions and ACLs. No key value was included in the review.
- **Recommended correction.** Give opted-in saved credentials a stable, owner-private location. Migrate only the existing user's file, preserve explicit environment-variable precedence and avoid logging values. Create the file privately from the outset in setup instructions. Restrict this checkout's file permissions independently.
- **Disposition.** Safe to correct automatically while retaining the current opt-in policy.

### L-5. XLS preflight approval omits inputs that change the extraction

- **Location.** `handlers/xls_conversion.py:42–90, 141–169, 188–218`, `xls_conversion/ai_parser.py:967–980, 1362–1366, 1976–1979, 2001–2005`.
- **Evidence and impact.** The cached check covers document text, image range, model, language, record type and whole-document mode. Conversion also accepts a language role and marker overrides. A role changes the extraction prompt, and overrides change the selected blocks. Neither participates in validating the cached approval. The normal UI commonly keeps these values consistent, while the server accepts stale or mismatched settings.
- **Recommended correction.** Bind the normalized language role and effective marker mapping to preflight, or remove unsupported conversion inputs. Have preflight and conversion consume the same parsed request and test changing either field.
- **Disposition.** Safe to correct automatically.

## INFORMATIONAL

### I-1. The offline JavaScript regression job covers a retired parser

- **Location.** `xls_conversion/README.md:29–35`, `xls_conversion/tests/harness.js:1–6`, `xls_conversion/tests/run_parser_test.py`, `.github/workflows/tests.yml:62–66`.
- **Why it matters.** The six-entry parser diagnostic passed. It loads the baptism regex parser, while the live conversion feature uses the Python AI extraction pipeline. The matrimony and death regex parsers are documented as unmaintained reference files. Counting this CI job as live extraction coverage would overstate assurance.
- **Recommended correction.** Label the job explicitly as a legacy-fixture check. Put regressions for provider-output interpretation and live entry-point behavior in the active Python/HTTP suite. The existing reference files can be retained.
- **Disposition.** Safe to correct automatically.

## Scope and verification

- Inventoried all **198 tracked files** across the server, handlers, state and persistence, provider clients, transcription and translation, index and transcript comparison, spreadsheet/Word export, browser code, styles, shipped profiles and worksheet bundles, launchers, installers, CI, documentation, historical reviews and tests. Static analysis parsed all 110 tracked Python files. The 12 worksheet DOCX packages and two distribution ZIPs passed integrity checks. The bundled worksheets matched their source copies byte for byte.
- Reviewed Host/Origin/request-token handling, credential routing and persistence, subprocess calls, local path resolution, upload and archive parsing, output encoding, concurrency, dependency locks and release handling. The server binds to loopback. Its cookie protects browser requests and the project explicitly trusts other processes on the machine. There is no application database or multi-user authorization layer in this checkout. The tracked-file credential-pattern scan found no matching literal. Its scope was the current tree.
- **Pytest:** 545 passed, one Windows-CI-only shortcut test skipped, both in the existing environment and in a fresh Python 3.12.0 environment with the release package lock and development requirements. Loopback access was enabled for the HTTP fixtures. The offline parser test passed. Both environments passed `pip check`.
- **Static checks:** Ruff's CI correctness subset (`F,E9`) passed. Full Ruff reported 84 diagnostics in the checkout environment, including 50 broad exception catches. They were assessed in context and are not 84 separate vulnerabilities. JavaScript and shell syntax checks and C launcher syntax compilation passed.
- **Advisories:** The checked-in Python runtime lock, listed development pins, fully resolved temporary test environment and worksheet npm lockfile returned no known vulnerabilities in the registries queried. The existing local environment yielded M-14. Advisory results are a November 22, 2026 snapshot.
- **Evidence boundaries:** Functional checks used ordinary synthetic records, temporary files and mocked provider results. The review did not submit paid AI jobs, use production credentials for diagnostics, load-test the server, execute the Windows installer, or sign, notarize or publish a release. Platform release behavior and the identified concurrency interleavings are reported from source where no end-to-end observation is stated.

OVERALL STATUS: CHANGES_REQUIRED
