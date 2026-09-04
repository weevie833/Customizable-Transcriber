"""Home page ("/"). Split out of app.py as part of the
app.py-modularization pass -- see CLAUDE.md. No external dependencies: this
page is entirely static aside from the shared header/nav shell every page
repeats."""

from __future__ import annotations

from pages import FOOTER_HTML


def home_page() -> str:
    """The app's default landing page ("/"). Same header/nav/CSS shell as every
    other page (privacy_page() is the closest existing template), plus a hero
    section: the welcome heading with the language flags right next to it (the
    same .lang-flag buttons/cookie every other page's header toggle already
    uses -- see static/i18n.js -- so picking a language here keeps every page
    in sync), a short bilingual description of the app, and a pointer to the
    not-yet-built Getting Started page."""
    return """<!doctype html>
<html lang="en">
  <head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Home</title>
  <script src="/static/i18n.js" defer></script>
  <link rel="stylesheet" href="/static/base.css">
  <style>
    .panel {
      background: #ffffff;
      border: 1px solid #d9d4c8;
      border-radius: 8px;
      padding: 24px 28px;
      margin-bottom: 18px;
    }
    .panel p {
      margin: 12px 0;
    }
    .hero-top {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: baseline;
      gap: 10px 24px;
      margin-bottom: 6px;
    }
    .hero-top h1 {
      font-size: 24px;
    }
    /* The header's "Home" text is a <p>, not a heading, and is visually
       hidden (.sr-only) besides -- the hero text below is this page's one
       real, visible <h1> (see WCAG review notes in CLAUDE.md: two <h1>s
       gave screen-reader heading navigation two competing "page title"
       landmarks). No .site-title cosmetic rule needed anymore now that
       the logo replaced every page's visible header title. */
    .callout {
      background: #eef4fb;
      border: 1px solid #cddcee;
      border-radius: 6px;
      padding: 12px 16px;
      margin-top: 18px;
    }
    .callout p {
      margin: 0;
    }
    .section-divider {
      border: none;
      border-top: 1px solid #d9d4c8;
      margin: 26px 0 20px;
    }
    .panel h2 {
      font-size: 19px;
      margin: 0 0 4px;
    }
    .workflow-steps {
      list-style: none;
      margin: 16px 0 0;
      padding: 0;
      border-top: 1px solid #d9d4c8;
    }
    .step-row {
      display: flex;
      align-items: flex-start;
      gap: 18px;
      padding: 16px 0;
      border-bottom: 1px solid #d9d4c8;
    }
    .step-icon {
      flex: 0 0 64px;
      width: 64px;
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .step-icon svg {
      width: 56px;
      height: 56px;
      display: block;
    }
    .step-text {
      flex: 1 1 auto;
      min-width: 0;
      padding-top: 4px;
    }
    .step-text p {
      margin: 0;
    }
    .step-text .callout {
      margin-top: 10px;
    }
    @media (max-width: 720px) {
      main {
        width: min(100% - 28px, 980px);
        padding-top: 20px;
      }
      .site-header { align-items: stretch; }
    }
  </style>
</head>
<body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<main id="main-content" tabindex="-1">
  <header class="site-header">
    <p class="sr-only">Home</p>
    <a class="site-logo" href="/" aria-current="page" aria-label="Customizable Transcription — Home">
      <svg width="40" height="40" viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">
        <rect width="40" height="40" rx="8" fill="#255c99"/>
        <text x="20" y="27" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="16" font-weight="700" fill="#ffffff" text-anchor="middle">CT</text>
      </svg>
    </a>
    <div class="header-nav-row">
      <nav class="site-nav" aria-label="Primary navigation">
        <a class="nav-link" href="/prompt-builder">Prompt Builder</a>
        <a class="nav-link" href="/transcribe">Transcribe</a>
        <a class="nav-link" href="/xls-conversion">XLSX Conversion</a>
        <a class="nav-link" href="/test-mode">Test Mode</a>
      </nav>
      <div class="lang-toggle" role="group" aria-label="Language / Lingua">
        <button type="button" class="lang-flag" data-lang="en" aria-pressed="true" title="English" aria-label="English">🇺🇸</button>
        <button type="button" class="lang-flag" data-lang="it" aria-pressed="false" title="Italiano" aria-label="Italiano">🇮🇹</button>
      </div>
    </div>
  </header>
  <section class="panel">
    <div class="hero-top">
      <h1>Welcome to the Customizable Transcription application.</h1>
    </div>
    <div data-lang-block="en">
      <p>The Customizable Transcription app is designed to help you process large batches of archival images directly from your computer without uploading anything to the Internet. The app can output a transcript of your images into a formatted DOCX file, including translations to Italian and English. You can then convert the transcript into an XLSX index file using the Italian Parish Records standardized index templates.</p>
    </div>
    <div data-lang-block="it" hidden>
      <p>L'app di Trascrizione Personalizzabile è progettata per aiutarti a elaborare grandi lotti di immagini d'archivio direttamente dal tuo computer, senza caricare nulla su Internet. L'app può generare la trascrizione delle tue immagini in un file DOCX formattato, comprese le traduzioni in italiano e inglese. Puoi quindi convertire la trascrizione in un file indice XLSX utilizzando i modelli di indice standardizzati per i registri parrocchiali italiani.</p>
    </div>
    <hr class="section-divider">

    <div data-lang-block="en">
      <h2>Workflow Overview</h2>
      <p>Below is a general overview of the workflow. Go to the <a href="/getting-started">Getting Started</a> page for a complete explanation of each step.</p>
      <div class="callout"><p><strong>Prerequisite:</strong> You must subscribe to a Google Gemini pro account or an Anthropic Claude pro account to use the app because it requires using a direct data connection to the AI system to process your files. Then, you must go to Gemini's <a href="https://aistudio.google.com/api-keys" target="_blank" rel="noopener noreferrer">AI Studio</a> or to <a href="https://platform.claude.com/dashboard" target="_blank" rel="noopener noreferrer">Claude's Platform dashboard</a> to create an API Key. An API key is a password that allows the app to use your pro account to process files.</p></div>
      <ol class="workflow-steps">
        <li class="step-row">
          <div class="step-icon">
            <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
              <rect x="20" y="8" width="20" height="26" rx="2" fill="#ffffff" stroke="#8a8377" stroke-width="1.6"/>
              <rect x="30" y="14" width="20" height="26" rx="2" fill="#ffffff" stroke="#8a8377" stroke-width="1.6"/>
              <path d="M6 24 h16 l4 -5 h24 a3 3 0 0 1 3 3 v28 a3 3 0 0 1 -3 3 H9 a3 3 0 0 1 -3 -3 V27 a3 3 0 0 1 3 -3 Z" fill="#cddcee" stroke="#255c99" stroke-width="1.8"/>
            </svg>
          </div>
          <div class="step-text"><p>Gather your images in a dedicated folder on your computer. Make sure they are named descriptively and numbered sequentially. Good example: "Chiusa Sclafani Battesimi_001.jpg". Use a renamer utility app to rename all of your files in one command. See the <a href="/getting-started">Getting Started</a> page for an explanation.</p></div>
        </li>
        <li class="step-row">
          <div class="step-icon">
            <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
              <rect x="12" y="6" width="40" height="52" rx="3" fill="#ffffff" stroke="#8a8377" stroke-width="1.6"/>
              <rect x="18" y="15" width="7" height="7" rx="1.5" fill="none" stroke="#255c99" stroke-width="1.6"/>
              <path d="M19.5 18.5 l1.8 1.8 l3.2 -3.6" fill="none" stroke="#2f9e5c" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
              <line x1="29" y1="18.5" x2="46" y2="18.5" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <rect x="18" y="27" width="7" height="7" rx="1.5" fill="none" stroke="#255c99" stroke-width="1.6"/>
              <path d="M19.5 30.5 l1.8 1.8 l3.2 -3.6" fill="none" stroke="#2f9e5c" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
              <line x1="29" y1="30.5" x2="46" y2="30.5" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <rect x="18" y="40" width="28" height="9" rx="1.5" fill="#f7f5f0" stroke="#8a8377" stroke-width="1.4"/>
              <line x1="21" y1="44.5" x2="33" y2="44.5" stroke="#d9d4c8" stroke-width="1.8" stroke-linecap="round"/>
            </svg>
          </div>
          <div class="step-text"><p>Build your prompt using the Prompt Builder page. Use the <a id="home-download-worksheets" href="/static/prompt-builder-worksheets/prompt-builder-worksheets-en.zip" download="prompt-builder-worksheets-en.zip">Prompt Builder DOCX files</a> as a worksheet, then copy your content into the Prompt Builder page.</p></div>
        </li>
        <li class="step-row">
          <div class="step-icon">
            <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
              <rect x="14" y="10" width="36" height="46" rx="3" fill="#ffffff" stroke="#8a8377" stroke-width="1.6"/>
              <rect x="24" y="6" width="16" height="8" rx="2" fill="#cddcee" stroke="#255c99" stroke-width="1.4"/>
              <line x1="21" y1="26" x2="43" y2="26" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <line x1="21" y1="34" x2="37" y2="34" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <circle cx="32" cy="46" r="11" fill="#2f9e5c"/>
              <path d="M26.5 46.2 l4 4 l7.5 -8" fill="none" stroke="#ffffff" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <div class="step-text"><p>Test your prompt in the Preflight Test area of the Prompt Builder (optional but highly recommended), refine your prompt, and you are ready to go.</p></div>
        </li>
        <li class="step-row">
          <div class="step-icon">
            <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
              <path d="M16 6 h22 l10 10 v36 a3 3 0 0 1 -3 3 H16 a3 3 0 0 1 -3 -3 V9 a3 3 0 0 1 3 -3 Z" fill="#ffffff" stroke="#255c99" stroke-width="1.6"/>
              <path d="M38 6 v10 h10 Z" fill="#cddcee" stroke="#255c99" stroke-width="1.4" stroke-linejoin="round"/>
              <line x1="19" y1="30" x2="41" y2="30" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <line x1="19" y1="36" x2="41" y2="36" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <line x1="19" y1="42" x2="34" y2="42" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <rect x="14" y="47" width="36" height="12" rx="2" fill="#255c99"/>
              <text x="32" y="55.5" font-family="Arial, sans-serif" font-size="9" font-weight="700" fill="#ffffff" text-anchor="middle">DOCX</text>
            </svg>
          </div>
          <div class="step-text">
            <p>Go to the Transcribe page and select your AI Model, then paste in your API key. Select your Prompt Profile, then run the preflight check. If the preflight is clear, click Confirm and Run and the app will process your files automatically. The app will post an alert when the batch is completed. Follow the Progress Console for the status of your batch. When it is completed, click the Download Document button.</p>
            <div class="callout"><p><strong>Pro Tip:</strong> Always start with a small batch of 1-3 files to test your prompt for accuracy first before running the entire batch.</p></div>
          </div>
        </li>
        <li class="step-row">
          <div class="step-icon">
            <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
              <path d="M16 6 h22 l10 10 v36 a3 3 0 0 1 -3 3 H16 a3 3 0 0 1 -3 -3 V9 a3 3 0 0 1 3 -3 Z" fill="#ffffff" stroke="#2f9e5c" stroke-width="1.6"/>
              <path d="M38 6 v10 h10 Z" fill="#d3f0df" stroke="#2f9e5c" stroke-width="1.4" stroke-linejoin="round"/>
              <rect x="19" y="22" width="22" height="20" fill="none" stroke="#d9d4c8" stroke-width="1.6"/>
              <line x1="19" y1="28.7" x2="41" y2="28.7" stroke="#d9d4c8" stroke-width="1.4"/>
              <line x1="19" y1="35.3" x2="41" y2="35.3" stroke="#d9d4c8" stroke-width="1.4"/>
              <line x1="26.3" y1="22" x2="26.3" y2="42" stroke="#d9d4c8" stroke-width="1.4"/>
              <line x1="33.7" y1="22" x2="33.7" y2="42" stroke="#d9d4c8" stroke-width="1.4"/>
              <rect x="14" y="47" width="36" height="12" rx="2" fill="#2f9e5c"/>
              <text x="32" y="55.5" font-family="Arial, sans-serif" font-size="9" font-weight="700" fill="#ffffff" text-anchor="middle">XLSX</text>
            </svg>
          </div>
          <div class="step-text"><p>When your transcript is completed, check it to make sure everything was processed. Then, go to the XLSX Conversion page. Select the AI Model and paste in your API key. Upload or drop your DOCX transcript into the panel, select the range of transcription you want, choose the output language, run the Preflight, then click Convert. Your conversion XLSX file will download automatically.</p></div>
        </li>
      </ol>
    </div>
    <div data-lang-block="it" hidden>
      <h2>Panoramica del flusso di lavoro</h2>
      <p>Di seguito è riportata una panoramica generale del flusso di lavoro. Vai alla pagina <a href="/getting-started">Per iniziare</a> per una spiegazione completa di ogni passaggio.</p>
      <div class="callout"><p><strong>Prerequisito:</strong> Per usare l'app devi sottoscrivere un account Google Gemini Pro o un account Anthropic Claude Pro, poiché l'app richiede una connessione dati diretta al sistema di intelligenza artificiale per elaborare i tuoi file. Successivamente, devi accedere a Gemini <a href="https://aistudio.google.com/api-keys" target="_blank" rel="noopener noreferrer">AI Studio</a> oppure alla <a href="https://platform.claude.com/dashboard" target="_blank" rel="noopener noreferrer">dashboard della piattaforma di Claude</a> per creare una chiave API. Una chiave API è una password che consente all'app di utilizzare il tuo account Pro per elaborare i file.</p></div>
      <ol class="workflow-steps">
        <li class="step-row">
          <div class="step-icon">
            <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
              <rect x="20" y="8" width="20" height="26" rx="2" fill="#ffffff" stroke="#8a8377" stroke-width="1.6"/>
              <rect x="30" y="14" width="20" height="26" rx="2" fill="#ffffff" stroke="#8a8377" stroke-width="1.6"/>
              <path d="M6 24 h16 l4 -5 h24 a3 3 0 0 1 3 3 v28 a3 3 0 0 1 -3 3 H9 a3 3 0 0 1 -3 -3 V27 a3 3 0 0 1 3 -3 Z" fill="#cddcee" stroke="#255c99" stroke-width="1.8"/>
            </svg>
          </div>
          <div class="step-text"><p>Raccogli le tue immagini in una cartella dedicata sul tuo computer. Assicurati che siano denominate in modo descrittivo e numerate in sequenza. Buon esempio: "Chiusa Sclafani Battesimi_001.jpg". Usa un'app di ridenominazione per rinominare tutti i tuoi file con un solo comando. Consulta la pagina <a href="/getting-started">Per iniziare</a> per una spiegazione.</p></div>
        </li>
        <li class="step-row">
          <div class="step-icon">
            <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
              <rect x="12" y="6" width="40" height="52" rx="3" fill="#ffffff" stroke="#8a8377" stroke-width="1.6"/>
              <rect x="18" y="15" width="7" height="7" rx="1.5" fill="none" stroke="#255c99" stroke-width="1.6"/>
              <path d="M19.5 18.5 l1.8 1.8 l3.2 -3.6" fill="none" stroke="#2f9e5c" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
              <line x1="29" y1="18.5" x2="46" y2="18.5" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <rect x="18" y="27" width="7" height="7" rx="1.5" fill="none" stroke="#255c99" stroke-width="1.6"/>
              <path d="M19.5 30.5 l1.8 1.8 l3.2 -3.6" fill="none" stroke="#2f9e5c" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
              <line x1="29" y1="30.5" x2="46" y2="30.5" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <rect x="18" y="40" width="28" height="9" rx="1.5" fill="#f7f5f0" stroke="#8a8377" stroke-width="1.4"/>
              <line x1="21" y1="44.5" x2="33" y2="44.5" stroke="#d9d4c8" stroke-width="1.8" stroke-linecap="round"/>
            </svg>
          </div>
          <div class="step-text"><p>Crea il tuo prompt utilizzando la pagina Generatore di prompt. Usa i <a id="home-download-worksheets-it" href="/static/prompt-builder-worksheets/prompt-builder-worksheets-it.zip" download="prompt-builder-worksheets-it.zip">file DOCX del Generatore di prompt</a> come foglio di lavoro, poi copia i tuoi contenuti nella pagina Generatore di prompt.</p></div>
        </li>
        <li class="step-row">
          <div class="step-icon">
            <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
              <rect x="14" y="10" width="36" height="46" rx="3" fill="#ffffff" stroke="#8a8377" stroke-width="1.6"/>
              <rect x="24" y="6" width="16" height="8" rx="2" fill="#cddcee" stroke="#255c99" stroke-width="1.4"/>
              <line x1="21" y1="26" x2="43" y2="26" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <line x1="21" y1="34" x2="37" y2="34" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <circle cx="32" cy="46" r="11" fill="#2f9e5c"/>
              <path d="M26.5 46.2 l4 4 l7.5 -8" fill="none" stroke="#ffffff" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <div class="step-text"><p>Testa il tuo prompt nell'area Controllo preliminare del Generatore di prompt (facoltativo ma altamente consigliato), perfeziona il tuo prompt e sei pronto per partire.</p></div>
        </li>
        <li class="step-row">
          <div class="step-icon">
            <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
              <path d="M16 6 h22 l10 10 v36 a3 3 0 0 1 -3 3 H16 a3 3 0 0 1 -3 -3 V9 a3 3 0 0 1 3 -3 Z" fill="#ffffff" stroke="#255c99" stroke-width="1.6"/>
              <path d="M38 6 v10 h10 Z" fill="#cddcee" stroke="#255c99" stroke-width="1.4" stroke-linejoin="round"/>
              <line x1="19" y1="30" x2="41" y2="30" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <line x1="19" y1="36" x2="41" y2="36" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <line x1="19" y1="42" x2="34" y2="42" stroke="#d9d4c8" stroke-width="2.2" stroke-linecap="round"/>
              <rect x="14" y="47" width="36" height="12" rx="2" fill="#255c99"/>
              <text x="32" y="55.5" font-family="Arial, sans-serif" font-size="9" font-weight="700" fill="#ffffff" text-anchor="middle">DOCX</text>
            </svg>
          </div>
          <div class="step-text">
            <p>Vai alla pagina Trascrivi e seleziona il tuo modello IA, poi incolla la tua chiave API. Seleziona il tuo profilo del prompt, quindi esegui il controllo preliminare. Se il controllo preliminare è positivo, clicca su Conferma ed esegui e l'app elaborerà i tuoi file automaticamente. L'app mostrerà un avviso al termine dell'elaborazione del lotto. Segui la Console di avanzamento per lo stato del tuo lotto. Al termine, clicca sul pulsante Scarica documento.</p>
            <div class="callout"><p><strong>Consiglio:</strong> Inizia sempre con un piccolo lotto di 1-3 file per verificare prima l'accuratezza del tuo prompt, prima di elaborare l'intero lotto.</p></div>
          </div>
        </li>
        <li class="step-row">
          <div class="step-icon">
            <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
              <path d="M16 6 h22 l10 10 v36 a3 3 0 0 1 -3 3 H16 a3 3 0 0 1 -3 -3 V9 a3 3 0 0 1 3 -3 Z" fill="#ffffff" stroke="#2f9e5c" stroke-width="1.6"/>
              <path d="M38 6 v10 h10 Z" fill="#d3f0df" stroke="#2f9e5c" stroke-width="1.4" stroke-linejoin="round"/>
              <rect x="19" y="22" width="22" height="20" fill="none" stroke="#d9d4c8" stroke-width="1.6"/>
              <line x1="19" y1="28.7" x2="41" y2="28.7" stroke="#d9d4c8" stroke-width="1.4"/>
              <line x1="19" y1="35.3" x2="41" y2="35.3" stroke="#d9d4c8" stroke-width="1.4"/>
              <line x1="26.3" y1="22" x2="26.3" y2="42" stroke="#d9d4c8" stroke-width="1.4"/>
              <line x1="33.7" y1="22" x2="33.7" y2="42" stroke="#d9d4c8" stroke-width="1.4"/>
              <rect x="14" y="47" width="36" height="12" rx="2" fill="#2f9e5c"/>
              <text x="32" y="55.5" font-family="Arial, sans-serif" font-size="9" font-weight="700" fill="#ffffff" text-anchor="middle">XLSX</text>
            </svg>
          </div>
          <div class="step-text"><p>Quando la trascrizione è completata, controllala per assicurarti che tutto sia stato elaborato. Poi, vai alla pagina Conversione XLSX. Seleziona il modello IA e incolla la tua chiave API. Carica o trascina il tuo documento DOCX trascritto nel pannello, seleziona l'intervallo di trascrizione che desideri, scegli la lingua di output, esegui il controllo preliminare, poi clicca su Converti. Il tuo file di conversione XLSX verrà scaricato automaticamente.</p></div>
        </li>
      </ol>
    </div>
  </section>
  %%FOOTER%%
</main>
</body>
</html>""".replace("%%FOOTER%%", FOOTER_HTML)
