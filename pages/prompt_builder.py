"""Prompt Builder page ("/prompt-builder") and its small HTML-fragment
helper functions (pb_*). Split out of app.py as part of the
app.py-modularization pass -- see docs/DESIGN.md's "Codebase structure"
section."""

from __future__ import annotations

import html

from customizable_transcription.core import DEFAULT_MODEL, MODELS
from pages import FOOTER_HTML, file_picker_html, json_data_island_html
from profiles_store import load_custom_profiles, profiles_with_display_labels
from prompt_builder_content import (
    PROMPT_BUILDER_COMMON_ABBREVIATIONS,
    PROMPT_BUILDER_CORE_RULES,
    PROMPT_BUILDER_RECORD_TYPES,
    PROMPT_BUILDER_RELATIONSHIP_TERMS,
    PROMPT_BUILDER_RELATIVE_DATE_TERMS,
    PROMPT_BUILDER_SCRIBAL_QUIRKS,
    PROMPT_BUILDER_SECTION_HELP,
)


def pb_record_type_options_html() -> str:
    church = ["battesimi", "matrimoni", "morti"]
    civil = ["civil_birth", "civil_marriage", "civil_death"]

    def options(keys: list[str]) -> str:
        return "\n".join(
            f'          <option value="{key}">{html.escape(PROMPT_BUILDER_RECORD_TYPES[key]["label"])}</option>'
            for key in keys
        )

    return (
        f'<optgroup label="Church Records">\n{options(church)}\n        </optgroup>\n'
        f'        <optgroup label="Civil Records">\n{options(civil)}\n        </optgroup>'
    )


def pb_info_button_html(panel_id: str, text: str) -> str:
    # A small "i" button that toggles a popup panel with plain-language help
    # text -- wired generically in prompt-builder.js (click/Escape/outside-
    # click to close), so this function only has to emit matching markup.
    return (
        f'<span class="pb-info-wrap">'
        f'<button type="button" class="pb-info-btn" aria-expanded="false" aria-controls="{panel_id}" aria-label="More information">i</button>'
        f'<span class="pb-info-panel" id="{panel_id}" role="note" hidden>{html.escape(text)}</span>'
        f'</span>'
    )


def pb_checklist_html(name: str, values: list[str]) -> str:
    # Everything a checklist offers is a plausible-by-default fact about the
    # kind of register being described (a common abbreviation, a common
    # scribal habit...), so every preset starts checked; unchecking one is a
    # user override, not the normal path.
    items = [
        f'<label class="pb-checkbox"><input type="checkbox" name="{name}" value="{html.escape(value)}" checked>{html.escape(value)}</label>'
        for value in values
    ]
    return "\n        ".join(items)


def pb_common_abbrev_checklist_html() -> str:
    items = []
    for written, expansion, meaning in PROMPT_BUILDER_COMMON_ABBREVIATIONS:
        value = html.escape(f"{written}|{expansion}|{meaning}")
        label_text = html.escape(f"{written} = {expansion} ({meaning})")
        items.append(f'<label class="pb-checkbox"><input type="checkbox" name="commonAbbrev" value="{value}" checked>{label_text}</label>')
    return "\n        ".join(items)


# Shared by every formula field (Entry structure, Groom's/Bride's/Witness/Act
# formula) across all 6 types -- generic on purpose, same reasoning as the
# marginal-heading/role-vocab info texts above: one field-specific example per
# type per field would be a lot of upkeep for text that says the same thing
# every time regardless of which formula field or record type it's attached to.
PB_FORMULA_INFO_TEXT = (
    "This is the exact standing phrase your register repeats in every entry, written out with the parts that "
    "change -- names, dates, roles -- marked as bracketed placeholders like [FATHER] or [WITNESS]. It teaches the "
    "AI where each real name or date sits in the sentence, even past abbreviations. Edit the sample text below to "
    "match your own register's actual wording."
)

# These three were previously inlined as literal strings inside prompt_builder_page()'s
# own f-string -- each contained a backslash (an escaped quote or apostrophe) inside a
# `{...}` expression part, which Python <3.12 rejects outright ("f-string expression
# part cannot include a backslash"). This app's documented floor is 3.10 (pyproject.toml),
# so those three lines were a real SyntaxError under the CI matrix's 3.10 jobs the whole
# time -- invisible locally on a 3.12+ interpreter, since PEP 701 lifted the restriction
# there. Pulled out to plain module-level constants (same pattern as PB_FORMULA_INFO_TEXT
# above) so the f-string only ever sees a bare identifier inside `{}`; the backslashes
# themselves are unchanged and perfectly legal in an ordinary string literal.
PB_SCRIBAL_INFO_TEXT = (
    "Paleographic quirks are common habits of a scribe's handwriting that can look like errors but are not -- "
    "things like a long ſ that resembles an f, or a macron over a vowel marking a dropped letter. Checking these "
    "tells the AI what to expect from this hand, so it does not misread a normal scribal habit as an unfamiliar "
    "name or a typo."
)
PB_ADDITIONAL_RULES_INFO_TEXT = (
    "A catch-all for a register-specific judgment call that doesn't fit any question above -- for example, "
    "\"never copy a surname from one parent to the other\" or a rule about when two blocks disagreeing counts as "
    "an error versus expected grammar. Most profiles won't need this; it exists for the occasional rule that's "
    "specific to your source and not covered by a preset elsewhere on this page."
)
PB_SPAN_IMAGES_INFO_TEXT = (
    "Some registers are photographed so that each entry begins on the right-hand page of one image and finishes "
    "on the left-hand page of the next image (the back of the same leaf). If yours does, check this box. The AI "
    "will treat the text at the top of a left page as the end of the previous image's last entry -- not a new "
    "entry -- and will ignore faint ink showing through from the other side of the leaf. Only applies when the "
    "page layout is two facing pages."
)

