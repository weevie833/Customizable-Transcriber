# Informativa sul trattamento dei dati e sulla privacy

Questo documento spiega cosa succede ai dati quando si utilizza l'app
Trascrittore Personalizzabile, chi è responsabile di cosa e cosa considerare
se la si utilizza nell'Unione Europea o per conto di una parrocchia, di una
diocesi o di un archivio. È scritto per funzionare per due tipi di lettori
contemporaneamente: un genealogista che lo usa per proprio conto, e
un'istituzione (una parrocchia, un archivio diocesano) che vuole qualcosa da
mostrare al proprio ufficio di conformità o al proprio responsabile della
protezione dei dati.

**Questo non è un parere legale.** È una descrizione fattuale del
funzionamento del software e una mappa pratica delle questioni di conformità
che questa descrizione solleva. Se stai trattando registri che potrebbero
riguardare persone viventi, o se stai distribuendo questo strumento per
conto di un'istituzione, richiedi una tua revisione legale prima di
affidarti a questo documento.

## Uso previsto

L'app Trascrittore Personalizzabile è realizzata e testata su **registri
archivistici storici, ecclesiastici e civili** — gli esempi di lavoro in
tutto questo progetto sono registri di battesimo, matrimonio e morte del
XVIII e XIX secolo. Questo uso previsto è rilevante per l'analisi di
conformità qui sotto: le tutele del GDPR si applicano alle persone viventi e
non si estendono ai defunti (GDPR, Considerando 27; alcuni Stati membri
dell'UE estendono alcune tutele ai defunti secondo il proprio diritto
nazionale — se questo potrebbe riguardarti, verifica localmente). Gran parte
di ciò che questo strumento è progettato per elaborare rientra fuori
dall'ambito di applicazione del GDPR proprio per questo motivo.

**Nulla nel software impone questo utilizzo.** È uno strumento di semplice
trascrizione ed estrazione — non ha modo di distinguere un registro
dell'Ottocento da uno del 2020, e nulla impedisce che venga utilizzato su
registri recenti che nominano persone viventi. Se lo fai, l'analisi
contenuta in questo documento cambia sostanzialmente — vedi "Se i tuoi
registri riguardano persone viventi" più sotto.

## Come è strutturato il software, e perché questo è importante

L'app Trascrittore Personalizzabile è un'applicazione locale. Tu (o la tua
istituzione) cloni il codice sorgente e lo esegui interamente sul tuo
computer — non esiste alcun servizio ospitato, nessun server centrale gestito
dagli autori del software, e nessun sistema di account. In concreto:

- Le persone che pubblicano questo software **non ricevono, non vedono e non conservano mai** alcun dato che elabori con esso. Non c'è nulla di cui possano essere titolari o responsabili del trattamento — non hanno alcuna visibilità sul tuo utilizzo.
- Ogni file che questa app legge o scrive — immagini di origine, trascrizioni, fogli di calcolo esportati, profili di prompt salvati — risiede sul tuo filesystem, sotto il tuo controllo, per tutto il tempo che deciderai di conservarlo. Eliminarlo è interamente nelle tue mani; non esiste una copia lato fornitore di cui richiedere separatamente la cancellazione.
- L'unica eccezione alla regola "resta sul tuo computer" è la fase di elaborazione tramite IA stessa — vedi sotto.

## Ruoli secondo il GDPR: chi è il titolare del trattamento

Il GDPR distingue un **titolare del trattamento** (decide perché e come i
dati personali vengono trattati) da un **responsabile del trattamento**
(li tratta secondo le istruzioni del titolare). Applicato a questo software:

- **Chi pubblica il software non è né l'uno né l'altro.** Senza un server centrale, non c'è alcun punto in cui l'editore tratti i dati di qualcuno.
- **Tu sei il titolare del trattamento** per tutto ciò che elabori. Questo vale sia che tu sia un ricercatore individuale sia una parrocchia — lo stesso obbligo esisterebbe se svolgessi questo lavoro con uno scanner e un foglio di calcolo invece che con questa app. Il software può aiutarti ad adempiere a questo obbligo (o non aiutarti), ma non può assolverlo al posto tuo.
- **Google (Gemini) e Anthropic (Claude) agiscono come responsabili del trattamento** — o, più precisamente, come i fornitori di IA alla cui infrastruttura si estendono le tue responsabilità di titolare — per la fase specifica in cui l'app invia contenuti alla loro API per la trascrizione o l'estrazione. Vedi sotto.

## Quali dati questa app invia effettivamente a terzi, e a chi

Quando esegui una trascrizione o un'estrazione tramite Conversione XLSX,
l'app invia quanto segue direttamente dal tuo computer al fornitore di IA
che hai scelto (Google Gemini o Anthropic Claude) — mai tramite alcun
server gestito dall'editore del software:

- Le **immagini di origine o il testo del DOCX caricato** che stai elaborando in quella sessione.
- Il **contenuto del prompt** che descrive come trascrivere/estrarre il contenuto (che può includere un lessico di nomi/luoghi che hai fornito, se il tuo profilo ne ha uno).
- La tua **chiave API**, per autenticare quella richiesta.

