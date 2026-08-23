// Generates the Prompt Builder worksheet DOCX files (church record types
// only), one per record type per language.
//
// Usage:
//   npm install                       (once, installs the `docx` package)
//   node build.js ..                  (writes profiles/worksheets/en/*.docx
//                                       and profiles/worksheets/it/*.docx)
//
// After regenerating, re-zip and copy into the served location:
//   cd en && zip -X -j ../../../static/prompt-builder-worksheets/prompt-builder-worksheets-en.zip *.docx && cd ..
//   cd it && zip -X -j ../../../static/prompt-builder-worksheets/prompt-builder-worksheets-it.zip *.docx && cd ..
//
// Edit the `strings()` function and the per-type TYPES config below, not the
// generated .docx files directly -- same "rebuild, don't hand-edit" rule as
// profiles/sources/chiusa-sclafani/build_prompt.py.

const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, BorderStyle,
  AlignmentType, Table, TableRow, TableCell, WidthType, ShadingType,
  Header, Footer, PageNumber,
} = require("docx");

// Output layout:
//   <OUT_DIR>/en/<slug>.docx
//   <OUT_DIR>/it/<slug-it>.docx
const OUT_DIR = process.argv[2] || __dirname;

const INK = "1f2933";
const MUTED = "5f6b76";
const RULE = "8a8377";
const ACCENT = "255c99";
const BOX_SHADE = "f7f5f0";

// ---------- per-language fixed strings ----------
// Italian phrasing reuses the app's own static/i18n.js DICTIONARY wherever an
// exact string exists there, for consistency between the worksheet and the
// live Prompt Builder page. Strings that only exist on the worksheet (info
// text bodies, "checked by default" notes, box captions, etc.) are original
// translations written for this document.

