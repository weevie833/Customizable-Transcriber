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

  var RECORD_TYPES = {
    battesimi: { label: "Church Battesimi", nounSingular: "baptism", nounPlural: "baptisms", principal: "the baptized individual", locatorKind: "page", hasMarginalHeadingDefault: true },
    matrimoni: { label: "Church Matrimoni", nounSingular: "marriage", nounPlural: "marriages", principal: "the couple", locatorKind: "page", hasMarginalHeadingDefault: true },
    morti: { label: "Church Morti", nounSingular: "death", nounPlural: "deaths", principal: "the deceased", locatorKind: "page", hasMarginalHeadingDefault: true },
    civil_birth: { label: "Civil Birth", nounSingular: "birth", nounPlural: "births", principal: "the child", locatorKind: "act", hasMarginalHeadingDefault: false },
    civil_marriage: { label: "Civil Marriage", nounSingular: "marriage", nounPlural: "marriages", principal: "the couple", locatorKind: "act", hasMarginalHeadingDefault: false },
    civil_death: { label: "Civil Death", nounSingular: "death", nounPlural: "deaths", principal: "the deceased", locatorKind: "act", hasMarginalHeadingDefault: false },
  };

  // Same particle list used throughout the app (see ai_parser.py's
  // GENERAL_EXTRACTION_RULES) -- kept consistent so "what counts as part of
  // a surname" means the same thing everywhere.
  var SURNAME_PARTICLES = ["da", "dal", "de", "del", "della", "di", "d'", "la", "le", "li", "lo"];

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
  ].join("\n");

  function fidelityRulesBlock(langs) {
    var hasTranslation = langs.length > 0;
    var translationWord = langs.length > 1 ? "translations" : "translation";
    var lines = [
      "# FIDELITY RULES",
      "",
      "- Transcribe exactly what is on the page. Preserve archaic and non-standard spelling, inconsistent capitalization, and scribal error. Do not silently correct the scribe.",
    ];
    if (hasTranslation) {
      lines.push("- Preserve abbreviations exactly as written in the transcription. Do NOT insert bracketed expansions into the transcription itself. Expand them only in the " + translationWord + ".");
      lines.push("- Retain source-language name forms in the " + translationWord + " too -- do not anglicize, modernize, or translate a personal name to an English or Italian equivalent.");
    } else {
      lines.push("- Preserve abbreviations exactly as written. Do not expand them.");
    }
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

  // ---- Name-lexicon splitting (see the Section 2 "Name lexicon" toggle) ----
  //
  // If the user pastes complete names ("Giuseppe de Natale"), feeding that
  // pairing to the model as-is risks teaching it that this given name and
  // this surname belong together -- a bias toward a specific match, not
  // toward either name component being independently plausible. Splitting
  // into two separate, deduplicated, unpaired lists (matching how Chiusa
  // Sclafani's own lexicon keeps surnames and given names apart) avoids
  // that. A trailing surname particle stays attached to the surname rather
  // than being swallowed into "given name".

  function splitFullName(line) {
    line = line.trim();
    if (!line) return null;
    if (line.indexOf(",") !== -1) {
      var parts = line.split(",");
      return { given: parts.slice(1).join(",").trim(), surname: parts[0].trim() };
    }
    var tokens = line.split(/\s+/).filter(Boolean);
    if (tokens.length === 0) return null;
    if (tokens.length === 1) return { given: tokens[0], surname: "" };
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
    var language = pbVal("language") || "the source language";
    var era = pbVal("era");
    var locality = pbVal("locality");
    var province = pbVal("province");
    var institution = pbVal("institution");
    var volumeRange = pbVal("volumeRange");
    var handDescriptor = pbVal("handDescriptor");
    var pageLayout = pbVal("pageLayout");
    var pageNumberScheme = pbVal("pageNumberScheme");
    var pageNumberCorner = pbVal("pageNumberCorner");
    var monthConvention = pbVal("monthConvention");
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
    } else if (pageLayout) {
      layoutLines.push(pageLayout);
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
    } else if (monthConvention && monthConvention !== "standard") {
      calendarLines.push("# CALENDAR AND TIME CONVENTIONS", "", monthConvention);
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
    var roleVocab = pbChecked(typeField("roleVocab"));
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

    var lexicon = pbVal("nameLexicon");
    if (lexicon) {
      // Splitting is always on -- there is no user-facing toggle. Whatever
      // the user pastes ("Given Surname" or "Surname, Given", one name per
      // line) gets decomposed into independent given-name and surname
      // lists so the lexicon can't bias the model toward one specific
      // full-name pairing.
      var givenNames = [];
      var surnames = [];
      lexicon.split("\n").forEach(function (line) {
        var parsed = splitFullName(line);
        if (!parsed) return;
        if (parsed.given && givenNames.indexOf(parsed.given) === -1) givenNames.push(parsed.given);
        if (parsed.surname && surnames.indexOf(parsed.surname) === -1) surnames.push(parsed.surname);
      });
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

    return parts.join("\n\n");
  }

  // ---- Section 3: Output Format ----

  function locatorPreviewText() {
    var scheme = pbVal("pageNumberScheme");
    var meta = typeMeta();
    if (meta.locatorKind === "act" || scheme === "native_acts") {
      return "Act <act number> - Entry <n>:";
    }
    if (scheme === "none") {
      return "Entry <n>:";
    }
    return "Page <page number> - Entry <n>:";
  }

  function buildOutputFormat() {
    var parts = [];
    var langs = translationLanguages();
    var language = pbVal("language") || "Source";

    var outputDescription = langs.length
      ? "Your output is read by downstream tooling that turns it into a Word document and, separately, a spreadsheet. Exact labels and phrasing matter -- deviating from them does not merely change the styling, it can silently produce empty spreadsheet cells."
      : "Your output is read by downstream tooling that turns it into a Word document. Exact labels matter -- deviating from them does not merely change the styling, it can break how the document is built. No translation is requested for this profile: transcription only.";
    parts.push(
      outputDescription + "\n\n" +
      "Output plain text only. No JSON, no markdown code fences, no bullet lists, no headings, no preamble, no closing commentary, and no `--- START OF RECORD ---` line; the application adds that itself."
    );

    var hasMarginal = document.querySelector('[name="' + typeField("hasMarginalHeading") + '"]');
    var includeMarginal = hasMarginal ? hasMarginal.checked : false;

    var blockLines = ["# BLOCK STRUCTURE", "", "For every entry, emit these labeled blocks, in this order, SEPARATED BY BLANK LINES:", "",
      "    " + locatorPreviewText(), ""];
    if (includeMarginal) {
      blockLines.push("    Marginal Heading: <verbatim transcription of the heading -- optional, omit if the page has none>", "");
    }
    blockLines.push(
      "    Date: <date exactly as written> [<day> <Month> <year>]", "",
      "    Notes: <one line -- optional, omit if there is nothing to say>", "",
      "    " + language + " Transcription:", "", "    <the body of the entry, as ONE unbroken line>"
    );
    langs.forEach(function (lang) {
      blockLines.push("", "    " + lang + " Translation:", "", "    <the entire " + lang + " translation as ONE unbroken line>");
    });
    parts.push(blockLines.join("\n"));

    var exampleEntry = pbVal("exampleEntry");
    if (exampleEntry) {
      parts.push(
        "# EXAMPLE ENTRY (REFERENCE ONLY)\n\n" +
        "The following is a verified, complete, 100% accurate transcription of one real entry from this exact register, given purely as a formatting and style reference. Match its conventions -- spelling, abbreviation style, how it handles line breaks -- but do not copy its content into your own output; it is not the entry you are transcribing.\n\n" +
        exampleEntry
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
    var confidence = document.querySelector('[name="confidenceRationale"]');
    if (confidence && confidence.checked) {
      notesLines.push("State an explicit confidence rating -- `Confidence: High/Medium/Low` -- with a one-line rationale whenever a reading rests on inference rather than directly on the letterforms.");
    }
    parts.push("# NOTES\n\n" + notesLines.join(" "));

    var checklist = ["# FINAL CHECK BEFORE YOU OUTPUT", "",
      "1. Every block separated by a blank line; " + language + (langs.length ? " and " + langs.join("/") : "") + " each on one line.",
    ];
    var next = 2;
    if (langs.indexOf("English") !== -1) { checklist.push(next + ". Every English translation opens with \"On the Nth day of <Month> <year>.\""); next++; }
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
    // the output later. See CLAUDE.md's Prompt Builder section. record_type
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
  }

  function updateRecordTypeVisibility() {
    var type = selectedRecordType();
    document.querySelectorAll(".pb-type-group").forEach(function (group) {
      group.hidden = group.getAttribute("data-record-type") !== type;
    });
    var cornerRow = document.getElementById("pb-page-number-corner-row");
    if (cornerRow) cornerRow.hidden = pbVal("pageNumberScheme") !== "two_per_image";
    updateMarginalHeadingVisibility();
    updateRecordTypeLanguageDefault();
    updateLanguageDefaults();
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

  function updateLanguageDefaults() {
    var language = pbVal("language").toLowerCase();
    var declension = document.querySelector('[name="latinDeclension"]');
    if (declension) declension.checked = language.indexOf("latin") !== -1;
    var monthSelect = document.querySelector('[name="monthConvention"]');
    if (monthSelect && !monthSelect.dataset.touched) {
      monthSelect.value = language.indexOf("latin") !== -1 ? "latin_march" : "standard";
    }
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
    container.appendChild(row);
    wireRow(row);
    return row;
  }

  function addVariantRow() {
    addRow(
      "pb-variant-rows",
      '<input type="text" class="pb-variant-name" placeholder="Variant name, e.g. emergency home baptism">' +
      '<input type="text" class="pb-variant-markers" placeholder="Marker phrases that identify it">'
    );
  }

  function addAbbrevRow() {
    addRow(
      "pb-abbrev-rows",
      '<input type="text" class="pb-abbrev-written" placeholder="Written, e.g. Sac.os">' +
      '<input type="text" class="pb-abbrev-expansion" placeholder="Expansion">' +
      '<input type="text" class="pb-abbrev-meaning" placeholder="Meaning">'
    );
  }

  function addSimpleRow(containerId, placeholder) {
    addRow(containerId, '<input type="text" class="pb-simple-value" placeholder="' + placeholder + '">', "pb-row-simple");
  }

  function resetForm() {
    if (!window.confirm("Clear every questionnaire answer? This cannot be undone.")) return;
    document.getElementById("pb-questionnaire-form").reset();
    ["pb-variant-rows", "pb-abbrev-rows", "pb-relativedate-rows", "pb-scribal-rows", "pb-honorific-rows", "pb-relationship-rows"].forEach(function (id) {
      var container = document.getElementById(id);
      if (container) container.innerHTML = "";
    });
    // Clear the touched flags too, not just the field values -- form.reset()
    // only restores values, so without this a field touched before Reset would
    // permanently stop taking its auto-default afterward. (Fixes the same latent
    // gap for Month-abbreviation convention, which had this flag already but
    // nothing ever cleared it.)
    var monthSelect = document.querySelector('[name="monthConvention"]');
    if (monthSelect) delete monthSelect.dataset.touched;
    var languageSelect = document.querySelector('[name="language"]');
    if (languageSelect) delete languageSelect.dataset.touched;
    updateRecordTypeVisibility();
  }

  function pbSetAllOpen(open) {
    document.querySelectorAll("details.pb-section").forEach(function (d) { d.open = open; });
  }

  // Offline-worksheet download button. Independent of i18n.js's DICTIONARY
  // text-swap (that mechanism only replaces static text nodes/attributes) --
  // this button also has to swap *which file* it points at, so it reads the
  // same "tb-lang" localStorage key i18n.js writes and drives its own label,
  // caption, and href/download filename directly.
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
    var lang = localStorage.getItem("tb-lang") === "it" ? "it" : "en";
    var copy = WORKSHEET_DOWNLOAD[lang];
    if (link) {
      link.textContent = copy.label;
      link.setAttribute("href", copy.href);
      link.setAttribute("download", copy.filename);
    }
    if (caption) caption.textContent = copy.caption;
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("pb-questionnaire-form").addEventListener("input", function (event) {
      if (event.target.name === "recordType") { updateRecordTypeVisibility(); return; }
      if (event.target.name === "language") { event.target.dataset.touched = "1"; updateLanguageDefaults(); return; }
      if (event.target.name === "pageNumberScheme") { updateRecordTypeVisibility(); return; }
      if (event.target.classList.contains("pb-marginal-toggle")) { updateMarginalHeadingVisibility(); pbRefresh(); return; }
      if (event.target.name === "translateEnglish" || event.target.name === "translateItalian") { updateTranslationVisibility(); return; }
      if (event.target.name === "monthConvention") { event.target.dataset.touched = "1"; }
      pbRefresh();
    });

    var addVariantButton = document.getElementById("pb-add-variant");
    if (addVariantButton) addVariantButton.addEventListener("click", addVariantRow);
    var addAbbrevButton = document.getElementById("pb-add-abbrev");
    if (addAbbrevButton) addAbbrevButton.addEventListener("click", addAbbrevRow);
    var addRelativeDateButton = document.getElementById("pb-add-relativedate");
    if (addRelativeDateButton) addRelativeDateButton.addEventListener("click", function () { addSimpleRow("pb-relativedate-rows", "Add another term"); });
    var addScribalButton = document.getElementById("pb-add-scribal");
    if (addScribalButton) addScribalButton.addEventListener("click", function () { addSimpleRow("pb-scribal-rows", "Add another quirk"); });
    var addHonorificButton = document.getElementById("pb-add-honorific");
    if (addHonorificButton) addHonorificButton.addEventListener("click", function () { addSimpleRow("pb-honorific-rows", "Add another honorific"); });
    var addRelationshipButton = document.getElementById("pb-add-relationship");
    if (addRelationshipButton) addRelationshipButton.addEventListener("click", function () { addSimpleRow("pb-relationship-rows", "Add another term"); });

    var resetButton = document.getElementById("pb-reset-form");
    if (resetButton) resetButton.addEventListener("click", resetForm);

    var expandButton = document.getElementById("pb-expand-all");
    if (expandButton) expandButton.addEventListener("click", function () { pbSetAllOpen(true); });
    var collapseButton = document.getElementById("pb-collapse-all");
    if (collapseButton) collapseButton.addEventListener("click", function () { pbSetAllOpen(false); });

    wireInfoButtons();
    updateTranslationVisibility();
    updateRecordTypeVisibility();

    updateWorksheetDownloadButton();
    document.querySelectorAll(".lang-flag").forEach(function (button) {
      button.addEventListener("click", updateWorksheetDownloadButton);
    });
  });
})();
