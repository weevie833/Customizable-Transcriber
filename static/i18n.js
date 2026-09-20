/*
 * Client-side EN/IT toggle for the Customizable Transcription UI.
 *
 * Scope: static UI chrome (headings, nav, labels, buttons, hints,
 * placeholders, footers) plus the settings-alert modal (showSettingsAlert()
 * in static/app-common.js) and the run-status/run-button labels JS rewrites
 * at runtime (updateRunStatus()/updateRunButton() in this file's own
 * callers) -- all three used to bypass DICTIONARY entirely (a raw
 * `.textContent =`/`.title =` assignment isn't something this file walks
 * and translates on its own) and stayed English regardless of the selected
 * language; each now calls window.tbRefreshLanguage() (exposed below) right
 * after setting its text, or -- for a message assembled from variable parts
 * (missingRunSettingMessage()/apiKeyMismatchMessage()) -- runs it through
 * window.tbTranslateStatusText()'s pattern matching first, since no single
 * DICTIONARY key can cover every combination it can produce.
 *
 * Still NOT translated: user-entered profile content, and transcription/
 * log output itself (the free-form text inside #log, as opposed to the
 * fixed status labels around it) -- those stay English by design. The
 * #summary/#log status text and the alert/label text above share the same
 * pattern-based translator, window.tbTranslateStatusText() below -- see its
 * own comment for the full set of callers.
 *
 * How it works: on load it reads the stored language preference and, if
 * Italian, walks the DOM once translating any text node or attribute whose
 * *exact* trimmed value matches a key in DICTIONARY below, saving the
 * original English value first so switching back to English is an exact
 * restore rather than a second lossy translation pass.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "tb-lang";

  // Persisted as a cookie (not localStorage) so the choice is a plain,
  // inspectable browser cookie as requested for the homepage's language
  // picker -- every .lang-flag button on every page reads/writes this same
  // cookie, so they all stay in sync no matter which page set it.
  var COOKIE_DAYS = 400; // Chrome's own cookie-expiry cap; longest safe value.

  function getCookie(name) {
    var match = document.cookie.match(
      new RegExp("(?:^|; )" + name.replace(/([.$?*|{}()\[\]\\/+^])/g, "\\$1") + "=([^;]*)")
    );
    return match ? decodeURIComponent(match[1]) : null;
  }

  function setCookie(name, value, days) {
    var date = new Date();
    date.setTime(date.getTime() + days * 24 * 60 * 60 * 1000);
    document.cookie =
      name + "=" + encodeURIComponent(value) + "; expires=" + date.toUTCString() + "; path=/; SameSite=Lax";
  }

  // English -> Italian. Keys must match the exact (trimmed) text as it
  // appears in the DOM/attribute; anything without a match is left as-is.
  var DICTIONARY = {
    // Shared chrome: nav, footer, alerts
    "Skip to main content": "Vai al contenuto principale",
    "Run settings needed": "Impostazioni di esecuzione mancanti",
    "OK": "OK",
    "Transcribe": "Trascrivi",
    "XLSX Conversion": "Conversione XLSX",
    "Test Mode": "Modalità di test",
    "Prompt Builder": "Generatore di prompt",
    "Home": "Home",
    "Customizable Transcription — Home": "Trascrizione Personalizzabile — Home",
    "Welcome to the Customizable Transcription application.": "Benvenuti nell'applicazione di Trascrizione Personalizzabile.",
    "Getting Started": "Per iniziare",
    "Primary navigation": "Navigazione principale",
    // The footer license string below includes a trailing "·" -- the text
    // node in the DOM is the license sentence *plus* the &middot; separator
    // before the Privacy link, all in one node, so the dictionary key must
    // match that exact trimmed string or the whole sentence silently stops
    // translating (found while auditing Prompt Builder's i18n coverage --
    // this one affects all 7 pages, predating that specific rework). Same
    // text everywhere now (see pages/__init__.py's FOOTER_HTML and
    // xls_conversion/index.html's own copy of it), so one dictionary entry
    // covers every page instead of one per distinct wording.
    "© 2026 Steve Covello. All rights reserved — free to download and run for personal use; redistribution, hosting, and derivative works require permission. ·":
      "© 2026 Steve Covello. Tutti i diritti riservati — libero da scaricare ed eseguire per uso personale; la ridistribuzione, l'hosting e le opere derivate richiedono un'autorizzazione. ·",

    // Source folder / run controls shared by Transcribe + Test Mode
    "Source folder": "Cartella di origine",
    "Browse…": "Sfoglia…",
    "Reset All": "Reimposta tutto",
    "Reset": "Reimposta",
    "Or paste an absolute folder path": "Oppure incolla un percorso di cartella assoluto",
    "Use this path": "Usa questo percorso",
    "Browse opens a native folder dialog.": "Sfoglia apre una finestra di selezione cartella nativa.",
    "Model": "Modello",
    "API key": "Chiave API",
    "Select a model": "Seleziona un modello",
    "Used only for this browser session/request. It is not saved to the project files. Submitting a run sends this key and the selected source content directly to your chosen AI provider's API — see PRIVACY.md.":
      "Usata solo per questa sessione/richiesta del browser. Non viene salvata nei file del progetto. L'avvio di un'esecuzione invia questa chiave e il contenuto sorgente selezionato direttamente all'API del provider IA scelto — consulta PRIVACY.md.",
    "Used only for this browser session/request. It is not saved to the project files. Converting sends this key and the selected source content directly to your chosen AI provider's API — see PRIVACY.md.":
      "Usata solo per questa sessione/richiesta del browser. Non viene salvata nei file del progetto. La conversione invia questa chiave e il contenuto sorgente selezionato direttamente all'API del provider IA scelto — consulta PRIVACY.md.",
    "Paste your API key for this run": "Incolla la tua chiave API per questa esecuzione",
    "Gemini API key": "Chiave API Gemini",
    "Claude API key": "Chiave API Claude",
    "Paste your Gemini API key": "Incolla la tua chiave API Gemini",
    "Paste your Claude API key": "Incolla la tua chiave API Claude",
    "Only the key(s) actually needed are required -- if every model in use is Gemini, the Claude field can stay blank, and vice versa. Whichever key matches a given run's own model is the one used for that run, so one queue can freely mix Gemini and Claude models. Not saved to the project files. Submitting a run sends the matching key and the selected source content directly to that provider's API — see PRIVACY.md.":
      "Sono richieste solo le chiavi effettivamente necessarie -- se tutti i modelli in uso sono Gemini, il campo Claude può restare vuoto, e viceversa. La chiave usata per ciascuna esecuzione è quella corrispondente al modello di quella esecuzione, quindi una singola coda può mescolare liberamente modelli Gemini e Claude. Non viene salvata nei file del progetto. L'avvio di un'esecuzione invia la chiave corrispondente e il contenuto sorgente selezionato direttamente all'API di quel provider — consulta PRIVACY.md.",
    "Process order": "Ordine di elaborazione",
    "Oldest-to-newest": "Dal più vecchio al più recente",
    "Newest-to-oldest": "Dal più recente al più vecchio",
    "File type": "Tipo di file",
    "JPEG includes .jpg and .jpeg files.": "JPEG include i file .jpg e .jpeg.",
    "Prompt profile": "Profilo del prompt",
    "Select a Profile": "Seleziona un profilo",
    "Delete Profile": "Elimina profilo",
    "Preflight Check": "Controllo preliminare",
    "Confirm and run": "Conferma ed esegui",
    // Off-Peak Mode (batch_transcription.py/handlers/transcribe_offpeak.py).
    // "Confirm and Run Now" replaced the old "Confirm and run" label above
    // on the Transcribe page specifically, to disambiguate it from the new
    // "Confirm and Run<br>Off-Peak" button next to it -- Test Mode's own
    // identical button kept the original wording, so that entry above is
    // still live, just no longer covering Transcribe. The off-peak button's
    // two lines are two separate DOM text nodes (split by the <br>), so
    // each needs its own key. "Off-Peak" is deliberately kept as an English
    // loanword (not translated) rather than given an entry, matching how
    // the feature is referred to as "Modalità Off-Peak" everywhere else in
    // this dictionary and in GETTING_STARTED.it.html -- there is no
    // separate Italian term for it in this app.
    "Confirm and Run Now": "Conferma ed esegui ora",
    "Confirm and Run": "Conferma ed esegui",
    "Confirm settings:": "Conferma impostazioni:",
    "Progress:": "Avanzamento:",
    // updateRunStatus() (static/app-common.js): a third branch alongside
    // "Progress:"/"Confirm settings:" above, for an off-peak run specifically.
    "Off-peak progress:": "Avanzamento off-peak:",
    // Settings-alert modal (showSettingsAlert()) titles/messages and the
    // Run button's tooltip (both set via a raw .textContent/.title
    // assignment -- see this file's own top-of-file comment on why these
    // need window.tbRefreshLanguage() rather than just a DICTIONARY entry).
    // ("Run settings needed", the modal's default title, already has an
    // entry near the top of this dictionary.)
    "Batch completed": "Lotto completato",
    "Scroll down and review the Progress Console and click the Download Document button.":
      "Scorri verso il basso, controlla la Console di avanzamento e clicca sul pulsante Scarica documento.",
    "Scroll down and review the Progress Console and download each model's document.":
      "Scorri verso il basso, controlla la Console di avanzamento e scarica il documento di ciascun modello.",
    "Please run the preflight check before starting transcription.":
      "Esegui il controllo preliminare prima di avviare la trascrizione.",
    "Please run the preflight check before starting.":
      "Esegui il controllo preliminare prima di avviare l'esecuzione.",
    "Paste a folder path first.": "Incolla prima un percorso di cartella.",
    "Couldn't open the folder picker.": "Impossibile aprire il selettore di cartelle.",
    "Couldn't open the outputs folder.": "Impossibile aprire la cartella di output.",
    "Couldn't use that path.": "Impossibile usare quel percorso.",
    "A transcription process is already running.": "Un processo di trascrizione è già in corso.",
    "Choose a source folder before running transcription.":
      "Scegli una cartella di origine prima di avviare la trascrizione.",
    "Paste your Gemini API key before running transcription.":
      "Incolla la tua chiave API di Gemini prima di avviare la trascrizione.",
    "Select a prompt profile before running transcription.":
      "Seleziona un profilo del prompt prima di avviare la trascrizione.",
    "Check selected settings before transcription.":
      "Controlla le impostazioni selezionate prima della trascrizione.",
    "A test run is already in progress.": "Un'esecuzione di test è già in corso.",
    "Paste the API key for each model provider in use before running.":
      "Incolla la chiave API per ciascun provider di modello in uso prima di procedere.",
    "Select a prompt profile before running.": "Seleziona un profilo del prompt prima di procedere.",
    "Check selected settings before running.": "Controlla le impostazioni selezionate prima di procedere.",
    "Order:": "Ordine:",
    "File type:": "Tipo di file:",
    "Prompt Profile:": "Profilo del prompt:",
    "Process running. Review the Progress Console below.":
      "Elaborazione in corso. Controlla la Console di avanzamento qui sotto.",
    "Progress Console": "Console di avanzamento",
    "Stop": "Interrompi",
    "Download Document": "Scarica documento",
    "Refresh Status": "Aggiorna stato",
    "Open Outputs Folder": "Apri cartella di output",
    "The DOCX file will be downloaded to wherever your browser saves downloaded files. Check your browser's Downloads button for download history.":
      "Il file DOCX verrà scaricato nella cartella in cui il tuo browser salva i file scaricati. Controlla il pulsante Download del tuo browser per la cronologia dei download.",
    "Output:": "Output:",

    // Transcribe page
    // Off-Peak Mode info-button popup (OFF_PEAK_INFO_TEXT, pages/transcribe.py).
    "Off-Peak Mode submits your whole run to your provider's batch queue instead of processing images in real time -- typically billed at roughly half the standard per-token rate. The app must stay open and running for the entire job; there is no way to submit it and close the app. The provider processes it on its own schedule, which can take anywhere from a few minutes to several hours -- there is no guaranteed turnaround time. Clicking Stop cancels the batch entirely on the provider's side: any images not yet completed are lost, not paused.":
      "La Modalità Off-Peak invia l'intera esecuzione alla coda batch del tuo provider invece di elaborare le immagini in tempo reale — di norma fatturata a circa la metà della tariffa standard per token. L'app deve rimanere aperta e in esecuzione per tutta la durata del lavoro; non è possibile inviarlo e poi chiudere l'app. Il provider lo elabora secondo i propri tempi, che possono variare da pochi minuti a diverse ore — non è garantito alcun tempo di consegna. Cliccando su Interrompi, il lotto viene annullato completamente lato provider: le immagini non ancora completate vengono perse, non messe in pausa.",
    "Use the Prompt Builder page to create prompts, or bypass the Prompt Builder and place your prompt in the sections below. Manual prompts cannot be edited in the Prompt Builder.":
      "Usa la pagina Prompt Builder per creare i prompt, oppure aggira il Prompt Builder e inserisci il tuo prompt nelle sezioni qui sotto. I prompt inseriti manualmente non possono essere modificati nel Prompt Builder.",
    "Manual prompts can only be edited here - they cannot be edited in the Prompt Builder.":
      "I prompt inseriti manualmente possono essere modificati solo qui - non possono essere modificati nel Prompt Builder.",
    "Manual Prompt Override": "Prompt manuale personalizzato",
    "Save new custom profile as": "Salva nuovo profilo personalizzato come",
    "Leave blank to update the selected profile. Enter a new name to save the three boxes below as a reusable profile.":
      "Lascia vuoto per aggiornare il profilo selezionato. Inserisci un nuovo nome per salvare le tre caselle qui sotto come profilo riutilizzabile.",
    "Example: Palermo baptisms": "Esempio: Battesimi di Palermo",
    "Save Profile": "Salva profilo",
    "Role and local context": "Ruolo e contesto locale",
    "Plain text. Shows the profile role plus tone and style. Edit this box to update the selected profile or create a new version when you run transcription.":
      "Testo semplice. Mostra il ruolo del profilo, oltre a tono e stile. Modifica questa casella per aggiornare il profilo selezionato o creare una nuova versione quando avvii la trascrizione.",
    "Ground truth and reference material": "Materiale di riferimento e dati verificati",
    "Plain text. Shows the profile technical reference, taxonomy, dictionaries, names, places, formulas, and ground truth material.":
      "Testo semplice. Mostra i riferimenti tecnici del profilo, la tassonomia, i dizionari, i nomi, i luoghi, le formule e il materiale di riferimento verificato.",
    "Output format": "Formato di output",
    "Plain text. Shows the profile output structure and transcription/translation examples.":
      "Testo semplice. Mostra la struttura di output del profilo e gli esempi di trascrizione/traduzione.",
    "The profile sections below are plain text fields. The app handles JSON formatting automatically when it saves, so quotes, brackets, and commas typed here will not break the profile file.":
      "Le sezioni del profilo qui sotto sono campi di testo semplice. L'app gestisce automaticamente la formattazione JSON al salvataggio, quindi virgolette, parentesi e virgole digitate qui non danneggeranno il file del profilo.",

    // Test Mode page
    "Test Mode - Model Comparison": "Modalità di test - Confronto tra modelli",
    "Runs the same source images and prompt profile through different models to compare performance.":
      "Esegue le stesse immagini di origine e lo stesso profilo di prompt su diversi modelli per confrontarne le prestazioni.",
    "Model A": "Modello A",
    "Model B": "Modello B",
    "Batch label (optional)": "Etichetta del batch (opzionale)",
    "Example: Gemini 3.1 Pro Preview vs Claude Opus 5": "Esempio: Gemini 3.1 Pro Preview vs Claude Opus 5",
    "Add to Batch": "Aggiungi al batch",
    "Batch queue": "Coda dei batch",
    "No batches queued yet. Click \"Add to Batch\" to queue the Model A/B pair above, or leave the queue empty and just run this one pair directly.":
      "Nessun batch ancora in coda. Fai clic su \"Aggiungi al batch\" per accodare la coppia Modello A/B sopra, oppure lascia la coda vuota ed esegui direttamente questa singola coppia.",
    "Batches:": "Batch:",
    "Test Mode runs the profile as saved — edit or create profiles from the Transcribe page.":
      "La Modalità di test esegue il profilo così com'è salvato — modifica o crea profili dalla pagina Trascrivi.",
    // Test Mode — Compare transcripts (DOCX) collapsible section. Key was
    // "Compare Results" until the heading text itself changed to
    // "Compare transcripts (DOCX)" when Index Compare was added below it
    // (to distinguish the two sections) -- the dictionary key was never
    // updated to match, so the heading silently stopped translating. Found
    // auditing i18n coverage for the Index Compare DOCX-report rework.
    "Compare transcripts (DOCX)": "Confronta trascrizioni (DOCX)",
    "Upload uncorrected DOCX transcripts to compare to a corrected DOCX.":
      "Carica le trascrizioni DOCX non corrette da confrontare con un DOCX corretto.",
    "Label for this model": "Etichetta per questo modello",
    "Add another": "Aggiungi un altro",
    "100% Corrected DOCX": "DOCX corretto al 100%",
    "This label doesn't appear in the results table (the corrected file is the yardstick every row is measured against, not a row itself) — it's carried into the downloadable report so the ground truth used is easy to identify later.":
      "Questa etichetta non compare nella tabella dei risultati (il file corretto è il metro di paragone rispetto a cui ogni riga viene misurata, non è una riga essa stessa) — viene riportata nel report scaricabile in modo da poter identificare facilmente in seguito i dati di riferimento usati.",
    "Run Comparison": "Esegui confronto",
    "Compare each transcript against a fully corrected version of the same content. Results show different types of error rates.":
      "Confronta ogni trascrizione con una versione completamente corretta dello stesso contenuto. I risultati mostrano diversi tipi di tassi di errore.",
    "Download Comparison Report": "Scarica il report di confronto",
    "Explains CER/WER/WER-BoW in plain language and estimates the correction effort each score implies.":
      "Spiega CER/WER/WER-BoW in linguaggio semplice e stima lo sforzo di correzione implicato da ciascun punteggio.",

    // Test Mode — Compare Indexes (XLSX) collapsible section (index_compare/)
    "Compare Indexes (XLSX)": "Confronta indici (XLSX)",
    "Each candidate XLSX index is scored for statistical accuracy against the 100% Corrected XLSX index -- a downloadable report ranks them by character error rate, the same way the Compare Transcripts report above ranks transcripts. It does not list individual field differences; review a candidate's own spreadsheet against the corrected index by eye to find and fix specific entries.":
      "Ogni indice XLSX candidato viene valutato per accuratezza statistica rispetto all'indice XLSX corretto al 100% — un report scaricabile li classifica in base al tasso di errore sui caratteri, allo stesso modo in cui il report di confronto trascrizioni qui sopra classifica le trascrizioni. Non elenca le differenze dei singoli campi; confronta a occhio il foglio di calcolo di ciascun candidato con l'indice corretto per trovare e correggere le singole voci.",
    "100% Corrected XLSX": "XLSX corretto al 100%",
    "Label for this index": "Etichetta per questo indice",

    // Prompt Builder page
    "Pick from presets below to describe your register. The app assembles a complete transcription profile from your answers. It becomes available on the Transcribe and Test Mode pages, but you must reload those pages first before they will appear.":
      "Scegli tra le opzioni preimpostate qui sotto per descrivere il tuo registro. L'app assembla un profilo di trascrizione completo dalle tue risposte. Diventa disponibile nelle pagine Trascrivi e Modalità di test, ma devi prima ricaricare quelle pagine perché compaia.",
    "Expand all": "Espandi tutto",
    "Collapse all": "Comprimi tutto",
    "Reset form": "Reimposta modulo",
    "1. Role & Local Context": "1. Ruolo e contesto locale",
    "2. Reference Material": "2. Materiale di riferimento",
    "3. Output Format": "3. Formato di output",
    "Full prompt preview": "Anteprima del prompt completo",
    "as sent to the model": "come inviato al modello",
    "Read-only. This is the three sections above assembled exactly the way the app builds the real system prompt — including the fixed rules and headers it adds automatically — so you can see what the AI actually receives.":
      "Sola lettura. Queste sono le tre sezioni sopra assemblate esattamente come l'app costruisce il prompt di sistema reale — comprese le regole fisse e le intestazioni che aggiunge automaticamente — così puoi vedere cosa riceve realmente l'IA.",
    "Save this as a new profile": "Salva come nuovo profilo",
    "e.g. Caiazzo Battesimi 1780s": "es. Caiazzo Battesimi 1780s",
    "Creates a new profile file; it never overwrites another profile.": "Crea un nuovo file di profilo; non sovrascrive mai un altro profilo.",
    "Load an existing profile to edit": "Carica un profilo esistente da modificare",
    "Select a profile": "Seleziona un profilo",
    "Create a new profile": "Crea un nuovo profilo",
    "Only profiles created or edited in the Prompt Builder can be edited here - custom profiles are excluded. Saving edits will update that same profile unless you choose \"Save as a new profile\" instead.":
      "Qui possono essere modificati solo i profili creati o modificati nel Prompt Builder — i profili personalizzati sono esclusi. Salvando le modifiche si aggiornerà lo stesso profilo, a meno che tu non scelga \"Salva come nuovo profilo\".",
    "Update Profile": "Aggiorna profilo",
    "Save as New Profile": "Salva come nuovo profilo",
    "Answer these questions to define who the AI is, what it's transcribing, and the ground rules for accuracy: your record type, source language, era, place, and page layout. The uncertainty protocol (never guess a name, use [illegible] instead) and fidelity rules (preserve spelling, don't silently correct the scribe) are generated automatically — every profile gets them, no matter what you select below.":
      "Rispondi a queste domande per definire chi è l'IA, cosa sta trascrivendo e le regole di base per l'accuratezza: il tipo di registro, la lingua di origine, l'epoca, il luogo e l'impaginazione della pagina. Il protocollo per l'incertezza (non indovinare mai un nome, usa invece [illeggibile]) e le regole di fedeltà (conserva l'ortografia, non correggere silenziosamente lo scriba) vengono generati automaticamente — ogni profilo li riceve, indipendentemente da cosa selezioni qui sotto.",
    "Answer these questions to give the AI your project's own ground truth: the standard formula your register's entries follow, an abbreviation key for the hand and language, and — optionally — a name lexicon (surnames and given names actually attested in your source) so it can break ties between similar letterforms without inventing names that aren't real. A lexicon only ever breaks ties; it never overrules what's on the page.":
      "Rispondi a queste domande per fornire all'IA i dati di riferimento del tuo progetto: la formula standard seguita dalle voci del tuo registro, una legenda delle abbreviazioni per la grafia e la lingua e — facoltativamente — un lessico dei nomi (cognomi e nomi propri effettivamente attestati nella tua fonte) così da poter risolvere i dubbi tra forme di lettere simili senza inventare nomi che non esistono. Un lessico serve solo a risolvere i dubbi; non prevale mai su ciò che è scritto sulla pagina.",
    "Answer these questions to define the exact text format the AI must output. Choose whether you want a translation at all, and in which language(s) — the locator line and block structure below are generated for you from that choice and your Section 1 answers.":
      "Rispondi a queste domande per definire il formato di testo esatto che l'IA deve produrre. Scegli se vuoi una traduzione e in quale lingua o lingue — la riga del localizzatore e la struttura a blocchi qui sotto vengono generate automaticamente in base a questa scelta e alle tue risposte nella Sezione 1.",

    // Prompt Builder — Section 1 questionnaire fields
    "Record type": "Tipo di registro",
    "Source language": "Lingua di origine",
    "Latin": "Latino",
    "Italian": "Italiano",
    "Other": "Altro",
    "Latin and Italian mixed": "Latino e italiano misti",
    "Era": "Epoca",
    "Locality": "Località",
    "Province / region": "Provincia / regione",
    "Institution name": "Nome dell'istituzione",
    "Volume / date range covered": "Volume / intervallo di date coperto",
    "Hand / script descriptor (optional)": "Descrizione della grafia (opzionale)",
    "Page layout": "Impaginazione della pagina",
    "One page per image": "Una pagina per immagine",
    "Two facing pages, read left then right": "Due pagine affiancate, lette da sinistra a destra",
    "Page-numbering scheme": "Schema di numerazione delle pagine",
    "No page numbers": "Nessun numero di pagina",
    "One number per image": "Un numero per immagine",
    "Two numbers, one per facing page": "Due numeri, uno per pagina affiancata",
    "Register has its own act/entry numbers": "Il registro ha i propri numeri di atto/voce",
    "Where are the page numbers?": "Dove si trovano i numeri di pagina?",
    "Include Latin grammatical case-declension guidance": "Includi le indicazioni sulla declinazione grammaticale latina",
    "Month-abbreviation convention": "Convenzione delle abbreviazioni dei mesi",
    "Latin March-counting (7bris-10bris)": "Conteggio latino da marzo (7bris-10bris)",
    "Standard month names": "Nomi standard dei mesi",
    "Hour convention": "Convenzione oraria",
    "Italian hours, counted from sunset": "Ore italiane, contate dal tramonto",
    "Standard clock time": "Ora standard dell'orologio",
    "Not applicable": "Non applicabile",
    "Relative-date vocabulary": "Vocabolario delle date relative",
    "nudius tertius = day before yesterday": "nudius tertius = l'altro ieri",
    "hodie = today": "hodie = oggi",
    "hac nocte = last night": "hac nocte = la notte scorsa",
    "die praeterita = yesterday": "die praeterita = ieri",
    "ejusdem = of the same (month)": "ejusdem = dello stesso (mese)",
    "Add another term": "Aggiungi un altro termine",
    "e.g. 18th-century": "es. XVIII secolo",
    "e.g. Chiusa Sclafani": "es. Chiusa Sclafani",
    "e.g. province of Palermo, Sicily": "es. provincia di Palermo, Sicilia",
    "e.g. the parish church of San Nicolò di Bari": "es. la parrocchia di San Nicolò di Bari",
    "e.g. 1752-1759": "es. 1752-1759",
    "e.g. Sicilian ecclesiastical chancery hand": "es. grafia cancelleresca ecclesiastica siciliana",
    "e.g. upper corner, left page's number upper-left, right page's upper-right":
      "es. angolo superiore, il numero della pagina sinistra in alto a sinistra, quello della pagina destra in alto a destra",

    // Prompt Builder — info-button popups (shared "More information" label + panel text)
    "More information": "Ulteriori informazioni",
    "Latin nouns and names change their ending depending on their grammatical role in the sentence -- this is called declension. The same person can appear in more than one form within a single entry: Franciscus (nominative, as the subject), Francisci (genitive, \"of Francis\"), Francisco (dative/ablative, \"to/from Francis\"). This is not a spelling error or an inconsistency to fix -- each form is correct for its context. Turning this on adds guidance so the AI recognizes these variants as the same name and transcribes each form exactly as written, instead of \"normalizing\" one to match another.":
      "I sostantivi e i nomi latini cambiano desinenza a seconda del loro ruolo grammaticale nella frase — questo si chiama declinazione. La stessa persona può comparire in più di una forma all'interno di una singola voce: Franciscus (nominativo, come soggetto), Francisci (genitivo, \"di Francesco\"), Francisco (dativo/ablativo, \"a/da Francesco\"). Non si tratta di un errore di ortografia o di un'incoerenza da correggere — ogni forma è corretta nel proprio contesto. Attivando questa opzione si aggiunge un'indicazione affinché l'IA riconosca queste varianti come lo stesso nome e trascriva ogni forma esattamente come scritta, invece di \"normalizzarne\" una per farla corrispondere a un'altra.",
    "These are the role-specific words this register uses for the people named in an entry -- for example, a different term depending on whether one person filled the role or several did. Checking a term tells the AI to recognize it and use it correctly when working out who filled which role. Leave a term unchecked if it never appears in your register.":
      "Queste sono le parole specifiche per ruolo che questo registro utilizza per le persone nominate in una voce — per esempio, un termine diverso a seconda che il ruolo sia stato ricoperto da una sola persona o da più persone. Selezionare un termine indica all'IA di riconoscerlo e di usarlo correttamente per stabilire chi ha ricoperto quale ruolo. Lascia deselezionato un termine se non compare mai nel tuo registro.",
    "Paleographic quirks are common habits of a scribe's handwriting that can look like errors but are not -- things like a long ſ that resembles an f, or a macron over a vowel marking a dropped letter. Checking these tells the AI what to expect from this hand, so it does not misread a normal scribal habit as an unfamiliar name or a typo.":
      "Le particolarità paleografiche sono abitudini comuni della grafia di uno scriba che possono sembrare errori ma non lo sono — cose come una ſ lunga che assomiglia a una f, o un macron sopra una vocale che indica una lettera omessa. Selezionare queste opzioni indica all'IA cosa aspettarsi da questa grafia, così da non scambiare un'abitudine scribale normale per un nome sconosciuto o un errore di battitura.",
    "This is about how a person's title gets written in a translation when they're named in a role -- a godparent, a witness, an informant. A \"role clause\" is the little phrase that introduces that person (e.g. \"The godfather was Don Carolus Calsi\").":
      "Questo riguarda il modo in cui il titolo di una persona viene scritto in una traduzione quando viene nominata in un ruolo — un padrino, un testimone, un dichiarante. Una \"formula di ruolo\" è la breve frase che introduce quella persona (ad es. \"Il padrino era Don Carolus Calsi\").",
    "Many church and civil registers write a short note in the margin next to each entry -- often just the name(s) involved -- as a running index down the side of the page. If your register does this, check the box and describe the pattern below, for example \"[child's name] filius/filia [father] et [mother] [surname].\" The AI will transcribe this margin note as its own \"Marginal Heading\" block, kept separate from the entry's main body text -- useful because the two occasionally disagree (a different spelling, a different name order), and both readings are worth preserving.":
      "Molti registri ecclesiastici e civili riportano una breve nota a margine accanto a ogni voce — spesso solo il nome o i nomi coinvolti — come una sorta di indice lungo il bordo della pagina. Se il tuo registro fa questo, seleziona la casella e descrivi lo schema qui sotto, ad esempio \"[nome del figlio] filius/filia [padre] et [madre] [cognome].\" L'IA trascriverà questa nota a margine come un blocco \"Marginal Heading\" a sé stante, separato dal corpo principale della voce — utile perché i due talvolta non concordano (un'ortografia diversa, un ordine dei nomi diverso), ed entrambe le letture meritano di essere conservate.",
    "Many church and civil registers write a short note in the margin next to each entry -- often just the name(s) involved -- as a running index down the side of the page. If your register does this, check the box and describe the pattern below, for example \"[Groom] et [Bride].\" The AI will transcribe this margin note as its own \"Marginal Heading\" block, kept separate from the entry's main body text -- useful because the two occasionally disagree (a different spelling, a different name order), and both readings are worth preserving.":
      "Molti registri ecclesiastici e civili riportano una breve nota a margine accanto a ogni voce — spesso solo il nome o i nomi coinvolti — come una sorta di indice lungo il bordo della pagina. Se il tuo registro fa questo, seleziona la casella e descrivi lo schema qui sotto, ad esempio \"[Sposo] et [Sposa].\" L'IA trascriverà questa nota a margine come un blocco \"Marginal Heading\" a sé stante, separato dal corpo principale della voce — utile perché i due talvolta non concordano (un'ortografia diversa, un ordine dei nomi diverso), ed entrambe le letture meritano di essere conservate.",
    "Many church and civil registers write a short note in the margin next to each entry -- often just the name(s) involved -- as a running index down the side of the page. If your register does this, check the box and describe the pattern below, for example \"[deceased's name].\" The AI will transcribe this margin note as its own \"Marginal Heading\" block, kept separate from the entry's main body text -- useful because the two occasionally disagree (a different spelling, a different name order), and both readings are worth preserving.":
      "Molti registri ecclesiastici e civili riportano una breve nota a margine accanto a ogni voce — spesso solo il nome o i nomi coinvolti — come una sorta di indice lungo il bordo della pagina. Se il tuo registro fa questo, seleziona la casella e descrivi lo schema qui sotto, ad esempio \"[nome del defunto].\" L'IA trascriverà questa nota a margine come un blocco \"Marginal Heading\" a sé stante, separato dal corpo principale della voce — utile perché i due talvolta non concordano (un'ortografia diversa, un ordine dei nomi diverso), ed entrambe le letture meritano di essere conservate.",
    "Many church and civil registers write a short note in the margin next to each entry -- often just the name(s) involved -- as a running index down the side of the page. If your register does this, check the box and describe the pattern below, for example \"Numero [Act #]\n[Child's given name] [Child's surname].\" The AI will transcribe this margin note as its own \"Marginal Heading\" block, kept separate from the entry's main body text -- useful because the two occasionally disagree (a different spelling, a different name order), and both readings are worth preserving.":
      "Molti registri ecclesiastici e civili riportano una breve nota a margine accanto a ogni voce — spesso solo il nome o i nomi coinvolti — come una sorta di indice lungo il bordo della pagina. Se il tuo registro fa questo, seleziona la casella e descrivi lo schema qui sotto, ad esempio \"Numero [N. atto]\n[Nome proprio del figlio] [Cognome del figlio].\" L'IA trascriverà questa nota a margine come un blocco \"Marginal Heading\" a sé stante, separato dal corpo principale della voce — utile perché i due talvolta non concordano (un'ortografia diversa, un ordine dei nomi diverso), ed entrambe le letture meritano di essere conservate.",
    "Many church and civil registers write a short note in the margin next to each entry -- often just the name(s) involved -- as a running index down the side of the page. If your register does this, check the box and describe the pattern below, for example \"Numero [Act #]\n[Groom's name] e [Bride's name].\" The AI will transcribe this margin note as its own \"Marginal Heading\" block, kept separate from the entry's main body text -- useful because the two occasionally disagree (a different spelling, a different name order), and both readings are worth preserving.":
      "Molti registri ecclesiastici e civili riportano una breve nota a margine accanto a ogni voce — spesso solo il nome o i nomi coinvolti — come una sorta di indice lungo il bordo della pagina. Se il tuo registro fa questo, seleziona la casella e descrivi lo schema qui sotto, ad esempio \"Numero [N. atto]\n[Nome dello sposo] e [Nome della sposa].\" L'IA trascriverà questa nota a margine come un blocco \"Marginal Heading\" a sé stante, separato dal corpo principale della voce — utile perché i due talvolta non concordano (un'ortografia diversa, un ordine dei nomi diverso), ed entrambe le letture meritano di essere conservate.",
    "Many church and civil registers write a short note in the margin next to each entry -- often just the name(s) involved -- as a running index down the side of the page. If your register does this, check the box and describe the pattern below, for example \"Numero [Act #]\n[Deceased's name].\" The AI will transcribe this margin note as its own \"Marginal Heading\" block, kept separate from the entry's main body text -- useful because the two occasionally disagree (a different spelling, a different name order), and both readings are worth preserving.":
      "Molti registri ecclesiastici e civili riportano una breve nota a margine accanto a ogni voce — spesso solo il nome o i nomi coinvolti — come una sorta di indice lungo il bordo della pagina. Se il tuo registro fa questo, seleziona la casella e descrivi lo schema qui sotto, ad esempio \"Numero [N. atto]\n[Nome del defunto].\" L'IA trascriverà questa nota a margine come un blocco \"Marginal Heading\" a sé stante, separato dal corpo principale della voce — utile perché i due talvolta non concordano (un'ortografia diversa, un ordine dei nomi diverso), ed entrambe le letture meritano di essere conservate.",
    "This is the exact standing phrase your register repeats in every entry, written out with the parts that change -- names, dates, roles -- marked as bracketed placeholders like [FATHER] or [WITNESS]. It teaches the AI where each real name or date sits in the sentence, even past abbreviations. Edit the sample text below to match your own register's actual wording.":
      "Questa è la formula fissa che il tuo registro ripete in ogni voce, scritta per esteso con le parti che cambiano — nomi, date, ruoli — indicate come segnaposto tra parentesi quadre, ad esempio [PADRE] o [TESTIMONE]. Questo insegna all'IA dove si trova ogni nome o data reale nella frase, anche oltre le abbreviazioni. Modifica il testo di esempio qui sotto per farlo corrispondere alla formulazione reale del tuo registro.",
    "Testis fuit = singular verb, Testes fuerunt = plural verb": "Testis fuit = verbo singolare, Testes fuerunt = verbo plurale",

    // Prompt Builder — Section 2 questionnaire fields
    "This register has a separate margin for each entry that states the name": "Questo registro ha un margine separato per ogni voce che riporta il nome",
    "Marginal heading structure": "Struttura dell'intestazione marginale",
    "Baptism record formula": "Formula del registro del battesimo",
    "Church wedding record formula": "Formula del registro del matrimonio religioso",
    "Entry structure - write out the structure used in each entry": "Struttura della voce - descrivi la struttura usata in ogni voce",
    "Groom's formula": "Formula dello sposo",
    "Bride's formula": "Formula della sposa",
    "Witness formula (optional — leave blank if this register has none)":
      "Formula dei testimoni (opzionale — lascia vuoto se questo registro non ne ha una)",
    "Act formula": "Formula dell'atto",
    "Role-clause vocabulary for Church Battesimi (optional)": "Vocabolario delle formule di ruolo per Battesimi parrocchiali (opzionale)",
    "Role-clause vocabulary for Church Matrimoni (optional)": "Vocabolario delle formule di ruolo per Matrimoni parrocchiali (opzionale)",
    "Role-clause vocabulary for Church Morti (optional)": "Vocabolario delle formule di ruolo per Morti parrocchiali (opzionale)",
    "Role-clause vocabulary for Civil Nati (optional)": "Vocabolario delle formule di ruolo per Nati civili (opzionale)",
    "Role-clause vocabulary for Civil Matrimoni (optional)": "Vocabolario delle formule di ruolo per Matrimoni civili (opzionale)",
    "Role-clause vocabulary for Civil Morti (optional)": "Vocabolario delle formule di ruolo per Morti civili (opzionale)",
    "P.nus / Patrinus = godfather (one male)": "P.nus / Patrinus = padrino (un uomo)",
    "P.na / Patrina = godmother (one female)": "P.na / Patrina = madrina (una donna)",
    "PP. / Patrini = two or more godparents": "PP. / Patrini = due o più padrini/madrine",
    "fuit = singular verb, fuere/fuerunt = plural verb": "fuit = verbo singolare, fuere/fuerunt = verbo plurale",
    "Testis / Testes = witness(es)": "Testis / Testes = testimone/i",
    "sponsus = groom": "sponsus = sposo",
    "sponsa = bride": "sponsa = sposa",
    "vidua = widow": "vidua = vedova",
    "viduus = widower": "viduus = vedovo",
    "conjux / uxor = spouse / wife": "conjux / uxor = coniuge / moglie",
    "The declarant's name, age, occupation, and domicile appear right after the opening clause, before the birth is described": "Il nome, l'età, la professione e il domicilio del dichiarante compaiono subito dopo la formula di apertura, prima della descrizione della nascita",
    "Grandfather names are sometimes given for both parents": "I nomi dei nonni sono talvolta indicati per entrambi i genitori",
    "Don = courtesy title for clergy or gentry": "Don = titolo di cortesia per clero o nobiltà",
    "Master = courtesy title for a young or unmarried man": "Master = titolo di cortesia per un uomo giovane o non sposato",
    "Age and occupation are commonly stated for both spouses": "Età e occupazione sono comunemente indicate per entrambi gli sposi",
    "Witnesses are often named in the running text": "I testimoni sono spesso nominati nel testo",
    "The informant's name, age, occupation, and domicile appear right after the opening clause, before the deceased is described": "Il nome, l'età, la professione e il domicilio del dichiarante compaiono subito dopo la formula di apertura, prima della descrizione del defunto",
    "Age and occupation are commonly stated": "Età e occupazione sono comunemente indicate",
    "The deceased's parentage is sometimes stated as unknown (e.g. \"ignoti genitori\") rather than named -- transcribe that statement literally rather than omitting it":
      "A volte la discendenza del defunto è indicata come sconosciuta (ad es. \"ignoti genitori\") anziché nominata — trascrivi quella dicitura testualmente invece di ometterla",
    "Entry variants (optional) — e.g. an emergency or conditional variant of the standard formula":
      "Varianti della voce (opzionale) — ad es. una variante di emergenza o condizionale della formula standard",
    "Add a variant": "Aggiungi una variante",
    "Variant name, e.g. emergency home baptism": "Nome della variante, ad es. battesimo di emergenza in casa",
    "Marker phrases that identify it": "Frasi distintive che la identificano",
    "Relationship-note vocabulary": "Vocabolario delle note di parentela",
    "uxor = wife of": "uxor = moglie di",
    "soror = sister of": "soror = sorella di",
    "frater = brother of": "frater = fratello di",
    "filius/filia = son/daughter of": "filius/filia = figlio/figlia di",
    "Abbreviation key — common terms (toggle on what applies)": "Legenda delle abbreviazioni — termini comuni (attiva quelli che si applicano)",
    "Add an abbreviation": "Aggiungi un'abbreviazione",
    "Written, e.g. Sac.os": "Come scritto, ad es. Sac.os",
    "Expansion": "Espansione",
    "Meaning": "Significato",
    "Sac.os = sacerdos (priest)": "Sac.os = sacerdos (sacerdote)",
    "Cap.us = capellanus (chaplain)": "Cap.us = capellanus (cappellano)",
    "Eccl.ae = ecclesiae (of the church)": "Eccl.ae = ecclesiae (della chiesa)",
    "Par.lis = parochialis (parish (adj.))": "Par.lis = parochialis (parrocchiale (agg.))",
    "S.ti = Sancti (of Saint)": "S.ti = Sancti (di San/Santo)",
    "jug. = jugales (married couple)": "jug. = jugales (coppia sposata)",
    "d.ti = dicti (of the said)": "d.ti = dicti (del suddetto)",
    "D. = Don / Dominus (courtesy title for clergy and gentry)": "D. = Don / Dominus (titolo di cortesia per clero e nobiltà)",
    "Scribal / paleographic quirks": "Particolarità scribali / paleografiche",
    "long ſ is easily mistaken for f": "la ſ lunga è facilmente confusa con la f",
    "u and v are not distinguished": "u e v non sono distinte",
    "a macron or tilde over a vowel marks an omitted n or m": "un macron o una tilde sopra una vocale indica una n o m omessa",
    "doubled consonants are inconsistent": "le consonanti doppie sono incoerenti",
    "terminal -us is often a superscript loop": "la -us finale è spesso un cappio in apice",
    "Add another quirk": "Aggiungi un'altra particolarità",
    "Apply the standard Italian surname-particle rule (de/di/d'/lo/la/le/li stay with the surname, never normalized)":
      "Applica la regola standard delle particelle nei cognomi italiani (de/di/d'/lo/la/le/li restano con il cognome, mai normalizzate)",
    "Surnames": "Cognomi",
    "Paste known surnames, one per line -- e.g. Esposito, De Amato, La Marca":
      "Incolla i cognomi noti, uno per riga — ad es. Esposito, De Amato, La Marca",
    "Adding a lexicon greatly increases the likelihood that the AI system will bias towards a correct identification of a name. Paste one surname per line. A multi-word surname (“De Amato”, “La Marca”) or an alias (“Bruno alias De Amato”) is a single entry -- keep it on one line exactly as written; it will not be split apart.":
      "Aggiungere un lessico aumenta notevolmente la probabilità che il sistema di IA si orienti verso un'identificazione corretta di un nome. Incolla un cognome per riga. Un cognome composto da più parole (\"De Amato\", \"La Marca\") o un alias (\"Bruno alias De Amato\") è una singola voce — tienilo su un'unica riga esattamente come scritto; non verrà suddiviso.",
    "Given names": "Nomi propri",
    "Paste known given names, one per line -- e.g. Giuseppe, Anna Maria, Giovanni Battista":
      "Incolla i nomi propri noti, uno per riga — ad es. Giuseppe, Anna Maria, Giovanni Battista",
    "Paste one given name per line. A compound or alias given name (“Anna Maria”, “Giovanni Battista”, “Anna alias Nonna”) is a single entry -- keep it on one line exactly as written; it will not be split apart.":
      "Incolla un nome proprio per riga. Un nome composto o un alias (\"Anna Maria\", \"Giovanni Battista\", \"Anna alias Nonna\") è una singola voce — tienilo su un'unica riga esattamente come scritto; non verrà suddiviso.",
    "Alternatively: Full names (given name + surname pairs)": "In alternativa: nomi completi (coppie nome + cognome)",
    "Paste full names, one per line -- e.g. Giuseppe de Natale  or  de Natale, Giuseppe":
      "Incolla nomi completi, uno per riga — ad es. Giuseppe de Natale  oppure  de Natale, Giuseppe",
    "Use this box when what you have is full names rather than two separate lists -- one name per line, either “Given Surname” (Giuseppe de Natale) or “Surname, Given name” (de Natale, Giuseppe). Each line is split and added to the Surnames and Given names lists above it. A surname particle (de/di/d'/lo/la/le/li) right before the last word stays attached to the surname. A line with only one word is skipped rather than guessed at -- put a name like that in the Surnames or Given names box instead.":
      "Usa questo campo quando hai nomi completi invece di due elenchi separati — un nome per riga, nel formato \"Nome Cognome\" (Giuseppe de Natale) oppure \"Cognome, Nome\" (de Natale, Giuseppe). Ogni riga viene suddivisa e aggiunta agli elenchi Cognomi e Nomi propri qui sopra. Una particella del cognome (de/di/d'/lo/la/le/li) subito prima dell'ultima parola resta attaccata al cognome. Una riga con una sola parola viene ignorata invece di essere interpretata a caso — inserisci un nome del genere nel campo Cognomi o Nomi propri.",
    "Example entry": "Voce di esempio",
    "Paste in a completed 100% accurate entry in the native language of the sources for this project. This will be used as a critically important formatting reference for the AI to generate the proper output.":
      "Incolla una voce completa e accurata al 100% nella lingua originale delle fonti di questo progetto. Verrà usata come riferimento di formattazione fondamentale affinché l'IA generi l'output corretto.",
    "Paste a 100% accurate example entry text from your source material, exactly as it was transcribed -- no labels or headers.":
      "Incolla un testo di esempio accurato al 100% dal tuo materiale di origine, esattamente come è stato trascritto — senza etichette o intestazioni.",

    // Prompt Builder — Section 3 questionnaire fields
    "Translation": "Traduzione",
    "Translation is optional — leave both unchecked for a transcription-only output with no translation at all":
      "La traduzione è facoltativa — lascia entrambe le caselle deselezionate per un output di sola trascrizione senza alcuna traduzione",
    "Translation is optional — leave unchecked for a transcription-only output with no translation.":
      "La traduzione è facoltativa — lascia la casella deselezionata per un output di sola trascrizione senza traduzione.",
    "English": "Inglese",
    "Translation style options": "Opzioni di stile della traduzione",
    "Expand abbreviations": "Espandi le abbreviazioni",
    "Convert names to ENG or IT equivalents": "Converti i nomi negli equivalenti inglesi o italiani",
    "Honorifics kept inside a role clause — everything else moves to Notes": "Titoli onorifici mantenuti nella formula di ruolo — tutto il resto va nelle Note",
    "Add another honorific": "Aggiungi un altro titolo onorifico",
    "Additional editorial rules (optional)": "Regole editoriali aggiuntive (opzionale)",
    "A catch-all for a register-specific judgment call that doesn't fit any question above -- for example, \"never copy a surname from one parent to the other\" or a rule about when two blocks disagreeing counts as an error versus expected grammar. Most profiles won't need this; it exists for the occasional rule that's specific to your source and not covered by a preset elsewhere on this page.":
      "Una casella per una regola di giudizio specifica del tuo registro che non rientra in nessuna domanda precedente — ad esempio \"non copiare mai un cognome da un genitore all'altro\" oppure una regola su quando il disaccordo tra due blocchi conta come errore anziché come normale grammatica. La maggior parte dei profili non ne ha bisogno; esiste per la regola occasionale specifica della tua fonte e non coperta da un'opzione preimpostata altrove in questa pagina.",
    "e.g. Never copy a surname from one parent to the other, even when only one is stated.":
      "es. Non copiare mai un cognome da un genitore all'altro, anche quando ne è indicato solo uno.",
    "Remove": "Rimuovi",

    // Prompt Builder — Example entries & Preflight Test
    "Example entries": "Voci di esempio",
    "Add another example": "Aggiungi un altro esempio",
    "Date line": "Riga della data",
    "Preflight checks the one image you upload: it compares the selected example's Date line, Main entry and Baptism / Church Wedding Record against that image. The example's Continuation is not included, because it belongs to the next image.":
      "Il Preflight verifica l'unica immagine che carichi: confronta la riga della data, la voce principale e il registro del battesimo / matrimonio religioso dell'esempio selezionato con quell'immagine. La continuazione dell'esempio non è inclusa, perché appartiene all'immagine successiva.",
    "Date exactly as written, then the standard form in brackets -- e.g. due del mese di Gennaro milleottocentoventitre [2 January 1823]":
      "La data esattamente come scritta, seguita dalla forma standard tra parentesi quadre -- ad es. due del mese di Gennaro milleottocentoventitre [2 January 1823]",
    "Main entry": "Voce principale",
    "Church Wedding Record (if any)": "Registro del matrimonio religioso (se presente)",
    "Baptism Record (if any)": "Registro del battesimo (se presente)",
    "Paste the text of the baptism column, exactly as transcribed -- no labels or headers.":
      "Incolla il testo della colonna del battesimo, esattamente come è stato trascritto — senza etichette o intestazioni.",
    "Continuation (if any)": "Continuazione (se presente)",
    "Paste the text of the right-hand church-wedding column, exactly as transcribed -- no labels or headers.":
      "Incolla il testo della colonna di destra sul matrimonio religioso, esattamente come è stato trascritto — senza etichette o intestazioni.",
    "If this entry runs onto the next image, paste the text that continues it at the top of that image, exactly as transcribed -- no labels or headers.":
      "Se questa voce prosegue nell'immagine successiva, incolla il testo che la continua in cima a quell'immagine, esattamente come è stato trascritto — senza etichette o intestazioni.",
    "Label (optional), e.g. Image 193 Entry 1": "Etichetta (opzionale), ad es. Immagine 193 Voce 1",
    "Each example is a verified, 100% accurate transcription of one real entry from this register, shown to the AI purely as a formatting and style reference -- never as content to copy. More than one example, especially covering different situations (a straightforward entry, one with an illegible word, one where a heading and body disagree), calibrates the AI's judgment better than a single example can. An optional label just helps you tell examples apart later -- e.g. in Preflight Test, if you add more than one.":
      "Ogni esempio è una trascrizione verificata e accurata al 100% di una voce reale di questo registro, mostrata all'IA puramente come riferimento di formattazione e stile — mai come contenuto da copiare. Più di un esempio, specialmente se copre situazioni diverse (una voce semplice, una con una parola illeggibile, una in cui intestazione e corpo non concordano), calibra il giudizio dell'IA meglio di un singolo esempio. Un'etichetta facoltativa ti aiuta solo a distinguere gli esempi in seguito — ad es. nel Test di controllo preliminare, se ne aggiungi più di uno.",
    "Preflight Test": "Test di controllo preliminare",
    "(optional but recommended)": "(facoltativo ma consigliato)",
    "For testing your prompt, upload the image or PDF that corresponds to the selected Example entry text above. JPEG, PNG, and PDF are all supported -- detected automatically from the file itself, so its filename doesn't need to say which one it is. The app will check your example against its source and offer suggestions to improve your prompt, if needed. Clicking \"Run Preflight Test\" first saves your current answers as a draft profile, so nothing is lost if something goes wrong.":
      "Per testare il tuo prompt, carica l'immagine o il PDF che corrisponde al testo della voce di esempio selezionata sopra. JPEG, PNG e PDF sono tutti supportati — rilevati automaticamente dal file stesso, quindi il nome del file non deve indicare di quale si tratta. L'app confronterà il tuo esempio con la fonte e, se necessario, offrirà suggerimenti per migliorare il tuo prompt. Facendo clic su \"Esegui test di controllo preliminare\" le tue risposte attuali vengono prima salvate come profilo bozza, così non si perde nulla in caso di problemi.",
    "Paste your API key for this test": "Incolla la tua chiave API per questo test",
    "Used only for this browser session/request. It is not saved to the project files or the profile. Running a preflight test sends this key and your uploaded file directly to your chosen AI provider's API — see PRIVACY.md.":
      "Usata solo per questa sessione/richiesta del browser. Non viene salvata nei file del progetto né nel profilo. L'esecuzione di un test di controllo preliminare invia questa chiave e il file caricato direttamente all'API del provider IA scelto — consulta PRIVACY.md.",
    "Which example does this image show?": "Quale esempio mostra questa immagine?",
    "Run Preflight Test": "Esegui test di controllo preliminare",
    "Suggestions -- check the ones you want, then apply them to your questionnaire.":
      "Suggerimenti — seleziona quelli che vuoi, poi applicali al tuo questionario.",
    "Apply selected": "Applica selezionati",
    "What the AI actually produced from your image": "Cosa ha effettivamente prodotto l'IA dalla tua immagine",

    // Prompt Builder — Import/Export Profiles
    "Import/Export Profiles": "Importa/Esporta profili",
    "Share and install profiles. Profiles are plain text (JSON) and do not contain executable code or macros.":
      "Condividi e installa profili. I profili sono testo semplice (JSON) e non contengono codice eseguibile né macro.",
    "Export a profile": "Esporta un profilo",
    "Profile to download": "Profilo da scaricare",
    "Download profile file": "Scarica il file del profilo",
    "Import a profile": "Importa un profilo",
    "Importing a profile never overwrites an existing profile.":
      "L'importazione di un profilo non sovrascrive mai un profilo esistente.",

    // Prompt Builder — Civil records: page format & baptism-column fields
    "Page format": "Formato della pagina",
    "Printed form with handwritten entries filled in": "Modulo a stampa con voci compilate a mano",
    "Entirely handwritten — no printed form on the page": "Interamente manoscritto — nessun modulo a stampa sulla pagina",
    "Civil registers from this period take two visibly different forms: an entirely handwritten narrative (common before national printed templates were adopted), or a printed form with the fixed legal wording already on the page and only the names, dates, and other specifics filled in by hand. If your register is a printed form, the AI is told to expect two different scripts on the same page -- the printed boilerplate and the clerk's handwriting -- and to weigh transcription accuracy toward the handwritten fill-ins, since that is where the names and dates that matter for indexing are recorded.":
      "I registri civili di questo periodo si presentano in due forme visibilmente diverse: una narrazione interamente manoscritta (comune prima dell'adozione dei moduli a stampa nazionali), oppure un modulo a stampa con il testo legale fisso già presente sulla pagina e solo i nomi, le date e gli altri dettagli compilati a mano. Se il tuo registro è un modulo a stampa, all'IA viene detto di aspettarsi due grafie diverse sulla stessa pagina — il testo a stampa fisso e la scrittura a mano del funzionario — e di orientare l'accuratezza della trascrizione verso le parti compilate a mano, poiché è lì che si trovano i nomi e le date rilevanti ai fini dell'indicizzazione.",
    "This register has a separate column recording when the child was baptized": "Questo registro ha una colonna separata che registra quando il bambino è stato battezzato",
    "Some civil birth registers print a genuine two-column form: the birth act on the left, and a separately headed column on the right recording when the church administered baptism, sharing the same act number. If your register does this, check the box. The AI will transcribe that column as its own \"Baptism Record\" block, kept separate from the main act -- rather than treating it as a note folded into the body or written in the margin, which is how baptism information is handled when this box is left unchecked.":
      "Alcuni registri civili di nascita stampano un vero e proprio modulo a due colonne: l'atto di nascita a sinistra e, a destra, una colonna con intestazione propria che registra quando la chiesa ha amministrato il battesimo, con lo stesso numero di atto. Se il tuo registro fa questo, seleziona la casella. L'IA trascriverà quella colonna come un blocco \"Baptism Record\" a sé stante, separato dall'atto principale — anziché trattarla come una nota inserita nel corpo o scritta a margine, che è il modo in cui le informazioni sul battesimo vengono gestite quando questa casella resta deselezionata.",
    "Describe the page layout": "Descrivi l'impaginazione della pagina",
    "e.g. one long page per image, read top to bottom":
      "es. una pagina lunga per immagine, letta dall'alto verso il basso",
    "Describe the month-abbreviation convention": "Descrivi la convenzione delle abbreviazioni dei mesi",
    "e.g. months abbreviated to their first three letters, with Xbre for December":
      "es. mesi abbreviati con le prime tre lettere, con Xbre per dicembre",
    "Entries start on the right page of an image and continue on the left page of the next image":
      "Le voci iniziano sulla pagina destra di un'immagine e continuano sulla pagina sinistra dell'immagine successiva",
    "Some registers are photographed so that each entry begins on the right-hand page of one image and finishes on the left-hand page of the next image (the back of the same leaf). If yours does, check this box. The AI will treat the text at the top of a left page as the end of the previous image's last entry -- not a new entry -- and will ignore faint ink showing through from the other side of the leaf. Only applies when the page layout is two facing pages.":
      "Alcuni registri sono fotografati in modo che ogni voce inizi sulla pagina di destra di un'immagine e finisca sulla pagina di sinistra dell'immagine successiva (il retro della stessa carta). Se il tuo registro è così, seleziona questa casella. L'IA tratterà il testo in cima a una pagina di sinistra come la fine dell'ultima voce dell'immagine precedente — non come una nuova voce — e ignorerà l'inchiostro tenue che traspare dall'altro lato della carta. Si applica solo quando l'impaginazione è a due pagine affiancate.",
    "This register has a separate right-hand column recording the parish's confirmation of the church wedding":
      "Questo registro ha una colonna separata a destra che registra la conferma della parrocchia del matrimonio religioso",
    "Some civil marriage registers print a two-column form: the marriage promise on the left, and a separate column on the right in which the parish priest confirms the church wedding took place, with its own date and witnesses. If your register does this, check the box. The AI will transcribe that column as its own \"Church Wedding Record\" block, kept separate from the main act -- rather than inserting it into the middle of the act's text, which is what happens when this box is left unchecked and the column is treated as a margin note. Witnesses named in that column attended the church wedding; they are not additional witnesses to the civil marriage promise.":
      "Alcuni registri civili di matrimonio stampano un modulo a due colonne: la promessa di matrimonio a sinistra e, a destra, una colonna separata in cui il parroco conferma che il matrimonio religioso ha avuto luogo, con la propria data e i propri testimoni. Se il tuo registro fa questo, seleziona la casella. L'IA trascriverà quella colonna come un blocco \"Church Wedding Record\" a sé stante, separato dall'atto principale — anziché inserirla nel mezzo del testo dell'atto, cosa che accade quando questa casella resta deselezionata e la colonna viene trattata come una nota a margine. I testimoni nominati in quella colonna hanno assistito al matrimonio religioso; non sono testimoni aggiuntivi della promessa di matrimonio civile.",

    // XLS Conversion page
    "Gemini 3.1 Pro Preview - higher accuracy": "Gemini 3.1 Pro Preview - maggiore precisione",
    "Gemini 2.5 Pro - stable, high-accuracy baseline": "Gemini 2.5 Pro - base stabile ad alta precisione",
    "Claude Opus 5 - highest accuracy": "Claude Opus 5 - massima precisione",
    "Claude Sonnet 5 - balanced speed / intelligence": "Claude Sonnet 5 - velocità/intelligenza bilanciate",
    "Claude Haiku 4.5 - fastest, lower cost": "Claude Haiku 4.5 - il più veloce, costo inferiore",
    "Choose the source material": "Scegli il materiale di origine",
    "Each record type uses its own extraction criteria and output columns, matching the official index templates.":
      "Ogni tipo di registro usa i propri criteri di estrazione e le proprie colonne di output, corrispondenti ai modelli di indice ufficiali.",
    "Source material": "Materiale di origine",
    "Church Records": "Registri parrocchiali",
    "Civil Records": "Registri civili",
    "Church Battesimi": "Battesimi parrocchiali",
    "Church Matrimoni": "Matrimoni parrocchiali",
    "Church Morti": "Morti parrocchiali",
    // Shared by both XLS Conversion's "Source material" dropdown
    // (xls_conversion/index.html + app.js) and Prompt Builder's own
    // record-type dropdown/DOCX "Record type:" label
    // (prompt_builder_content.py's "label" field) -- both were renamed from
    // "Civil Birth"/"Civil Marriage"/"Civil Death" to this "X civili"
    // pattern (matching "Church X"/"X parrocchiali" just above), so one set
    // of entries now covers both pages. The old English source strings
    // themselves are gone from the app entirely -- no DICTIONARY entry
    // needed for them, but see xls_conversion/app.js's DECLARED_LABEL_TO_VALUE
    // for where the old label text still has to be recognized, in a DOCX
    // generated before this rename.
    "Civil Nati": "Nati civili",
    "Civil Matrimoni": "Matrimoni civili",
    "Civil Morti": "Morti civili",
    "Upload the transcription": "Carica la trascrizione",
    "Select a Microsoft Word DOCX file containing the completed transcription and English translations.":
      "Seleziona un file DOCX di Microsoft Word contenente la trascrizione completata e le traduzioni in inglese.",
    "Choose DOCX file": "Scegli file DOCX",
    "or drag and drop it here": "oppure trascinalo qui",
    "No file selected": "Nessun file selezionato",
    // Shared .file-picker component (see static/base.css) -- the translatable
    // stand-in button/placeholder used everywhere a bare <input type="file">
    // used to show the browser's own, never-translatable "Choose File" text.
    "Choose file": "Scegli file",
    "The XLSX Conversion system is designed to convert transcriptions and translations generated by the Transcribe tool in this app. Transcriptions created from other methods might not convert accurately.":
      "Il sistema di conversione XLSX è progettato per convertire trascrizioni e traduzioni generate dallo strumento Trascrivi di questa app. Le trascrizioni create con altri metodi potrebbero non essere convertite in modo accurato.",
    "Transcribed image range": "Intervallo di immagini trascritte",
    "Image range": "Intervallo immagini",
    "Example: 004-100 or 004-100,118": "Esempio: 004-100 oppure 004-100,118",
    "Required. This controls how much material you want processed from your source.":
      "Obbligatorio. Determina la quantità di materiale che vuoi elaborare dalla tua fonte.",
    "Process all": "Elabora tutto",
    "Ignores the range above and processes every image found in the uploaded transcription.":
      "Ignora l'intervallo sopra ed elabora ogni immagine trovata nella trascrizione caricata.",
    "Choose output language(s)": "Scegli la lingua o le lingue di output",
    "Detect which languages this transcription contains, then choose how to convert them.":
      "Rileva quali lingue contiene questa trascrizione, poi scegli come convertirle.",
    "The source document does not contain preset data to identify the languages in the content. Click to manually detect the languages and select the next process for final output.":
      "Il documento di origine non contiene dati preimpostati per identificare le lingue nel contenuto. Fai clic per rilevare manualmente le lingue e selezionare il processo successivo per l'output finale.",
    "Detect Languages": "Rileva lingue",
    "Output": "Output",
    "One language → one spreadsheet": "Una lingua → un foglio di calcolo",
    "Two languages → two spreadsheets": "Due lingue → due fogli di calcolo",
    "Two languages → one spreadsheet, two tabs": "Due lingue → un foglio di calcolo, due schede",
    "Preflight and convert": "Controllo preliminare e conversione",
    "Confirm that every requested image is present and contains the selected language's material before creating the spreadsheet output.":
      "Conferma che ogni immagine richiesta sia presente e contenga il materiale nella lingua selezionata prima di creare il foglio di calcolo di output.",
    "Convert": "Converti",
    "Override Preflight and Convert": "Ignora il controllo preliminare e converti",
    "Converting the records. AI extraction may take several minutes.":
      "Conversione dei record in corso. L'estrazione con l'IA può richiedere diversi minuti.",
    "Process Status": "Stato del processo",
    "Upload a DOCX file to begin.": "Carica un file DOCX per iniziare.",
    "Preflight results": "Risultati del controllo preliminare",
    "Image verification and parser exceptions will appear here.": "La verifica delle immagini e le eccezioni del parser appariranno qui.",
    "Spreadsheet output": "Foglio di calcolo di output",
    "Download the extracted records as an Excel workbook or standards-compliant CSV.":
      "Scarica i record estratti come cartella di lavoro Excel o come CSV conforme agli standard.",
    "Download XLSX": "Scarica XLSX",
    "Download CSV": "Scarica CSV",
    // XLSX Conversion's own completion alert (showCompletionAlert() in
    // xls_conversion/app.js) -- shares showSettingsAlert() with Transcribe/
    // Test Mode's "Batch completed" alert, so it gets the same treatment
    // now that alert text is in scope for this file (see the top-of-file
    // comment).
    "Conversion completed": "Conversione completata",
    "Scroll down and review the Spreadsheet output panel, then click Download to save your file(s).":
      "Scorri verso il basso, controlla il pannello Foglio di calcolo di output, poi clicca su Scarica per salvare i tuoi file."
  };

  var SKIP_TAGS = { SCRIPT: true, STYLE: true, TEXTAREA: true, PRE: true, CODE: true };
  var TRANSLATABLE_ATTRS = ["placeholder", "title", "aria-label", "label"];

  function collectTextNodes(root) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        var parent = node.parentElement;
        if (!parent || SKIP_TAGS[parent.tagName]) return NodeFilter.FILTER_REJECT;
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_SKIP;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    var nodes = [];
    var current;
    while ((current = walker.nextNode())) nodes.push(current);
    return nodes;
  }

  function applyLanguage(lang) {
    var italian = lang === "it";

    collectTextNodes(document.body).forEach(function (node) {
      // node.tbOrig is the cached English baseline; node.tbLast is whatever
      // this function itself last wrote into nodeValue (English or its
      // translation). If something else (e.g. updateRunButton()'s
      // runButton.title, or showSettingsAlert()'s raw .textContent =
      // assignment on this same underlying text-node path) changed
      // nodeValue since our own last write, current !== tbLast and that new
      // value becomes the new baseline to translate from -- otherwise a
      // dynamically-set string stays frozen at whatever it was the very
      // first time this ran for that node. See the TRANSLATABLE_ATTRS loop
      // below for the identical fix applied to attributes.
      var current = node.nodeValue;
      if (node.tbOrig === undefined || (node.tbLast !== undefined && current !== node.tbLast)) {
        node.tbOrig = current;
      }
      var trimmed = node.tbOrig.trim();
      var translated = DICTIONARY[trimmed];
      var next = italian && translated ? node.tbOrig.replace(trimmed, translated) : node.tbOrig;
      node.nodeValue = next;
      node.tbLast = next;
    });

    var titleEl = document.querySelector("title");
    if (titleEl) {
      if (titleEl.tbOrig === undefined) titleEl.tbOrig = titleEl.textContent;
      var titleTranslated = DICTIONARY[titleEl.tbOrig.trim()];
      titleEl.textContent = italian && titleTranslated ? titleTranslated : titleEl.tbOrig;
    }

    TRANSLATABLE_ATTRS.forEach(function (attr) {
      var dataAttr = "data-tb-orig-" + attr;
      var lastAttr = "data-tb-last-" + attr;
      document.querySelectorAll("[" + attr + "]").forEach(function (el) {
        // Same fix as the text-node loop above, via a pair of DOM attributes
        // instead of JS properties (data-tb-orig-<attr> / data-tb-last-<attr>)
        // since attribute state, unlike node.tbOrig, needs to be readable by
        // el.getAttribute(). Without this, a dynamic setter like
        // updateRunButton() (pages/transcribe.py, pages/test_mode.py) that
        // sets runButton.title more than once, each followed by
        // tbRefreshLanguage(), would have its later titles overwritten back
        // to whichever value got cached on the very first call.
        var current = el.getAttribute(attr);
        var last = el.getAttribute(lastAttr);
        var orig = el.getAttribute(dataAttr);
        if (orig === null || (last !== null && current !== last)) {
          orig = current;
          el.setAttribute(dataAttr, orig);
        }
        var translated = DICTIONARY[orig.trim()];
        var next = italian && translated ? translated : orig;
        el.setAttribute(attr, next);
        el.setAttribute(lastAttr, next);
      });
    });

    document.documentElement.setAttribute("lang", lang);
    document.querySelectorAll(".lang-flag").forEach(function (button) {
      button.setAttribute("aria-pressed", button.getAttribute("data-lang") === lang ? "true" : "false");
    });

    // Whole-block bilingual content (e.g. the /privacy page's server-rendered
    // English/Italian markdown) that toggles by visibility instead of going
    // through the exact-string DICTIONARY lookup above.
    document.querySelectorAll("[data-lang-block]").forEach(function (el) {
      el.hidden = el.getAttribute("data-lang-block") !== lang;
    });
  }

  // Status/log text (the #summary and #log elements on Transcribe/Test Mode,
  // populated from /status JSON polling -- see refreshStatus() in
  // pages/transcribe.py and pages/test_mode.py) is otherwise explicitly out
  // of scope for this file (see the module docstring at the top): it's
  // generated server-side by a background job thread that has no per-request
  // access to the viewing browser's language cookie, and it's free-form text
  // (filenames, raw provider error bodies) that can't safely go through the
  // exact-string DICTIONARY lookup applyLanguage() uses for static chrome.
  //
  // The one deliberate exception: humanize_provider_error()'s two fixed
  // message shapes (customizable_transcription/core.py) and the transient-
  // retry progress line it's paired with (_with_transient_retry() in the
  // same file) -- these are common enough (any Gemini/Claude 429 or 5xx) and
  // specific enough in shape to safely pattern-match and translate at
  // display time, which is the only place a language choice is actually
  // known for a string a background thread produced. Everything these
  // patterns don't recognize (any other error, any other log line) is
  // returned completely unchanged -- this never guesses at a translation.
  //
  // Each entry's `re` must match the *entire* trimmed line ($ anchored) so a
  // partial coincidental match on an unrelated line can't misfire; `it`
  // rebuilds the Italian line from the same captured groups, leaving the
  // untranslatable parts (model id, HTTP status, the provider's own raw
  // error body) exactly as captured.
  var DYNAMIC_LINE_PATTERNS = [
    {
      re: /^"([^"]+)" is temporarily unavailable on the provider's own servers \(HTTP ([^)]+)\) -- this is not a problem with your API key or this app\. It already retried (\d+) times with a short delay before giving up\. This is usually temporary: wait a few minutes and try again, or switch to a different model for now\. \(Original error: ([\s\S]+)\)$/,
      it: function (m) {
        return (
          '"' + m[1] + '" non è al momento disponibile sui server del provider (HTTP ' + m[2] + ") -- " +
          "non è un problema della tua chiave API o di questa app. Ha già ritentato " + m[3] +
          " volte con un breve ritardo prima di rinunciare. Di solito è temporaneo: attendi qualche " +
          "minuto e riprova, oppure passa a un altro modello per ora. (Errore originale: " + m[4] + ")"
        );
      },
    },
    {
      re: /^"([^"]+)" is rate-limiting this API key right now \(HTTP 429, too many requests\)\. This already retried (\d+) times with a short delay and is still being limited -- wait a bit and try again, or switch to a different model for now\. \(Original error: ([\s\S]+)\)$/,
      it: function (m) {
        return (
          '"' + m[1] + '" sta limitando questa chiave API in questo momento (HTTP 429, troppe richieste). ' +
          "Ha già ritentato " + m[2] + " volte con un breve ritardo ed è ancora limitata -- attendi " +
          "un momento e riprova, oppure passa a un altro modello per ora. (Errore originale: " + m[3] + ")"
        );
      },
    },
    {
      re: /^Provider reported a temporary error \(([\s\S]+)\); retrying \((\d+)\/(\d+)\) in ([\d.]+)s\.\.\.$/,
      it: function (m) {
        return (
          "Il provider ha segnalato un errore temporaneo (" + m[1] + "); nuovo tentativo (" + m[2] + "/" +
          m[3] + ") tra " + m[4] + "s..."
        );
      },
    },
    // Below: missingRunSettingMessage()/apiKeyMismatchMessage() (pages/
    // transcribe.py, pages/test_mode.py) -- settings-alert messages
    // assembled from variable parts, not something a single DICTIONARY key
    // can cover. These are the same kind of problem the three patterns
    // above solve for #summary/#log text, so they're pattern-matched here
    // too rather than inventing a second mechanism -- see this function's
    // (and window.tbTranslateStatusText's) own comment for the fact that
    // this file's use now extends past status/log text to alert messages.
    {
      // "Before running transcription, please X." / "...X and Y." /
      // "...X, Y and Z." (up to 4 items on Test Mode) -- the clause is
      // split back into its atomic phrases, each looked up individually,
      // then rejoined in Italian list grammar ("X, Y e Z" instead of the
      // Oxford-less English "X, Y and Z").
      re: /^Before running transcription, please (.+)\.$/,
      it: function (m) {
        var PHRASES = {
          "choose a source folder": "scegliere una cartella di origine",
          "paste a Gemini API key": "incollare una chiave API di Gemini",
          "paste a Claude API key": "incollare una chiave API di Claude",
          "select a prompt profile": "selezionare un profilo del prompt",
        };
        var clause = m[1];
        var andIndex = clause.lastIndexOf(" and ");
        var last = andIndex === -1 ? clause : clause.slice(andIndex + 5);
        var rest = andIndex === -1 ? "" : clause.slice(0, andIndex);
        var parts = (rest ? rest.split(", ") : []).concat([last]).map(function (p) {
          return PHRASES[p] || p;
        });
        var clauseIt = parts.length === 1 ? parts[0] : parts.slice(0, -1).join(", ") + " e " + parts[parts.length - 1];
        return "Prima di avviare la trascrizione, " + clauseIt + ".";
      },
    },
    {
      // apiKeyMismatchMessage() (Test Mode only): one or both sentences,
      // space-joined in this fixed order (the Gemini-field check always
      // runs, and is pushed, first) -- see the app-code comment on why one
      // regex with an optional second sentence covers this instead of two
      // separate patterns.
      re: /^The Gemini API key looks like a Claude key -- check you pasted the right one\.(?: The Claude API key doesn't look like a Claude key\.)?$/,
      it: function (m) {
        var out = "La chiave API Gemini sembra una chiave Claude -- controlla di aver incollato quella giusta.";
        if (/ The Claude API key doesn't look like a Claude key\.$/.test(m[0])) {
          out += " La chiave API Claude non sembra una chiave Claude.";
        }
        return out;
      },
    },
    {
      // The Claude-field sentence can also appear alone (Gemini field
      // fine, Claude field wrong).
      re: /^The Claude API key doesn't look like a Claude key\.$/,
      it: function () {
        return "La chiave API Claude non sembra una chiave Claude.";
      },
    },
    {
      // estimate_off_peak_savings() (batch_transcription.py), zero-image case.
      re: /^Select a source folder to see an off-peak cost estimate\.$/,
      it: function () {
        return "Seleziona una cartella di origine per vedere una stima dei costi off-peak.";
      },
    },
    {
      // estimate_off_peak_savings() (batch_transcription.py), the real
      // estimate -- assembled from image_count, one of 3 fixed page_layout
      // notes, and total_tokens, so (like the two patterns above it) this
      // goes through pattern-matching rather than a single DICTIONARY key.
      // OFF_PEAK_DISCOUNT_DESCRIPTION is a module-level constant, not a
      // parameter, so its wording is matched literally rather than captured.
      re: /^≈([\d,]+) image\(s\) found \((.+)\) → roughly ([\d,]+) image tokens at your selected model's standard detail level\. Off-peak batch processing is typically billed at roughly half the standard per-token rate for both input and output\.$/,
      it: function (m) {
        var PAGE_NOTES = {
          "each image ≈1 register page, per this profile": "ogni immagine ≈1 pagina di registro, secondo questo profilo",
          "each image ≈2 facing pages, per this profile": "ogni immagine ≈2 pagine affiancate, secondo questo profilo",
          "page layout not specified in this profile": "impaginazione non specificata in questo profilo",
        };
        var pageNoteIt = PAGE_NOTES[m[2]] || m[2];
        return (
          "≈" + m[1] + " immagine/i trovate (" + pageNoteIt + ") → circa " + m[3] +
          " token immagine al livello di dettaglio standard del modello selezionato. L'elaborazione batch " +
          "off-peak è generalmente fatturata a circa la metà della tariffa standard per token, sia in " +
          "ingresso che in uscita."
        );
      },
    },
  ];

  // Wraps every pattern above so it also recognizes the two fixed English
  // prefixes run_job()/run_batch() (app.py, core.py) put in front of it in
  // the actual log -- "Fatal error: " and "Failed <image name>: ". The
  // prefix is only translated when the text after it matches one of the
  // known shapes; an unrelated "Fatal error: ..." (a bad API key, a missing
  // folder, anything else) is left completely alone, in English, exactly as
  // before this file existed.
  var PREFIXED_PATTERNS = [
    { prefixRe: /^Fatal error: /, prefixIt: "Errore fatale: " },
    { prefixRe: /^Failed ([^:]+): /, prefixIt: null }, // null: rebuilt per-match below (carries a captured name)
  ];

  function translateDynamicLine(line) {
    for (var i = 0; i < DYNAMIC_LINE_PATTERNS.length; i++) {
      var entry = DYNAMIC_LINE_PATTERNS[i];
      var match = line.match(entry.re);
      if (match) return entry.it(match);
    }
    for (var j = 0; j < PREFIXED_PATTERNS.length; j++) {
      var prefixed = PREFIXED_PATTERNS[j];
      var prefixMatch = line.match(prefixed.prefixRe);
      if (!prefixMatch) continue;
      var rest = line.slice(prefixMatch[0].length);
      var translatedRest = translateDynamicLine(rest);
      if (translatedRest === rest) continue; // rest didn't match any known shape -- leave the whole line alone
      var prefixIt = prefixed.prefixIt !== null ? prefixed.prefixIt : "Elaborazione non riuscita per " + prefixMatch[1] + ": ";
      return prefixIt + translatedRest;
    }
    return line;
  }

  // Exposed for refreshStatus() on Transcribe/Test Mode to run #summary and
  // #log text through before setting it, in place of a raw assignment from
  // the /status JSON, and (later) for missingRunSettingMessage()/
  // apiKeyMismatchMessage() to pre-translate a settings-alert message
  // assembled from variable parts before it reaches showSettingsAlert() --
  // see DYNAMIC_LINE_PATTERNS' own comment on why alert text ended up
  // going through the same mechanism as status/log text. Safe to call from
  // English (returns text unchanged, same as every pattern-miss case) and
  // safe on multi-line log text (each line -- one add_log()/add_test_log()
  // call -- is matched independently).
  window.tbTranslateStatusText = function (text) {
    if ((getCookie(STORAGE_KEY) || "en") !== "it" || !text) return text;
    return text
      .split("\n")
      .map(translateDynamicLine)
      .join("\n");
  };

  // Re-applies whatever language is currently active. Exposed for scripts on
  // other pages (e.g. Prompt Builder) that insert new DOM after page load --
  // applyLanguage()'s initial pass and the lang-flag click handler below both
  // only see the DOM as it exists at that moment, so content added later
  // (a dynamically-inserted repeatable-row placeholder, for example) is never
  // translated unless something calls this afterward. Safe to call anytime,
  // including from English (a no-op past the first call, since applyLanguage
  // restores tbOrig when not Italian).
  window.tbRefreshLanguage = function () {
    applyLanguage(getCookie(STORAGE_KEY) || "en");
  };

  // Populates the "#app-version" span every page's footer carries (after the
  // Privacy link) from the running app.py's /version endpoint, which just
  // reads the checked-in VERSION file -- see app.py's APP_VERSION comment.
  // A live fetch here (rather than server-templating it into each page) is
  // what lets xls_conversion/index.html pick it up too, since that page is
  // served as a plain static file with no Python string interpolation.
  // Fails silently (no element, or the request itself fails) so a missing
  // backend never leaves a broken footer.
  function loadAppVersion() {
    var el = document.getElementById("app-version");
    if (!el) return;
    fetch("/version", { cache: "no-store" })
      .then(function (resp) { return resp.ok ? resp.json() : null; })
      .then(function (data) {
        if (data && data.version) el.textContent = "· v" + data.version;
      })
      .catch(function () {});
  }

  function init() {
    var storedLang = getCookie(STORAGE_KEY) || "en";
    applyLanguage(storedLang);
    loadAppVersion();

    document.querySelectorAll(".lang-flag").forEach(function (button) {
      button.addEventListener("click", function () {
        var lang = button.getAttribute("data-lang");
        setCookie(STORAGE_KEY, lang, COOKIE_DAYS);
        applyLanguage(lang);
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