function strings(lang) {
  const it = lang === "it";
  return {
    docTitle: it ? "Foglio di lavoro del Generatore di prompt" : "Prompt Builder Worksheet",
    introBody: it
      ? "Completa questo questionario prima di usare la pagina Generatore di prompt nell'app. Ogni campo qui corrisponde a un campo della pagina Generatore di prompt, nello stesso ordine. Salta ciò che è contrassegnato come facoltativo se non si applica al tuo registro."
      : "Complete this questionnaire before you use the Prompt Builder page in the app. Every field here matches a field on the Prompt Builder page, in the same order. Skip anything marked optional if it doesn't apply to your register.",

    s1Title: it ? "1. Ruolo e contesto locale" : "1. Role & Local Context",
    s1Caption: it
      ? "Queste sono le regole di base che aiutano l'IA a capire cosa sta leggendo."
      : "These are the ground rules that help the AI understand what it's reading.",
    s2Title: it ? "2. Materiale di riferimento" : "2. Reference Material",
    s2Caption: it
      ? "Questo è il vocabolario, le formule e gli elenchi di nomi che permettono all'IA di riconoscere il linguaggio ricorrente di questo registro, invece di doverlo indovinare da capo a ogni voce."
      : "These are the vocabulary, formulas, and name lists that let the AI recognize this register's own recurring language instead of guessing at it fresh on every entry.",
    s3Title: it ? "3. Formato di output" : "3. Output Format",
    s3Caption: it
      ? "Questi campi determinano come deve essere scritta la trascrizione e se produrre una traduzione."
      : "These fields determine how the transcription should be written and whether to produce a translation.",

    recordTypeLabel: it ? "Tipo di registro" : "Record type",

    sourceLanguageLabel: it ? "Lingua di origine" : "Source language",
    sourceLanguageOptions: it
      ? ["Latino", "Italiano", "Latino e italiano misti", "Altro: _______________________"]
      : ["Latin", "Italian", "Latin and Italian mixed", "Other: _______________________"],

    eraLabel: it ? "Epoca" : "Era",
    eraNote: it ? "es. XVIII secolo" : "e.g. 18th-century",
    localityLabel: it ? "Località" : "Locality",
    localityNote: it ? "es. Chiusa Sclafani" : "e.g. Chiusa Sclafani",
    provinceLabel: it ? "Provincia / regione" : "Province / region",
    provinceNote: it ? "es. provincia di Palermo, Sicilia" : "e.g. province of Palermo, Sicily",
    institutionLabel: it ? "Nome dell'istituzione" : "Institution name",
    institutionNote: it ? "es. la parrocchia di San Nicolò di Bari" : "e.g. the parish church of San Nicolò di Bari",
    volumeLabel: it ? "Volume / intervallo di date coperto" : "Volume / date range covered",
    volumeNote: it ? "es. 1752-1759" : "e.g. 1752-1759",
    handLabel: it ? "Descrizione della grafia (opzionale)" : "Hand / script descriptor (optional)",
    handNote: it ? "es. grafia cancelleresca ecclesiastica siciliana" : "e.g. Sicilian ecclesiastical chancery hand",

    pageLayoutLabel: it ? "Impaginazione della pagina" : "Page layout",
    pageLayoutOptions: it
      ? ["Una pagina per immagine", "Due pagine affiancate, lette da sinistra a destra (impostazione predefinita dell'app)", "Altro"]
      : ["One page per image", "Two facing pages, read left then right (app default)", "Other"],

    pageNumberSchemeLabel: it ? "Schema di numerazione delle pagine" : "Page-numbering scheme",
    pageNumberSchemeOptions: it
      ? ["Nessun numero di pagina", "Un numero per immagine", "Due numeri, uno per pagina affiancata (impostazione predefinita dell'app)", "Il registro ha i propri numeri di atto/voce"]
      : ["No page numbers", "One number per image", "Two numbers, one per facing page (app default)", "Register has its own act/entry numbers"],

    pageNumberCornerLabel: it ? "Dove si trovano i numeri di pagina?" : "Where are the page numbers?",
    pageNumberCornerNote: it
      ? "es. angolo superiore, il numero della pagina sinistra in alto a sinistra, quello della pagina destra in alto a destra — salta se hai scelto \"Nessun numero di pagina\" sopra"
      : "e.g. upper corner, left page's number upper-left, right page's upper-right -- skip if \"No page numbers\" above",

    declensionLabel: it ? "Includi le indicazioni sulla declinazione grammaticale latina?" : "Include Latin grammatical case-declension guidance?",
    declensionItem: it ? "Sì, includi le indicazioni sulla declinazione" : "Yes, include declension guidance",
    declensionInfo: it
      ? "I sostantivi e i nomi latini cambiano desinenza a seconda del loro ruolo grammaticale nella frase — questo si chiama declinazione. La stessa persona può comparire in più di una forma all'interno di una singola voce: Franciscus (nominativo, come soggetto), Francisci (genitivo, \"di Francesco\"), Francisco (dativo/ablativo, \"a/da Francesco\"). Non si tratta di un errore di ortografia o di un'incoerenza da correggere — ogni forma è corretta nel proprio contesto. Attivando questa opzione si aggiunge un'indicazione affinché l'IA riconosca queste varianti come lo stesso nome e trascriva ogni forma esattamente come scritta, invece di \"normalizzarne\" una per farla corrispondere a un'altra."
      : "Latin nouns and names change their ending depending on their grammatical role in the sentence -- this is called declension. The same person can appear in more than one form within a single entry: Franciscus (nominative, as the subject), Francisci (genitive, \"of Francis\"), Francisco (dative/ablative, \"to/from Francis\"). This is not a spelling error or an inconsistency to fix -- each form is correct for its context. Turning this on adds guidance so the AI recognizes these variants as the same name and transcribes each form exactly as written, instead of \"normalizing\" one to match another.",

    monthLabel: it ? "Convenzione delle abbreviazioni dei mesi" : "Month-abbreviation convention",
    monthOptions: it
      ? ["Conteggio latino da marzo, 7bris-10bris = sett.-dic. (impostazione predefinita dell'app)", "Nomi standard dei mesi", "Altro"]
      : ["Latin March-counting, 7bris-10bris = Sept-Dec (app default)", "Standard month names", "Other"],

    hourLabel: it ? "Convenzione oraria" : "Hour convention",
    hourOptions: it
      ? ["Ore italiane, contate dal tramonto (impostazione predefinita dell'app)", "Ora standard dell'orologio", "Non applicabile"]
      : ["Italian hours, counted from sunset (app default)", "Standard clock time", "Not applicable"],

    relativeDateLabel: it ? "Vocabolario delle date relative" : "Relative-date vocabulary",
    relativeDateItems: it
      ? [
          "nudius tertius = l'altro ieri",
          "hodie = oggi",
          "hac nocte = la notte scorsa",
          "die praeterita = ieri",
          "ejusdem = dello stesso (mese)",
        ]
      : [
          "nudius tertius = day before yesterday",
          "hodie = today",
          "hac nocte = last night",
          "die praeterita = yesterday",
          "ejusdem = of the same (month)",
        ],
    addMoreRelativeDate: it
      ? "Aggiungi qui sotto i tuoi ulteriori termini di data relativa (uno per riga, termine = significato):"
      : "Add your own additional relative-date terms below (one per line, term = meaning):",

    marginalQuestionLabel: it
      ? "Questo registro ha un margine separato per ogni voce che riporta il nome?"
      : "Does this register have a separate margin for each entry that states the name?",
    marginalYesItem: it ? "Sì, trascrivi un blocco Intestazione marginale" : "Yes, transcribe a Marginal Heading block",
    marginalInfo: (placeholder) => it
      ? `Molti registri ecclesiastici e civili riportano una breve nota a margine accanto a ogni voce — spesso solo il nome o i nomi coinvolti — come una sorta di indice lungo il bordo della pagina. Se il tuo registro fa questo, seleziona la casella e descrivi lo schema qui sotto, ad esempio "${placeholder}." L'IA trascriverà questa nota a margine come un blocco "Marginal Heading" a sé stante, separato dal corpo principale della voce — utile perché i due talvolta non concordano (un'ortografia diversa, un ordine dei nomi diverso), ed entrambe le letture meritano di essere conservate.`
      : `Many church and civil registers write a short note in the margin next to each entry -- often just the name(s) involved -- as a running index down the side of the page. If your register does this, check the box and describe the pattern below, for example "${placeholder}." The AI will transcribe this margin note as its own "Marginal Heading" block, kept separate from the entry's main body text -- useful because the two occasionally disagree (a different spelling, a different name order), and both readings are worth preserving.`,

    marginalStructureLabel: it ? "Struttura dell'intestazione marginale" : "Marginal heading structure",
    marginalStructureNote: it ? "Necessaria solo se hai risposto \"sì\" sopra." : "Only needed if you checked \"yes\" above.",

    startingTextLabel: it ? "Testo di partenza dell'app (modificalo per adattarlo al tuo registro):" : "App's starting text (edit to match your own register):",
    yourVersionLabel: it ? "La tua versione:" : "Your version:",

    formulaInfo: it
      ? "Questa è la frase fissa che il tuo registro ripete in ogni voce, scritta per esteso con le parti che cambiano — nomi, date, ruoli — indicate come segnaposto tra parentesi quadre, ad esempio [PADRE] o [TESTIMONE]. Questo insegna all'IA dove si trova ogni nome o data reale nella frase, anche oltre le abbreviazioni. Modifica il testo di esempio qui sotto per farlo corrispondere alla formulazione reale del tuo registro."
      : "This is the exact standing phrase your register repeats in every entry, written out with the parts that change -- names, dates, roles -- marked as bracketed placeholders like [FATHER] or [WITNESS]. It teaches the AI where each real name or date sits in the sentence, even past abbreviations. Edit the sample text below to match your own register's actual wording.",
    formulaOptionalNote: it ? "(opzionale — lascia vuoto se questo registro non ne ha una)" : "(optional — leave blank if this register has none)",

    roleVocabLabel: (typeLabel) => it ? `Vocabolario delle formule di ruolo per ${typeLabel}` : `Role-clause vocabulary for ${typeLabel}`,
    roleVocabNote: it ? "opzionale" : "optional",
    roleVocabInfo: it
      ? "Queste sono le parole specifiche per ruolo che questo registro utilizza per le persone nominate in una voce — ad esempio un termine diverso a seconda che il ruolo sia stato ricoperto da una sola persona o da più persone. Selezionare un termine indica all'IA di riconoscerlo e di usarlo correttamente per stabilire chi ha ricoperto quale ruolo. Lascia deselezionato un termine se non compare mai nel tuo registro."
      : "These are the role-specific words this register uses for the people named in an entry -- for example, a different term depending on whether one person filled the role or several did. Checking a term tells the AI to recognize it and use it correctly when working out who filled which role. Leave a term unchecked if it never appears in your register.",
    addMoreRoleVocab: it
      ? "Aggiungi qui sotto il tuo ulteriore vocabolario delle formule di ruolo (termine = significato):"
      : "Add your own additional role-clause vocabulary below (term = meaning):",

    entryVariantsLabel: it ? "Varianti della voce" : "Entry variants",
    entryVariantsNote: it
      ? "opzionale — ad es. una variante di emergenza o condizionale della formula standard"
      : "optional -- e.g. an emergency or conditional variant of the standard formula",

    relationshipLabel: it ? "Vocabolario delle note di parentela" : "Relationship-note vocabulary",
    relationshipItems: it
      ? ["uxor = moglie di", "soror = sorella di", "frater = fratello di", "filius/filia = figlio/figlia di"]
      : ["uxor = wife of", "soror = sister of", "frater = brother of", "filius/filia = son/daughter of"],
    addMoreRelationship: it
      ? "Aggiungi qui sotto i tuoi ulteriori termini di parentela (termine = significato):"
      : "Add your own additional relationship terms below (term = meaning):",

    abbrevLabel: it ? "Legenda delle abbreviazioni — termini comuni" : "Abbreviation key -- common terms",
    abbrevItems: it
      ? [
          "Sac.os = sacerdos (sacerdote)",
          "Cap.us = capellanus (cappellano)",
          "Eccl.ae = ecclesiae (della chiesa)",
          "Par.lis = parochialis (parrocchiale, agg.)",
          "S.ti = Sancti (di San/Santo)",
          "jug. = jugales (coppia sposata)",
          "d.ti = dicti (del suddetto)",
          "D. = Don / Dominus (titolo di cortesia per il clero e i nobili)",
        ]
      : [
          "Sac.os = sacerdos (priest)",
          "Cap.us = capellanus (chaplain)",
          "Eccl.ae = ecclesiae (of the church)",
          "Par.lis = parochialis (parish, adj.)",
          "S.ti = Sancti (of Saint)",
          "jug. = jugales (married couple)",
          "d.ti = dicti (of the said)",
          "D. = Don / Dominus (courtesy title for clergy and gentry)",
        ],
    addMoreAbbrev: it
      ? "Aggiungi qui sotto le tue ulteriori abbreviazioni (come scritta = espansione = significato):"
      : "Add your own additional abbreviations below (written = expansion = meaning):",

    scribalLabel: it ? "Particolarità scribali / paleografiche" : "Scribal / paleographic quirks",
    scribalInfo: it
      ? "Le particolarità paleografiche sono abitudini comuni della grafia di uno scriba che possono sembrare errori ma non lo sono — cose come una ſ lunga che assomiglia a una f, o un macron sopra una vocale che indica una lettera omessa. Selezionare queste opzioni indica all'IA cosa aspettarsi da questa grafia, così da non scambiare un'abitudine scribale normale per un nome sconosciuto o un errore di battitura."
      : "Paleographic quirks are common habits of a scribe's handwriting that can look like errors but are not -- things like a long ſ that resembles an f, or a macron over a vowel marking a dropped letter. Checking these tells the AI what to expect from this hand, so it does not misread a normal scribal habit as an unfamiliar name or a typo.",
    scribalItems: it
      ? [
          "la ſ lunga è facilmente confusa con la f",
          "u e v non sono distinte",
          "un macron o una tilde sopra una vocale indica una n o m omessa",
          "le consonanti doppie sono incoerenti",
          "la -us finale è spesso un cappio in apice",
        ]
      : [
          "long ſ is easily mistaken for f",
          "u and v are not distinguished",
          "a macron or tilde over a vowel marks an omitted n or m",
          "doubled consonants are inconsistent",
          "terminal -us is often a superscript loop",
        ],
    addMoreScribal: it ? "Aggiungi qui sotto le tue ulteriori particolarità:" : "Add your own additional quirks below:",

    surnameParticleLabel: it ? "Applicare la regola standard delle particelle nei cognomi italiani?" : "Apply the standard Italian surname-particle rule?",
    surnameParticleNote: it
      ? "de/di/d'/lo/la/le/li restano attaccate al cognome, mai normalizzate."
      : "de/di/d'/lo/la/le/li stay attached to the surname, never normalized.",
    surnameParticleItem: it ? "Sì, applica la regola delle particelle del cognome" : "Yes, apply the surname-particle rule",

    lexiconLabel: it ? "Lessico dei nomi" : "Name lexicon",
    lexiconNote: it ? "opzionale, ma vivamente consigliato" : "optional, but strongly recommended",
    lexiconInfo: it
      ? "Aggiungere un lessico aumenta notevolmente la probabilità che il sistema di IA si orienti verso un'identificazione corretta di un nome."
      : "Adding a lexicon greatly increases the likelihood that the AI system will bias towards a correct identification of a name.",
    lexiconHint: it
      ? "Incolla o scrivi cognomi e nomi noti, nel formato \"Nome Cognome\" oppure \"Cognome, Nome\" — uno per riga. L'app li suddivide automaticamente in elenchi separati di cognomi e nomi."
      : "Paste or write known family names and given names, either as \"Given Surname\" or \"Surname, Given name\" -- one per line. The app automatically splits these into separate surname and given-name lists.",

    exampleEntryLabel: it ? "Voce di esempio" : "Example entry",
    exampleEntryNote: it
      ? "Digita una voce completa e accurata al 100% nella lingua originale delle tue fonti, esattamente come dovrebbe essere trascritta — senza etichette o intestazioni. Viene usata come riferimento di formattazione fondamentale per l'IA."
      : "Type in a completed, 100% accurate entry in the native language of your sources, exactly as it should be transcribed -- no labels or headers. This is used as a critically important formatting reference for the AI.",

    translationLabel: it ? "Traduzione" : "Translation",
    translationNote: it
      ? "opzionale — lascia entrambe le caselle deselezionate per un output di sola trascrizione senza alcuna traduzione"
      : "optional -- leave both unchecked for a transcription-only output with no translation at all",
    translationItems: it ? ["Inglese", "Italiano"] : ["English", "Italian"],

    translationStyleLabel: it ? "Opzioni di stile della traduzione" : "Translation style options",
    translationStyleNote: it ? "si applica solo se sopra è stata selezionata una lingua di traduzione" : "only applies if a translation language is checked above",
    translationStyleItems: it
      ? ["Espandi le abbreviazioni", "Converti i nomi negli equivalenti in inglese o italiano"]
      : ["Expand abbreviations", "Convert names to ENG or IT equivalents"],

    honorificsLabel: it ? "Titoli onorifici mantenuti nella formula di ruolo" : "Honorifics kept inside a role clause",
    honorificsInfo: it
      ? "Queste opzioni si applicano solo se sopra è stata selezionata una lingua di traduzione. I titoli NON selezionati qui (Dottore, Reverendo, un ordine religioso, ecc.) vengono spostati nel blocco Note dell'indice invece di rimanere in una formula di ruolo come \"Il padrino era Don Carolus Calsi.\""
      : "These options only apply if a translation language is checked above. Titles NOT checked here (Doctor, Reverend, a religious order, etc.) are moved to the Notes block of the index instead of staying in a role clause like \"The godfather was Don Carolus Calsi.\"",
    honorificsItems: ["Don", "Master"], // literal honorific tokens -- not translated, same as source-language formula text
    addMoreHonorifics: it ? "Aggiungi qui sotto i tuoi ulteriori titoli onorifici:" : "Add your own additional honorifics below:",

    confidenceLabel: it
      ? "Richiedere una valutazione di affidabilità dichiarata con una motivazione di una riga nelle Note?"
      : "Require a stated confidence rating with a one-line rationale in Notes?",
    confidenceInfo: it
      ? "Aggiunge una regola che richiede che le Note di ogni voce indichino un livello di affidabilità — Alto, Medio o Basso — con una motivazione di una riga, ad esempio \"Medio: cognome leggibile ma inchiostro sbiadito.\" Questo ti offre un modo rapido per individuare le voci che meritano un secondo controllo senza dover rileggere ogni trascrizione riga per riga."
      : "Adds a rule requiring every entry's Notes to state a confidence level -- High, Medium, or Low -- with a one-line reason, for example \"Medium: surname legible but ink-faded.\" This gives you a fast way to spot entries worth a second look without re-reading every transcription line by line.",
    confidenceItem: it ? "Sì, richiedi una valutazione di affidabilità" : "Yes, require a confidence rating",

    profileNameLabel: it ? "Nome del profilo che intendi salvare nell'app:" : "Profile name you plan to save this as in the app:",

    checkedByDefaultSuffix: it ? "(selezionata per impostazione predefinita nell'app)" : "(checked by default in the app)",
    allCheckedByDefaultNote: it
      ? "Tutte le voci seguenti sono selezionate per impostazione predefinita nell'app."
      : "All items below are checked by default in the app.",
    infoPrefix: it ? "Informazioni: " : "Info: ",

    pageLabel: it ? "Pagina " : "Page ",
  };
}