PB_HONORIFICS_INFO_TEXT = (
    "This is about how a person's title gets written in a translation when they're named in a role -- a "
    "godparent, a witness, an informant. A \"role clause\" is the little phrase that introduces that person "
    "(e.g. \"The godfather was Don Carolus Calsi\")."
)


def pb_formula_fields_html(type_key: str, config: dict, after_first: str = "") -> str:
    # placeholder here is live, pre-filled textarea content (not a `placeholder`
    # attribute) -- the user edits the sample formula in place rather than
    # typing into an empty box. The label text + note + info button are wrapped
    # in one <span> (not left as bare siblings) so they land on the label's
    # first grid row together -- same fix as Name lexicon's label, see there.
    rows = []
    for field in config["formula_fields"]:
        # Most formulas are one short standing phrase and fit the default
        # 2-row textarea; a field tuple may carry an optional 5th element
        # (textarea_rows) when its sample text is long enough to need more
        # -- e.g. civil_death's full declaration-of-death formula, several
        # sentences long, not a single clause like the church formulas.
        key, label, placeholder, optional = field[:4]
        textarea_rows = field[4] if len(field) > 4 else 2
        note = " (optional — leave blank if this register has none)" if optional else ""
        info_button = pb_info_button_html(f"pb-info-formula-{type_key}-{key}", PB_FORMULA_INFO_TEXT)
        rows.append(
            f'      <label><span>{html.escape(label)}{note}{info_button}</span>\n'
            f'        <textarea name="{type_key}_{key}" rows="{textarea_rows}">{html.escape(placeholder)}</textarea>\n'
            f'      </label>'
        )
        if not rows[1:] and after_first:
            rows.append(after_first.rstrip("\n"))
    return "\n".join(rows)


# Civil Birth only, confirmed against a real 1843 register: some registers
# print a genuine two-column form, the birth act on the left and a
# dedicated, separately-headed column on the right recording when the
# church administered baptism (same act number as the birth act, its own
# short administrative narrative -- the parish returning a slip, the
# civil officiant filing it). This is a real, distinct layout, not the
# same thing as a baptism note folded into the main body or written in
# the margin (that case is still handled unconditionally below, for
# registers that don't use this column).
PB_BAPTISM_COLUMN_INFO = (
    "Some civil birth registers print a genuine two-column form: the birth act on the left, and a separately "
    "headed column on the right recording when the church administered baptism, sharing the same act number. "
    "If your register does this, check the box. The AI will transcribe that column as its own \"Baptism Record\" "
    "block, kept separate from the main act -- rather than treating it as a note folded into the body or "
    "written in the margin, which is how baptism information is handled when this box is left unchecked."
)

PB_BAPTISM_FORMULA_DEFAULT = (
    'the baptism-column formula, e.g. "[DATE]: baptism administered to [CHILD] by [PRIEST] in the parish of [PARISH]"'
)


def pb_baptism_block_html(type_key: str) -> str:
    # Civil Nati only. The checkbox reveals its own formula field (same
    # checkbox-then-field pattern as the marginal heading just above it) and
    # also switches on the Baptism Record block and example part.
    if type_key != "civil_birth":
        return ""
    return f"""      <div class="pb-inline-row">
        <label class="pb-checkbox"><input type="checkbox" name="{type_key}_hasBaptismColumn" class="pb-baptism-toggle"> This register has a separate column recording when the child was baptized</label>{pb_info_button_html(f"pb-info-baptismcolumn-{type_key}", PB_BAPTISM_COLUMN_INFO)}
      </div>
      <div class="pb-baptism-formula" hidden>
        <label><span>Baptism record formula{pb_info_button_html(f"pb-info-baptism-formula-{type_key}", PB_FORMULA_INFO_TEXT)}</span>
          <textarea name="{type_key}_formula_baptism" rows="2">{html.escape(PB_BAPTISM_FORMULA_DEFAULT)}</textarea>
        </label>
      </div>
"""


# Civil Marriage only, confirmed against a real 1823 Napoli register: the
# act is printed as a two-column form, the marriage promise on the left and
# a separate right-hand column in which the parish confirms the church
# ceremony took place (parish, date, its own witnesses, and the officer's
# filing note). Left unchecked, that text is handled by the inline
# `[marginal]` rule instead, which splices it into the middle of the act's
# body wherever the page happens to break.
PB_CHURCH_WEDDING_COLUMN_INFO = (
    "Some civil marriage registers print a two-column form: the marriage promise on the left, and a separate "
    "column on the right in which the parish priest confirms the church wedding took place, with its own date "
    "and witnesses. If your register does this, check the box. The AI will transcribe that column as its own "
    "\"Church Wedding Record\" block, kept separate from the main act -- rather than inserting it into the "
    "middle of the act's text, which is what happens when this box is left unchecked and the column is treated "
    "as a margin note. Witnesses named in that column attended the church wedding; they are not additional "
    "witnesses to the civil marriage promise."
)

