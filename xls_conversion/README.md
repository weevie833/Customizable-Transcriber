# XLS Conversion

Unified DOCX-to-spreadsheet interface for battesimi, matrimoni, and morti transcriptions.

The source-specific parsers were consolidated from:

- `baptism-psv-utility 2/parser.js`
- `matrimoni-record-psv-utility/parser.js`
- `morti-record-psv-utility/parser.js`

The page uploads a local DOCX file to the localhost server and extracts its text.
Preflight requires a Gemini API key, an uploaded source transcription, and a
selected image range. Gemini then reviews every requested image to confirm that
each identified entry already contains English translation material. It never
rewrites, corrects, translates, or otherwise modifies the source, and preflight
does not report markers outside the requested range.

Battesimi conversion is AI-powered: the server sends each selected source block
to the selected Gemini model with a Battesimi-specific structured extraction
prompt, normalizes the returned JSON, and provides downloadable XLSX and CSV
output. XLSX files freeze the two template header rows. CSV files use standard
quoting and a UTF-8 byte-order mark for Excel compatibility. XLSX output is a
plain cell range without table or filter controls. Both header rows use bold
black text on an unfilled white background. Image numbers, baptism years and
days, and birth years and days are stored as numeric XLSX cells. The Gemini API key is required, validated before extraction, supplied
only as an in-memory override for the conversion request, and is not saved.

The Battesimi output matches the two-row, 20-column Italian Parish Records
template: source page and image, separate baptism and birth date components,
the individual's split name and inferred gender, split parent names with brief
other-information summaries, consolidated sponsors, a blank image-link field,
and concise notes. Explicit relative dates and cross-image same-day references
are resolved from the relevant baptism-date context. Generic “married couple”
and “married to” details are excluded from both parent Other Information fields.
