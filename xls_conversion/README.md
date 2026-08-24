# XLS Conversion

DOCX-to-spreadsheet interface that turns a completed transcription into the
official index template for one of 6 record types: Church Battesimi, Church
Matrimoni, Church Morti, Civil Birth, Civil Marriage, Civil Death.

The page uploads a local DOCX file to the localhost server and extracts its
text. Preflight requires an API key, an uploaded source transcription, and a
selected image range (or "Process all"). The selected model reviews every
requested image to confirm it contains material in the selected output
language(s). It never rewrites, corrects, translates, or otherwise modifies
the source, and preflight does not report markers outside the requested
range.

Extraction is AI-powered for all 6 record types (`xls_conversion/ai_parser.py`,
`RECORD_TYPES`): the server sends each selected source block to the selected
model — Gemini or Claude — with a record-type-specific structured extraction
prompt, normalizes the returned JSON, and provides downloadable XLSX and CSV
output matching that type's real official template (group/column headers,
field keys, numeric/zero-padded formatting, and column widths verified against
the templates). The API key is required, validated before extraction, supplied
only as an in-memory override for the conversion request, and is not saved.

For the fuller picture — how each record type's config differs, which fields
get AI-driven normalization, the shared extraction rules all 5 non-Battesimi
types use, and the two deliberately-orphaned regex parsers
(`baptism-parser.js`, `matrimony-parser.js`, `morti-parser.js` — offline
regression-test fixtures only, not loaded by this page) — see the project
root's `CLAUDE.md`, which is the actively-maintained source of truth. This
file is a short pointer, not a duplicate of it.