PB_CHURCH_WEDDING_FORMULA_DEFAULT = (
    'the church-wedding column formula, e.g. "[DATE]: the parish priest of [PARISH] confirms that the wedding of [GROOM] and [BRIDE] took place on [DATE], in the presence of [WITNESS1] and [WITNESS2]"'
)


def pb_church_wedding_block_html(type_key: str) -> str:
    # Civil Matrimoni only. Same checkbox-then-field pattern as the baptism
    # block; also switches on the Church Wedding Record block and example part.
    if type_key != "civil_marriage":
        return ""
    return f"""      <div class="pb-inline-row">
        <label class="pb-checkbox"><input type="checkbox" name="{type_key}_hasChurchWeddingColumn" class="pb-church-wedding-toggle"> This register has a separate right-hand column recording the parish's confirmation of the church wedding</label>{pb_info_button_html(f"pb-info-churchweddingcolumn-{type_key}", PB_CHURCH_WEDDING_COLUMN_INFO)}
      </div>
      <div class="pb-church-wedding-formula" hidden>
        <label><span>Church wedding record formula{pb_info_button_html(f"pb-info-church-wedding-formula-{type_key}", PB_FORMULA_INFO_TEXT)}</span>
          <textarea name="{type_key}_formula_churchWedding" rows="2">{html.escape(PB_CHURCH_WEDDING_FORMULA_DEFAULT)}</textarea>
        </label>
      </div>
"""


def pb_civil_fields_html(type_key: str, config: dict) -> str:
    # Civil-only structural questions -- framed by what the page visibly looks
    # like, not by which historical/legal era produced it. A non-expert user
    # is far more likely to recognize "is there a printed form on this page"
    # than to know whether their register predates or postdates 1865, and per
    # the scoping discussion accuracy on each record matters more than
    # correctly diagnosing which era produced it.
    page_format_info = (
        "Civil registers from this period take two visibly different forms: an entirely handwritten narrative "
        "(common before national printed templates were adopted), or a printed form with the fixed legal wording "
        "already on the page and only the names, dates, and other specifics filled in by hand. If your register is "
        "a printed form, the AI is told to expect two different scripts on the same page -- the printed boilerplate "
        "and the clerk's handwriting -- and to weigh transcription accuracy toward the handwritten fill-ins, since "
        "that is where the names and dates that matter for indexing are recorded."
    )
    return f"""      <div class="pb-civil-fields">
        <fieldset>
          <legend>Page format{pb_info_button_html(f"pb-info-pageformat-{type_key}", page_format_info)}</legend>
          <div class="pb-radio-group" role="radiogroup" aria-label="Page format">
            <label class="pb-radio"><input type="radio" name="{type_key}_pageFormat" value="printed_form" checked> Printed form with handwritten entries filled in</label>
            <label class="pb-radio"><input type="radio" name="{type_key}_pageFormat" value="handwritten"> Entirely handwritten — no printed form on the page</label>
          </div>
        </fieldset>
      </div>"""


def pb_section2_type_group_html(type_key: str) -> str:
    config = PROMPT_BUILDER_RECORD_TYPES[type_key]
    checked = " checked" if config["has_marginal_heading_default"] else ""
    formula_hidden = "" if config["has_marginal_heading_default"] else " hidden"
    marginal_placeholder = html.escape(config["marginal_heading_placeholder"])
    formula_html = pb_formula_fields_html(type_key, config, after_first=pb_baptism_block_html(type_key) + pb_church_wedding_block_html(type_key))
    role_vocab_html = pb_checklist_html(f"{type_key}_roleVocab", config["role_vocab"])
    # Both info-button texts below are generic on purpose -- they used to hardcode
    # Battesimi's own example ("[child's name] filius/filia...", "P.nus"/"PP.") and
    # got reused verbatim for every type via this shared function, so Matrimoni/
    # Morti/civil users saw Battesimi's vocabulary in their own popups. The marginal
    # one now quotes each type's own placeholder instead; the role-vocab one no
    # longer names specific terms at all, since there's no single example that fits
    # every type's own list.
    marginal_info_text = (
        "Many church and civil registers write a short note in the margin next to each entry -- often just the "
        "name(s) involved -- as a running index down the side of the page. If your register does this, check the "
        f'box and describe the pattern below, for example "{config["marginal_heading_placeholder"]}." The AI will '
        'transcribe this margin note as its own "Marginal Heading" block, kept separate from the entry\'s main body '
        "text -- useful because the two occasionally disagree (a different spelling, a different name order), and "
        "both readings are worth preserving."
    )
    role_vocab_info_text = (
        "These are the role-specific words this register uses for the people named in an entry -- for example, a "
        "different term depending on whether one person filled the role or several did. Checking a term tells the "
        "AI to recognize it and use it correctly when working out who filled which role. Leave a term unchecked if "
        "it never appears in your register."
    )
    # Civil-only: printed/handwritten page format, multi-page acts -- these
    # don't apply to church registers, which are prose throughout.
    is_civil = type_key.startswith("civil_")
    civil_fields_html = pb_civil_fields_html(type_key, config) if is_civil else ""
    # Marginal Heading was dropped for all civil types on the theory that
    # civil registers never showed a marginal-heading-style name index --
    # wrong for Civil Birth specifically: a real 1875 register shows exactly
    # this, a left-margin "Numero <N> / <Child's name>" index running down
    # the page, serving the same cross-check purpose as a church register's
    # marginal heading (the name appearing twice raises the odds either
    # reading is correct). Civil Marriage/Death haven't shown this pattern,
    # so they still skip the field -- see has_marginal_heading_support below.
    supports_marginal_heading = config.get("has_marginal_heading_support", True)
    marginal_block_html = "" if not supports_marginal_heading else f"""      <div class="pb-inline-row">
        <label class="pb-checkbox"><input type="checkbox" name="{type_key}_hasMarginalHeading" class="pb-marginal-toggle"{checked}> This register has a separate margin for each entry that states the name</label>{pb_info_button_html(f"pb-info-marginal-{type_key}", marginal_info_text)}
      </div>
      <div class="pb-marginal-formula"{formula_hidden}>
        <label><span>Marginal heading structure{pb_info_button_html(f"pb-info-marginal-structure-{type_key}", marginal_info_text)}</span>
          <textarea name="{type_key}_formula_marginalHeading" rows="2">{marginal_placeholder}</textarea>
        </label>
      </div>
"""
    role_vocab_class = "pb-checklist pb-checklist-stacked" if config.get("role_vocab_stacked") else "pb-checklist pb-checklist-2col"
    return f"""    <div class="pb-type-group" data-record-type="{type_key}" hidden>
{marginal_block_html}{formula_html}
{civil_fields_html}
      <p class="hint">Role-clause vocabulary for {html.escape(config["label"])} (optional){pb_info_button_html(f"pb-info-rolevocab-{type_key}", role_vocab_info_text)}</p>
      <div class="{role_vocab_class}">
        {role_vocab_html}
      </div>
{pb_role_vocab_extra_rows_html(type_key) if config.get("role_vocab_extendable") else ""}
    </div>"""


