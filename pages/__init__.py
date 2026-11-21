"""Page-render modules (Transcribe, Test Mode, Prompt Builder, Home, Privacy)
-- see docs/DESIGN.md's "Codebase structure" section."""

from __future__ import annotations

import html
import json

KOFI_URL = "https://ko-fi.com/forestiero"
"""Ko-fi donation page. Also hard-coded in xls_conversion/index.html (a
static file), so change both together."""

# A plain styled link, not Ko-fi's hosted button image: the CSP's img-src
# is 'self' data:, and a link sends nothing to Ko-fi until it is clicked.
# The cup is inline SVG (no text, so i18n.js leaves it alone).
FOOTER_SUPPORT_HTML = (
    '<div class="footer-support">'
    f'<a class="kofi-button" href="{KOFI_URL}" target="_blank" '
    'rel="noopener noreferrer">'
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" width="16" '
    'height="16"><path fill="currentColor" d="M4 5h13v2h1.5a3.5 3.5 0 0 1 0 7H17'
    'a6 6 0 0 1-6 5H10a6 6 0 0 1-6-6V5zm13 4v3h1.5a1.5 1.5 0 0 0 0-3H17z"/></svg>'
    "<span>Support on Ko-fi</span></a>"
    "<span>Help offset the costs for developing and maintaining this "
    "application.</span></div>"
)

FOOTER_HTML = (
    '<footer class="license">'
    + FOOTER_SUPPORT_HTML
    + "<div>&copy; 2026 Steve Covello. All rights reserved "
    "— free to download and run for personal use; redistribution, "
    "hosting, and derivative works require permission. &middot; "
    '<a href="/privacy">Privacy</a> <span id="app-version"></span></div></footer>'
)
"""The single footer every page (app.py's own getting_started_page()
included) embeds verbatim. Kept here, not duplicated per page, so a wording
or license change is one edit instead of six. Deliberately "all rights
reserved" rather than an open-source license."""


def json_for_inline_script(value: object) -> str:
    """json.dumps(value), safe to embed directly inside an inline <script>
    block as a JS literal (e.g. `window.X = {this};`) rather than a quoted
    string later passed through JSON.parse.

    Escaping "</" as "<\\/" is still valid JSON and valid JS (an escaped
    character in a JS string literal just means that character) -- it stops
    a "</script>" inside the value from prematurely closing the block. This
    matters because the browser's HTML tokenizer scans for that literal
    byte sequence while in script-data state, with no awareness that it's
    sitting inside a string: it doesn't matter that the JSON/JS parser would
    never have treated it as a tag.

    Shared here because every pages/*.py module needs exactly this to embed
    profile data, model lists, or run history -- and one call site
    (prompt_builder.py's restore_edit_label) once used bare json.dumps()
    instead, letting an attacker-controlled profile label containing
    "</script>" break out and run arbitrary JS on a page that later reached
    the error-rendering path with it.
    """
    return json.dumps(value).replace("</", "<\\/")


def json_data_island_html(element_id: str, value: object) -> str:
    """A `<script type="application/json" id="{element_id}">` holding
    json_for_inline_script()'s escaped output -- server-rendered dynamic
    data (profile lists, run history, questionnaire state) for an
    externalized page script to read via
    `JSON.parse(document.getElementById(element_id).textContent)`, instead
    of an executable inline `<script>window.X = {...}</script>` assignment.

    Exists so this data can keep reaching the page's own external JS
    (static/prompt-builder.js, and Transcribe's/Test Mode's own per-page
    scripts) after CSP's script-src drops 'unsafe-inline' (see
    reviews/CODEX_REVIEW.md finding L-2 / reviews/HUMAN_DECISIONS.md): a `type="application/
    json"` element is inert data as far as the browser's JS engine is
    concerned -- it's never parsed or executed as script, so CSP's
    script-src (which only ever governs what can *execute* as script) never
    applies to it, unlike a plain `<script>` block. The `</script`-breakout
    risk json_for_inline_script() already guards against is unrelated to
    that and still fully applies here: the HTML tokenizer looks for that
    literal byte sequence to end *any* `<script>` element's raw-text
    content, regardless of its `type` attribute.
    """
    return f'<script type="application/json" id="{element_id}">{json_for_inline_script(value)}</script>'


def info_button_html(panel_id: str, text: str) -> str:
    """A small "i" button that toggles a popup panel with plain-language help
    text -- same shape as Prompt Builder's own pb_info_button_html()
    (pages/prompt_builder.py), but using .info-btn/.info-panel (base.css)
    instead of Prompt Builder's own .pb-info-* classes, since Prompt Builder
    doesn't load base.css/app-common.js at all -- see base.css's own comment
    on .info-wrap for why this is a parallel copy, not a shared move. Wired
    generically by app-common.js's wireInfoButtons() (click/Escape/outside-
    click to close), so this function only has to emit matching markup."""
    return (
        f'<span class="info-wrap">'
        f'<button type="button" class="info-btn" aria-expanded="false" aria-controls="{panel_id}" aria-label="More information">i</button>'
        f'<span class="info-panel" id="{panel_id}" role="note" hidden>{html.escape(text)}</span>'
        f'</span>'
    )


def file_picker_html(input_id: str = "", accept: str = "", extra_attrs: str = "", drop_zone: bool = False) -> str:
    """A <label class="file-picker"> wrapping a visually-hidden <input
    type="file"> plus a translatable "Choose file" button stand-in and a
    filename/placeholder span.

    Exists because a bare <input type="file">'s own "Choose File" button
    text is supplied by the browser itself from its own UI language --
    never from this page's lang attribute or i18n.js's DICTIONARY -- so it
    can't be localized in place no matter what this app does. See
    static/base.css's own comment on .file-picker for the full rationale.

    The filename span never needs its own reset-to-placeholder logic: the
    initial "No file selected" text node is translated normally by i18n.js
    (on load and on every language toggle) like any other static text, and
    the one JS change-handler that touches this span only ever overwrites
    it with the chosen file's real name -- which never matches a DICTIONARY
    key, so it displays identically regardless of language, exactly as a
    filename should. Nothing ever needs to restore the placeholder text
    itself, so there's no hardcoded-English-overwrite risk to guard against.

    `input_id` is omitted entirely (not emitted as `id=""`) when blank --
    matters for the repeatable-row inputs (Test Mode's "Add another" rows),
    which are found by a `data-*` attribute instead of an id. `extra_attrs`
    is spliced verbatim into the <input> tag for exactly that kind of
    attribute (e.g. `data-extra-file`).

    `drop_zone` adds the `drop-zone` class (a file can also be dragged onto
    the picker; Test Mode wires this in static/test-mode.js) and a
    placeholder that says so.
    """
    id_attr = f' id="{input_id}"' if input_id else ""
    attrs = f" {extra_attrs}" if extra_attrs else ""
    css_class = "file-picker drop-zone" if drop_zone else "file-picker"
    placeholder = "No file selected - or drop one here" if drop_zone else "No file selected"
    return (
        f'<label class="{css_class}"><input type="file"{id_attr} accept="{accept}"{attrs}>'
        '<span class="file-picker-btn">Choose file</span>'
        f'<span class="file-picker-name">{placeholder}</span></label>'
    )
