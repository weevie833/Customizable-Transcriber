/*
 * Prompt Builder questionnaire engine.
 *
 * The HTML (rendered server-side in app.py's prompt_builder_page(), from the
 * PROMPT_BUILDER_RECORD_TYPES Python dict) provides one static field group per
 * record type, each wrapped `<div class="pb-type-group" data-record-type="...">`.
 * This script never builds DOM for those groups -- it only shows/hides the one
 * matching the selected record type and reads whichever group is currently
 * selected when assembling text. A hidden group's field values are never read,
 * so switching record type can't leak stale answers into the generated prompt.
 *
 * Small, static, per-type metadata this script itself needs (a noun to plug
 * into boilerplate sentences, mainly) lives in RECORD_TYPES below -- this is
 * deliberately separate from the Python-side PROMPT_BUILDER_RECORD_TYPES dict,
 * which is much larger (it drives HTML generation) and never needs to reach
 * the client as data since its content is already baked into the rendered
 * page.
 */
(function () {
  "use strict";

  // Reads the per-request dynamic data prompt_builder_page() embeds as a
  // JSON data island (see json_data_island_html() in pages/__init__.py and
  // CODEX_REVIEW.md finding L-2 / HUMAN_DECISIONS.md) instead of an
  // executable inline <script> assigning these directly -- needed so this
  // file keeps working once CSP's script-src drops 'unsafe-inline'.
  // Assigned to the same window.PB_* names every reader below already
  // used, so nothing past this point needed to change.
  (function loadPromptBuilderInitialData() {
    var el = document.getElementById("prompt-builder-initial-data");
    var data = el ? JSON.parse(el.textContent) : {};
    window.PB_CORE_RULES = data.coreRules;
    window.PB_SAVED_PROFILES = data.savedProfiles;
    window.PB_RESTORE_ON_ERROR = data.restoreOnError;
    window.PB_RESTORE_EDIT_ID = data.restoreEditId;
    window.PB_RESTORE_EDIT_LABEL = data.restoreEditLabel;
  })();

  var RECORD_TYPES = {
    battesimi: { label: "Church Battesimi", nounSingular: "baptism", nounPlural: "baptisms", principal: "the baptized individual", locatorKind: "page", hasMarginalHeadingDefault: true },
    matrimoni: { label: "Church Matrimoni", nounSingular: "marriage", nounPlural: "marriages", principal: "the couple", locatorKind: "page", hasMarginalHeadingDefault: true },
    morti: { label: "Church Morti", nounSingular: "death", nounPlural: "deaths", principal: "the deceased", locatorKind: "page", hasMarginalHeadingDefault: true },
    // nounSingular/nounPlural for the 3 civil types deliberately use the
    // same Italian category words as their church counterparts' labels
    // ("Church Battesimi"/"Church Matrimoni"/"Church Morti") instead of the
    // plain English nouns church types still use below -- the user's own
    // choice, for terminology consistency across civil and church records.
    // Used as a fixed collective label (same as "Church Battesimi" is never
    // inflected either), so nounSingular and nounPlural are identical here.
    // label here is never actually read (checked: no callsite reads
    // RECORD_TYPES[key].label) -- the record type's displayed name comes
    // from PROMPT_BUILDER_RECORD_TYPES's own "label" (prompt_builder_content.py),
    // rendered server-side. Kept in sync anyway so this dict doesn't show a
    // stale name to the next person reading it.
    civil_birth: { label: "Civil Nati", nounSingular: "Battesimi", nounPlural: "Battesimi", principal: "the child", locatorKind: "act", hasMarginalHeadingDefault: false },
    civil_marriage: { label: "Civil Matrimoni", nounSingular: "Matrimoni", nounPlural: "Matrimoni", principal: "the couple", locatorKind: "act", hasMarginalHeadingDefault: false },
    civil_death: { label: "Civil Morti", nounSingular: "Morti", nounPlural: "Morti", principal: "the deceased", locatorKind: "act", hasMarginalHeadingDefault: false },
  };

  var LATIN_DECLENSION_BLOCK = [
    "# LATIN NAME DECLENSION",
    "",
    "Latin does not mark a word's grammatical role with word order or with a preposition alone, the way English and Italian do. It marks role by changing the word's ending -- and personal names decline exactly like any other noun. The same person's name can therefore take more than one written form within a single entry, and that is correct grammar, not a scribal inconsistency, not a misreading, and not something to correct or flag.",
    "",
    "The cases you will meet in this register, using `Franciscus` and `Michael` as examples:",
    "",
    "- Nominative -- the dictionary form, used as a sentence's subject: `Franciscus`, `Michael`.",
    "- Genitive -- possession, \"of X\": `Francisci`, `Michaelis`.",
    "- Ablative -- origin, \"from/by X,\" the case that follows `ex`: `Francisco`, `Michaele`.",
    "- Accusative -- the direct object of a verb: `Franciscum`, `Michaelem`. The final `-m` is frequently written as a macron or tilde over the preceding vowel rather than spelled out.",
    "",
    "So `Franciscus`, `Francisci`, `Francisco`, and `Franciscum` are four grammatical forms of one name, not four people and not four spellings to reconcile. Seeing two different case-forms of the same name at two different points in one entry is expected, not an error.",
    "",
    "Transcribe each occurrence exactly as it is inflected on the page; never normalize a genitive or ablative form to the nominative within the transcription itself. That normalization happens only once, in the translation.",
    "",
    "A related pitfall, worth its own check: `filius` (\"son of\") and `filia` (\"daughter of\") differ by a single letter, and are a frequently misread pair. Because the fidelity rules above normalize a name's ending to agree with whichever gendered word was read, misreading one silently regenders that person's given names everywhere they appear in the transcription and translation, not just at the point of the error. Whenever `filius`/`filia` (or an equivalent inflected form) identifies a person by their parentage, check that reading against the person's own given-name endings (masculine `-us`/`-ius`, feminine `-a`) and against any other gendered form of the same word elsewhere in the entry (for example `natum`/`natam`, \"born,\" when the entry uses it), rather than assuming the first occurrence you read is correct. If the readings conflict, flag it on the Notes line and mark confidence low rather than silently picking one.",
  ].join("\n");

  function fidelityRulesBlock(langs) {
    var hasTranslation = langs.length > 0;
    var translationWord = langs.length > 1 ? "translations" : "translation";
    var lines = [
      "# FIDELITY RULES",
      "",
      "- Transcribe exactly what is on the page. Preserve archaic and non-standard spelling, inconsistent capitalization, and scribal error. Do not silently correct the scribe.",
    ];
    // Narrow columns and margin notes break words across lines with a trailing
    // hyphen. A real Napoli marriage run rejoined them in two acts but kept
    // "ottocen- toventitre" (hyphen plus a space) in a third.
    lines.push("- When a word is split across two lines by a hyphen at the end of a line, rejoin it as one word with no hyphen and no space (`ottocen-` at the end of one line and `toventitre` at the start of the next is written `ottocentoventitre`). Only a hyphen that falls at a line break is removed this way; a hyphen inside a word within a line is part of the text and stays.");
    if (hasTranslation) {
      lines.push("- Preserve abbreviations exactly as written in the transcription. Do NOT insert bracketed expansions into the transcription itself. Expand them only in the " + translationWord + ".");
      lines.push("- Retain source-language name forms in the " + translationWord + " too -- do not anglicize, modernize, or translate a personal name to an English or Italian equivalent.");
    } else {
      lines.push("- Preserve abbreviations exactly as written. Do not expand them.");
    }
    lines.push("- Write abbreviations using standard inline characters, not Unicode superscript characters, even when the source clearly raises a letter above the line (write `M.s`, `p.nti`, `R.di`, not `M.ˢ`, `p.ⁿᵗⁱ`, `R.ᵈⁱ`). This is a rule about how to encode the character, not a fidelity concession -- the abbreviation itself is still transcribed exactly as written, letter for letter.");
    lines.push("- Surname particles (`de`, `di`, `d'`, `lo`, `la`, `le`, `li`) are part of the surname and must be transcribed exactly as written. If the particle itself is unclear, mark it uncertain rather than choosing the more common form.");
    if (hasTranslation) {
      lines.push("- A name must be identical in the transcription and in the " + translationWord + ", apart from any necessary change of grammatical case ending.");
    }
    lines.push("- Do not summarize, comment, or add editorial content outside the Notes block defined in the output format.");
    return lines.join("\n");
  }

  var UNCERTAINTY_PROTOCOL_BLOCK = [
    "# UNCERTAINTY PROTOCOL",
    "",
    "This is the most important instruction in this prompt.",
    "",
    "An honest `[illegible]` is always more valuable than a plausible guess. These transcriptions are used for genealogical research, where a confident wrong reading is far more damaging than an acknowledged gap, because nothing downstream will ever catch it.",
    "",
    "- Wholly unreadable word: `[illegible]`",
    "- Partly readable: bracket the uncertain letters -- `Pu[?]io`, `Bre[??]no`",
    "- Torn, faded, or obscured page: `[damaged]`",
    "- Blank left by the scribe: `[blank]`",
    "",
    "Never complete a name from context, from the surrounding entries, or from the reference material. Never infer a name you cannot see.",
  ].join("\n");

  // ---- Name-lexicon ingestion (see the Section 2 "Surnames" / "Given
  // names" / "Full names" fields) ----
  //
  // Earlier version of this was a single textarea that accepted full "Given
  // Surname" names and split every line into a given-name half and a
  // surname half with a particle-aware heuristic (last token is the
  // surname, unless the token before it is a particle like "de"/"la"/"lo").
  // That heuristic silently corrupted the far more common real input shape:
  // a genealogical index (like this app's own profiles/lex.json) is
  // normally already compiled as two SEPARATE lists -- surnames only and
  // given names only -- not full-name pairs. Fed one of those lists, the
  // old splitter did real damage: a plain single-word surname ("Esposito")
  // has no second token, so it was misclassified whole as a GIVEN name; a
  // multi-word surname or alias ("De Amato", "Bruno alias De Amato") had
  // its last word torn off as a fabricated "surname" while the rest leaked
  // into given names; and the same happened in reverse to compound/alias
  // given names ("Anna Maria", "Anna alias Nonna") pasted into that list.
  //
  // There is no way to tell those two input shapes apart automatically --
  // "Anna Maria" (one compound given name) and "Giuseppe Rossi" (a
  // given+surname pair) are both just two space-separated tokens with no
  // particle. Guessing wrong is exactly what broke the surname/given-name
  // split before, so the fix is to stop guessing and let the user say which
  // shape their paste is, via which box they use:
  //
  // - "Surnames" / "Given names": already-separated lists. No splitting --
  //   each line (or comma/middle-dot separated entry within a line) is kept
  //   whole exactly as written, correct for both a single-word entry and a
  //   multi-word one.
  // - "Full names": genuine given+surname pairs, one per line, in either
  //   "Given Surname" or "Surname, Given name" form. Only this field runs
  //   the particle-aware split (splitFullNamePair below), and its results
  //   are merged into the same surname/given-name lists the other two boxes
  //   feed.
  function parseNameList(raw) {
    var out = [];
    if (!raw) return out;
    raw.split(/[\n,·]/).forEach(function (piece) {
      var name = piece.trim();
      if (name && out.indexOf(name) === -1) out.push(name);
    });
    return out;
  }

  // Same particle list used throughout the app (see ai_parser.py's
  // GENERAL_EXTRACTION_RULES) -- kept consistent so "what counts as part of
  // a surname" means the same thing everywhere.
  var SURNAME_PARTICLES = ["da", "dal", "de", "del", "della", "di", "d'", "la", "le", "li", "lo"];

  // Splits ONE "Given Surname" or "Surname, Given name" pair. A comma is
  // treated as the unambiguous "Surname, Given" separator (matching how
  // e.g. profiles/grimaldi-church-morti-v2.json's own lexicon is written);
  // without a comma, the last token is the surname, except a particle
  // ("de", "la", "lo"...) immediately before it stays attached ("Giuseppe
  // de Natale" -> given "Giuseppe", surname "de Natale"). A line with only
  // one token isn't a pair at all -- skipped rather than guessed, since a
  // wrong guess here is the exact failure mode this field exists to avoid;
  // a stray single-word entry belongs in the Surnames or Given names box
  // instead.
  function splitFullNamePair(line) {
    line = line.trim();
    if (!line) return null;
    if (line.indexOf(",") !== -1) {
      var parts = line.split(",");
      var given = parts.slice(1).join(",").trim();
      var surname = parts[0].trim();
      if (!given || !surname) return null;
      return { given: given, surname: surname };
    }
    var tokens = line.split(/\s+/).filter(Boolean);
    if (tokens.length < 2) return null;
    var last = tokens[tokens.length - 1];
    var secondLast = tokens.length >= 3 ? tokens[tokens.length - 2] : null;
    if (secondLast && SURNAME_PARTICLES.indexOf(secondLast.toLowerCase()) !== -1) {
      return { given: tokens.slice(0, -2).join(" "), surname: tokens.slice(-2).join(" ") };
    }
    return { given: tokens.slice(0, -1).join(" "), surname: last };
  }

  function pbVal(name) {
    var el = document.querySelector('[name="' + name + '"]');
    return el ? (el.value || "").trim() : "";
  }

  // pbVal() above is wrong for a radio group: querySelector() returns only the
  // first element sharing that name, so it would always report that button's
  // own static value regardless of which one the user actually picked. This
  // reads the one currently :checked instead (see e.g. the Page format radios
  // in pb_civil_fields_html()).
  function pbRadioVal(name) {
    var checked = document.querySelector('[name="' + name + '"]:checked');
    return checked ? checked.value : "";
  }

  function pbChecked(name) {
    var out = [];
    document.querySelectorAll('[name="' + name + '"]:checked').forEach(function (el) {
      out.push(el.value);
    });
    return out;
  }

  function pbSimpleValues(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return [];
    var out = [];
    container.querySelectorAll(".pb-simple-value").forEach(function (field) {
      var value = field.value.trim();
      if (value) out.push(value);
    });
    return out;
  }

  // Reads every Example entry row as {label, text}, skipping rows with no
  // text (a label alone isn't a usable example). Shared by buildOutputFormat()
  // (which feeds every example into the real system prompt) and Preflight
  // Test's example picker (runPreflightTest()/wirePreflightTest()), so both
  // always agree on what "the examples" are.
  // Each row is a main entry plus two optional parts: the Church Wedding
  // Record column (civil_marriage with that checkbox on -- read as empty
  // otherwise, same leak-proofing as the other per-type fields) and the
  // Continuation that picks up at the top of the next image.
  function churchWeddingColumnActive() {
    if (selectedRecordType() !== "civil_marriage") return false;
    var box = document.querySelector('[name="' + typeField("hasChurchWeddingColumn") + '"]');
    return !!(box && box.checked);
  }

  // Same idea for Civil Nati's Baptism Record column.
  function baptismColumnActive() {
    if (selectedRecordType() !== "civil_birth") return false;
    var box = document.querySelector('[name="' + typeField("hasBaptismColumn") + '"]');
    return !!(box && box.checked);
  }

  // The baptism part is the last class name so a row saved before it existed
  // (four values) still loads into the right fields.
  function pbExampleEntries() {
    var weddingActive = churchWeddingColumnActive();
    var baptismActive = baptismColumnActive();
    return pbRows("pb-example-rows", ["pb-example-label", "pb-example-text", "pb-example-wedding", "pb-example-continuation", "pb-example-baptism"])
      .map(function (row) {
        return { label: row[0], text: row[1], wedding: weddingActive ? row[2] : "", continuation: row[3], baptism: baptismActive ? row[4] : "" };
      })
      .filter(function (example) { return example.text; });
  }

  // One example as it appears in the system prompt. A plain entry is just its
  // text; with either optional part the parts are labelled, so the model can
  // tell the act from the separate column and from the next image's opening.
  function exampleAsPromptText(example) {
    if (!example.wedding && !example.baptism && !example.continuation) return example.text;
    var out = "Main entry:\n\n" + example.text;
    if (example.wedding) out += "\n\nChurch Wedding Record:\n\n" + example.wedding;
    if (example.baptism) out += "\n\nBaptism Record:\n\n" + example.baptism;
    if (example.continuation) {
      out += "\n\nContinuation (this is the opening of the NEXT image: it picks up mid-sentence, carries the note \"Entry appears to continue from the previous image.\", and has no Date block of its own):\n\n" + example.continuation;
    }
    return out;
  }

  function exampleFormatNotes(examples) {
    var notes = [];
    if (examples.some(function (e) { return e.wedding; })) {
      notes.push("Where an example shows a Church Wedding Record, that is the text of the separate right-hand column: in your own output it goes in its own `Church Wedding Record:` block, never inside the entry's text.");
    }
    if (examples.some(function (e) { return e.baptism; })) {
      notes.push("Where an example shows a Baptism Record, that is the text of the separate baptism column: in your own output it goes in its own `Baptism Record:` block, never inside the entry's text.");
    }
    if (examples.some(function (e) { return e.continuation; })) {
      notes.push("Where an example shows a Continuation, the main entry breaks off at the bottom of its image and the continuation is what you will meet at the top of the next image; transcribe such a fragment exactly as shown, with no invented opening.");
    }
    return notes.length ? "\n\n" + notes.join(" ") : "";
  }

  function pbRows(containerId, classNames) {
    var container = document.getElementById(containerId);
    if (!container) return [];
    var rows = [];
    container.querySelectorAll(".pb-row").forEach(function (rowEl) {
      var row = {};
      var complete = false;
      classNames.forEach(function (className, index) {
        var field = rowEl.querySelector("." + className);
        var value = field ? field.value.trim() : "";
        row[index] = value;
        if (value) complete = true;
      });
      if (complete) rows.push(row);
    });
    return rows;
  }

  function selectedRecordType() {
    var el = document.querySelector('[name="recordType"]');
    return el ? el.value : "battesimi";
  }

  function typeField(suffix) {
    return selectedRecordType() + "_" + suffix;
  }

  function typeMeta() {
    return RECORD_TYPES[selectedRecordType()] || RECORD_TYPES.battesimi;
  }

  function translationLanguages() {
    var langs = [];
    var en = document.querySelector('[name="translateEnglish"]');
    var it = document.querySelector('[name="translateItalian"]');
    if (en && en.checked) langs.push("English");
    if (it && it.checked) langs.push("Italian");
    return langs;
  }

  // ---- Section 1: Role & Local Context ----

  function buildRoleContext() {
    var meta = typeMeta();
    var isCivil = selectedRecordType().indexOf("civil_") === 0;
    var language = pbVal("language") || "the source language";
    // Era, Institution name, and Hand/script descriptor are hidden for civil
    // types (see updateRecordTypeVisibility()) -- read as empty here too, not
    // just visually hidden, so a value left over from a church-type profile
    // (or typed before switching record type) can't silently leak into a
    // civil prompt.
    var era = isCivil ? "" : pbVal("era");
    var locality = pbVal("locality");
    var province = pbVal("province");
    var institution = isCivil ? "" : pbVal("institution");
    var volumeRange = pbVal("volumeRange");
    var handDescriptor = isCivil ? "" : pbVal("handDescriptor");
    var pageLayout = pbVal("pageLayout");
    var pageLayoutOther = pbVal("pageLayoutOther");
    // Page-numbering scheme is hidden for civil types too -- civil acts are
    // always located by "Act <act number>:" (see RECORD_TYPES' locatorKind
    // above), never by page number, so this field has no effect on them.
    var pageNumberScheme = isCivil ? "" : pbVal("pageNumberScheme");
    var pageNumberCorner = pbVal("pageNumberCorner");
    var monthConvention = pbVal("monthConvention");
    var monthConventionOther = pbVal("monthConventionOther");
    var hourConvention = pbVal("hourConvention");
    var relativeDateTerms = pbChecked("relativeDateTerms").concat(pbSimpleValues("pb-relativedate-rows"));
    var latinDeclension = document.querySelector('[name="latinDeclension"]');
    var includeDeclension = latinDeclension ? latinDeclension.checked : false;
    var langs = translationLanguages();

    var parts = [];

    var opening = "You are an expert paleographer and historian";
    if (era || locality) {
      opening += " specializing in" + (era ? " " + era : "") + (locality ? " " + language + " records from " + locality : "");
    }
    opening += (province ? ", " + province : "") + ". You read the source handwriting fluently and transcribe word for word.";
    parts.push(opening);

    var translationClause = "";
    if (langs.length === 1) translationClause = " plus an " + langs[0] + " translation";
    else if (langs.length === 2) translationClause = " plus " + langs.join(" and ") + " translations";
    var task = "Your task: read images of handwritten " + meta.nounSingular + " records" +
      (institution ? " from " + institution : "") +
      " and convert each entry into a verbatim " + language + " transcription" + translationClause + ", in the structured format defined in the output format section.";
    parts.push(task);

    if (volumeRange) {
      parts.push("This volume covers " + volumeRange + ". If an entry's year is unclear or absent, infer it from adjacent entries and record how you inferred it.");
    }

    if (handDescriptor) {
      parts.push("Handwriting note: " + handDescriptor);
    }

    var layoutLines = ["# PAGE LAYOUT", ""];
    if (pageLayout === "two_facing") {
      layoutLines.push("Each image shows two facing pages. Read the LEFT page top to bottom first, then the RIGHT page.");
    } else if (pageLayout === "one_page") {
      layoutLines.push("Each image shows one page of the register.");
    } else if (pageLayout === "other" && pageLayoutOther) {
      // "Other" with nothing typed contributes no line at all -- this used to
      // push the raw select value, so the generated prompt literally said
      // "other".
      layoutLines.push(pageLayoutOther);
    }
    // Only meaningful for two facing pages -- the checkbox is hidden for any
    // other layout (see updateOtherFieldVisibility()), and ignored here too so
    // a stale checked box can't leak into a one-page-per-image prompt.
    var spansImagesBox = document.querySelector('[name="entriesSpanFacingImages"]');
    if (pageLayout === "two_facing" && spansImagesBox && spansImagesBox.checked) {
      layoutLines.push(
        "In this register an entry usually begins on the RIGHT page of an image and finishes on the LEFT page of the NEXT image. " +
        "The text at the top of a left page is therefore normally the end of the previous image's last entry -- its closing paragraph, witness names, or signatures -- not a new entry: " +
        "treat it as a continuation and add the note \"Entry appears to continue from the previous image.\" " +
        "Only text that opens with its own beginning (an act or entry number, a printed heading, an opening date) starts a new entry. " +
        "A left page is the reverse side of the leaf shown on the previous image's right page, so faint ink from that other side may show through the paper: ignore it, and never transcribe show-through text as an entry."
      );
    }
    if (pageNumberScheme === "none") {
      layoutLines.push("This register has no visible page numbers.");
    } else if (pageNumberScheme === "one_per_image") {
      layoutLines.push("Each image carries one page number.");
    } else if (pageNumberScheme === "two_per_image") {
      layoutLines.push(
        "Each image depicts two facing pages, and each page carries its own page number" +
        (pageNumberCorner ? " in " + pageNumberCorner : "") +
        ". These two numbers are independent of the image filename -- locate both before transcribing. If a page number is faded, cropped, or otherwise unreadable, write `[illegible]` for that entry's page number rather than guessing it."
      );
    } else if (pageNumberScheme === "native_acts") {
      layoutLines.push("This register has its own act/entry numbers printed or written on the page -- transcribe those rather than inventing a page-based locator.");
    }
    if (layoutLines.length > 2) parts.push(layoutLines.join("\n"));

    parts.push(
      "Before you output anything, count the distinct " + meta.nounSingular + " entries actually visible on the page -- your entry count must equal that count: never more, never fewer. Do not add an entry unless you can point to its own text on the page you were given; never generate one from the formula, from a nearby date, or from pattern-completion. A fabricated entry is worse than a skipped one -- a skipped entry leaves a detectable gap, but a fabricated one reads exactly like a real record and will be trusted as one by every downstream user."
    );

    // Unconditional for all 6 record types -- not gated behind a checkbox.
    // Used to be a civil-only opt-in, then briefly an opt-in for every type;
    // promoted to always-on (same tier as the anti-hallucination entry-count
    // check just above and the fidelity rules below -- no profile has a
    // legitimate reason to want the model inventing a plausible ending
    // instead of flagging a genuine cutoff) after a real Church Morti
    // transcript showed the failure mode with the instruction absent
    // entirely. The instruction itself only ever fires when the model
    // perceives an actual cutoff, so it costs nothing on a register where
    // entries never span images.
    parts.push(
      "An entry in this register can continue onto a following page image. If the visible portion of an entry looks incomplete -- cut off mid-sentence, no closing signature or date -- do not treat that as an error and do not invent a plausible ending. Transcribe exactly what is visible and add a note in the Notes block: \"Entry appears to continue on the next image.\" " +
      "The reverse can also happen: if this image's content appears to pick up mid-record -- no opening date or officiant clause, starting straight into witness names or a closing signature block -- transcribe it under the SAME locator/entry number as the record it continues, not as a new entry, and add a note: \"Entry appears to continue from the previous image.\" Do not attempt to reconstruct the missing opening; transcribe only what is visible. Both notes use this exact wording so the downstream XLS Conversion step can recognize and link the split record automatically -- do not paraphrase them."
    );

    if (isCivil) {
      var civilPageFormat = pbRadioVal(typeField("pageFormat"));
      if (civilPageFormat === "printed_form") {
        parts.push(
          "This register is a printed form with handwritten entries filled in. Expect two visually distinct scripts on the same page: the fixed printed boilerplate, and the clerk's handwriting in the blanks. Transcribe both, but weigh accuracy toward the handwritten fill-in content -- that is where the names, dates, and facts that matter for indexing are recorded; the printed boilerplate repeats unchanged throughout the register."
        );
      }
      // A signer who could not write is marked with a cross rather than a
      // signature, usually paired with a clerk's note that they "do not know
      // how to write" (non sa/sanno scrivere). The mark itself is part of the
      // document -- reproduce it, don't paraphrase it away.
      parts.push(
        "If a signer's line is marked with a cross (\"+\") because they could not write, transcribe the \"+\" literally as part of that line, exactly as the clerk wrote it, rather than describing it in prose."
      );
      if (selectedRecordType() === "civil_birth") {
        var hasBaptismColumn = document.querySelector('[name="' + typeField("hasBaptismColumn") + '"]');
        if (hasBaptismColumn && hasBaptismColumn.checked) {
          // Confirmed against a real 1843 register: a genuine two-column
          // printed form, birth act on the left, a separately headed
          // "Indicazione del giorno in cui è stato amministrato il
          // Sacramento del Battesimo" column on the right, same act number
          // as the main act. Real content, not just a date -- typically the
          // parish returning a slip and the civil officiant filing it.
          parts.push(
            "This register prints a two-column form: the birth act on the left, and a separately headed column on the right recording when the church administered baptism, sharing the same act number as the main act. Transcribe the right column's content as its own \"Baptism Record\" block, kept fully separate from the main act -- do not fold it into the main act's running text."
          );
        } else {
          // Confirmed against real 1817/1813 examples: a note about the child's
          // church baptism, when present at all, is not a separate physical
          // column -- it's either folded into the same paragraph as the rest of
          // the act, or written in the margin.
          parts.push(
            "This birth act may include a note about the child's church baptism. If that note appears as part of the main paragraph, transcribe it as continuous running text along with the rest of the entry -- do not break it into a separate block. If instead it is written in the margin, prefix that portion with `[marginal]` before transcribing it, still inline within the same running text."
          );
        }
      }
      if (selectedRecordType() === "civil_marriage") {
        // Confirmed twice independently against a real 1816 register (two
        // separate acts, two different parishes): "Sposati dal Parroco della
        // Parrocchia di ... come dall'attestato inserito negli atti" appears
        // near the closing/signatures, as running text -- not a separate
        // column. Same inline-vs-margin handling as the birth act's baptism
        // note above.
        var hasChurchWeddingColumn = document.querySelector('[name="' + typeField("hasChurchWeddingColumn") + '"]');
        if (hasChurchWeddingColumn && hasChurchWeddingColumn.checked) {
          // Confirmed against a real 1823 Napoli register: a printed two-
          // column form, the marriage promise on the left and a right-hand
          // column in which the parish confirms the church ceremony. Handled
          // inline via `[marginal]` (the unchecked branch below), the column
          // got spliced into the middle of the act's body wherever the page
          // broke off -- the body's real continuation was on the next image.
          parts.push(
            "This register prints a two-column form: the marriage promise on the left, and a separately headed column on the right in which the parish priest confirms that the church wedding took place (the parish, the date, the witnesses to that ceremony, and the civil officer's filing note). Transcribe the right column's content as its own \"Church Wedding Record\" block, kept fully separate from the main act -- never insert it into the act's running text, even where the act's text breaks off at the bottom of the page and the column continues beside it. The witnesses named in this column attended the church wedding; they are not additional witnesses to the marriage promise recorded in the act itself."
          );
        } else {
          parts.push(
            "This marriage act may include a note about the church wedding that finalized it (officiant, parish, date). If that note appears as part of the running text, transcribe it as continuous running text along with the rest of the entry -- do not break it into a separate block. If instead it is written in the margin, prefix that portion with `[marginal]` before transcribing it, still inline within the same running text."
          );
        }
      }
    }

    var calendarLines = [];
    if (monthConvention === "latin_march") {
      calendarLines.push(
        "# CALENDAR AND TIME CONVENTIONS",
        "",
        "These abbreviations count months from March and are a frequent source of error:",
        "",
        "    7bris  = September      9bris        = November",
        "    8bris  = October        10bris/Xbris = December",
        "",
        "`ejusdem` (\"of the same\") means the month named in the most recent preceding entry. Resolve it and record the resolved date."
      );
    } else if (monthConvention === "other" && monthConventionOther) {
      calendarLines.push("# CALENDAR AND TIME CONVENTIONS", "", monthConventionOther);
    }
    if (hourConvention === "italian_hours") {
      calendarLines.push(
        (calendarLines.length ? "" : "# CALENDAR AND TIME CONVENTIONS\n"),
        "Hours are Italian hours (ore italiane), counted from sunset, not modern clock time. Translate the hour number literally and do not convert it to a modern time."
      );
    }
    if (relativeDateTerms.length) {
      calendarLines.push((calendarLines.length ? "" : "# CALENDAR AND TIME CONVENTIONS\n"), "Relative-date vocabulary: " + relativeDateTerms.join("; ") + ".");
    }
    if (calendarLines.length) parts.push(calendarLines.filter(Boolean).join("\n"));

    if (includeDeclension) parts.push(LATIN_DECLENSION_BLOCK);

    parts.push(fidelityRulesBlock(langs));
    parts.push(UNCERTAINTY_PROTOCOL_BLOCK);

    return parts.join("\n\n");
  }

  // ---- Section 2: Reference Material ----

  function buildReferenceContext() {
    var parts = [];

    var formulaLines = ["# THE STANDARD ENTRY FORMULA", ""];
    var hasMarginal = document.querySelector('[name="' + typeField("hasMarginalHeading") + '"]');
    if (hasMarginal && hasMarginal.checked) {
      var marginalFormula = pbVal(typeField("formula_marginalHeading"));
      if (marginalFormula) formulaLines.push("Marginal heading formula:\n\n    " + marginalFormula, "");
    }
    ["formula_body", "formula_groom", "formula_bride", "formula_witness", "formula_act"].forEach(function (key) {
      var value = pbVal(typeField(key));
      if (value) formulaLines.push(value, "");
    });
    if (churchWeddingColumnActive()) {
      var churchWeddingFormula = pbVal(typeField("formula_churchWedding"));
      if (churchWeddingFormula) formulaLines.push("Church Wedding Record formula (the separate right-hand column):\n\n    " + churchWeddingFormula, "");
    }
    if (baptismColumnActive()) {
      var baptismFormula = pbVal(typeField("formula_baptism"));
      if (baptismFormula) formulaLines.push("Baptism Record formula (the separate baptism column):\n\n    " + baptismFormula, "");
    }
    var roleVocab = pbChecked(typeField("roleVocab")).concat(pbSimpleValues(selectedRecordType() + "-rolevocab-rows"));
    if (roleVocab.length) {
      formulaLines.push("Role-clause vocabulary: " + roleVocab.join(" · "), "");
    }
    var relationshipTerms = pbChecked("relationshipTerms").concat(pbSimpleValues("pb-relationship-rows"));
    if (relationshipTerms.length) {
      formulaLines.push("Relationship-note vocabulary: " + relationshipTerms.join(" · "), "");
    }
    var variants = pbRows("pb-variant-rows", ["pb-variant-name", "pb-variant-markers"]);
    if (variants.length) {
      formulaLines.push("Entry variants to classify:");
      variants.forEach(function (row) {
        formulaLines.push("- " + row[0] + (row[1] ? " -- markers: " + row[1] : ""));
      });
      formulaLines.push("");
    }
    if (formulaLines.length > 2) parts.push(formulaLines.join("\n").trim());

    var abbrevRows = [];
    pbChecked("commonAbbrev").forEach(function (encoded) {
      abbrevRows.push(encoded.split("|"));
    });
    pbRows("pb-abbrev-rows", ["pb-abbrev-written", "pb-abbrev-expansion", "pb-abbrev-meaning"]).forEach(function (row) {
      abbrevRows.push([row[0], row[1], row[2]]);
    });
    if (abbrevRows.length) {
      var abbrevLines = ["# ABBREVIATION KEY", "", "| Written | Expansion | Meaning |", "|---|---|---|"];
      abbrevRows.forEach(function (row) {
        abbrevLines.push("| `" + row[0] + "` | " + (row[1] || "") + " | " + (row[2] || "") + " |");
      });
      parts.push(abbrevLines.join("\n"));
    }

    var scribalQuirks = pbChecked("scribalQuirks").concat(pbSimpleValues("pb-scribal-rows"));
    if (scribalQuirks.length) {
      parts.push("Scribal habits in this hand: " + scribalQuirks.join("; ") + ". Weigh these before concluding a name is unfamiliar.");
    }

    var surnameParticle = document.querySelector('[name="surnameParticleRule"]');
    if (surnameParticle && surnameParticle.checked) {
      parts.push(
        "Surname particles (`de`, `di`, `d'`, `lo`, `la`, `le`, `li`) are part of the surname. Transcribe the particle exactly as written and never normalize one form to another, even where both forms are attested for what looks like the same family."
      );
    }

    var surnames = parseNameList(pbVal("nameLexiconSurnames"));
    var givenNames = parseNameList(pbVal("nameLexiconGivenNames"));
    pbVal("nameLexiconFullNames").split("\n").forEach(function (line) {
      var parsed = splitFullNamePair(line);
      if (!parsed) return;
      if (parsed.given && givenNames.indexOf(parsed.given) === -1) givenNames.push(parsed.given);
      if (parsed.surname && surnames.indexOf(parsed.surname) === -1) surnames.push(parsed.surname);
    });
    if (surnames.length || givenNames.length) {
      var lexiconBody = "Surnames:\n" + surnames.join(" · ") + "\n\nGiven names:\n" + givenNames.join(" · ");
      var lexiconLines = [
        "# ATTESTED NAME LEXICON",
        "",
        "The list below comes from names known to be associated with this source. It is NOT a closed set.",
        "",
        "RULES FOR USING THIS LEXICON:",
        "1. Never substitute a listed name unless the letterforms on the page independently support that reading. The lexicon breaks ties; it does not overrule your eyes.",
        "2. If your reading is not in the lexicon, keep your reading. Do not snap it to the nearest listed name.",
        "3. Surnames and given names below are listed separately and are NOT paired combinations -- a given name does not imply any particular surname just because both appeared in the same source line. Use each independently to break ties.",
      ];
      lexiconLines.push("", lexiconBody);
      var language = pbVal("language");
      if (language.toLowerCase().indexOf("latin") !== -1) {
        lexiconLines.push(
          "",
          "This list may mix Latin and vernacular forms of the same names. The scribe wrote " + language + " -- transcribe the form that is actually on the page; treat any other-language form above as evidence the family existed, not as a model for how to render the name."
        );
      }
      parts.push(lexiconLines.join("\n"));
    }

    // Catch-all for a register-specific judgment call that doesn't fit any
    // preset question above (e.g. "never copy a surname between parents",
    // or when a heading/body disagreement is expected grammar rather than an
    // error to flag) -- see the field's own info-button text in app.py.
    var additionalRules = pbVal("additionalRules");
    if (additionalRules) {
      parts.push("# ADDITIONAL EDITORIAL RULES\n\n" + additionalRules);
    }

    return parts.join("\n\n");
  }

  // ---- Section 3: Output Format ----

  // No "- Entry <n>" suffix here: this locator's only job is to say WHICH
  // PAGE (or act) an entry is on. An entry's own number -- when the source
  // actually has one -- belongs solely in the Marginal Heading block, right
  // before the name it labels (see the "Entry N -" core rule in
  // neutral_system_scaffold()/PROMPT_BUILDER_CORE_RULES). Putting a second,
  // synthetic per-image counter here too just duplicated that number (or
  // worse, showed a different one), which is confusing in the DOCX and is
  // never read by any downstream code -- ai_parser.py groups records by
  // image number and lets the model find entry boundaries in the text
  // itself; it never parses this line for an entry count. The "no page
  // numbers" scheme is the one exception: with no page number to fall back
  // on, a bare per-image ordinal is the only thing left to mark where one
  // entry ends and the next begins.
  function locatorPreviewText() {
    var scheme = pbVal("pageNumberScheme");
    var meta = typeMeta();
    if (meta.locatorKind === "act" || scheme === "native_acts") {
      return "Act <act number>:";
    }
    if (scheme === "none") {
      return "Entry <n>:";
    }
    return "Page <page number>:";
  }

  // Only used for the block-structure labels below, and only once Italian is
  // one of the selected translation languages -- see buildOutputFormat().
  // Falls back to the English name for anything not in this list (e.g. a
  // future language option) rather than producing an empty label.
  var ITALIAN_LANGUAGE_NAMES = {
    "Latin": "Latino",
    "Italian": "Italiano",
    "English": "Inglese",
    "Latin and Italian mixed": "Latino e Italiano misti",
    "Other": "Altro",
  };

  function italianLanguageName(name) {
    return ITALIAN_LANGUAGE_NAMES[name] || name;
  }

  function buildOutputFormat() {
    var parts = [];
    var langs = translationLanguages();
    var language = pbVal("language") || "Source";
    // Once Italian is selected as a translation, every block header that
    // names a language switches to Italian phrasing -- "Trascrizione in
    // Latino:" instead of "Latin Transcription:", "Traduzione in Inglese:"
    // instead of "English Translation:" -- so the labels an Italian-speaking
    // indexer reads in the DOCX read as Italian throughout, not a mix. This
    // only touches labels that name a language; Date/Notes/Marginal Heading
    // are untouched.
    var useItalianLabels = langs.indexOf("Italian") !== -1;

    var outputDescription = langs.length
      ? "Your output is read by downstream tooling that turns it into a Word document and, separately, a spreadsheet. Exact labels and phrasing matter -- deviating from them does not merely change the styling, it can silently produce empty spreadsheet cells."
      : "Your output is read by downstream tooling that turns it into a Word document. Exact labels matter -- deviating from them does not merely change the styling, it can break how the document is built. No translation is requested for this profile: transcription only.";
    parts.push(
      outputDescription + "\n\n" +
      "Output plain text only. No JSON, no markdown code fences, no bullet lists, no headings, no preamble, no closing commentary, and no `--- START OF RECORD ---` line; the application adds that itself."
    );

    var hasMarginal = document.querySelector('[name="' + typeField("hasMarginalHeading") + '"]');
    var includeMarginal = hasMarginal ? hasMarginal.checked : false;

    // An "Act <act number>:" locator is never actually needed: unlike a page
    // number (genuinely separate information -- where on the physical
    // register an entry sits), the act number is always also stated inside
    // the entry's own legal text ("Numero d'ordine uno...") and extracted
    // from there directly by ai_parser.py's own act_number field -- this
    // heading was never read by anything downstream, just a redundant
    // restatement of a number already visible two lines below it. Confirmed
    // against a real Civil Death transcript before removing it. The "Page
    // <page number>:"/"Entry <n>:" locators stay -- neither is restated
    // anywhere else in the entry, so removing those would be a real loss of
    // information, not a redundancy.
    var usesActLocator = typeMeta().locatorKind === "act" || pbVal("pageNumberScheme") === "native_acts";
    var blockLines = ["# BLOCK STRUCTURE", "", "For every entry, emit these labeled blocks, in this order, SEPARATED BY BLANK LINES:", ""];
    if (!usesActLocator) {
      blockLines.push("    " + locatorPreviewText(), "");
    }
    if (includeMarginal) {
      blockLines.push("    Marginal Heading: <verbatim transcription of the heading -- optional, omit if the page has none>", "");
    }
    var transcriptionLabel = useItalianLabels
      ? "Trascrizione in " + italianLanguageName(language) + ":"
      : language + " Transcription:";
    blockLines.push(
      "    Date: <date exactly as written> [<day> <Month> <year>]", "",
      "    Notes: <one line -- optional, omit if there is nothing to say>", "",
      "    " + transcriptionLabel, "", "    <the body of the entry, as ONE unbroken line>"
    );
    langs.forEach(function (lang) {
      var translationLabel = useItalianLabels
        ? "Traduzione in " + italianLanguageName(lang) + ":"
        : lang + " Translation:";
      blockLines.push("", "    " + translationLabel, "", "    <the entire " + lang + " translation as ONE unbroken line>");
    });
    if (selectedRecordType() === "civil_birth") {
      var hasBaptismColumnBlock = document.querySelector('[name="' + typeField("hasBaptismColumn") + '"]');
      if (hasBaptismColumnBlock && hasBaptismColumnBlock.checked) {
        blockLines.push("", "    Baptism Record: <verbatim transcription of the register's baptism-administration column -- optional, omit if this entry has none>");
      }
    }
    if (selectedRecordType() === "civil_marriage") {
      var hasChurchWeddingBlock = document.querySelector('[name="' + typeField("hasChurchWeddingColumn") + '"]');
      if (hasChurchWeddingBlock && hasChurchWeddingBlock.checked) {
        blockLines.push("", "    Church Wedding Record: <verbatim transcription of the register's right-hand church-wedding column -- optional, omit if this entry has none>");
        langs.forEach(function (lang) {
          blockLines.push("", "    Church Wedding Record (" + lang + " translation): <the " + lang + " translation of that column, as ONE unbroken line -- omit if the block above is omitted>");
        });
      }
    }
    // An entry that only continues the previous image's has no opening date
    // of its own. Without this, a real Napoli marriage run gave every such
    // fragment a Date inferred from the neighbouring entry and a translation
    // opening with a date the fragment never states ("On the [blank] day of
    // [blank] 1823.") -- the fixed date-opener rule below collided with the
    // continuation rule above.
    blockLines.push(
      "",
      "A continuation fragment -- an entry that carries the note \"Entry appears to continue from the previous image.\" -- has no opening date of its own. Leave out its `Date:` block entirely: do not infer a date from adjacent entries and do not write a placeholder such as `[blank]`."
    );
    parts.push(blockLines.join("\n"));

    // Civil-only: a register's opening/title page (province, comune, and
    // circondario; the year(s) and act type the volume covers; a page
    // count; a judicial delegation or certification statement -- see the
    // real 1850 Napoli "Atti di Morte" title page this was written
    // against) states no dated act at all. Without an explicit exception,
    // the entry-count anti-hallucination check above ("your entry count
    // must equal that count") reads as "zero acts visible -> output
    // nothing", silently dropping this content instead of preserving it.
    // Fixed by giving it its own locator ("Front Matter:", not "Preamble:"
    // -- the OUTPUT FORMAT rules above already use "no preamble" to mean
    // "no AI-added commentary before your output", and reusing that word
    // for a real transcribed block would read as a contradiction) so it's
    // still transcribed and translated in full, but is clearly not one of
    // the register's acts -- see GENERAL_EXTRACTION_RULES in
    // xls_conversion/ai_parser.py for the matching instruction that tells
    // the downstream XLS Conversion step to skip a block labeled this way
    // rather than trying to force it into a spreadsheet row.
    if (selectedRecordType().indexOf("civil_") === 0) {
      var frontMatterLines = [
        "# REGISTER FRONT MATTER",
        "",
        "An image may show this register's own opening or administrative material instead of any dated acts -- for example a title page naming the province, comune, and circondario; the year(s) and act type the volume covers; a page count; or a judicial delegation or certification statement. This is not an act, and the entry-count check above does not apply to it: do not skip it. Transcribe and translate it in full, using the same fidelity and uncertainty rules as any other page, but label the whole block with its own locator instead of the usual entry structure:",
        "",
        "    Front Matter:", "",
        "    " + transcriptionLabel, "", "    <the full transcription>",
      ];
      langs.forEach(function (lang) {
        var frontMatterTranslationLabel = useItalianLabels
          ? "Traduzione in " + italianLanguageName(lang) + ":"
          : lang + " Translation:";
        frontMatterLines.push("", "    " + frontMatterTranslationLabel, "", "    <the full " + lang + " translation>");
      });
      frontMatterLines.push(
        "",
        "This \"Front Matter:\" locator tells the downstream XLS Conversion step this text is not one of the register's acts, so it is never turned into a spreadsheet row."
      );
      parts.push(frontMatterLines.join("\n"));
    }

    var examples = pbExampleEntries();
    if (examples.length === 1) {
      parts.push(
        "# EXAMPLE ENTRY (REFERENCE ONLY)\n\n" +
        "The following is a verified, complete, 100% accurate transcription of one real entry from this exact register, given purely as a formatting and style reference. Match its conventions -- spelling, abbreviation style, how it handles line breaks -- but do not copy its content into your own output; it is not the entry you are transcribing.\n\n" +
        exampleAsPromptText(examples[0]) + exampleFormatNotes(examples)
      );
    } else if (examples.length > 1) {
      var exampleBlocks = examples.map(function (example, index) {
        return "Example " + (index + 1) + (example.label ? " -- " + example.label : "") + ":\n\n" + exampleAsPromptText(example);
      });
      parts.push(
        "# EXAMPLE ENTRIES (REFERENCE ONLY)\n\n" +
        "The following are verified, complete, 100% accurate transcriptions of real entries from this exact register, given purely as formatting and style references -- deliberately covering more than one situation (e.g. a straightforward entry, one with an uncertain reading, one where a heading and body disagree). Match their conventions -- spelling, abbreviation style, how they handle line breaks -- but do not copy their content into your own output; none of them is the entry you are transcribing.\n\n" +
        exampleBlocks.join("\n\n---\n\n") + exampleFormatNotes(examples)
      );
    }

    if (langs.length) {
      var phrasingLines = ["# REQUIRED PHRASINGS", ""];
      langs.forEach(function (lang) {
        if (lang === "English") {
          phrasingLines.push("Open every English translation with: \"On the Nth day of <Month> <year>.\" Use a numeral with its ordinal suffix and always state the year, even when inferred.", "");
        } else {
          phrasingLines.push("Open every Italian translation with the date, for example \"Il giorno 23 di settembre 1752.\" Always state the year, even when inferred.", "");
        }
      });
      phrasingLines.push("This opening applies to a complete entry only. The translation of a continuation fragment (see BLOCK STRUCTURE) has no date to state, so it begins directly with the translated text.", "");
      var expandAbbrev = document.querySelector('[name="translateExpandAbbreviations"]');
      if (expandAbbrev && expandAbbrev.checked) {
        phrasingLines.push("Expand every abbreviation in the translation to its full form -- do not carry an abbreviated form over into translated text.", "");
      }
      var convertNames = document.querySelector('[name="translateConvertNames"]');
      if (convertNames && convertNames.checked) {
        phrasingLines.push("Convert personal names in the translation to their standard " + langs.join("/") + " equivalent (for example, Ioannes -> John in English, Giovanni in Italian) rather than transliterating the source-language form.", "");
      }
      var honorifics = pbChecked("honorifics").concat(pbSimpleValues("pb-honorific-rows"));
      if (honorifics.length) {
        phrasingLines.push(
          "When naming someone in a role (godparent, witness, informant, or similar), keep only " + honorifics.join(" or ") + " with the personal name. Every other title or rank is stripped and moved to Notes instead -- never both.",
          ""
        );
      }
      if (phrasingLines.length > 2) parts.push(phrasingLines.join("\n").trim());
    }

    var notesLines = ["Notes carries everything the other blocks cannot: scribal errors, conflicting dates, marginalia, your confidence when a reading is weak, and any disagreement between blocks."];
    if (selectedRecordType().indexOf("civil_") === 0) {
      notesLines.push("If a note was added in this register's margin at a later date -- for example a cross-reference to a subsequent marriage or death recorded elsewhere in the register -- record it here too, not in the main transcription.");
    }
    parts.push("# NOTES\n\n" + notesLines.join(" "));

    var checklist = ["# FINAL CHECK BEFORE YOU OUTPUT", "",
      "1. Every block separated by a blank line; " + language + (langs.length ? " and " + langs.join("/") : "") + " each on one line.",
    ];
    var next = 2;
    if (langs.indexOf("English") !== -1) { checklist.push(next + ". Every English translation opens with \"On the Nth day of <Month> <year>.\" (except a continuation fragment, which has no date of its own)."); next++; }
    checklist.push(next + ". No JSON, no code fences, no START OF RECORD line, no text outside the blocks.");
    parts.push(checklist.join("\n"));

    return parts.join("\n\n");
  }

  // ---- Wiring ----

  function pbAssembleFullPrompt(role, reference, format) {
    var rules = window.PB_CORE_RULES.map(function (r) { return "- " + r; }).join("\n");
    var scaffold = "# ROLE AND LOCAL CONTEXT\n" + role + "\n\n# CORE TRANSCRIPTION RULES\n" + rules + "\n\n# OUTPUT FORMAT\n" + format;
    var sections = [scaffold];
    if (reference.trim()) {
      sections.push(
        "# USER-SUPPLIED GROUND TRUTH AND REFERENCE MATERIAL\n" +
        "Use the following material as the primary local knowledge base for this run. " +
        "It may include JSON dictionaries, names, places, formulas, abbreviations, sample " +
        "transcriptions/translations, or other ground-truth notes. Do not invent content " +
        "from this reference; use it only to resolve or constrain readings visible in the source image.\n\n" +
        "```text\n" + reference + "\n```"
      );
    }
    return sections.join("\n\n");
  }

  function pbWordCount(text) {
    var trimmed = (text || "").trim();
    return trimmed ? trimmed.split(/\s+/).length : 0;
  }

  function pbRefresh() {
    updateExampleSubsections();
    var role = buildRoleContext();
    var reference = buildReferenceContext();
    var format = buildOutputFormat();

    document.querySelector('[name="role_context"]').value = role;
    document.querySelector('[name="reference_context"]').value = reference;
    document.querySelector('[name="output_format"]').value = format;

    // Fed straight through to the saved profile JSON (not part of the
    // assembled prose above) -- lets write_docx() stamp a deterministic
    // "what does this document contain" box at the top of every transcription
    // this profile produces, instead of XLSX Conversion having to guess from
    // the output later. record_type
    // reuses the same key selectedRecordType() already returns for the
    // questionnaire itself -- XLS Conversion's own "Source material" select
    // uses identical keys/labels, so no separate mapping is needed anywhere.
    document.querySelector('[name="native_language"]').value = pbVal("language");
    document.querySelector('[name="translation_languages"]').value = translationLanguages().join(",");
    document.querySelector('[name="record_type"]').value = selectedRecordType();

    document.getElementById("wc-role_context").textContent = pbWordCount(role) + " words";
    document.getElementById("wc-reference_context").textContent = pbWordCount(reference) + " words";
    document.getElementById("wc-output_format").textContent = pbWordCount(format) + " words";

    document.getElementById("pb-preview-content").textContent = pbAssembleFullPrompt(role, reference, format);
  }

  function updateMarginalHeadingVisibility() {
    var toggle = document.querySelector('[name="' + typeField("hasMarginalHeading") + '"]');
    var group = document.querySelector('.pb-type-group[data-record-type="' + selectedRecordType() + '"]');
    var box = group ? group.querySelector(".pb-marginal-formula") : null;
    if (box) box.hidden = !(toggle && toggle.checked);
    var baptismBox = group ? group.querySelector(".pb-baptism-formula") : null;
    if (baptismBox) baptismBox.hidden = !baptismColumnActive();
    var churchWeddingBox = group ? group.querySelector(".pb-church-wedding-formula") : null;
    if (churchWeddingBox) churchWeddingBox.hidden = !churchWeddingColumnActive();
  }

  function updateRecordTypeVisibility() {
    var type = selectedRecordType();
    document.querySelectorAll(".pb-type-group").forEach(function (group) {
      group.hidden = group.getAttribute("data-record-type") !== type;
    });
    var cornerRow = document.getElementById("pb-page-number-corner-row");
    var isCivil = type.indexOf("civil_") === 0;
    if (cornerRow) cornerRow.hidden = isCivil || pbVal("pageNumberScheme") !== "two_per_image";
    // These Section 1 fields describe a physical register/institution the way
    // a church record does; civil acts don't have an "institution" in the same
    // sense, don't carry a scribe's individual hand the way a parish register
    // does (they're issued by a civil registry office, not one clergyman), and
    // -- per the scoping decision -- the questionnaire deliberately avoids
    // asking about "era" at all for civil records (see the civil-records
    // planning discussion: visual appearance, not historical period). Hidden
    // rather than removed from the page, since church types still use them.
    ["pb-church-only-era", "pb-church-only-institution", "pb-church-only-handdescriptor", "pb-church-only-pagenumberscheme", "pb-church-only-translateitalian", "pb-church-only-translation-hint"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.hidden = isCivil;
    });
    // Civil profiles only ever have one translation checkbox (English --
    // Italian was removed above, since the source is already Italian), so
    // the church version's "leave both unchecked" reads wrong once there's
    // only one box to leave unchecked.
    var civilTranslationHint = document.getElementById("pb-civil-only-translation-hint");
    if (civilTranslationHint) civilTranslationHint.hidden = !isCivil;
    // The source material for a civil record is already Italian, so
    // translating it into Italian is meaningless -- unlike the plain-text
    // fields above, a checkbox left checked from a church-type profile would
    // otherwise silently survive the switch and still count as a requested
    // translation language.
    if (isCivil) {
      var translateItalian = document.querySelector('[name="translateItalian"]');
      if (translateItalian) translateItalian.checked = false;
    }
    updateMarginalHeadingVisibility();
    updateRecordTypeLanguageDefault();
    updateLanguageDefaults();
    updateOtherFieldVisibility();
    updateTranslationVisibility();
  }

  // The "Other" choice on Page layout and Month-abbreviation convention each
  // reveal a text box for describing it (a bare "Other" used to add nothing
  // but the literal word "other" to the prompt). The "entries continue onto
  // the next image" checkbox only makes sense for two facing pages.
  function updateOtherFieldVisibility() {
    var layoutOtherRow = document.getElementById("pb-page-layout-other-row");
    if (layoutOtherRow) layoutOtherRow.hidden = pbVal("pageLayout") !== "other";
    var monthOtherRow = document.getElementById("pb-month-convention-other-row");
    var monthField = document.getElementById("pb-latin-month-field");
    if (monthOtherRow) monthOtherRow.hidden = pbVal("monthConvention") !== "other" || !!(monthField && monthField.hidden);
    var spanRow = document.getElementById("pb-span-images-row");
    if (spanRow) spanRow.hidden = pbVal("pageLayout") !== "two_facing";
  }

  // Church records default to Latin, civil records to Italian -- a starting
  // point, not a hardcoded rule (real exceptions exist: Napoleonic-era civil
  // acts in French, South Tyrol civil records in German, vernacular-Italian
  // parish entries). Only applied while the user hasn't picked a language
  // themselves; same touched-flag pattern as Month-abbreviation convention.
  function updateRecordTypeLanguageDefault() {
    var languageSelect = document.querySelector('[name="language"]');
    if (!languageSelect || languageSelect.dataset.touched) return;
    var defaultLanguage = selectedRecordType().indexOf("civil_") === 0 ? "Italian" : "Latin";
    if (languageSelect.value !== defaultLanguage) languageSelect.value = defaultLanguage;
  }

  // Preset checklists whose items are themselves Latin vocabulary -- hidden
  // (not deleted) when the source language isn't Latin, since a civil
  // register in Italian has no use for nudius tertius or Sac.os. The
  // repeatable "Add another" row + button for each stays visible always (see
  // the checklist <div> ids below, which deliberately wrap only the preset
  // checkboxes, not the whole question) -- a civil profile may still need its
  // own Italian-specific relative dates, abbreviations, or scribal quirks,
  // and there's no reason to make the user re-discover that field elsewhere.
  var LATIN_PRESET_CHECKLISTS = [
    { name: "relativeDateTerms", boxId: "pb-latin-relativedate-checklist" },
    { name: "relationshipTerms", boxId: "pb-latin-relationship-checklist" },
    { name: "commonAbbrev", boxId: "pb-latin-abbrev-checklist" },
    { name: "scribalQuirks", boxId: "pb-latin-scribal-checklist" },
  ];

  function updateLanguageDefaults() {
    var language = pbVal("language").toLowerCase();
    var isLatin = language.indexOf("latin") !== -1;
    var declension = document.querySelector('[name="latinDeclension"]');
    if (declension) declension.checked = isLatin;
    var monthSelect = document.querySelector('[name="monthConvention"]');
    if (monthSelect && !monthSelect.dataset.touched) {
      monthSelect.value = isLatin ? "latin_march" : "standard";
    }
    // Same forced-sync approach as the declension checkbox above: it
    // re-applies whenever language or record type changes, so a deliberate
    // manual override survives until the next such change -- same tradeoff
    // already accepted for declension. Without this, an item checked (or
    // left at its default-checked state) while hidden would still silently
    // leak Latin vocabulary into a civil profile's generated prompt.
    LATIN_PRESET_CHECKLISTS.forEach(function (entry) {
      document.querySelectorAll('[name="' + entry.name + '"]').forEach(function (el) {
        el.checked = isLatin;
      });
      var box = document.getElementById(entry.boxId);
      if (box) box.hidden = !isLatin;
    });
    var declensionRow = document.getElementById("pb-latin-declension-row");
    if (declensionRow) declensionRow.hidden = !isLatin;
    var monthField = document.getElementById("pb-latin-month-field");
    if (monthField) monthField.hidden = !isLatin;
    updateOtherFieldVisibility();
    pbRefresh();
  }

  function updateTranslationVisibility() {
    var langs = translationLanguages();
    var honorificsSection = document.getElementById("pb-honorifics-section");
    if (honorificsSection) honorificsSection.hidden = langs.length === 0;
    var translationOptionsSection = document.getElementById("pb-translation-options-section");
    if (translationOptionsSection) translationOptionsSection.hidden = langs.length === 0;
    pbRefresh();
  }

  // ---- Info buttons (the small "i" popups scattered through the form) ----

  function closeAllInfoPanels(except) {
    document.querySelectorAll(".pb-info-panel").forEach(function (panel) {
      if (panel === except) return;
      panel.hidden = true;
      var btn = document.querySelector('.pb-info-btn[aria-controls="' + panel.id + '"]');
      if (btn) btn.setAttribute("aria-expanded", "false");
    });
  }

  function wireInfoButtons() {
    document.addEventListener("click", function (event) {
      var btn = event.target.closest(".pb-info-btn");
      if (btn) {
        var panel = document.getElementById(btn.getAttribute("aria-controls"));
        var wasOpen = panel && !panel.hidden;
        closeAllInfoPanels();
        if (panel && !wasOpen) {
          panel.hidden = false;
          btn.setAttribute("aria-expanded", "true");
        }
        event.preventDefault();
        return;
      }
      if (!event.target.closest(".pb-info-panel")) closeAllInfoPanels();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeAllInfoPanels();
    });
  }

  function wireRow(row) {
    var removeButton = row.querySelector(".pb-row-remove");
    if (removeButton) {
      removeButton.addEventListener("click", function () {
        row.remove();
        pbRefresh();
      });
    }
    row.querySelectorAll("input, textarea").forEach(function (field) {
      field.addEventListener("input", pbRefresh);
    });
  }

  function addRow(containerId, rowHtml, extraClass) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var row = document.createElement("div");
    row.className = "pb-row" + (extraClass ? " " + extraClass : "");
    row.innerHTML = rowHtml + ' <button type="button" class="button-tiny pb-row-remove">Remove</button>';
    // These repeatable-row fields have no <label> -- there's no static markup
    // for a dynamically-added row to attach one to -- so their placeholder
    // was their only accessible name, which fails WCAG SC 3.3.2 (placeholder
    // text isn't a substitute for a label). Backfill aria-label from the
    // same string instead: TRANSLATABLE_ATTRS in i18n.js already includes
    // aria-label, so tbRefreshLanguage() below picks it up and translates it
    // using the same dictionary entry as the placeholder itself.
    row.querySelectorAll("input[placeholder], textarea[placeholder]").forEach(function (field) {
      if (!field.hasAttribute("aria-label")) {
        field.setAttribute("aria-label", field.getAttribute("placeholder"));
      }
    });
    container.appendChild(row);
    wireRow(row);
    // New placeholders/labels (and the "Remove" button above) are only ever
    // written in English -- i18n.js's own load-time pass and lang-flag click
    // handler can't see DOM that didn't exist yet when they ran. Re-applying
    // here picks up whatever language is currently active, in Italian or not.
    if (window.tbRefreshLanguage) window.tbRefreshLanguage();
    return row;
  }

  function addVariantRow() {
    return addRow(
      "pb-variant-rows",
      '<input type="text" class="pb-variant-name" placeholder="Variant name, e.g. emergency home baptism">' +
      '<input type="text" class="pb-variant-markers" placeholder="Marker phrases that identify it">'
    );
  }

  function addAbbrevRow() {
    return addRow(
      "pb-abbrev-rows",
      '<input type="text" class="pb-abbrev-written" placeholder="Written, e.g. Sac.os">' +
      '<input type="text" class="pb-abbrev-expansion" placeholder="Expansion">' +
      '<input type="text" class="pb-abbrev-meaning" placeholder="Meaning">'
    );
  }

  function addSimpleRow(containerId, placeholder) {
    return addRow(containerId, '<input type="text" class="pb-simple-value" placeholder="' + placeholder + '">', "pb-row-simple");
  }

  // Shared by the JS-built rows here and mirrored by the server-rendered first
  // row in pages/prompt_builder.py -- keep the two in sync.
  function addExampleRow() {
    var row = addRow(
      "pb-example-rows",
      '<input type="text" class="pb-example-label" placeholder="Label (optional), e.g. Image 193 Entry 1">' +
      '<label class="pb-example-part"><span>Main entry</span>' +
      '<textarea class="pb-example-text" rows="5" placeholder="Paste a 100% accurate example entry text from your source material, exactly as it was transcribed -- no labels or headers."></textarea></label>' +
      '<label class="pb-example-part pb-example-wedding-part" hidden><span>Church Wedding Record (if any)</span>' +
      '<textarea class="pb-example-wedding" rows="3" placeholder="Paste the text of the right-hand church-wedding column, exactly as transcribed -- no labels or headers."></textarea></label>' +
      '<label class="pb-example-part pb-example-baptism-part" hidden><span>Baptism Record (if any)</span>' +
      '<textarea class="pb-example-baptism" rows="3" placeholder="Paste the text of the baptism column, exactly as transcribed -- no labels or headers."></textarea></label>' +
      '<label class="pb-example-part"><span>Continuation (if any)</span>' +
      '<textarea class="pb-example-continuation" rows="3" placeholder="If this entry runs onto the next image, paste the text that continues it at the top of that image, exactly as transcribed -- no labels or headers."></textarea></label>',
      "pb-example-row"
    );
    updateExampleSubsections();
    return row;
  }

  // The Church Wedding / Baptism Record parts only apply when their checkbox is on.
  function updateExampleSubsections() {
    var show = churchWeddingColumnActive();
    document.querySelectorAll(".pb-example-wedding-part").forEach(function (el) { el.hidden = !show; });
    var showBaptism = baptismColumnActive();
    document.querySelectorAll(".pb-example-baptism-part").forEach(function (el) { el.hidden = !showBaptism; });
  }

  // ---- Load an existing profile back into the questionnaire ----
  //
  // save_prompt_builder_profile() on the server writes every field this
  // form knows about into pb_answers (see pbSerializeAnswers below) for any
  // profile saved from this page. Loading one back just replays that
  // snapshot into the form -- it never tries to parse the assembled prose,
  // which is a one-way, lossy operation the rest of this app has always
  // deliberately avoided (see docs/DESIGN.md's "Prompt Builder design"
  // section).
  //
  // Repeatable rows (variants, abbreviations, and the four simple-value
  // lists) carry no `name` attribute -- they're read positionally via
  // pbRows()/pbSimpleValues() elsewhere in this file -- so they're captured
  // and restored separately from the plain named fields below.
  var PB_ROW_CONTAINERS = {
    "pb-variant-rows": { classNames: ["pb-variant-name", "pb-variant-markers"], build: addVariantRow },
    "pb-abbrev-rows": { classNames: ["pb-abbrev-written", "pb-abbrev-expansion", "pb-abbrev-meaning"], build: addAbbrevRow },
    "pb-example-rows": { classNames: ["pb-example-label", "pb-example-text", "pb-example-wedding", "pb-example-continuation", "pb-example-baptism"], build: addExampleRow },
    "pb-relativedate-rows": { classNames: ["pb-simple-value"], build: function () { return addSimpleRow("pb-relativedate-rows", "Add another term"); } },
    "pb-scribal-rows": { classNames: ["pb-simple-value"], build: function () { return addSimpleRow("pb-scribal-rows", "Add another quirk"); } },
    "pb-honorific-rows": { classNames: ["pb-simple-value"], build: function () { return addSimpleRow("pb-honorific-rows", "Add another honorific"); } },
    "pb-relationship-rows": { classNames: ["pb-simple-value"], build: function () { return addSimpleRow("pb-relationship-rows", "Add another term"); } },
    // Civil Birth only for now -- see role_vocab_extendable in app.py's
    // PROMPT_BUILDER_RECORD_TYPES. Extending this to another type just means
    // adding that type's own "<type>-rolevocab-rows" entry here to match.
    "civil_birth-rolevocab-rows": { classNames: ["pb-simple-value"], build: function () { return addSimpleRow("civil_birth-rolevocab-rows", "Add another term"); } },
  };

  function pbSerializeAnswers() {
    var form = document.getElementById("pb-questionnaire-form");
    var data = { fields: {}, checked: {}, rows: {} };
    if (!form) return data;

    form.querySelectorAll("input[name], textarea[name], select[name]").forEach(function (el) {
      if (el.type === "hidden" || el.closest(".pb-row")) return;
      if (el.type === "checkbox" || el.type === "radio") {
        // Record the group even when nothing in it is checked -- otherwise
        // restoring can't tell "the user unchecked every item" apart from
        // "this snapshot has no opinion, leave the HTML default checked".
        if (!data.checked[el.name]) data.checked[el.name] = [];
        if (el.checked) data.checked[el.name].push(el.value);
      } else {
        data.fields[el.name] = el.value;
      }
    });

    Object.keys(PB_ROW_CONTAINERS).forEach(function (containerId) {
      data.rows[containerId] = pbRows(containerId, PB_ROW_CONTAINERS[containerId].classNames);
    });

    return data;
  }

  function pbRestoreAnswers(data) {
    var form = document.getElementById("pb-questionnaire-form");
    if (!form || !data) return;

    Object.keys(data.fields || {}).forEach(function (name) {
      var el = form.querySelector('[name="' + name + '"]');
      if (!el) return;
      el.value = data.fields[name];
      el.dataset.touched = "1";
    });

    // Compare against the live `.value` property, not an attribute selector --
    // a checkbox with no `value=` attribute in the markup (e.g. latinDeclension)
    // still has a real `.value` of "on", but no matching `[value="on"]` attribute
    // to select on. Every name recorded during serialize is set here, including
    // groups saved with nothing checked, so an explicit "unchecked everything"
    // answer is restored as such rather than falling back to the HTML default.
    Object.keys(data.checked || {}).forEach(function (name) {
      var wanted = data.checked[name] || [];
      form.querySelectorAll('[name="' + name + '"]').forEach(function (el) {
        el.checked = wanted.indexOf(el.value) !== -1;
      });
    });

    // Back-compat: a profile saved before Example entry became a repeatable
    // list carries its one example under the old plain field name
    // ("exampleEntry"), not as a "pb-example-rows" row -- there's no element
    // named "exampleEntry" left in the DOM for the loop above to write it
    // into, so without this it would silently vanish on load. Synthesize one
    // unlabeled row from it, but only when the snapshot has no rows of its
    // own already (a profile saved after this change always does, even with
    // just one example, so this only ever fires for the old shape).
    var legacyExampleEntry = (data.fields || {}).exampleEntry;
    if (legacyExampleEntry && !(data.rows && data.rows["pb-example-rows"] && data.rows["pb-example-rows"].length)) {
      data = Object.assign({}, data, { rows: Object.assign({}, data.rows, { "pb-example-rows": [{ 0: "", 1: legacyExampleEntry }] }) });
    }

    Object.keys(PB_ROW_CONTAINERS).forEach(function (containerId) {
      var container = document.getElementById(containerId);
      if (container) container.innerHTML = "";
      var config = PB_ROW_CONTAINERS[containerId];
      (data.rows && data.rows[containerId] || []).forEach(function (row) {
        var rowEl = config.build();
        if (!rowEl) return;
        config.classNames.forEach(function (className, index) {
          var field = rowEl.querySelector("." + className);
          if (field) field.value = row[index] || "";
        });
      });
    });

    updateRecordTypeVisibility();
    updateTranslationVisibility();
    pbRefresh();
  }

  // Default text restored by pbClearEditing() -- read once, before pbSetEditing()
  // can ever overwrite it, so the two functions never need to duplicate the string.
  var PB_NAME_HINT_DEFAULT_TEXT = null;

  function pbSetEditing(profileId, label) {
    var idField = document.getElementById("pb-edit-profile-id");
    if (idField) idField.value = profileId;
    var nameField = document.querySelector('[name="new_profile_name"]');
    if (nameField) nameField.value = label;
    var status = document.getElementById("pb-editing-status");
    if (status) {
      status.hidden = false;
      status.textContent = 'Editing "' + label + '". "Update Profile" below overwrites it; "Save as New Profile" creates a separate copy instead.';
    }
    var updateButton = document.getElementById("pb-update-button");
    if (updateButton) updateButton.hidden = false;
    var loadSelect = document.getElementById("pb-load-select");
    if (loadSelect) loadSelect.value = profileId;
    // The name field's hint below is only accurate for "Save as New Profile" --
    // while editing, "Update Profile" also reads this field (to rename in
    // place), which #pb-editing-status above already explains. Leaving the
    // default "never overwrites" text in place here would flatly contradict
    // it, so swap it while a profile is loaded for editing.
    var nameHint = document.getElementById("pb-name-hint");
    if (nameHint) {
      if (PB_NAME_HINT_DEFAULT_TEXT === null) PB_NAME_HINT_DEFAULT_TEXT = nameHint.textContent;
      nameHint.textContent = 'Used by both buttons below: "Update Profile" renames and overwrites the profile you loaded; "Save as New Profile" creates a separate copy under this name instead.';
    }
  }

  function pbClearEditing() {
    var idField = document.getElementById("pb-edit-profile-id");
    if (idField) idField.value = "";
    var status = document.getElementById("pb-editing-status");
    if (status) status.hidden = true;
    var updateButton = document.getElementById("pb-update-button");
    if (updateButton) updateButton.hidden = true;
    var loadSelect = document.getElementById("pb-load-select");
    if (loadSelect) loadSelect.value = "";
    var nameHint = document.getElementById("pb-name-hint");
    if (nameHint && PB_NAME_HINT_DEFAULT_TEXT !== null) nameHint.textContent = PB_NAME_HINT_DEFAULT_TEXT;
  }

  // Preflight Test (Output Format section): runs the current, in-progress
  // prompt against one uploaded image and compares the AI's actual output to
  // the user's own hand-transcribed Example entry, surfacing classified
  // suggestions for gaps in the prompt's reference material. Reads the
  // assembled prompt straight from #pb-preview-content (kept live by
  // pbRefresh() on every field change) rather than recomputing it, so this
  // always tests exactly what "Full prompt preview" shows.
  //
  // Clicking "Run Preflight Test" first silently saves the current
  // questionnaire as a draft profile (see saveDraftBeforePreflight()) -- a
  // safety checkpoint in its own right, and also what lets a later "Apply
  // selected" mutate the live form without risking unsaved work if something
  // goes wrong. Nothing here writes to any field until the user explicitly
  // checks a suggestion and clicks "Apply selected".
  var PB_PREFLIGHT_SUGGESTIONS = [];

  // What each suggestion category is called in the UI, and (for the ones with
  // no safe auto-apply target) whether it gets a checkbox at all. Must match
  // PREFLIGHT_SUGGESTION_CATEGORIES in app.py.
  var PB_PREFLIGHT_CATEGORY_LABELS = {
    abbreviation: "Abbreviation key",
    lexicon_surname: "Surname lexicon",
    lexicon_given_name: "Given-name lexicon",
    scribal_quirk: "Scribal quirk",
    relative_date_term: "Relative-date vocabulary",
    relationship_term: "Relationship terms",
    role_vocab: "Role-clause vocabulary",
    other: "Needs manual edit"
  };

  // Populates the "Which example does this image show?" picker from the
  // current Example entry rows and shows/hides it -- hidden with 0 or 1
  // examples (nothing to choose), shown with 2+. Called fresh whenever the
  // user is about to act (choosing an image, clicking Run), not kept
  // continuously in sync, so editing example rows elsewhere on the page never
  // needs to reach into this panel. Returns the current example list so
  // callers that already need it (runPreflightTest()) don't have to read it
  // twice.
  function refreshPreflightExamplePicker() {
    var row = document.getElementById("pb-preflight-example-row");
    var select = document.getElementById("pb-preflight-example-select");
    var examples = pbExampleEntries();
    if (!row || !select) return examples;

    var previousValue = select.value;
    select.innerHTML = "";
    examples.forEach(function (example, index) {
      var option = document.createElement("option");
      option.value = String(index);
      option.textContent = "Example " + (index + 1) + (example.label ? " -- " + example.label : "");
      select.appendChild(option);
    });
    if (previousValue && select.querySelector('option[value="' + previousValue + '"]')) {
      select.value = previousValue;
    }
    row.hidden = examples.length < 2;
    return examples;
  }

  function wirePreflightTest() {
    var button = document.getElementById("pb-preflight-run");
    if (button) button.addEventListener("click", runPreflightTest);
    var applyButton = document.getElementById("pb-preflight-apply");
    if (applyButton) applyButton.addEventListener("click", applySelectedPreflightSuggestions);
    var fileInput = document.getElementById("pb-preflight-image");
    if (fileInput) fileInput.addEventListener("change", refreshPreflightExamplePicker);
  }

  // Import/Export Profiles -- lets one user hand a profile to another (email
  // attachment, USB stick, whatever) without needing shared access to either
  // person's profiles/ folder. Export downloads a small JSON file (see
  // export_profile_payload() in app.py for the file format and why it's
  // structured the way it is); import posts it back as an ordinary file
  // upload, same multipart pattern Preflight Test's image upload already
  // uses, rather than something new.
  function wireImportExport() {
    var exportButton = document.getElementById("pb-export-button");
    if (exportButton) exportButton.addEventListener("click", exportSelectedProfile);
    var importButton = document.getElementById("pb-import-button");
    if (importButton) importButton.addEventListener("click", importProfileFile);
  }

  function exportSelectedProfile() {
    var select = document.getElementById("pb-export-select");
    var statusEl = document.getElementById("pb-export-status");
    var profileId = select ? select.value : "";
    if (!profileId) {
      if (statusEl) statusEl.textContent = "Select a profile to export first.";
      return;
    }
    if (statusEl) statusEl.textContent = "";
    // A GET request with Content-Disposition: attachment downloads the file
    // without navigating away from the page -- no need for fetch/blob here.
    window.location.href = "/prompt-builder/export-profile?profile_id=" + encodeURIComponent(profileId);
  }

  function importProfileFile() {
    var fileInput = document.getElementById("pb-import-file");
    var statusEl = document.getElementById("pb-import-status");
    var file = fileInput && fileInput.files && fileInput.files[0];
    if (!file) {
      if (statusEl) statusEl.textContent = "Choose a profile file first.";
      return;
    }
    if (statusEl) statusEl.textContent = "Importing…";
    var formData = new FormData();
    formData.append("file", file);
    fetch("/prompt-builder/import-profile", { method: "POST", body: formData })
      .then(function (resp) {
        return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
      })
      .then(function (result) {
        if (!result.ok) throw new Error(result.data.error || "Couldn't import that file.");
        var id = result.data.id;
        var label = result.data.label;

        var exportSelect = document.getElementById("pb-export-select");
        if (exportSelect && !exportSelect.querySelector('option[value="' + id + '"]')) {
          var exportOption = document.createElement("option");
          exportOption.value = id;
          exportOption.textContent = label;
          exportSelect.appendChild(exportOption);
        }

        // Only the "Load an existing profile" dropdown is restricted to
        // pb_answers-carrying profiles -- see load_custom_profiles() in
        // app.py -- so only add there when the imported file actually had
        // that structured questionnaire snapshot.
        if (result.data.has_pb_answers) {
          var loadSelect = document.getElementById("pb-load-select");
          if (loadSelect && !loadSelect.querySelector('option[value="' + id + '"]')) {
            var loadOption = document.createElement("option");
            loadOption.value = id;
            loadOption.textContent = label;
            loadSelect.appendChild(loadOption);
          }
        }

        if (statusEl) {
          statusEl.textContent = "Imported \"" + label + "\". Reload the Transcribe or Test Mode tab to see it in the profile list there.";
        }
        fileInput.value = "";
      })
      .catch(function (err) {
        if (statusEl) statusEl.textContent = (err && err.message) || String(err);
      });
  }

  // Persists the current in-progress questionnaire as an ordinary profile
  // (auto-named if the user hasn't typed one yet), via the JSON-friendly
  // sibling of the real Save buttons -- see save_prompt_builder_draft() in
  // app.py. Once a draft exists, subsequent Preflight Test runs (and the
  // real Save buttons) update that same profile in place rather than
  // piling up a new one on every click.
  function saveDraftBeforePreflight() {
    var idField = document.getElementById("pb-edit-profile-id");
    var payload = {
      role_context: pbVal("role_context"),
      reference_context: pbVal("reference_context"),
      output_format: pbVal("output_format"),
      native_language: pbVal("language"),
      translation_languages: translationLanguages().join(","),
      record_type: selectedRecordType(),
      edit_profile_id: idField ? idField.value : "",
      name: pbVal("new_profile_name"),
      pb_answers: pbSerializeAnswers()
    };
    return fetch("/prompt-builder/save-draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (resp) {
        return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
      })
      .then(function (result) {
        if (!result.ok) throw new Error(result.data.error || "Couldn't save a draft.");
        pbSetEditing(result.data.id, result.data.label);
        window.PB_SAVED_PROFILES = window.PB_SAVED_PROFILES || {};
        window.PB_SAVED_PROFILES[result.data.id] = { label: result.data.label, answers: payload.pb_answers };
        var loadSelect = document.getElementById("pb-load-select");
        if (loadSelect && !loadSelect.querySelector('option[value="' + result.data.id + '"]')) {
          var option = document.createElement("option");
          option.value = result.data.id;
          option.textContent = result.data.label;
          loadSelect.appendChild(option);
        }
        return result.data;
      });
  }

  function runPreflightTest() {
    var button = document.getElementById("pb-preflight-run");
    var fileInput = document.getElementById("pb-preflight-image");
    var statusEl = document.getElementById("pb-preflight-status");
    var resultsEl = document.getElementById("pb-preflight-results");
    var suggestionsEl = document.getElementById("pb-preflight-suggestions");
    var rawOutputEl = document.getElementById("pb-preflight-raw-output");
    var applyStatusEl = document.getElementById("pb-preflight-apply-status");

    function showStatus(message) {
      statusEl.hidden = false;
      statusEl.textContent = message;
    }

    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
      showStatus("Choose a file first.");
      return;
    }
    var examples = refreshPreflightExamplePicker();
    if (!examples.length) {
      showStatus("Add an Example entry above first -- the preflight test compares the AI's output against it.");
      return;
    }
    var exampleSelect = document.getElementById("pb-preflight-example-select");
    var selectedIndex = examples.length > 1 && exampleSelect ? Number(exampleSelect.value || 0) : 0;
    var exampleEntry = (examples[selectedIndex] || examples[0]).text;

    var modelSelect = document.getElementById("pb-preflight-model");
    var apiKeyInput = document.getElementById("pb-preflight-api-key");
    var model = modelSelect ? modelSelect.value : "";
    var apiKey = apiKeyInput ? apiKeyInput.value.trim() : "";

    resultsEl.hidden = true;
    if (applyStatusEl) applyStatusEl.textContent = "";
    button.disabled = true;
    showStatus("Saving a draft of your prompt…");

    // Two sequential AI calls happen server-side (transcribe, then critique),
    // each capped at PREFLIGHT_TIMEOUT_SECONDS (90s) in app.py -- so a slow
    // provider can legitimately take a couple of minutes total. This client-
    // side abort is a backstop set comfortably past that combined worst case
    // (not the expected case), so the button and status text always recover
    // with a clear message instead of appearing to hang forever if something
    // below this layer (network, proxy, browser) never returns at all.
    var abortController = typeof AbortController !== "undefined" ? new AbortController() : null;
    var abortTimer = abortController
      ? setTimeout(function () { abortController.abort(); }, 240000)
      : null;

    saveDraftBeforePreflight()
      .then(function () {
        showStatus("Running preflight test… this calls the AI twice (reading your image, then comparing it) and can take a couple of minutes.");
        var formData = new FormData();
        formData.append("image", fileInput.files[0]);
        formData.append("example_entry", exampleEntry);
        formData.append("full_prompt", document.getElementById("pb-preview-content").textContent);
        formData.append("record_type", selectedRecordType());
        formData.append("model", model);
        formData.append("api_key", apiKey);
        var fetchOptions = { method: "POST", body: formData };
        if (abortController) fetchOptions.signal = abortController.signal;
        return fetch("/prompt-builder/preflight-test", fetchOptions);
      })
      .then(function (resp) {
        if (abortTimer) clearTimeout(abortTimer);
        return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
      })
      .then(function (result) {
        button.disabled = false;
        if (!result.ok) {
          showStatus(result.data.error || "Preflight test failed.");
          return;
        }
        statusEl.hidden = true;
        resultsEl.hidden = false;
        suggestionsEl.innerHTML = "";
        PB_PREFLIGHT_SUGGESTIONS = result.data.suggestions || [];
        renderPreflightSuggestions();
        rawOutputEl.textContent = result.data.raw_output || "";
      })
      .catch(function (err) {
        if (abortTimer) clearTimeout(abortTimer);
        button.disabled = false;
        if (err && err.name === "AbortError") {
          showStatus("Preflight test timed out waiting for a response. Try again, or try a different model.");
          return;
        }
        showStatus((err && err.message) || ("Preflight test failed: " + err));
      });
  }

  function renderPreflightSuggestions() {
    var suggestionsEl = document.getElementById("pb-preflight-suggestions");
    suggestionsEl.innerHTML = "";

    if (!PB_PREFLIGHT_SUGGESTIONS.length) {
      var p = document.createElement("p");
      p.className = "hint";
      p.textContent = "No gaps found — the AI's output matched your example entry closely.";
      suggestionsEl.appendChild(p);
      return;
    }

    PB_PREFLIGHT_SUGGESTIONS.forEach(function (suggestion, index) {
      var row = document.createElement("label");
      row.className = "pb-suggestion-row" + (suggestion.category === "other" ? " pb-suggestion-other" : "");

      if (suggestion.category !== "other") {
        var checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.dataset.suggestionIndex = String(index);
        row.appendChild(checkbox);
      }

      var text = document.createElement("span");
      text.className = "pb-suggestion-text";
      var categoryTag = document.createElement("span");
      categoryTag.className = "pb-suggestion-category";
      categoryTag.textContent = (PB_PREFLIGHT_CATEGORY_LABELS[suggestion.category] || suggestion.category) + ":";
      text.appendChild(categoryTag);
      text.appendChild(document.createTextNode(suggestion.note || suggestion.value || ""));
      row.appendChild(text);

      suggestionsEl.appendChild(row);
    });
  }

  // Adds one accepted suggestion's value to the questionnaire field its
  // category maps to, matching PREFLIGHT_SUGGESTION_CATEGORIES in app.py.
  // Skips a value already present (case-insensitive) rather than adding a
  // duplicate row/line. Returns true if something was actually added.
  function applyPreflightSuggestion(suggestion) {
    switch (suggestion.category) {
      case "abbreviation":
        return applyAbbreviationSuggestion(suggestion);
      case "lexicon_surname":
        return appendToLexiconField("nameLexiconSurnames", suggestion.value);
      case "lexicon_given_name":
        return appendToLexiconField("nameLexiconGivenNames", suggestion.value);
      case "scribal_quirk":
        return appendSimpleRowValue("pb-scribal-rows", suggestion.value);
      case "relative_date_term":
        return appendSimpleRowValue("pb-relativedate-rows", suggestion.value);
      case "relationship_term":
        return appendSimpleRowValue("pb-relationship-rows", suggestion.value);
      case "role_vocab":
        return appendSimpleRowValue(selectedRecordType() + "-rolevocab-rows", suggestion.value);
      default:
        return false; // "other" -- no safe auto-apply target
    }
  }

  function appendToLexiconField(fieldName, value) {
    if (!value) return false;
    var field = document.querySelector('[name="' + fieldName + '"]');
    if (!field) return false;
    var existing = field.value.split("\n").map(function (line) { return line.trim(); });
    if (existing.some(function (line) { return line.toLowerCase() === value.trim().toLowerCase(); })) return false;
    field.value = (field.value.replace(/\s+$/, "") + "\n" + value.trim()).replace(/^\n/, "");
    return true;
  }

  function appendSimpleRowValue(containerId, value) {
    if (!value) return false;
    var container = document.getElementById(containerId);
    if (!container) return false;
    var isDuplicate = Array.prototype.some.call(container.querySelectorAll(".pb-simple-value"), function (input) {
      return input.value.trim().toLowerCase() === value.trim().toLowerCase();
    });
    if (isDuplicate) return false;
    var row = addSimpleRow(containerId, "Add another term");
    var input = row && row.querySelector(".pb-simple-value");
    if (input) input.value = value.trim();
    return true;
  }

  function applyAbbreviationSuggestion(suggestion) {
    if (!suggestion.written && !suggestion.expansion) return false;
    var isDuplicate = Array.prototype.some.call(document.querySelectorAll("#pb-abbrev-rows .pb-abbrev-written"), function (input) {
      return suggestion.written && input.value.trim().toLowerCase() === suggestion.written.trim().toLowerCase();
    });
    if (isDuplicate) return false;
    var row = addAbbrevRow();
    if (!row) return false;
    var written = row.querySelector(".pb-abbrev-written");
    var expansion = row.querySelector(".pb-abbrev-expansion");
    var meaning = row.querySelector(".pb-abbrev-meaning");
    if (written) written.value = suggestion.written || "";
    if (expansion) expansion.value = suggestion.expansion || "";
    if (meaning) meaning.value = suggestion.meaning || "";
    return true;
  }

  function applySelectedPreflightSuggestions() {
    var suggestionsEl = document.getElementById("pb-preflight-suggestions");
    var applyStatusEl = document.getElementById("pb-preflight-apply-status");
    var checkboxes = suggestionsEl.querySelectorAll('input[type="checkbox"]:checked');
    if (!checkboxes.length) {
      if (applyStatusEl) applyStatusEl.textContent = "Check at least one suggestion first.";
      return;
    }

    var appliedCount = 0;
    var skippedCount = 0;
    Array.prototype.forEach.call(checkboxes, function (checkbox) {
      var suggestion = PB_PREFLIGHT_SUGGESTIONS[Number(checkbox.dataset.suggestionIndex)];
      if (!suggestion) return;
      if (applyPreflightSuggestion(suggestion)) {
        appliedCount += 1;
        var row = checkbox.closest(".pb-suggestion-row");
        if (row) { row.style.opacity = "0.55"; checkbox.disabled = true; }
      } else {
        skippedCount += 1;
      }
    });

    if (appliedCount) pbRefresh();

    var message = appliedCount
      ? "Added " + appliedCount + " suggestion" + (appliedCount === 1 ? "" : "s") + " to your questionnaire above."
      : "Nothing to add -- ";
    if (skippedCount) {
      message += (appliedCount ? " " : "") + skippedCount + " already matched an existing entry and " +
        (skippedCount === 1 ? "was" : "were") + " skipped.";
    }
    if (applyStatusEl) applyStatusEl.textContent = message;
  }

  function wireProfileLoader() {
    var loadSelect = document.getElementById("pb-load-select");
    if (loadSelect) {
      loadSelect.addEventListener("change", function () {
        var profileId = loadSelect.value;
        if (!profileId) { pbClearEditing(); return; }
        var entry = (window.PB_SAVED_PROFILES || {})[profileId];
        if (!entry) return;
        pbRestoreAnswers(entry.answers);
        pbSetEditing(profileId, entry.label);
      });
    }

    var form = document.getElementById("pb-questionnaire-form");
    if (form) {
      form.addEventListener("submit", function () {
        var answersField = document.getElementById("pb-answers-json");
        if (answersField) answersField.value = JSON.stringify(pbSerializeAnswers());
      });
    }

    // If the previous save attempt failed, the server re-renders this page
    // with whatever was submitted so it isn't lost -- restore it, and keep
    // "Update Profile" pointed at the same profile if that's what was
    // being edited. See save_prompt_builder_profile()'s except branch.
    if (window.PB_RESTORE_ON_ERROR) {
      pbRestoreAnswers(window.PB_RESTORE_ON_ERROR);
      if (window.PB_RESTORE_EDIT_ID) pbSetEditing(window.PB_RESTORE_EDIT_ID, window.PB_RESTORE_EDIT_LABEL);
    }
  }

  function resetForm() {
    if (!window.confirm("Clear every questionnaire answer? This cannot be undone.")) return;
    document.getElementById("pb-questionnaire-form").reset();
    Object.keys(PB_ROW_CONTAINERS).forEach(function (id) {
      var container = document.getElementById(id);
      if (container) container.innerHTML = "";
    });
    // Example entries ships with one row visible by default (see the
    // DOMContentLoaded wiring above) -- restore that same starting state
    // instead of leaving the section with zero rows after a reset.
    addExampleRow();
    // Clear the touched flags too, not just the field values -- form.reset()
    // only restores values, so without this a field touched before Reset would
    // permanently stop taking its auto-default afterward. (Fixes the same latent
    // gap for Month-abbreviation convention, which had this flag already but
    // nothing ever cleared it.)
    var monthSelect = document.querySelector('[name="monthConvention"]');
    if (monthSelect) delete monthSelect.dataset.touched;
    var languageSelect = document.querySelector('[name="language"]');
    if (languageSelect) delete languageSelect.dataset.touched;
    pbClearEditing();
    updateRecordTypeVisibility();
  }

  function pbSetAllOpen(open) {
    document.querySelectorAll("details.pb-section").forEach(function (d) { d.open = open; });
  }

  // Offline-worksheet download button. Independent of i18n.js's DICTIONARY
  // text-swap (that mechanism only replaces static text nodes/attributes) --
  // this button also has to swap *which file* it points at, so it reads the
  // same "tb-lang" cookie i18n.js writes and drives its own label, caption,
  // and href/download filename directly.
  function getLangCookie() {
    var match = document.cookie.match(/(?:^|; )tb-lang=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : null;
  }

  var WORKSHEET_DOWNLOAD = {
    en: {
      label: "Download DOCX (ENG)",
      caption: "Download DOCX templates of the questionnaire to complete offline, then copy your selections into the app.",
      href: "/static/prompt-builder-worksheets/prompt-builder-worksheets-en.zip",
      filename: "prompt-builder-worksheets-en.zip",
    },
    it: {
      label: "Scarica DOCX (IT)",
      caption: "Scarica i modelli DOCX del questionario da completare offline, poi copia le tue scelte nell'app.",
      href: "/static/prompt-builder-worksheets/prompt-builder-worksheets-it.zip",
      filename: "prompt-builder-worksheets-it.zip",
    },
  };

  function updateWorksheetDownloadButton() {
    var link = document.getElementById("pb-download-worksheets");
    var caption = document.getElementById("pb-download-caption");
    if (!link && !caption) return;
    var lang = getLangCookie() === "it" ? "it" : "en";
    var copy = WORKSHEET_DOWNLOAD[lang];
    if (link) {
      link.textContent = copy.label;
      link.setAttribute("href", copy.href);
      link.setAttribute("download", copy.filename);
    }
    if (caption) caption.textContent = copy.caption;
  }

  // Shows the chosen filename next to the .file-picker translatable
  // stand-in button (static/base.css) -- see file_picker_html()'s own
  // docstring (pages/__init__.py) for why this never needs to restore the
  // placeholder text itself. Delegated on document so it also covers any
  // .file-picker added to the DOM after this script runs, with nothing
  // extra to wire up.
  document.addEventListener("change", function (event) {
    var input = event.target;
    if (!input || input.tagName !== "INPUT" || input.type !== "file") return;
    var picker = input.closest(".file-picker");
    var nameEl = picker && picker.querySelector(".file-picker-name");
    if (nameEl && input.files && input.files.length) nameEl.textContent = input.files[0].name;
  });

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("pb-questionnaire-form").addEventListener("input", function (event) {
      if (event.target.name === "recordType") { updateRecordTypeVisibility(); return; }
      if (event.target.name === "language") { event.target.dataset.touched = "1"; updateLanguageDefaults(); return; }
      if (event.target.name === "pageNumberScheme" || event.target.name === "pageLayout") { updateRecordTypeVisibility(); return; }
      if (event.target.classList.contains("pb-marginal-toggle") || event.target.classList.contains("pb-baptism-toggle") || event.target.classList.contains("pb-church-wedding-toggle")) { updateMarginalHeadingVisibility(); pbRefresh(); return; }
      if (event.target.name === "translateEnglish" || event.target.name === "translateItalian") { updateTranslationVisibility(); return; }
      if (event.target.name === "monthConvention") { event.target.dataset.touched = "1"; updateRecordTypeVisibility(); return; }
      pbRefresh();
    });

    var addVariantButton = document.getElementById("pb-add-variant");
    if (addVariantButton) addVariantButton.addEventListener("click", addVariantRow);
    var addAbbrevButton = document.getElementById("pb-add-abbrev");
    if (addAbbrevButton) addAbbrevButton.addEventListener("click", addAbbrevRow);
    var addExampleButton = document.getElementById("pb-add-example");
    if (addExampleButton) addExampleButton.addEventListener("click", addExampleRow);
    var addRelativeDateButton = document.getElementById("pb-add-relativedate");
    if (addRelativeDateButton) addRelativeDateButton.addEventListener("click", function () { addSimpleRow("pb-relativedate-rows", "Add another term"); });
    var addScribalButton = document.getElementById("pb-add-scribal");
    if (addScribalButton) addScribalButton.addEventListener("click", function () { addSimpleRow("pb-scribal-rows", "Add another quirk"); });
    var addHonorificButton = document.getElementById("pb-add-honorific");
    if (addHonorificButton) addHonorificButton.addEventListener("click", function () { addSimpleRow("pb-honorific-rows", "Add another honorific"); });
    var addRelationshipButton = document.getElementById("pb-add-relationship");
    if (addRelationshipButton) addRelationshipButton.addEventListener("click", function () { addSimpleRow("pb-relationship-rows", "Add another term"); });
    document.querySelectorAll(".pb-add-rolevocab").forEach(function (button) {
      button.addEventListener("click", function () {
        addSimpleRow(button.dataset.recordType + "-rolevocab-rows", "Add another term");
      });
    });

    var resetButton = document.getElementById("pb-reset-form");
    if (resetButton) resetButton.addEventListener("click", resetForm);

    var expandButton = document.getElementById("pb-expand-all");
    if (expandButton) expandButton.addEventListener("click", function () { pbSetAllOpen(true); });
    var collapseButton = document.getElementById("pb-collapse-all");
    if (collapseButton) collapseButton.addEventListener("click", function () { pbSetAllOpen(false); });

    // The Output Format section ships with one example row already in the
    // markup (server-rendered, not JS-generated) so the text box is visible
    // without an extra click -- wire it up the same way addRow() wires a
    // JS-created one (Remove button, pbRefresh on input).
    document.querySelectorAll(".pb-row").forEach(wireRow);

    wireInfoButtons();
    wirePreflightTest();
    wireImportExport();
    wireProfileLoader();
    updateTranslationVisibility();
    updateRecordTypeVisibility();

    updateWorksheetDownloadButton();
    document.querySelectorAll(".lang-flag").forEach(function (button) {
      button.addEventListener("click", updateWorksheetDownloadButton);
    });
  });
})();
