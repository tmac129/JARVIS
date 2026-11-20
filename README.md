# JARVIS

Assistente personale per **macOS** e **Windows**, in italiano, a voce e a testo. Un HUD olografico sul computer, una pagina web per il telefono e un comando `jarvis` che agisce su Calendario, Promemoria, Mail, Note, WhatsApp, file, Spotify e impostazioni di sistema.

Il ragionamento è affidato a Claude tramite la CLI ufficiale di Claude Code. Le azioni frequenti (volume, musica, sveglie, timer, apri o chiudi un'app, batteria) passano da un router locale: rispondono subito e senza consumare token.

> Progetto personale, non affiliato ad Anthropic, Apple, Microsoft, Google, Spotify, Marvel o Disney.

**In breve**: JARVIS ascolta o legge i tuoi comandi in italiano e li esegue sulle app che usi ogni giorno. Ogni mattina ti fa un briefing parlato con impegni, promemoria e posta importante.

## Una cartella per piattaforma

| Cartella | Piattaforma | Linguaggio | App collegate | Stato |
|---|---|---|---|---|
| [`macos/`](macos) | macOS 14 o successivo | Swift | app di sistema Apple (Calendario, Promemoria, Mail, Contatti, Note) | provata |
| [`windows/`](windows) | Windows 10 e 11 | Python 3.11 o successivo | account **Google** (Calendar, Tasks, Gmail, Contatti) | **sperimentale: scritta e provata con test automatici su macOS, non ancora provata su un PC Windows** |

Le due versioni hanno gli stessi comandi, lo stesso router, le stesse conferme di sicurezza e la stessa interfaccia. Dove un servizio Apple non ha un equivalente identico, la tabella delle differenze più sotto lo dice con precisione.

## Cosa serve, in sintesi

- Un **Mac** con macOS 14 o successivo, oppure un **PC Windows** 10 o 11 (con WebView2, Python 3.11 o successivo e Git for Windows). **Linux non è supportato**, e non esistono app per iPhone o Android (dal telefono si usa la pagina web).
- Un **abbonamento Claude Pro** (o Max) collegato a Claude Code. Il piano gratuito non basta. In alternativa, un account Anthropic Console a consumo.
- Su Windows, un **account Google** (Calendar, Tasks, Gmail e Contatti vengono letti tramite le API ufficiali di Google).
- Opzionali: Spotify, WhatsApp, Tailscale (per usare il telefono fuori casa).

## App collegate

| Funzione | Cosa può fare | macOS | Windows |
|---|---|---|---|
| Calendario | leggere, creare, spostare, eliminare (con conferma) gli impegni; avviso 15 minuti prima | Calendario (EventKit) | Google Calendar |
| Promemoria | elencare, creare e completare | Promemoria (EventKit) | Google Tasks |
| Mail | leggere le non lette, cercare, preparare bozze, inviare (sempre con conferma) | Mail | Gmail |
| Contatti | cercare indirizzi email e numeri | Contatti | Contatti Google |
| WhatsApp | inviare messaggi (con conferma) | app per Mac: lettura e invio | app per Windows: solo invio |
| Note | creare, cercare, leggere, aggiungere testo | app Note | file Markdown in `Documenti\JARVIS Note` |
| Musica | riproduzione, pausa, brano successivo e precedente, brano in corso, ricerca | Spotify | qualsiasi player (Spotify, browser, Lettore multimediale...); ricerca per nome con Spotify |
| File | cercare, spostare, copiare, rinominare, cestinare, aprire | Finder (Spotlight) | Esplora risorse (ricerca diretta) |
| Documenti e schermo | leggere PDF, Word, RTF, immagini; descrivere cosa c'è sullo schermo | PDFKit, screencapture | pypdf, python-docx, Pillow |
| Sveglie e timer | sveglie ricorrenti e timer con voce | launchd | Utilità di pianificazione |
| Sistema | volume, luminosità, Wi-Fi, tema scuro, blocco, sospensione, batteria, app | AppleScript | pycaw, WinRT, API di Windows |

### Differenze note su Windows

Non sono nascoste: sono i punti dove Windows o Google non offrono la stessa cosa di macOS.

- **WhatsApp, lettura**: `jarvis wa unread`, `chats` e `read` non sono disponibili. WhatsApp per Windows non espone un database locale leggibile come la versione per Mac. L'invio funziona (apre la chat con il testo pronto e preme Invio solo se WhatsApp è in primo piano, sempre dopo la tua conferma). L'unica via ufficiale per leggere sarebbe la WhatsApp Business Cloud API, che richiede un account Business e non è inclusa.
- **Promemoria**: Google Tasks salva solo la **data** di scadenza e non ha la priorità. JARVIS scrive orario e priorità nelle note del promemoria e li mostra nell'elenco, ma Google non ti avvisa all'orario.
- **Note**: non esiste un'app Note di Windows con API locale. Le note sono file `.md` in `Documenti\JARVIS Note`, che puoi aprire con qualunque editor.
- **Sveglie**: partono anche con JARVIS chiuso (Utilità di pianificazione, con riattivazione del PC), ma funzionano solo se hai effettuato l'accesso a Windows.
- **Wi-Fi e luminosità**: dipendono dall'hardware (la luminosità richiede uno schermo integrato o un monitor con DDC/CI). Se Windows rifiuta il comando, JARVIS lo dice.
- **Documenti `.doc`** (vecchio formato Word) non sono supportati: salva come `.docx` o PDF.
- **Voce in uscita**: la qualità dipende dalle voci italiane installate in Windows. Aggiungi la lingua italiana in Impostazioni se la voce è in inglese.

## Briefing del mattino

Ogni mattina, a partire dalle 7:00 e fino a mezzogiorno, JARVIS parla per primo, una sola volta al giorno, mentre l'app è in esecuzione. Il briefing è letto ad alta voce e comprende:

- gli impegni di oggi e i promemoria in scadenza;
- le mail che sembrano importanti;
- su **macOS** anche i messaggi WhatsApp non letti. Su **Windows** il briefing non include WhatsApp, perché la lettura dei messaggi non è disponibile.

Il briefing si può far partire in qualsiasi momento ("briefing") o disattivare dal menu. Le fonti non raggiungibili vengono saltate senza errori.

## Funzioni

- **HUD**: finestra con nucleo animato, telemetria (CPU, memoria, batteria, rete), feed delle azioni e trascrizione. macOS: ⌥Spazio o ⌘⇧J. Windows: Ctrl+Maiusc+J (Alt+Spazio resta al menu finestra di Windows).
- **Voce**: push-to-talk (macOS ⌥⇧Spazio, Windows Alt+Maiusc+Spazio) e ascolto continuo opzionale della parola "Jarvis". Il riconoscimento avviene sul computer: Speech su macOS, Vosk con modello italiano offline su Windows. Le risposte sono lette ad alta voce.
- **Router a più livelli**: Haiku per i comandi normali, Sonnet per analisi e testi. Opus (ragionamento approfondito) e Fable (massima capacità, costo più alto) si usano solo con `/opus` o `/fable`. `/sonnet`, `/haiku`, `/opus` e `/fable` forzano il modello.
- **Iniziativa**: briefing del mattino, avviso 15 minuti prima degli impegni, avviso di batteria scarica.
- **Telefono**: pagina web servita dal computer sulla rete locale, protetta da token. Va aggiunta alla schermata Home.

## Account Claude (obbligatorio)

JARVIS non contiene chiavi né un proprio accesso a Claude. Usa la CLI ufficiale di Claude Code installata sul tuo computer, con il **tuo** account: ogni persona usa il proprio abbonamento e i propri limiti. Il piano gratuito di Claude non basta: Claude Code è incluso negli abbonamenti Pro e Max.

Il login avviene sempre nella CLI ufficiale di Anthropic, mai dentro JARVIS: l'app non vede né salva la tua password o i token di accesso. Ogni richiesta che passa da Claude consuma i limiti del tuo piano (o credito API con la Console). Le azioni frequenti gestite dal router locale non consumano nulla.

Per collegare l'account (dopo aver installato Claude Code, vedi sotto) esegui:

```
claude auth login
```

Si apre il browser per l'accesso a claude.ai. Per pagare a consumo con un account Anthropic Console usa `claude auth login --console`. Controlla con `claude auth status`. Lo stato compare anche nel menu di JARVIS.

## Installazione su macOS

Richiede macOS 14 o successivo, Xcode o i Command Line Tools, e Claude Code collegato al tuo account.

1. Installa Claude Code:

   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   ```
2. Collega il tuo account (si apre il browser):

   ```bash
   claude auth login
   ```
3. Installa gli strumenti di sviluppo Apple, se non li hai:

   ```bash
   xcode-select --install
   ```
4. Scarica JARVIS ed entra nella cartella della versione macOS:

   ```bash
   git clone https://github.com/tmac129/JARVIS.git
   cd JARVIS/macos
   ```
5. Compila e installa:

   ```bash
   ./scripts/build.sh
   ```
6. Al primo uso macOS chiede i permessi elencati più sotto.
7. Verifica:

   ```bash
   jarvis help
   python3 scripts/test_jarvis.py --solo offline
   ```

Lo script compila in modalità release, installa `/Applications/JARVIS.app` e collega il comando in `~/.local/bin/jarvis`. Se esiste un certificato "Apple Development" lo usa per la firma, altrimenti firma ad-hoc. Con un'identità stabile macOS ricorda i permessi tra una build e l'altra. Se `jarvis` non viene trovato, aggiungi `~/.local/bin` al `PATH`.

Al primo avvio macOS chiede i permessi solo quando servono:

| Permesso | Serve per |
|---|---|
| Calendari, Promemoria, Contatti | impegni, promemoria, destinatari |
| Automazione (Mail, Note, Spotify, System Events, WhatsApp) | comandare le app |
| Accessibilità | luminosità, invio automatico su WhatsApp |
| Registrazione schermo | "cosa c'è sullo schermo?" |
| Microfono e Riconoscimento vocale | comandi a voce |
| Accesso completo al disco (opzionale) | lettura veloce di Mail e WhatsApp dai loro database |

Nessuna dipendenza di terze parti: solo framework Apple (AppKit, WebKit, EventKit, PDFKit, Speech, Network) e SQLite di sistema.

### Gmail, Google Calendar, Outlook e altri account su macOS

> Questa sezione vale **solo per macOS**. Su Windows gli account si collegano con il progetto Google Cloud descritto nella sezione Windows più sotto (`jarvis google login`); **Outlook, iCloud e Microsoft To Do non sono supportati su Windows**.

JARVIS per macOS lavora con le app di sistema. Per usare un account Google, Microsoft o iCloud basta aggiungerlo a macOS, senza configurare nulla in JARVIS: **Impostazioni di Sistema > Account Internet > Aggiungi account**, poi attiva le voci che vuoi condividere (Mail, Calendari, Contatti, Promemoria, Note).

## Installazione su Windows

> **Stato: sperimentale.** La versione Windows ha più di 60 test automatici che passano (router, date, conferme, file, note, documenti, ponte verso Claude con un finto `claude`, e tutte le richieste a Google verificate contro le definizioni ufficiali delle API). Le parti che dipendono da Windows stesso (finestra, icona nella barra, volume, luminosità, Wi-Fi, sveglie, voce, scorciatoie, cattura dello schermo) **non sono ancora state provate su un PC Windows pulito**. Se qualcosa non funziona, apri una issue indicando la versione di Windows e il messaggio mostrato.

Richiede Windows 10 o 11 (con WebView2, già presente nelle versioni aggiornate), Python 3.11 o successivo e un account Google.

### 1. Programmi di base

1. Installa [Git for Windows](https://git-scm.com/downloads/win). Claude Code lo usa per il suo strumento Bash, quindi è necessario.
2. Installa [Python 3.12](https://www.python.org/downloads/) e **spunta "Add python.exe to PATH"** nella prima schermata.

### 2. Claude Code

1. In PowerShell:

   ```powershell
   irm https://claude.ai/install.ps1 | iex
   ```

   Da Prompt dei comandi (CMD) il comando equivalente è:

   ```
   curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd
   ```

   Non serve l'amministratore. Chiudi e riapri il terminale a fine installazione.
2. Collega l'account (si apre il browser) e controlla:

   ```powershell
   claude auth login
   claude auth status
   ```

### 3. JARVIS

```powershell
git clone https://github.com/tmac129/JARVIS.git
cd JARVIS\windows
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

In alternativa, `install.bat` esegue gli stessi passi. Se non hai Python 3.12 usa `py -3` al posto di `py -3.12`.

Verifica l'installazione (non servono account né rete):

```powershell
python -m unittest discover -s tests
jarvis help
jarvis doctor
```

`jarvis doctor` controlla Claude Code, Git Bash, le librerie, WebView2, audio, microfono e sveglie, e stampa un report senza dati personali (il nome utente nei percorsi è nascosto): incollalo quando segnali un problema.

### 4. Account Google

JARVIS legge Calendar, Tasks, Gmail e Contatti con le API ufficiali di Google. Per farlo serve un progetto nella Google Cloud Console **tuo**: nessuna credenziale è inclusa nel repository, e restano sul tuo PC.

1. Vai su [console.cloud.google.com](https://console.cloud.google.com/) e crea un progetto (per esempio "JARVIS").
2. In **API e servizi > Libreria** abilita quattro API: **Google Calendar API**, **Tasks API**, **Gmail API**, **People API**.
3. Configura la schermata di consenso OAuth (sezione "Google Auth Platform" o "Schermata consenso OAuth", a seconda della versione della console): tipo di utente **Esterno**, nome app "JARVIS", la tua email come contatto.
4. Aggiungi il tuo account Google tra gli **utenti di prova**. Importante: finché l'app resta in stato "Test", Google fa scadere l'accesso dopo **7 giorni** e dovrai rifare il login. Per evitarlo, sposta l'app in **produzione** dalla stessa schermata: per uso personale non serve la verifica di Google, vedrai solo l'avviso "App non verificata" (Avanzate > Vai a JARVIS).
5. In **Credenziali > Crea credenziali > ID client OAuth** scegli tipo **App desktop**, poi scarica il file JSON.
6. Salva il file con questo nome esatto, creando la cartella se manca:

   ```
   %APPDATA%\JARVIS\google_client.json
   ```
7. Collega l'account (si apre il browser; accetta i permessi richiesti):

   ```powershell
   jarvis google login
   ```
8. Controlla:

   ```powershell
   jarvis google status
   jarvis cal list oggi
   ```

Permessi richiesti a Google: Calendar (lettura e scrittura), Tasks (lettura e scrittura), Gmail (lettura, bozze e invio; la cancellazione definitiva non è richiesta), Contatti (sola lettura). `jarvis google logout` rimuove il token da questo PC; puoi revocare l'accesso anche da [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

### 5. Voce (facoltativo)

Per i comandi a voce serve il modello italiano di Vosk (circa 50 MB, scaricato una volta da alphacephei.com):

```powershell
jarvis setup-voice
```

Il riconoscimento resta sul PC: nessun audio viene inviato in rete. Consenti l'accesso al microfono alle app desktop in **Impostazioni > Privacy e sicurezza > Microfono**.

Per una voce italiana più naturale installane una migliore da **Impostazioni > Ora e lingua > Voce > Aggiungi voci**. Dal menu dell'icona, **Voce > Scarica voci italiane migliori...** apre la guida.

### 6. Avvio

```powershell
jarvis-hud
```

Compare la finestra HUD e un'icona nella barra delle applicazioni (vicino all'orologio, forse dentro la freccia "mostra icone nascoste"). La X nasconde la finestra; si esce dal menu dell'icona. Dal menu puoi anche attivare l'avvio automatico all'accesso.

### Permessi e configurazione su Windows

Il menu **Permessi e configurazione** controlla (in sola lettura) microfono, notifiche, modello vocale offline e account Google, e apre la pagina di Impostazioni giusta con un clic. Windows non ha i permessi Accessibilità e Registrazione schermo di macOS, quindi non servono.

### Su Windows, in breve

- **Claude** può eseguire solo il comando `jarvis`: `jarvis.exe` vive nella cartella `.venv\Scripts`, aggiunta al `PATH` solo per il processo di Claude.
- **Dati**: `%APPDATA%\JARVIS` (preferenze, log, token Google, stato).
- **Server per il telefono**: alla prima attivazione Windows chiede di consentire l'accesso di rete: scegli **Reti private**.
- **Se qualcosa non va**: `%APPDATA%\JARVIS\claude.err.log` contiene gli errori di Claude Code; il feed del HUD mostra le azioni eseguite.

## Uso

- **HUD**: richiama con la scorciatoia (vedi sopra), scrivi o premi MIC. ESC nasconde.
- **Terminale**: `jarvis help` mostra tutti i comandi. `jarvis chat` apre una conversazione, `jarvis ask "..."` invia una domanda singola.
- **Telefono**: menu JARVIS (barra dei menu su Mac, icona nella barra su Windows) > Telefono > "Accesso dal telefono attivo", poi "Collega telefono (codice QR)".

Esempi: "che impegni ho domani?", "manda una mail a Marco con la relazione allegata", "sposta i pdf della scrivania nella cartella Scuola", "metti una sveglia alle 7", "briefing".

### Scegliere i moduli

Dal menu di JARVIS > **Moduli** puoi attivare o disattivare: Mail e contatti, Calendario, Promemoria, WhatsApp, Note, File e documenti, Musica, Schermo. Sveglie, timer e comandi di sistema restano sempre attivi.

Un modulo disattivato sparisce dalle istruzioni date a Claude e dal briefing, e i suoi comandi vengono rifiutati anche quando arrivano dal telefono o dal terminale. La scelta è salvata in `modules.json` (macOS: `~/Library/Application Support/JARVIS`, Windows: `%APPDATA%\JARVIS`) e resta valida dopo il riavvio.

## Sicurezza e privacy

- **Conferma obbligatoria** per le azioni irreversibili o rischiose: inviare mail e WhatsApp, eliminare eventi, cestinare file, spostamenti in blocco, operazioni da o verso cartelle di sistema o nascoste, apertura di app e script. Il modello può solo *chiedere* la conferma. Il dialogo mostra il riepilogo registrato dallo strumento, non testo che il modello o una mail potrebbero falsificare.
- **Claude con permessi minimi**: il solo strumento `Bash` limitato al comando `jarvis` (in più `Read`, solo per le richieste che leggono lo schermo), nessun server MCP, `jarvis confirm` vietato. In più il comando rifiuta le conferme quando lo chiama il modello.
- **Testi non fidati**: il prompt di sistema tratta mail, chat, pagine web e documenti come dati, non come istruzioni. Resta comunque un sistema basato su un modello linguistico: leggi sempre il riepilogo prima di confermare.
- **Server per il telefono**: spento di default. Usa un token casuale e HTTP in chiaro sulla rete locale. Attivalo solo su reti fidate o tramite Tailscale, non esporre mai la porta 8787 su Internet e non condividere il link con il token.
- **Dati locali**: preferenze, log delle azioni, token e stato sono nella cartella dati dell'utente (vedi sopra), mai nel repository. Su Windows il token Google è in `google_token.json` in quella cartella: trattalo come una password. I testi delle richieste passano dalla CLI di Claude Code secondo le condizioni del tuo account.
- **Login**: i login di Claude e di Google li esegui tu, dal terminale; il modello non può avviarli.

Per segnalare una vulnerabilità vedi [SECURITY.md](SECURITY.md).

## Struttura

```
macos/
  Sources/JarvisCore/   strumenti (Mail, Calendario, File, ...), router, prompt, bridge verso Claude
  Sources/jarvis/       CLI `jarvis`
  Sources/JarvisApp/    app macOS: HUD, voce, iniziativa, server per il telefono, telemetria
  HUD/                  interfaccia web dell'HUD e pagina mobile
  Resources/            Info.plist e icona
  scripts/              build, icona, test end-to-end
windows/
  jarvis/               pacchetto Python: core, router, bridge verso Claude, CLI
  jarvis/tools/         strumenti (Google Calendar, Tasks, Gmail, file, sistema, musica, ...)
  jarvis/app/           app Windows: HUD, icona nella barra, voce, iniziativa, server per il telefono
  jarvis/HUD/           interfaccia web dell'HUD e pagina mobile
  tests/                test automatici
```

## Test

**macOS.** Con JARVIS.app in esecuzione e l'accesso da telefono attivo, dalla cartella `macos`:

```bash
python3 scripts/test_jarvis.py
```

La suite completa crea e poi elimina eventi, note e file di prova, e verifica le conferme senza inviare nulla. I controlli che non richiedono l'app né l'account Claude: `python3 scripts/test_jarvis.py --solo offline`.

**Windows.** Dalla cartella `windows`, con l'ambiente virtuale attivo:

```powershell
python -m unittest discover -s tests
```

In alternativa, da `JARVIS` con pytest installato: `python -m pytest windows/tests`.

Non servono account, rete né Claude: il ponte verso Claude si prova su macOS e Linux con un finto `claude` (su Windows quei test vengono saltati), e le richieste a Google si verificano con risposte simulate.

## Licenza

[MIT](LICENSE)