// ---------- doc building blocks ----------

function titleBlock(S, recordLabel) {
  return [
    new Paragraph({
      spacing: { after: 60 },
      children: [new TextRun({ text: S.docTitle, bold: true, size: 40, color: ACCENT })],
    }),
    new Paragraph({
      spacing: { after: 200 },
      children: [new TextRun({ text: recordLabel, bold: true, size: 28, color: INK })],
    }),
    new Paragraph({
      spacing: { after: 260 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: RULE, space: 8 } },
      children: [new TextRun({ text: S.introBody, size: 20, color: MUTED })],
    }),
  ];
}

function sectionHeading(number, title, caption) {
  const paras = [
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      spacing: { before: 320, after: 80 },
      children: [new TextRun({ text: title, color: ACCENT, bold: true })],
    }),
  ];
  if (caption) {
    paras.push(new Paragraph({
      spacing: { after: 160 },
      children: [new TextRun({ text: caption, italics: true, size: 19, color: MUTED })],
    }));
  }
  return paras;
}

function fieldLabel(text, opts = {}) {
  const runs = [new TextRun({ text, bold: true, size: 21 })];
  if (opts.note) runs.push(new TextRun({ text: `  ${opts.note}`, italics: true, size: 18, color: MUTED }));
  return new Paragraph({ spacing: { before: 180, after: 40 }, children: runs });
}

