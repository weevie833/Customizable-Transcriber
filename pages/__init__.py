"""Page-render modules (Transcribe, Test Mode, Prompt Builder, Home, Privacy)
-- see CLAUDE.md's app.py-modularization section."""

from __future__ import annotations

import json

FOOTER_HTML = (
    '<footer class="license">&copy; 2026 Steve Covello. All rights reserved '
    "— free to download and run for personal use; redistribution, "
    "hosting, and derivative works require permission. &middot; "
    '<a href="/privacy">Privacy</a> <span id="app-version"></span></footer>'
)
"""The single footer every page (app.py's own getting_started_page()
included) embeds verbatim. Kept here, not duplicated per page, so a wording
or license change is one edit instead of six -- see CLAUDE.md's license
section for why this text reads "all rights reserved" rather than an open
license."""


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


def file_picker_html(input_id: str = "", accept: str = "", extra_attrs: str = "") -> str:
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
    """
    id_attr = f' id="{input_id}"' if input_id else ""
    attrs = f" {extra_attrs}" if extra_attrs else ""
    return (
        f'<label class="file-picker"><input type="file"{id_attr} accept="{accept}"{attrs}>'
        '<span class="file-picker-btn">Choose file</span>'
        '<span class="file-picker-name">No file selected</span></label>'
    )
