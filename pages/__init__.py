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