Nient'altro lascia il tuo computer. L'app non invia analitiche o telemetria
da nessuna parte e non trasmette nulla all'editore del software.

**Controllo degli aggiornamenti.** Per avvisarti quando è disponibile una
nuova versione, l'app chiede a GitHub (github.com) il nome della sua ultima
versione pubblicata, al massimo circa due volte al giorno mentre l'app è in
esecuzione. La richiesta non contiene nulla su di te, sui tuoi file o sulle
tue impostazioni; come ogni richiesta web, mostra a GitHub il tuo indirizzo
IP. Per disattivarlo, avvia l'app con la variabile d'ambiente
`CT_NO_UPDATE_CHECK=1`.

**Gestione della chiave API** (verificata nell'audit di preparazione alla
produzione di questo progetto): le chiavi vengono mantenute solo in memoria
per la durata della richiesta che le utilizza. Non vengono mai scritte in
alcun file, non vengono mai registrate nei log e non vengono mai trasmesse
altrove se non all'endpoint API del singolo fornitore di IA che stai
utilizzando in quel momento.

## Se i tuoi registri riguardano persone viventi

Se utilizzi questo strumento su materiale che nomina o riguarda persone che
potrebbero essere ancora in vita — un registro recente, un testimone o un
parente citato in una voce altrimenti storica, qualsiasi cosa non
chiaramente chiusa dal tempo — stai trattando dati personali nel pieno
senso del GDPR, e l'analisi sopra si fa considerevolmente più stringente:

- **I registri ecclesiastici sono dati di "categoria particolare".** Un atto di battesimo, matrimonio o morte rivela intrinsecamente l'appartenenza religiosa, che l'articolo 9 del GDPR tratta come una categoria a sensibilità più elevata rispetto ai dati personali ordinari, richiedendo una base giuridica più solida (consenso esplicito, o uno degli altri motivi ristretti dell'articolo 9(2)) rispetto al trattamento ordinario.
- **Devi avere una tua base giuridica** per trattare quei dati in generale, e per inviarli specificamente a Google o Anthropic.
- **Devi avere un tuo accordo con il fornitore di IA.** Sia Google che Anthropic offrono accordi sul trattamento dei dati (DPA) e si basano su clausole contrattuali standard/internazionali (o meccanismi di trasferimento comparabili) per i clienti che trattano dati personali UE tramite le loro API — ma quell'accordo deve esistere direttamente tra *te* (o la tua istituzione) e il fornitore. Questo software non può crearlo né sostituirlo. Verifica direttamente i termini attuali di ciascun fornitore, poiché il meccanismo di trasferimento specifico su cui si basano cambia nel tempo.
- **Trasferimento internazionale**: le chiamate API di Gemini e Claude vengono elaborate su infrastrutture al di fuori dell'UE. Verifica che il tuo accordo con qualsiasi fornitore tu utilizzi si basi su un meccanismo di trasferimento attualmente valido, indipendentemente dalla questione delle categorie particolari sopra descritta.
- **Se sei una parrocchia o un'istituzione diocesana**, questo è molto probabilmente il punto in cui il tuo responsabile della protezione dei dati o il tuo ufficio di conformità deve essere coinvolto prima della distribuzione, non dopo.

## Conservazione dei dati

Questo software non impone alcuna politica di conservazione propria — non
c'è nulla da conservare, poiché non trattiene dati al di fuori del singolo
ciclo di richiesta/risposta di ciascuna chiamata IA. Tutto ciò che conservi
(immagini di origine, trascrizioni, fogli di calcolo esportati, profili
salvati) viene mantenuto esattamente per il tempo che deciderai di
conservare i file sul tuo disco, ed eliminato esattamente quando li
elimini. Se la tua istituzione ha una propria politica di conservazione dei
registri, applicala allo stesso modo in cui la applicheresti a qualsiasi
altro file locale.

## Le tue responsabilità come operatore

In sintesi, se utilizzi questo software, sei responsabile di:

1. Verificare se il materiale che stai elaborando rientra nell'ambito storico-archivistico per cui questo strumento è stato costruito, oppure riguarda persone viventi — e trattare i due casi in modo diverso come descritto sopra.
2. Avere una base giuridica per qualsiasi trattamento di dati di persone viventi, con particolare attenzione allo status di categoria particolare dei registri religiosi.
3. Avere un tuo accordo in essere con qualsiasi fornitore o fornitori di IA tu utilizzi, se stai trattando dati personali di persone viventi tramite essi.
4. Applicare le tue (o della tua istituzione) pratiche di conservazione e cancellazione dei registri ai file prodotti da questo software.
5. Proteggere le tue chiavi API e il computer su cui questo software viene eseguito, allo stesso modo in cui faresti per qualsiasi altro strumento che gestisce materiale sensibile.

## Domande

Questo documento descrive il comportamento del software alla versione che
stai leggendo in questo momento. Se hai domande specifiche relative alla
tua implementazione — soprattutto come istituzione — indirizzale alla tua
funzione legale o di conformità piuttosto che affidarti esclusivamente a
questa informativa.