function hint(text) {
  return new Paragraph({
    spacing: { after: 60 },
    children: [new TextRun({ text, italics: true, size: 18, color: MUTED })],
  });
}

function infoNote(S, text) {
  return new Paragraph({
    spacing: { after: 140 },
    indent: { left: 200 },
    children: [
      new TextRun({ text: S.infoPrefix, italics: true, bold: true, size: 18, color: MUTED }),
      new TextRun({ text, italics: true, size: 18, color: MUTED }),
    ],
  });
}

function defaultCheckedNote(S) {
  return new Paragraph({
    spacing: { after: 60 },
    children: [new TextRun({ text: S.allCheckedByDefaultNote, italics: true, size: 18, color: MUTED })],
  });
}

function blankLine() {
  return new Paragraph({
    spacing: { after: 160 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE, space: 4 } },
    children: [new TextRun({ text: " ", size: 21 })],
  });
}

function blankLines(n) {
  const out = [];
  for (let i = 0; i < n; i++) out.push(blankLine());
  return out;
}

function choiceList(options) {
  return options.map((text) =>
    new Paragraph({
      spacing: { after: 40 },
      indent: { left: 200 },
      children: [new TextRun({ text: `☐  ${text}`, size: 21 })],
    })
  );
}

function checklistUnchecked(items) {
  return items.map((text) =>
    new Paragraph({
      spacing: { after: 40 },
      indent: { left: 200 },
      children: [new TextRun({ text: `☐  ${text}`, size: 21 })],
    })
  );
}

