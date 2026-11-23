# Human decisions required

Customizable Transcriber 0.5.6, commit `79a7acc34dbb9d435a3b256659a4f92a34a4c1c5`. Reviewed November 22, 2026. Two findings require a product decision. The remaining corrections in [the engineering review](./CODEX_REVIEW.md) can proceed independently.

## HD-1. What evidence counts as a match when both index rows lack a locator?

**Finding M-15.** Index Compare can pair unrelated people by row order after their names and years fail to match. A test with different people a century apart returned one match. This affects the missing and extra counts, field error rates, and comparison report. See `index_compare/align.py:146–164, 229–244` and `index_compare/scoring.py:175–185`.

**Recommended decision.** Require an identity match when both page or act locators are absent. Count unresolved rows as missing or extra. If source order is reliable for some collections, allow the researcher to opt in to positional pairing and label those pairs separately in the report.

**Alternative.** Keep position as the default for unlocated rows and disclose how many pairs rely on position alone. This favors complete, consistently ordered indexes and can overstate coverage when rows were added, omitted or reordered.

**Acceptance criterion.** The reviewer can distinguish pairs supported by record evidence from those inferred only from position. A conflicting-year pair follows the selected policy in both the screen and downloaded report.

## HD-2. Which source provenance belongs in a shareable transcript?

**Finding L-3.** Both transcription modes write the absolute source folder into Markdown and Word. It can identify a user account or a private collection directory when the file is shared. See `customizable_transcriber/core.py:1300–1303`, `batch_transcription.py:1033–1036` and `run_support.py:646–655`.

**Recommended decision.** Export a collection label and relative image identifiers by default. Keep the full path in local job details. Allow deliberate inclusion in exports for users who need machine-specific provenance.

**Alternative.** Retain the absolute path by default, show what will be included before export, and provide an omission control for shared copies.

**Acceptance criterion.** A user can tell whether the exported document will reveal the local directory. Both real-time and off-peak outputs follow the same choice.

OVERALL STATUS: CHANGES_REQUIRED