def pb_role_vocab_extra_rows_html(type_key: str) -> str:
    return (
        f'      <div id="{type_key}-rolevocab-rows"></div>\n'
        f'      <button type="button" class="button-tiny pb-add-rolevocab" data-record-type="{type_key}">Add another term</button>'
    )


def prompt_builder_page(
    new_profile_name: str = "",
    message: str = "",
    message_kind: str = "",
    restore_answers: dict | None = None,
    restore_edit_id: str = "",
    restore_edit_label: str = "",
) -> str:
    escaped_name = html.escape(new_profile_name)

    banner_html = ""
    if message:
        banner_class = "pb-banner-success" if message_kind == "success" else "pb-banner-error"
        banner_html = f'<div class="pb-banner {banner_class}" role="status">{html.escape(message)}</div>'

    # Profiles loadable back into the questionnaire -- only those saved from
    # Prompt Builder itself carry the structured pb_answers a reload needs.
    # A hand-authored or Transcribe-page-edited profile has no such record and
    # simply isn't offered here; see load_custom_profiles(). Embedded as data,
    # not fetched on selection, matching the same "snapshot on page render"
    # pattern already used for the profile list on the Transcribe/Test Mode
    # pages -- reload this page after saving elsewhere to see a fresh list.
    loadable_profiles = [profile for profile in load_custom_profiles() if profile.get("pb_answers")]
    load_profile_options = "\n".join(
        f'<option value="{html.escape(profile["id"])}">{html.escape(profile["label"])}</option>'
        for profile in loadable_profiles
    )
    # Import/Export Profiles -- unlike the "load to edit" list above, export
    # offers every saved profile (shipped examples included), since sharing a
    # profile with someone else has nothing to do with whether it also
    # happens to be editable back in this questionnaire.
    export_profile_options = "\n".join(
        f'<option value="{html.escape(profile["id"])}">{html.escape(profile["display_label"])}</option>'
        for profile in profiles_with_display_labels()
    )
    # One data island instead of five separate window.PB_* assignments --
    # see json_data_island_html()'s own docstring (pages/__init__.py) and
    # CODEX_REVIEW.md finding L-2 / HUMAN_DECISIONS.md. restore_edit_label
    # carries a profile's free-text label back into the page verbatim (e.g.
    # after a failed save, or loading a profile to edit) -- a label is
    # user-settable and reachable via an imported profile's own "label"
    # field (see profiles_store.import_custom_profile, which places no
    # restriction on it), so it needs the same </script>-safe treatment
    # every other embedded value here gets; json_data_island_html() (via
    # json_for_inline_script()) already provides that for the whole bundle.
    initial_data_html = json_data_island_html(
        "prompt-builder-initial-data",
        {
            "coreRules": PROMPT_BUILDER_CORE_RULES,
            "savedProfiles": {
                profile["id"]: {"label": profile["label"], "answers": profile["pb_answers"]}
                for profile in loadable_profiles
            },
            "restoreOnError": restore_answers or None,
            "restoreEditId": restore_edit_id,
            "restoreEditLabel": restore_edit_label,
        },
    )

    record_type_options = pb_record_type_options_html()
    # Prompt Builder may be the very first page a brand-new user opens, before
    # any API key has ever been set up on this machine -- unlike the Transcribe
    # page's model/key row, there's no "state['model']" carried over from a
    # prior run to default from. Preflight Test is optional, so this defaults
    # to DEFAULT_MODEL with no key pre-filled and lets the request itself fail
    # with a clear error if neither a pasted key nor a .env key is available.
    preflight_model_options = "\n".join(
        f'<option value="{html.escape(model_id)}" {"selected" if model_id == DEFAULT_MODEL else ""}>{html.escape(label)}</option>'
        for model_id, label in MODELS.items()
    )
    section2_type_groups = "\n".join(pb_section2_type_group_html(key) for key in PROMPT_BUILDER_RECORD_TYPES)
    relative_date_checklist = pb_checklist_html("relativeDateTerms", PROMPT_BUILDER_RELATIVE_DATE_TERMS)
    relationship_checklist = pb_checklist_html("relationshipTerms", PROMPT_BUILDER_RELATIONSHIP_TERMS)
    scribal_checklist = pb_checklist_html("scribalQuirks", PROMPT_BUILDER_SCRIBAL_QUIRKS)
    common_abbrev_checklist = pb_common_abbrev_checklist_html()

    return f"""<!doctype html>
<html lang="en">
  <head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Prompt Builder</title>
  <script src="/static/i18n.js" defer></script>
  <link rel="stylesheet" href="/static/base.css">
  <link rel="stylesheet" href="/static/prompt-builder.css">
  {initial_data_html}
  <script src="/static/prompt-builder.js" defer></script>
  </head>
<body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<main id="main-content" tabindex="-1">
  <header class="site-header">
    <h1 class="sr-only">Prompt Builder</h1>
    <div class="header-nav-row">
      <nav class="site-nav" aria-label="Primary navigation">
        <a class="nav-link nav-home" href="/" aria-label="Home" title="Home">🏠</a>
        <a class="nav-link" href="/prompt-builder" aria-current="page">Prompt Builder</a>
        <a class="nav-link" href="/transcribe">Transcribe</a>
        <a class="nav-link" href="/xls-conversion">XLSX Conversion</a>
        <a class="nav-link" href="/test-mode">Test Mode</a>
      </nav>
      <div class="header-right">
        <a class="nav-link nav-secondary" href="/getting-started">Getting Started</a>
        <div class="lang-toggle" role="group" aria-label="Language / Lingua">
          <button type="button" class="lang-flag" data-lang="en" aria-pressed="true" title="English" aria-label="English">🇺🇸</button>
          <button type="button" class="lang-flag" data-lang="it" aria-pressed="false" title="Italiano" aria-label="Italiano">🇮🇹</button>
        </div>
      </div>
    </div>
  </header>
  {banner_html}
  <form method="post" action="/prompt-builder/save-profile" id="pb-questionnaire-form">
    <input type="hidden" name="role_context">
    <input type="hidden" name="reference_context">
    <input type="hidden" name="output_format">
    <input type="hidden" name="native_language">
    <input type="hidden" name="translation_languages">
    <input type="hidden" name="record_type">
    <input type="hidden" name="edit_profile_id" id="pb-edit-profile-id" value="">
    <input type="hidden" name="pb_answers_json" id="pb-answers-json">

    <div class="pb-top-split">
      <div class="pb-top-panel pb-top-create">
        <h2 class="panel-title">Create a new profile</h2>
        <div class="pb-download-row">
          <a id="pb-download-worksheets" class="pb-download-btn" href="/static/prompt-builder-worksheets/prompt-builder-worksheets-en.zip" download="prompt-builder-worksheets-en.zip">Download DOCX (ENG)</a>
          <p class="pb-download-caption" id="pb-download-caption">Download DOCX templates of the questionnaire to complete offline, then copy your selections into the app.</p>
        </div>
        <p class="hint">Pick from presets below to describe your register. The app assembles a complete transcription profile from your answers. It becomes available on the Transcribe and Test Mode pages, but you must reload those pages first before they will appear.</p>
      </div>

      <div class="pb-top-panel" id="pb-load-bar">
        <label>Load an existing profile to edit
          <select id="pb-load-select">
            <option value="">Select a profile</option>
            {load_profile_options}
          </select>
        </label>
        <p class="hint">Only profiles created or edited in the Prompt Builder can be edited here - custom profiles are excluded. Saving edits will update that same profile unless you choose "Save as a new profile" instead.</p>
        <p class="hint pb-editing-status" id="pb-editing-status" hidden></p>
      </div>
    </div>

    <div class="pb-toolbar">
      <button type="button" id="pb-expand-all" class="button-tiny">Expand all</button>
      <button type="button" id="pb-collapse-all" class="button-tiny">Collapse all</button>
      <button type="button" id="pb-reset-form" class="button-tiny">Reset form</button>
    </div>

    <details class="pb-section" open>
      <summary>
        <span class="pb-summary-text">1. Role &amp; Local Context</span>
        <span class="pb-word-count" id="wc-role_context">0 words</span>
      </summary>
      <p class="pb-section-caption">{PROMPT_BUILDER_SECTION_HELP["role_context"]}</p>

      <div class="pb-field-grid">
        <label>Record type
          <select name="recordType">
            {record_type_options}
          </select>
        </label>

        <label>Source language
          <select name="language">
            <option value="Latin">Latin</option>
            <option value="Italian">Italian</option>
            <option value="Latin and Italian mixed">Latin and Italian mixed</option>
            <option value="Other">Other</option>
          </select>
        </label>
      </div>

      <div class="pb-field-grid">
        <div id="pb-church-only-era">
        <label>Era
          <input type="text" name="era" placeholder="e.g. 18th-century">
        </label>
        </div>
        <label>Locality
          <input type="text" name="locality" placeholder="e.g. Chiusa Sclafani">
        </label>
        <label>Province / region
          <input type="text" name="province" placeholder="e.g. province of Palermo, Sicily">
        </label>
        <div id="pb-church-only-institution">
        <label>Institution name
          <input type="text" name="institution" placeholder="e.g. the parish church of San Nicolò di Bari">
        </label>
        </div>
        <label>Volume / date range covered
          <input type="text" name="volumeRange" placeholder="e.g. 1752-1759">
        </label>
        <div id="pb-church-only-handdescriptor">
        <label>Hand / script descriptor (optional)
          <input type="text" name="handDescriptor" placeholder="e.g. Sicilian ecclesiastical chancery hand">
        </label>
        </div>
      </div>

      <div class="pb-field-grid">
        <label>Page layout
          <select name="pageLayout">
            <option value="one_page">One page per image</option>
            <option value="two_facing" selected>Two facing pages, read left then right</option>
            <option value="other">Other</option>
          </select>
        </label>

        <label>Hour convention
          <select name="hourConvention">
            <option value="italian_hours" selected>Italian hours, counted from sunset</option>
            <option value="clock_time">Standard clock time</option>
            <option value="not_applicable">Not applicable</option>
          </select>
        </label>
      </div>

      <div id="pb-page-layout-other-row" hidden>
        <label>Describe the page layout
          <input type="text" name="pageLayoutOther" placeholder="e.g. one long page per image, read top to bottom">
        </label>
      </div>
      <div class="pb-inline-row" id="pb-span-images-row">
        <label class="pb-checkbox"><input type="checkbox" name="entriesSpanFacingImages"> Entries start on the right page of an image and continue on the left page of the next image</label>{pb_info_button_html("pb-info-span-images", PB_SPAN_IMAGES_INFO_TEXT)}
      </div>

      <div class="pb-field-grid">
        <div id="pb-church-only-pagenumberscheme">
        <label>Page-numbering scheme
          <select name="pageNumberScheme">
            <option value="none">No page numbers</option>
            <option value="one_per_image">One number per image</option>
            <option value="two_per_image" selected>Two numbers, one per facing page</option>
            <option value="native_acts">Register has its own act/entry numbers</option>
          </select>
        </label>
        </div>

        <div id="pb-latin-month-field">
        <label>Month-abbreviation convention
          <select name="monthConvention">
            <option value="latin_march" selected>Latin March-counting (7bris-10bris)</option>
            <option value="standard">Standard month names</option>
            <option value="other">Other</option>
          </select>
        </label>
        </div>
      </div>
      <div id="pb-month-convention-other-row" hidden>
        <label>Describe the month-abbreviation convention
          <input type="text" name="monthConventionOther" placeholder="e.g. months abbreviated to their first three letters, with Xbre for December">
        </label>
      </div>
      <div id="pb-page-number-corner-row">
        <label>Where are the page numbers?
          <input type="text" name="pageNumberCorner" placeholder="e.g. upper corner, left page's number upper-left, right page's upper-right">
        </label>
      </div>

      <div class="pb-inline-row" id="pb-latin-declension-row">
        <label class="pb-checkbox"><input type="checkbox" name="latinDeclension" checked> Include Latin grammatical case-declension guidance</label>{pb_info_button_html("pb-info-declension", 'Latin nouns and names change their ending depending on their grammatical role in the sentence -- this is called declension. The same person can appear in more than one form within a single entry: Franciscus (nominative, as the subject), Francisci (genitive, "of Francis"), Francisco (dative/ablative, "to/from Francis"). This is not a spelling error or an inconsistency to fix -- each form is correct for its context. Turning this on adds guidance so the AI recognizes these variants as the same name and transcribes each form exactly as written, instead of "normalizing" one to match another.')}
      </div>

      <div>
        <p class="hint">Relative-date vocabulary</p>
        <div class="pb-checklist pb-checklist-2col" id="pb-latin-relativedate-checklist">
          {relative_date_checklist}
        </div>
        <div id="pb-relativedate-rows"></div>
        <button type="button" id="pb-add-relativedate" class="button-tiny">Add another term</button>
      </div>
    </details>

    <details class="pb-section">
      <summary>
        <span class="pb-summary-text">2. Reference Material</span>
        <span class="pb-word-count" id="wc-reference_context">0 words</span>
      </summary>
      <p class="pb-section-caption">{PROMPT_BUILDER_SECTION_HELP["reference_context"]}</p>

{section2_type_groups}

      <p class="hint">Entry variants (optional) — e.g. an emergency or conditional variant of the standard formula</p>
      <div id="pb-variant-rows"></div>
      <button type="button" id="pb-add-variant" class="button-tiny">Add a variant</button>

      <p class="hint">Relationship-note vocabulary</p>
      <div class="pb-checklist" id="pb-latin-relationship-checklist">
        {relationship_checklist}
      </div>
      <div id="pb-relationship-rows"></div>
      <button type="button" id="pb-add-relationship" class="button-tiny">Add another term</button>

      <p class="hint">Abbreviation key — common terms (toggle on what applies)</p>
      <div class="pb-checklist pb-checklist-2col" id="pb-latin-abbrev-checklist">
        {common_abbrev_checklist}
      </div>
      <div id="pb-abbrev-rows"></div>
      <button type="button" id="pb-add-abbrev" class="button-tiny">Add an abbreviation</button>

      <p class="hint">Scribal / paleographic quirks{pb_info_button_html("pb-info-scribal", PB_SCRIBAL_INFO_TEXT)}</p>
      <div class="pb-checklist pb-checklist-2col" id="pb-latin-scribal-checklist">
        {scribal_checklist}
      </div>
      <div id="pb-scribal-rows"></div>
      <button type="button" id="pb-add-scribal" class="button-tiny">Add another quirk</button>

      <label class="pb-checkbox"><input type="checkbox" name="surnameParticleRule" checked> Apply the standard Italian surname-particle rule (de/di/d'/lo/la/le/li stay with the surname, never normalized)</label>

      <label><span>Surnames{pb_info_button_html("pb-info-lexicon-surnames", "Adding a lexicon greatly increases the likelihood that the AI system will bias towards a correct identification of a name. Paste one surname per line. A multi-word surname (“De Amato”, “La Marca”) or an alias (“Bruno alias De Amato”) is a single entry -- keep it on one line exactly as written; it will not be split apart.")}</span>
        <textarea name="nameLexiconSurnames" rows="4" placeholder="Paste known surnames, one per line -- e.g. Esposito, De Amato, La Marca"></textarea>
      </label>

      <label><span>Given names{pb_info_button_html("pb-info-lexicon-givennames", "Paste one given name per line. A compound or alias given name (“Anna Maria”, “Giovanni Battista”, “Anna alias Nonna”) is a single entry -- keep it on one line exactly as written; it will not be split apart.")}</span>
        <textarea name="nameLexiconGivenNames" rows="4" placeholder="Paste known given names, one per line -- e.g. Giuseppe, Anna Maria, Giovanni Battista"></textarea>
      </label>

      <label><span>Alternatively: Full names (given name + surname pairs){pb_info_button_html("pb-info-lexicon-fullnames", "Use this box when what you have is full names rather than two separate lists -- one name per line, either “Given Surname” (Giuseppe de Natale) or “Surname, Given name” (de Natale, Giuseppe). Each line is split and added to the Surnames and Given names lists above it. A surname particle (de/di/d'/lo/la/le/li) right before the last word stays attached to the surname. A line with only one word is skipped rather than guessed at -- put a name like that in the Surnames or Given names box instead.")}</span>
        <textarea name="nameLexiconFullNames" rows="4" placeholder="Paste full names, one per line -- e.g. Giuseppe de Natale  or  de Natale, Giuseppe"></textarea>
      </label>

      <label><span>Additional editorial rules (optional){pb_info_button_html("pb-info-additional-rules", PB_ADDITIONAL_RULES_INFO_TEXT)}</span>
        <textarea name="additionalRules" rows="4" placeholder="e.g. Never copy a surname from one parent to the other, even when only one is stated."></textarea>
      </label>
    </details>

    <details class="pb-section">
      <summary>
        <span class="pb-summary-text">3. Output Format</span>
        <span class="pb-word-count" id="wc-output_format">0 words</span>
      </summary>
      <p class="pb-section-caption">{PROMPT_BUILDER_SECTION_HELP["output_format"]}</p>

      <div class="pb-example-entries">
        <span>Example entries{pb_info_button_html("pb-info-example-entries", "Each example is a verified, 100% accurate transcription of one real entry from this register, shown to the AI purely as a formatting and style reference -- never as content to copy. More than one example, especially covering different situations (a straightforward entry, one with an illegible word, one where a heading and body disagree), calibrates the AI's judgment better than a single example can. An optional label just helps you tell examples apart later -- e.g. in Preflight Test, if you add more than one.")}</span>
        <p class="hint">Paste in a completed 100% accurate entry in the native language of the sources for this project. This will be used as a critically important formatting reference for the AI to generate the proper output.</p>
        <div id="pb-example-rows">
          <div class="pb-row pb-example-row">
            <input type="text" class="pb-example-label" placeholder="Label (optional), e.g. Image 193 Entry 1">
            <label class="pb-example-part"><span>Date line</span>
              <input type="text" class="pb-example-date" placeholder="Date exactly as written, then the standard form in brackets -- e.g. due del mese di Gennaro milleottocentoventitre [2 January 1823]"></label>
            <label class="pb-example-part"><span>Main entry</span>
              <textarea class="pb-example-text" rows="5" placeholder="Paste a 100% accurate example entry text from your source material, exactly as it was transcribed -- no labels or headers."></textarea></label>
            <label class="pb-example-part pb-example-wedding-part" hidden><span>Church Wedding Record (if any)</span>
              <textarea class="pb-example-wedding" rows="3" placeholder="Paste the text of the right-hand church-wedding column, exactly as transcribed -- no labels or headers."></textarea></label>
            <label class="pb-example-part pb-example-baptism-part" hidden><span>Baptism Record (if any)</span>
              <textarea class="pb-example-baptism" rows="3" placeholder="Paste the text of the baptism column, exactly as transcribed -- no labels or headers."></textarea></label>
            <label class="pb-example-part"><span>Continuation (if any)</span>
              <textarea class="pb-example-continuation" rows="3" placeholder="If this entry runs onto the next image, paste the text that continues it at the top of that image, exactly as transcribed -- no labels or headers."></textarea></label>
            <button type="button" class="button-tiny pb-row-remove">Remove</button>
          </div>
        </div>
        <button type="button" id="pb-add-example" class="button-tiny">Add another example</button>
      </div>

      <div class="pb-preflight">
        <h3>Preflight Test <span class="pb-preflight-optional">(optional but recommended)</span></h3>
        <p class="hint">For testing your prompt, upload the image or PDF that corresponds to the selected Example entry text above. JPEG, PNG, and PDF are all supported -- detected automatically from the file itself, so its filename doesn't need to say which one it is. The app will check your example against its source and offer suggestions to improve your prompt, if needed. Clicking "Run Preflight Test" first saves your current answers as a draft profile, so nothing is lost if something goes wrong.</p>
        <div class="row">
          <label>Model
            <select id="pb-preflight-model">
              {preflight_model_options}
            </select>
          </label>
          <label>API key
            <input type="password" id="pb-preflight-api-key" autocomplete="off" placeholder="Paste your API key for this test">
            <p class="hint">Used only for this browser session/request. It is not saved to the project files or the profile. Running a preflight test sends this key and your uploaded file directly to your chosen AI provider's API — see PRIVACY.md.</p>
          </label>
        </div>
        {file_picker_html("pb-preflight-image", "image/jpeg,image/png,application/pdf")}
        <label id="pb-preflight-example-row" hidden>Which example does this image show?
          <select id="pb-preflight-example-select"></select>
        </label>
        <button type="button" id="pb-preflight-run" class="button-tiny">Run Preflight Test</button>
        <p class="hint" id="pb-preflight-status" role="status" aria-live="polite" hidden></p>
        <div id="pb-preflight-results" hidden>
          <p class="hint" id="pb-preflight-suggestions-label">Suggestions -- check the ones you want, then apply them to your questionnaire.</p>
          <div id="pb-preflight-suggestions"></div>
          <div class="pb-preflight-apply-row">
            <button type="button" id="pb-preflight-apply" class="button-tiny">Apply selected</button>
            <span id="pb-preflight-apply-status" class="hint" role="status" aria-live="polite"></span>
          </div>
          <details class="pb-preflight-raw-details">
            <summary>What the AI actually produced from your image</summary>
            <pre id="pb-preflight-raw-output" class="pb-preview"></pre>
          </details>
        </div>
      </div>

      <h3>Translation</h3>
      <p class="hint" id="pb-church-only-translation-hint">Translation is optional — leave both unchecked for a transcription-only output with no translation at all</p>
      <p class="hint" id="pb-civil-only-translation-hint" hidden>Translation is optional — leave unchecked for a transcription-only output with no translation.</p>
      <div class="pb-checklist pb-checklist-tight">
        <label class="pb-checkbox"><input type="checkbox" name="translateEnglish" value="English">English</label>
        <label class="pb-checkbox" id="pb-church-only-translateitalian"><input type="checkbox" name="translateItalian" value="Italian">Italian</label>
      </div>

      <div id="pb-translation-options-section">
        <p class="hint">Translation style options</p>
        <div class="pb-checklist pb-checklist-tight">
          <label class="pb-checkbox"><input type="checkbox" name="translateExpandAbbreviations" value="expand">Expand abbreviations</label>
          <label class="pb-checkbox"><input type="checkbox" name="translateConvertNames" value="convert">Convert names to ENG or IT equivalents</label>
        </div>
      </div>

      <div id="pb-honorifics-section">
        <p class="hint">Honorifics kept inside a role clause — everything else moves to Notes{pb_info_button_html("pb-info-honorifics", PB_HONORIFICS_INFO_TEXT)}</p>
        <div class="pb-checklist pb-checklist-tight">
          <label class="pb-checkbox"><input type="checkbox" name="honorifics" value="Don" checked>Don</label>
          <label class="pb-checkbox"><input type="checkbox" name="honorifics" value="Master" checked>Master</label>
        </div>
        <div id="pb-honorific-rows"></div>
        <button type="button" id="pb-add-honorific" class="button-tiny">Add another honorific</button>
      </div>

    </details>

    <details class="pb-section">
      <summary>
        <span class="pb-summary-text">Full prompt preview</span>
        <span class="pb-word-count">as sent to the model</span>
      </summary>
      <p class="pb-section-caption">Read-only. This is the three sections above assembled exactly the way the app builds the real system prompt — including the fixed rules and headers it adds automatically — so you can see what the AI actually receives.</p>
      <pre id="pb-preview-content"></pre>
    </details>

    <label id="pb-name-label">Save this as a new profile
      <input type="text" name="new_profile_name" value="{escaped_name}" placeholder="e.g. Caiazzo Battesimi 1780s" autocomplete="off" required>
      <p class="hint" id="pb-name-hint">Creates a new profile file; it never overwrites another profile.</p>
    </label>
    <div class="pb-save-actions">
      <button id="pb-update-button" type="submit" name="save_mode" value="update" hidden>Update Profile</button>
      <button id="pb-save-button" type="submit" name="save_mode" value="new">Save as New Profile</button>
    </div>
  </form>

  <details class="pb-section" id="pb-import-export-section">
    <summary>
      <span class="pb-summary-text">Import/Export Profiles</span>
    </summary>
    <p class="pb-section-caption">Share and install profiles. Profiles are plain text (JSON) and do not contain executable code or macros.</p>

    <div class="pb-ie-grid">
      <div class="pb-ie-box">
        <h3>Export a profile</h3>
        <select id="pb-export-select" aria-label="Profile to download">
          <option value="">Select a profile</option>
          {export_profile_options}
        </select>
        <button type="button" id="pb-export-button" class="button-tiny">Download profile file</button>
        <p class="hint" id="pb-export-status" role="status" aria-live="polite"></p>
      </div>

      <div class="pb-ie-box">
        <h3>Import a profile</h3>
        {file_picker_html("pb-import-file", ".json,application/json")}
        <p class="hint">Importing a profile never overwrites an existing profile.</p>
        <button type="button" id="pb-import-button" class="button-tiny">Import profile</button>
        <p class="hint" id="pb-import-status" role="status" aria-live="polite"></p>
      </div>
    </div>
  </details>

  {FOOTER_HTML}
</main>
</body>
</html>"""