function soloCheckbox(S, text, { checkedByDefault = false } = {}) {
  const runs = [new TextRun({ text: `☐  ${text}`, size: 21 })];
  if (checkedByDefault) {
    runs.push(new TextRun({ text: `  ${S.checkedByDefaultSuffix}`, italics: true, size: 18, color: MUTED }));
  }
  return new Paragraph({ spacing: { after: 60 }, indent: { left: 200 }, children: runs });
}

function writingBox(S, n, startingText) {
  const inner = [];
  if (startingText) {
    inner.push(new Paragraph({
      spacing: { after: 100 },
      children: [new TextRun({ text: S.startingTextLabel, italics: true, size: 17, color: MUTED })],
    }));
    inner.push(new Paragraph({
      spacing: { after: 140 },
      children: [new TextRun({ text: startingText, italics: true, size: 19, color: INK })],
    }));
    inner.push(new Paragraph({
      spacing: { after: 80 },
      children: [new TextRun({ text: S.yourVersionLabel, italics: true, size: 17, color: MUTED })],
    }));
  }
  for (let i = 0; i < n; i++) {
    inner.push(new Paragraph({
      spacing: { after: 160 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE, space: 4 } },
      children: [new TextRun({ text: " " })],
    }));
  }
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      left: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      right: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      insideHorizontal: { style: BorderStyle.NONE, size: 0, color: RULE },
      insideVertical: { style: BorderStyle.NONE, size: 0, color: RULE },
    },
    rows: [
      new TableRow({
        children: [
          new TableCell({
            width: { size: 100, type: WidthType.PERCENTAGE },
            shading: { type: ShadingType.CLEAR, fill: BOX_SHADE },
            margins: { top: 140, bottom: 140, left: 160, right: 160 },
            children: inner,
          }),
        ],
      }),
    ],
  });
}

