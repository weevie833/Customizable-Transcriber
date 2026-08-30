/*
 * Client-side EN/IT toggle for the Transcription Bot UI.
 *
 * Scope: static UI chrome only (headings, nav, labels, buttons, hints,
 * placeholders, footers). It does NOT translate: user-entered profile
 * content, transcription/log/status output, or strings that other inline
 * <script> blocks write into the page at runtime (alerts, dynamic hints,
 * progress rows) -- those stay English by design for this pass.
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

  // English -> Italian. Keys must match the exact (trimmed) text as it
  // appears in the DOM/attribute; anything without a match is left as-is.
  var DICTIONARY = {
    // Shared chrome: nav, byline, footer, alerts
    "Skip to main content": "Vai al contenuto principale",
    "Run settings needed": "Impostazioni di esecuzione mancanti",
    "OK": "OK",
    "Created by Steve Covello, 2026": "Creato da Steve Covello, 2026",
    "Transcribe": "Trascrivi",
    "XLSX Conversion": "Conversione XLSX",
    "Test Mode": "Modalità di test",
    "Prompt Builder": "Generatore di prompt",
    "Primary navigation": "Navigazione principale",
    "Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). Free to use, modify, and share — derivative works, including hosted versions, must stay open source under the same license.":
      "Distribuito sotto licenza GNU Affero General Public License v3.0 (AGPL-3.0). Libero da usare, modificare e condividere — le opere derivate, comprese le versioni ospitate su server, devono rimanere open source sotto la stessa licenza.",
    "Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).":
      "Distribuito sotto licenza GNU Affero General Public License v3.0 (AGPL-3.0).",

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
    "API key for Model A": "Chiave API per il Modello A",
    "API key for Model B": "Chiave API per il Modello B",
    "Paste the API key for Model A": "Incolla la chiave API per il Modello A",
    "Paste the API key for Model B": "Incolla la chiave API per il Modello B",
    "Each key must match its model's provider (a Gemini key for a Gemini model, a Claude key for a Claude model). Used for every run in the queue. Not saved to the project files. Submitting a run sends each key and the selected source content directly to that provider's API — see PRIVACY.md.":
      "Ogni chiave deve corrispondere al provider del proprio modello (una chiave Gemini per un modello Gemini, una chiave Claude per un modello Claude). Usata per ogni esecuzione della coda. Non viene salvata nei file del progetto. L'avvio di un'esecuzione invia ciascuna chiave e il contenuto sorgente selezionato direttamente all'API di quel provider — consulta PRIVACY.md.",
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
    "Confirm settings:": "Conferma impostazioni:",
    "Order:": "Ordine:",
    "File type:": "Tipo di file:",
    "Prompt Profile:": "Profilo del prompt:",
    "Process running. Review the Progress Console below.":
      "Elaborazione in corso. Controlla la Console di avanzamento qui sotto.",
    "Progress Console": "Console di avanzamento",
    "Stop": "Interrompi",
    "Download Document": "Scarica documento",
    "Refresh Status": "Aggiorna stato",
    "The DOCX file will be downloaded to wherever your browser saves downloaded files. Check your browser's Downloads button for download history.":
      "Il file DOCX verrà scaricato nella cartella in cui il tuo browser salva i file scaricati. Controlla il pulsante Download del tuo browser per la cronologia dei download.",
    "Output:": "Output:",

    // Transcribe page
    "Customizable Transcription": "Trascrizione personalizzabile",
    "Use the Prompt Builder page to create prompts, or bypass the Prompt Builder and place your prompt in the sections below. Manual prompts cannot be edited in the Prompt Builder.":
      "Usa la pagina Prompt Builder per creare i prompt, oppure aggira il Prompt Builder e inserisci il tuo prompt nelle sezioni qui sotto. I prompt inseriti manualmente non possono essere modificati nel Prompt Builder.",
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
    "Example: Flash-Lite vs 3.6 Flash": "Esempio: Flash-Lite vs 3.6 Flash",
    "Add to Batch": "Aggiungi al batch",
    "Batch queue": "Coda dei batch",
    "No batches queued yet. Click \"Add to Batch\" to queue the Model A/B pair above, or leave the queue empty and just run this one pair directly.":
      "Nessun batch ancora in coda. Fai clic su \"Aggiungi al batch\" per accodare la coppia Modello A/B sopra, oppure lascia la coda vuota ed esegui direttamente questa singola coppia.",
    "Batches:": "Batch:",
    "Test Mode runs the profile as saved — edit or create profiles from the Transcribe page.":
      "La Modalità di test esegue il profilo così com'è salvato — modifica o crea profili dalla pagina Trascrivi.",
    "Compare Results": "Confronta risultati",
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
    "Download Comparison Report (.docx)": "Scarica il report di confronto (.docx)",
    "Explains CER/WER/WER-BoW in plain language and estimates the correction effort each score implies.":
      "Spiega CER/WER/WER-BoW in linguaggio semplice e stima lo sforzo di correzione implicato da ciascun punteggio.",

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
    "Only profiles created or edited in Prompt Builder can be loaded here -- a profile written by hand or edited only on the Transcribe page's free-text editor isn't listed. Loading one fills in this questionnaire with its saved answers; saving updates that same profile unless you choose \"Save as a new profile\" below instead.":
      "Qui è possibile caricare solo i profili creati o modificati nel Prompt Builder — un profilo scritto a mano o modificato solo nell'editor a testo libero della pagina Trascrivi non è elencato. Caricandone uno, il questionario viene compilato con le sue risposte salvate; salvando si aggiorna lo stesso profilo, a meno che tu non scelga \"Salva come nuovo profilo\" qui sotto.",
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
    "Many church and civil registers write a short note in the margin next to each entry -- often just the name(s) involved -- as a running index down the side of the page. If your register does this, check the box and describe the pattern below, for example \"[Child's name].\" The AI will transcribe this margin note as its own \"Marginal Heading\" block, kept separate from the entry's main body text -- useful because the two occasionally disagree (a different spelling, a different name order), and both readings are worth preserving.":
      "Molti registri ecclesiastici e civili riportano una breve nota a margine accanto a ogni voce — spesso solo il nome o i nomi coinvolti — come una sorta di indice lungo il bordo della pagina. Se il tuo registro fa questo, seleziona la casella e descrivi lo schema qui sotto, ad esempio \"[Nome del bambino].\" L'IA trascriverà questa nota a margine come un blocco \"Marginal Heading\" a sé stante, separato dal corpo principale della voce — utile perché i due talvolta non concordano (un'ortografia diversa, un ordine dei nomi diverso), ed entrambe le letture meritano di essere conservate.",
    "Many church and civil registers write a short note in the margin next to each entry -- often just the name(s) involved -- as a running index down the side of the page. If your register does this, check the box and describe the pattern below, for example \"[Groom's name] and [Bride's name].\" The AI will transcribe this margin note as its own \"Marginal Heading\" block, kept separate from the entry's main body text -- useful because the two occasionally disagree (a different spelling, a different name order), and both readings are worth preserving.":
      "Molti registri ecclesiastici e civili riportano una breve nota a margine accanto a ogni voce — spesso solo il nome o i nomi coinvolti — come una sorta di indice lungo il bordo della pagina. Se il tuo registro fa questo, seleziona la casella e descrivi lo schema qui sotto, ad esempio \"[Nome dello sposo] e [Nome della sposa].\" L'IA trascriverà questa nota a margine come un blocco \"Marginal Heading\" a sé stante, separato dal corpo principale della voce — utile perché i due talvolta non concordano (un'ortografia diversa, un ordine dei nomi diverso), ed entrambe le letture meritano di essere conservate.",
    "Many church and civil registers write a short note in the margin next to each entry -- often just the name(s) involved -- as a running index down the side of the page. If your register does this, check the box and describe the pattern below, for example \"[Deceased's name].\" The AI will transcribe this margin note as its own \"Marginal Heading\" block, kept separate from the entry's main body text -- useful because the two occasionally disagree (a different spelling, a different name order), and both readings are worth preserving.":
      "Molti registri ecclesiastici e civili riportano una breve nota a margine accanto a ogni voce — spesso solo il nome o i nomi coinvolti — come una sorta di indice lungo il bordo della pagina. Se il tuo registro fa questo, seleziona la casella e descrivi lo schema qui sotto, ad esempio \"[Nome del defunto].\" L'IA trascriverà questa nota a margine come un blocco \"Marginal Heading\" a sé stante, separato dal corpo principale della voce — utile perché i due talvolta non concordano (un'ortografia diversa, un ordine dei nomi diverso), ed entrambe le letture meritano di essere conservate.",
    "This is the exact standing phrase your register repeats in every entry, written out with the parts that change -- names, dates, roles -- marked as bracketed placeholders like [FATHER] or [WITNESS]. It teaches the AI where each real name or date sits in the sentence, even past abbreviations. Edit the sample text below to match your own register's actual wording.":
      "Questa è la formula fissa che il tuo registro ripete in ogni voce, scritta per esteso con le parti che cambiano — nomi, date, ruoli — indicate come segnaposto tra parentesi quadre, ad esempio [PADRE] o [TESTIMONE]. Questo insegna all'IA dove si trova ogni nome o data reale nella frase, anche oltre le abbreviazioni. Modifica il testo di esempio qui sotto per farlo corrispondere alla formulazione reale del tuo registro.",
    "Testis fuit = singular verb, Testes fuerunt = plural verb": "Testis fuit = verbo singolare, Testes fuerunt = verbo plurale",

    // Prompt Builder — Section 2 questionnaire fields
    "This register has a separate margin for each entry that states the name": "Questo registro ha un margine separato per ogni voce che riporta il nome",
    "Marginal heading structure": "Struttura dell'intestazione marginale",
    "Entry structure - write out the structure used in each entry": "Struttura della voce - descrivi la struttura usata in ogni voce",
    "Groom's formula": "Formula dello sposo",
    "Bride's formula": "Formula della sposa",
    "Witness formula (optional — leave blank if this register has none)":
      "Formula dei testimoni (opzionale — lascia vuoto se questo registro non ne ha una)",
    "Act formula": "Formula dell'atto",
    "Role-clause vocabulary for Church Battesimi (optional)": "Vocabolario delle formule di ruolo per Battesimi parrocchiali (opzionale)",
    "Role-clause vocabulary for Church Matrimoni (optional)": "Vocabolario delle formule di ruolo per Matrimoni parrocchiali (opzionale)",
    "Role-clause vocabulary for Church Morti (optional)": "Vocabolario delle formule di ruolo per Morti parrocchiali (opzionale)",
    "Role-clause vocabulary for Civil Birth (optional)": "Vocabolario delle formule di ruolo per Nascita civile (opzionale)",
    "Role-clause vocabulary for Civil Marriage (optional)": "Vocabolario delle formule di ruolo per Matrimonio civile (opzionale)",
    "Role-clause vocabulary for Civil Death (optional)": "Vocabolario delle formule di ruolo per Morte civile (opzionale)",
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
    "Remove": "Rimuovi",

    // XLS Conversion page
    "Gemini 3.7 Flash - latest balanced speed / intelligence": "Gemini 3.7 Flash - ultimo modello, velocità/intelligenza bilanciate",
    "Gemini 3.6 Flash - previous balanced speed / intelligence": "Gemini 3.6 Flash - modello precedente, velocità/intelligenza bilanciate",
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
    "Civil Birth": "Nascita civile",
    "Civil Marriage": "Matrimonio civile",
    "Civil Death": "Morte civile",
    "Upload the transcription": "Carica la trascrizione",
    "Select a Microsoft Word DOCX file containing the completed transcription and English translations.":
      "Seleziona un file DOCX di Microsoft Word contenente la trascrizione completata e le traduzioni in inglese.",
    "Choose DOCX file": "Scegli file DOCX",
    "or drag and drop it here": "oppure trascinalo qui",
    "No file selected": "Nessun file selezionato",
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
    "Download CSV": "Scarica CSV"
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
      if (node.tbOrig === undefined) node.tbOrig = node.nodeValue;
      if (italian) {
        var trimmed = node.tbOrig.trim();
        var translated = DICTIONARY[trimmed];
        if (translated) node.nodeValue = node.tbOrig.replace(trimmed, translated);
      } else {
        node.nodeValue = node.tbOrig;
      }
    });

    var titleEl = document.querySelector("title");
    if (titleEl) {
      if (titleEl.tbOrig === undefined) titleEl.tbOrig = titleEl.textContent;
      var titleTranslated = DICTIONARY[titleEl.tbOrig.trim()];
      titleEl.textContent = italian && titleTranslated ? titleTranslated : titleEl.tbOrig;
    }

    TRANSLATABLE_ATTRS.forEach(function (attr) {
      var dataAttr = "data-tb-orig-" + attr;
      document.querySelectorAll("[" + attr + "]").forEach(function (el) {
        var orig = el.getAttribute(dataAttr);
        if (orig === null) {
          orig = el.getAttribute(attr);
          el.setAttribute(dataAttr, orig);
        }
        var translated = DICTIONARY[orig.trim()];
        el.setAttribute(attr, italian && translated ? translated : orig);
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

  // Re-applies whatever language is currently active. Exposed for scripts on
  // other pages (e.g. Prompt Builder) that insert new DOM after page load --
  // applyLanguage()'s initial pass and the lang-flag click handler below both
  // only see the DOM as it exists at that moment, so content added later
  // (a dynamically-inserted repeatable-row placeholder, for example) is never
  // translated unless something calls this afterward. Safe to call anytime,
  // including from English (a no-op past the first call, since applyLanguage
  // restores tbOrig when not Italian).
  window.tbRefreshLanguage = function () {
    applyLanguage(localStorage.getItem(STORAGE_KEY) || "en");
  };

  function init() {
    var storedLang = localStorage.getItem(STORAGE_KEY) || "en";
    applyLanguage(storedLang);

    document.querySelectorAll(".lang-flag").forEach(function (button) {
      button.addEventListener("click", function () {
        var lang = button.getAttribute("data-lang");
        localStorage.setItem(STORAGE_KEY, lang);
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