function spacer(after = 120) {
  return new Paragraph({ spacing: { after }, children: [] });
}

// ---------- Section 1 ----------

function section1(S, recordLabel) {
  return [
    ...sectionHeading(1, S.s1Title, S.s1Caption),

    fieldLabel(S.recordTypeLabel),
    new Paragraph({ spacing: { after: 160 }, indent: { left: 200 },
      children: [new TextRun({ text: `☒  ${recordLabel}`, size: 21, bold: true })] }),

    fieldLabel(S.sourceLanguageLabel),
    ...choiceList(S.sourceLanguageOptions),

    fieldLabel(S.eraLabel, { note: S.eraNote }),
    blankLine(),
    fieldLabel(S.localityLabel, { note: S.localityNote }),
    blankLine(),
    fieldLabel(S.provinceLabel, { note: S.provinceNote }),
    blankLine(),
    fieldLabel(S.institutionLabel, { note: S.institutionNote }),
    blankLine(),
    fieldLabel(S.volumeLabel, { note: S.volumeNote }),
    blankLine(),
    fieldLabel(S.handLabel, { note: S.handNote }),
    blankLine(),

    fieldLabel(S.pageLayoutLabel),
    ...choiceList(S.pageLayoutOptions),

    fieldLabel(S.pageNumberSchemeLabel),
    ...choiceList(S.pageNumberSchemeOptions),

    fieldLabel(S.pageNumberCornerLabel, { note: S.pageNumberCornerNote }),
    blankLine(),

    fieldLabel(S.declensionLabel),
    soloCheckbox(S, S.declensionItem, { checkedByDefault: true }),
    infoNote(S, S.declensionInfo),

    fieldLabel(S.monthLabel),
    ...choiceList(S.monthOptions),

    fieldLabel(S.hourLabel),
    ...choiceList(S.hourOptions),

    fieldLabel(S.relativeDateLabel),
    defaultCheckedNote(S),
    ...checklistUnchecked(S.relativeDateItems),
    hint(S.addMoreRelativeDate),
    ...blankLines(3),
  ];
}

// ---------- Section 2 ----------

function section2(S, type) {
  const out = [
    ...sectionHeading(2, S.s2Title, S.s2Caption),

    fieldLabel(S.marginalQuestionLabel),
    soloCheckbox(S, S.marginalYesItem, { checkedByDefault: type.hasMarginalHeadingDefault }),
    infoNote(S, S.marginalInfo(type.marginalPlaceholder)),

    fieldLabel(S.marginalStructureLabel, { note: S.marginalStructureNote }),
    writingBox(S, 3, type.marginalPlaceholder),
  ];

  for (const f of type.formulaFields) {
    out.push(fieldLabel(f.label, f.optional ? { note: S.formulaOptionalNote } : undefined));
    out.push(infoNote(S, S.formulaInfo));
    out.push(writingBox(S, 4, f.placeholder));
  }

  out.push(fieldLabel(S.roleVocabLabel(type.label), { note: S.roleVocabNote }));
  out.push(infoNote(S, S.roleVocabInfo));
  out.push(defaultCheckedNote(S));
  out.push(...checklistUnchecked(type.roleVocab));
  out.push(hint(S.addMoreRoleVocab));
  out.push(...blankLines(2));

  out.push(fieldLabel(S.entryVariantsLabel, { note: S.entryVariantsNote }));
  out.push(...blankLines(3));

  out.push(fieldLabel(S.relationshipLabel));
  out.push(defaultCheckedNote(S));
  out.push(...checklistUnchecked(S.relationshipItems));
  out.push(hint(S.addMoreRelationship));
  out.push(...blankLines(2));

  out.push(fieldLabel(S.abbrevLabel));
  out.push(defaultCheckedNote(S));
  out.push(...checklistUnchecked(S.abbrevItems));
  out.push(hint(S.addMoreAbbrev));
  out.push(...blankLines(3));

  out.push(fieldLabel(S.scribalLabel));
  out.push(infoNote(S, S.scribalInfo));
  out.push(defaultCheckedNote(S));
  out.push(...checklistUnchecked(S.scribalItems));
  out.push(hint(S.addMoreScribal));
  out.push(...blankLines(2));

  out.push(fieldLabel(S.surnameParticleLabel, { note: S.surnameParticleNote }));
  out.push(soloCheckbox(S, S.surnameParticleItem, { checkedByDefault: true }));

  out.push(fieldLabel(S.lexiconLabel, { note: S.lexiconNote }));
  out.push(infoNote(S, S.lexiconInfo));
  out.push(hint(S.lexiconHint));
  out.push(writingBox(S, 10, null));

  return out;
}

// ---------- Section 3 ----------

function section3(S) {
  return [
    ...sectionHeading(3, S.s3Title, S.s3Caption),

    fieldLabel(S.exampleEntryLabel, { note: S.exampleEntryNote }),
    writingBox(S, 8, null),

    fieldLabel(S.translationLabel, { note: S.translationNote }),
    ...checklistUnchecked(S.translationItems),

    fieldLabel(S.translationStyleLabel, { note: S.translationStyleNote }),
    ...checklistUnchecked(S.translationStyleItems),

    fieldLabel(S.honorificsLabel),
    infoNote(S, S.honorificsInfo),
    defaultCheckedNote(S),
    ...checklistUnchecked(S.honorificsItems),
    hint(S.addMoreHonorifics),
    ...blankLines(2),

    fieldLabel(S.confidenceLabel),
    infoNote(S, S.confidenceInfo),
    soloCheckbox(S, S.confidenceItem, { checkedByDefault: true }),

    spacer(200),
    new Paragraph({
      border: { top: { style: BorderStyle.SINGLE, size: 6, color: RULE, space: 8 } },
      spacing: { before: 100, after: 40 },
      children: [new TextRun({ text: S.profileNameLabel, bold: true, size: 21 })],
    }),
    blankLine(),
  ];
}

// ---------- record type configs (church only) ----------
// marginalPlaceholder and formulaFields[].placeholder are the register's own
// source-language sample text (Latin) -- identical in both language editions,
// same as the app's own formula textareas are never translated.

const TYPES = {
  battesimi: {
    fileSlug: "prompt-builder-worksheet-church-battesimi",
    fileSlugIt: "generatore-di-prompt-battesimi-parrocchiali",
    label: { en: "Church Battesimi", it: "Battesimi parrocchiali" },
    hasMarginalHeadingDefault: true,
    marginalPlaceholder: "[child's name] filius/filia [father] et [mother] [surname]",
    formulaFields: {
      en: [
        {
          label: "Entry structure -- write out the structure used in each entry",
          placeholder: "Ego Sac.os D. [CELEBRANT] ... hodie baptizavi infantem ... natum/natam ex [FATHER] et [MOTHER] [SURNAME], cui nomen imposui [CHILD'S NAME]. P.nus/P.na/PP. fuit/fuere [GODPARENT(S)].",
          optional: false,
        },
      ],
      it: [
        {
          label: "Struttura della voce - descrivi la struttura usata in ogni voce",
          placeholder: "Ego Sac.os D. [CELEBRANT] ... hodie baptizavi infantem ... natum/natam ex [FATHER] et [MOTHER] [SURNAME], cui nomen imposui [CHILD'S NAME]. P.nus/P.na/PP. fuit/fuere [GODPARENT(S)].",
          optional: false,
        },
      ],
    },
    roleVocab: {
      en: [
        "P.nus / Patrinus = godfather (one male)",
        "P.na / Patrina = godmother (one female)",
        "PP. / Patrini = two or more godparents",
        "fuit = singular verb, fuere/fuerunt = plural verb",
      ],
      it: [
        "P.nus / Patrinus = padrino (un uomo)",
        "P.na / Patrina = madrina (una donna)",
        "PP. / Patrini = due o più padrini/madrine",
        "fuit = verbo singolare, fuere/fuerunt = verbo plurale",
      ],
    },
  },
  matrimoni: {
    fileSlug: "prompt-builder-worksheet-church-matrimoni",
    fileSlugIt: "generatore-di-prompt-matrimoni-parrocchiali",
    label: { en: "Church Matrimoni", it: "Matrimoni parrocchiali" },
    hasMarginalHeadingDefault: true,
    marginalPlaceholder: "[Groom] et [Bride]",
    formulaFields: {
      en: [
        { label: "Groom's formula", placeholder: "the groom clause: name, then \"filius [Father] et [Mother]\"", optional: false },
        { label: "Bride's formula", placeholder: "the bride clause: name, then \"filia [Father] et [Mother]\"", optional: false },
        { label: "Witness formula", placeholder: "how witnesses are introduced, e.g. \"Testes fuerunt [Witness1] et [Witness2]\"", optional: true },
      ],
      it: [
        { label: "Formula dello sposo", placeholder: "the groom clause: name, then \"filius [Father] et [Mother]\"", optional: false },
        { label: "Formula della sposa", placeholder: "the bride clause: name, then \"filia [Father] et [Mother]\"", optional: false },
        { label: "Formula dei testimoni", placeholder: "how witnesses are introduced, e.g. \"Testes fuerunt [Witness1] et [Witness2]\"", optional: true },
      ],
    },
    roleVocab: {
      en: [
        "Testis / Testes = witness(es)",
        "sponsus = groom",
        "sponsa = bride",
        "Testis fuit = singular verb, Testes fuerunt = plural verb",
      ],
      it: [
        "Testis / Testes = testimone/i",
        "sponsus = sposo",
        "sponsa = sposa",
        "Testis fuit = verbo singolare, Testes fuerunt = verbo plurale",
      ],
    },
  },
  morti: {
    fileSlug: "prompt-builder-worksheet-church-morti",
    fileSlugIt: "generatore-di-prompt-morti-parrocchiali",
    label: { en: "Church Morti", it: "Morti parrocchiali" },
    hasMarginalHeadingDefault: true,
    marginalPlaceholder: "[deceased's name]",
    formulaFields: {
      en: [
        {
          label: "Entry structure -- write out the structure used in each entry",
          placeholder: "...obiit [NAME], [AGE] annorum, filius/filia [FATHER] et [MOTHER] ...",
          optional: false,
        },
      ],
      it: [
        {
          label: "Struttura della voce - descrivi la struttura usata in ogni voce",
          placeholder: "...obiit [NAME], [AGE] annorum, filius/filia [FATHER] et [MOTHER] ...",
          optional: false,
        },
      ],
    },
    roleVocab: {
      en: ["vidua = widow", "viduus = widower", "conjux / uxor = spouse / wife"],
      it: ["vidua = vedova", "viduus = vedovo", "conjux / uxor = coniuge / moglie"],
    },
  },
};

// ---------- assemble & write ----------

function buildDoc(lang, type) {
  const S = strings(lang);
  const recordLabel = type.label[lang];
  const typeForSection2 = {
    label: recordLabel,
    hasMarginalHeadingDefault: type.hasMarginalHeadingDefault,
    marginalPlaceholder: type.marginalPlaceholder,
    formulaFields: type.formulaFields[lang],
    roleVocab: type.roleVocab[lang],
  };

  const children = [
    ...titleBlock(S, recordLabel),
    ...section1(S, recordLabel),
    ...section2(S, typeForSection2),
    ...section3(S),
  ];

  return new Document({
    creator: "Transcription Bot",
    title: `${S.docTitle} — ${recordLabel}`,
    sections: [
      {
        properties: {
          page: {
            size: { width: 12240, height: 15840 }, // US Letter
            margin: { top: 1080, bottom: 1080, left: 1080, right: 1080 },
          },
        },
        headers: {
          default: new Header({
            children: [
              new Paragraph({
                alignment: AlignmentType.RIGHT,
                children: [new TextRun({ text: `${S.docTitle} — ${recordLabel}`, size: 16, color: MUTED })],
              }),
            ],
          }),
        },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [
                  new TextRun({ text: S.pageLabel, size: 16, color: MUTED }),
                  new TextRun({ children: [PageNumber.CURRENT], size: 16, color: MUTED }),
                ],
              }),
            ],
          }),
        },
        children,
      },
    ],
  });
}

async function main() {
  for (const lang of ["en", "it"]) {
    const dir = path.join(OUT_DIR, lang);
    fs.mkdirSync(dir, { recursive: true });
    for (const key of Object.keys(TYPES)) {
      const type = TYPES[key];
      const doc = buildDoc(lang, type);
      const buf = await Packer.toBuffer(doc);
      const slug = lang === "it" ? type.fileSlugIt : type.fileSlug;
      const outPath = path.join(dir, `${slug}.docx`);
      fs.writeFileSync(outPath, buf);
      console.log("wrote", outPath);
    }
  }
}

main().catch((err) => { console.error(err); process.exit(1); });
