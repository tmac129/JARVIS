# JARVIS

Assistente personale per macOS, in italiano, a voce e a testo. Un HUD olografico sul Mac, una pagina web per il telefono e un comando `jarvis` che agisce su Calendario, Promemoria, Mail, Note, WhatsApp, Finder, musica e impostazioni di sistema.

Il ragionamento è affidato a Claude tramite la CLI ufficiale di Claude Code. Le azioni frequenti (volume, musica, sveglie, timer, apri o chiudi un'app, batteria) passano da un router locale: rispondono subito e senza consumare token.

> Progetto personale, non affiliato ad Anthropic, Apple, Marvel o Disney.

**In breve**: JARVIS è un assistente che gira sul tuo Mac, ascolta o legge i tuoi comandi in italiano e li esegue sulle app che usi ogni giorno. Ogni mattina ti fa un briefing parlato con impegni, messaggi e posta importanti, le notizie principali dall'Italia e cosa succede sui mercati finanziari.

**Cosa serve, in sintesi**

- Un **Mac** con macOS 14 o successivo. La versione attuale è solo per macOS. Una versione per Windows è in programma (vedi Installazione). Non esistono versioni per Linux, iPhone o Android.
- Un **abbonamento Claude Pro** (o Max) collegato a Claude Code. Il piano gratuito non basta. In alternativa, un account Anthropic Console a consumo.
- Le app di sistema che vuoi far usare a JARVIS (vedi [App collegate](#app-collegate)).

## App collegate

JARVIS non ha un proprio account per le tue app: lavora con quelle già installate e configurate sul Mac, e macOS chiede il permesso la prima volta che servono.

| App | Cosa può fare |
|---|---|
| Calendario | leggere gli impegni, crearli, spostarli, eliminarli (con conferma), avvisarti 15 minuti prima |
| Promemoria | elencare, creare e completare promemoria |
| Mail | leggere le non lette, cercare, preparare bozze e inviare (l'invio chiede sempre conferma) |
| Contatti | cercare indirizzi email e numeri per i destinatari |
| WhatsApp (app per Mac) | leggere i messaggi non letti e inviarne (con conferma) |
| Note | creare e cercare note |
| Musica e Spotify | riproduzione, pausa, brano successivo, ricerca |
| Finder | cercare, spostare, copiare, rinominare, cestinare e aprire file |
| Documenti e schermo | leggere PDF, Word, RTF, immagini e descrivere cosa c'è sullo schermo |
| Sveglie e timer | sveglie ricorrenti (launchd) e timer con voce |
| Sistema | volume, luminosità, Wi-Fi, batteria, apri o chiudi app |
| Notizie | titoli da ANSA e Sole 24 Ore (Italia, economia, finanza) |

Gmail, Google Calendar, Outlook e iCloud funzionano aggiungendo l'account a macOS (vedi sotto). Ogni modulo si può disattivare dal menu di JARVIS.

## Briefing del mattino

Ogni mattina, a partire dalle 7:00 e fino a mezzogiorno, JARVIS parla per primo, una sola volta al giorno, mentre l'app è in esecuzione sul Mac. Il briefing è letto ad alta voce e comprende:

- gli impegni di oggi e i promemoria in scadenza;
- le mail e i messaggi WhatsApp che sembrano importanti;
- **le notizie principali in Italia**: i titoli più rilevanti di ANSA e Sole 24 Ore;
- **cosa succede in borsa e sui mercati**: i titoli di finanza ed economia di Sole 24 Ore e ANSA Economia.

Le notizie di borsa sono titoli giornalistici sintetizzati da Claude, non quotazioni in tempo reale e non consigli di investimento. Il briefing si può far partire in qualsiasi momento ("briefing") o disattivare dal menu. Le fonti non raggiungibili vengono saltate senza errori.

## Funzioni

- **HUD per macOS**: finestra con nucleo animato, telemetria (CPU, memoria, batteria, rete), feed delle azioni e trascrizione. Si richiama con ⌥Spazio o ⌘⇧J.
- **Voce**: push-to-talk con ⌥⇧Spazio e ascolto continuo opzionale della parola "Jarvis". Il riconoscimento avviene sul dispositivo quando macOS lo supporta. Le risposte sono lette ad alta voce.
- **Router a più livelli**: Haiku per i comandi normali, Sonnet per analisi e testi. Opus (ragionamento approfondito) e Fable (massima capacità, costo più alto) si usano solo con `/opus` o `/fable`. `/sonnet`, `/haiku`, `/opus` e `/fable` forzano il modello.
- **Strumenti**: Mail (lettura, ricerca, bozze, invio), Contatti, Calendario, Promemoria, sveglie (launchd) e timer, file (ricerca Spotlight, sposta, copia, rinomina, cestina), WhatsApp, Note, musica (Spotify e Apple Music), notizie RSS, lettura di documenti (PDF, Word, RTF, immagini), schermate.
- **Iniziativa**: briefing del mattino, avviso 15 minuti prima degli impegni, avviso di batteria scarica.
- **Telefono**: pagina web servita dal Mac sulla rete locale, protetta da token. Va aggiunta alla schermata Home.

## Requisiti

| | |
|---|---|
| Sistema | macOS 14 Sonoma o successivo (sviluppato e provato su Apple Silicon) |
| Compilatore | Swift 5.10+ (Xcode 16 o Command Line Tools) |
| AI | [Claude Code](https://code.claude.com/docs) installato e collegato al **tuo** account (vedi sotto) |
| Account | Abbonamento Claude **Pro** o Max, oppure un account Anthropic Console con consumo a pagamento |
| Opzionali | WhatsApp per Mac, Spotify, Tailscale (per usarlo da fuori casa) |

Nessuna dipendenza di terze parti: solo framework Apple (AppKit, WebKit, EventKit, PDFKit, Speech, Network) e SQLite di sistema. Lo script di test usa solo la libreria standard di Python 3.

**Linux non è supportato.** La versione attuale usa API native di macOS (AppleScript, EventKit, launchd, WebKit). Una versione per Windows è in programma e userà app compatibili con Windows (Outlook, Microsoft To Do) al posto di quelle Apple. Fino ad allora, `scripts\build.bat` spiega la situazione ed esce.

## Account Claude (obbligatorio)

JARVIS non contiene chiavi né un proprio accesso a Claude. Usa la CLI ufficiale di Claude Code installata sul tuo Mac, con il **tuo** account: ogni persona usa il proprio abbonamento e i propri limiti. Il piano gratuito di Claude non basta: Claude Code è incluso negli abbonamenti Pro e Max.

1. Installa Claude Code seguendo la [guida ufficiale](https://code.claude.com/docs/en/setup). Su macOS: `curl -fsSL https://claude.ai/install.sh | bash`. Su Windows, vedi la sezione Installazione.
2. Collega l'account dal Terminale:

   ```bash
   claude auth login
   ```

   Si apre il browser per l'accesso a claude.ai. Per pagare a consumo con un account Anthropic Console usa invece `claude auth login --console`.
3. Controlla che il collegamento sia attivo:

   ```bash
   claude auth status
   ```

   Lo stato compare anche nella prima riga del menu di JARVIS (per esempio "Account Claude: Pro"). Se l'account non è collegato, la voce spiega cosa fare e copia il comando.

Il login avviene sempre nella CLI ufficiale di Anthropic, mai dentro JARVIS: l'app non vede né salva la tua password o i token di accesso. Ogni richiesta che passa da Claude consuma i limiti del tuo piano (o credito API con la Console). Le azioni frequenti gestite dal router locale non consumano nulla.

## Installazione

### macOS (versione attuale)

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
4. Scarica e installa JARVIS:

   ```bash
   git clone https://github.com/tmac129/JARVIS.git
   cd JARVIS
   ./scripts/build.sh
   ```
5. Al primo uso macOS chiede i permessi elencati più sotto.
6. Verifica: `jarvis help`.

Lo script compila in modalità release, installa `/Applications/JARVIS.app` e collega il comando in `~/.local/bin/jarvis`. Se esiste un certificato "Apple Development" lo usa per la firma, altrimenti firma ad-hoc. Con un'identità stabile macOS ricorda i permessi tra una build e l'altra.

Al primo avvio macOS chiede i permessi solo quando servono:

| Permesso | Serve per |
|---|---|
| Calendari, Promemoria, Contatti | impegni, promemoria, destinatari |
| Automazione (Mail, Note, Music, Spotify, System Events, WhatsApp) | comandare le app |
| Accessibilità | luminosità, invio automatico su WhatsApp |
| Registrazione schermo | "cosa c'è sullo schermo?" |
| Microfono e Riconoscimento vocale | comandi a voce |
| Accesso completo al disco (opzionale) | lettura veloce di Mail e WhatsApp dai loro database |

### Windows (in programma)

> La versione Windows non è ancora disponibile. I passi seguenti descrivono l'installazione prevista e saranno verificati quando il porting sarà completato. Non seguirli come guida funzionante prima di allora.

1. Installa [Git for Windows](https://git-scm.com/downloads/win).
2. Installa [Python 3.12](https://www.python.org/downloads/) e spunta "Add python.exe to PATH".
3. Apri PowerShell e installa Claude Code:

   ```powershell
   irm https://claude.ai/install.ps1 | iex
   ```
4. Avvia `claude` e completa il login nel browser. Controlla con `claude auth status`.
5. Scarica JARVIS:

   ```powershell
   git clone https://github.com/tmac129/JARVIS.git
   cd JARVIS
   ```
6. Crea l'ambiente Python e installa le dipendenze:

   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
7. Avvia JARVIS: `python -m jarvis`. Al primo avvio, collega i tuoi account Microsoft seguendo il codice mostrato nel terminale.

## Uso

- **HUD**: ⌥Spazio, scrivi o premi MIC. ESC nasconde.
- **Terminale**: `jarvis help` mostra tutti i comandi. `jarvis chat` apre una conversazione, `jarvis ask "..."` invia una domanda singola.
- **Telefono**: menu JARVIS nella barra dei menu > "Accesso da iPhone attivo", poi "Collega iPhone (codice QR)".

Esempi: "che impegni ho domani?", "manda una mail a Marco con la relazione allegata", "sposta i pdf della scrivania nella cartella Scuola", "metti una sveglia alle 7", "briefing".

### Scegliere i moduli

Dal menu di JARVIS > **Moduli** puoi attivare o disattivare: Mail e contatti, Calendario, Promemoria, WhatsApp, Note, File e documenti, Musica, Notizie, Schermo. Sveglie, timer e comandi di sistema restano sempre attivi.

Un modulo disattivato sparisce dalle istruzioni date a Claude e dal briefing, e i suoi comandi vengono rifiutati anche quando arrivano dal telefono o dal Terminale. La scelta è salvata in `~/Library/Application Support/JARVIS/modules.json` e resta valida dopo il riavvio.

### Gmail, Google Calendar, Outlook e altri account

JARVIS lavora con le app di sistema: Mail, Calendario, Promemoria, Contatti e Note. Per usare un account Google, Microsoft o iCloud basta aggiungerlo a macOS, senza configurare nulla in JARVIS:

**Impostazioni di Sistema > Account Internet > Aggiungi account**, poi attiva le voci che vuoi condividere (Mail, Calendari, Contatti, Promemoria, Note).

Da quel momento "che impegni ho domani?" legge anche Google Calendar e "mail non lette" anche Gmail, tramite le app Apple. Ogni persona sceglie cosa collegare direttamente in macOS, e può revocarlo da lì in qualsiasi momento.

## Sicurezza e privacy

- **Conferma obbligatoria** per le azioni irreversibili o rischiose: inviare mail e WhatsApp, eliminare eventi, cestinare file, spostamenti in blocco, operazioni da o verso cartelle di sistema o nascoste, apertura di app e script. Il modello può solo *chiedere* la conferma. Il dialogo mostra il riepilogo registrato dallo strumento, non testo che il modello o una mail potrebbero falsificare.
- **Claude con permessi minimi**: il solo strumento `Bash` limitato al comando `jarvis` (in più `Read`, solo per le richieste che leggono lo schermo), nessun server MCP, `jarvis confirm` vietato. In più il binario rifiuta le conferme quando lo chiama il modello.
- **Testi non fidati**: il prompt di sistema tratta mail, chat, pagine web e documenti come dati, non come istruzioni. Resta comunque un sistema basato su un modello linguistico: leggi sempre il riepilogo prima di confermare.
- **Server per il telefono**: spento di default. Usa un token casuale a 24 caratteri e HTTP in chiaro sulla rete locale. Attivalo solo su reti fidate o tramite Tailscale, non esporre mai la porta 8787 su Internet e non condividere il link con il token.
- **Dati locali**: preferenze, log delle azioni, token e stato sono in `~/Library/Application Support/JARVIS`, mai nel repository. I testi delle richieste passano dalla CLI di Claude Code secondo le condizioni del tuo account.

Per segnalare una vulnerabilità vedi [SECURITY.md](SECURITY.md).

## Struttura

```
Sources/JarvisCore/   strumenti (Mail, Calendario, File, ...), router, prompt, bridge verso Claude
Sources/jarvis/       CLI `jarvis`
Sources/JarvisApp/    app macOS: HUD, voce, iniziativa, server per il telefono, telemetria
HUD/                  interfaccia web dell'HUD e pagina mobile
Resources/            Info.plist e icona
scripts/              build, icona, test end-to-end
```

## Test

Con JARVIS.app in esecuzione e l'accesso da iPhone attivo:

```bash
python3 scripts/test_jarvis.py
```

La suite completa crea e poi elimina eventi, note e file di prova, e verifica le conferme senza inviare nulla.

I controlli che non richiedono l'app né l'account Claude si lanciano con `python3 scripts/test_jarvis.py --solo offline`.

## Licenza

[MIT](LICENSE)
# JARVIS

Assistente personale per macOS, in italiano, a voce e a testo. Un HUD olografico sul Mac, una pagina web per il telefono e un comando `jarvis` che agisce su Calendario, Promemoria, Mail, Note, WhatsApp, Finder, musica e impostazioni di sistema.

Il ragionamento è affidato a Claude tramite la CLI ufficiale di Claude Code. Le azioni frequenti (volume, musica, sveglie, timer, apri o chiudi un'app, batteria) passano da un router locale: rispondono subito e senza consumare token.

> Progetto personale, non affiliato ad Anthropic, Apple, Marvel o Disney.

**In breve**: JARVIS è un assistente che gira sul tuo Mac, ascolta o legge i tuoi comandi in italiano e li esegue sulle app che usi ogni giorno. Ogni mattina ti fa un briefing parlato con impegni, messaggi e posta importanti, le notizie principali dall'Italia e cosa succede sui mercati finanziari.

**Cosa serve, in sintesi**

- Un **Mac** con macOS 14 o successivo. È disponibile **solo per macOS**: non esistono versioni per Windows, Linux, iPhone o Android.
- Un **abbonamento Claude Pro** (o Max) collegato a Claude Code. Il piano gratuito non basta. In alternativa, un account Anthropic Console a consumo.
- Le app di sistema che vuoi far usare a JARVIS (vedi [App collegate](#app-collegate)).

## App collegate

JARVIS non ha un proprio account per le tue app: lavora con quelle già installate e configurate sul Mac, e macOS chiede il permesso la prima volta che servono.

| App | Cosa può fare |
|---|---|
| Calendario | leggere gli impegni, crearli, spostarli, eliminarli (con conferma), avvisarti 15 minuti prima |
| Promemoria | elencare, creare e completare promemoria |
| Mail | leggere le non lette, cercare, preparare bozze e inviare (l'invio chiede sempre conferma) |
| Contatti | cercare indirizzi email e numeri per i destinatari |
| WhatsApp (app per Mac) | leggere i messaggi non letti e inviarne (con conferma) |
| Note | creare e cercare note |
| Musica e Spotify | riproduzione, pausa, brano successivo, ricerca |
| Finder | cercare, spostare, copiare, rinominare, cestinare e aprire file |
| Documenti e schermo | leggere PDF, Word, RTF, immagini e descrivere cosa c'è sullo schermo |
| Sveglie e timer | sveglie ricorrenti (launchd) e timer con voce |
| Sistema | volume, luminosità, Wi-Fi, batteria, apri o chiudi app |
| Notizie | titoli da ANSA e Sole 24 Ore (Italia, economia, finanza) |

Gmail, Google Calendar, Outlook e iCloud funzionano aggiungendo l'account a macOS (vedi sotto). Ogni modulo si può disattivare dal menu di JARVIS.

## Briefing del mattino

Ogni mattina, a partire dalle 7:00 e fino a mezzogiorno, JARVIS parla per primo, una sola volta al giorno, mentre l'app è in esecuzione sul Mac. Il briefing è letto ad alta voce e comprende:

- gli impegni di oggi e i promemoria in scadenza;
- le mail e i messaggi WhatsApp che sembrano importanti;
- **le notizie principali in Italia**: i titoli più rilevanti di ANSA e Sole 24 Ore;
- **cosa succede in borsa e sui mercati**: i titoli di finanza ed economia di Sole 24 Ore e ANSA Economia.

Le notizie di borsa sono titoli giornalistici sintetizzati da Claude, non quotazioni in tempo reale e non consigli di investimento. Il briefing si può far partire in qualsiasi momento ("briefing") o disattivare dal menu. Le fonti non raggiungibili vengono saltate senza errori.

## Funzioni

- **HUD per macOS**: finestra con nucleo animato, telemetria (CPU, memoria, batteria, rete), feed delle azioni e trascrizione. Si richiama con ⌥Spazio o ⌘⇧J.
- **Voce**: push-to-talk con ⌥⇧Spazio e ascolto continuo opzionale della parola "Jarvis". Il riconoscimento avviene sul dispositivo quando macOS lo supporta. Le risposte sono lette ad alta voce.
- **Router a più livelli**: Haiku per i comandi normali, Sonnet per analisi e testi. Opus (ragionamento approfondito) e Fable (massima capacità, costo più alto) si usano solo con `/opus` o `/fable`. `/sonnet`, `/haiku`, `/opus` e `/fable` forzano il modello.
- **Strumenti**: Mail (lettura, ricerca, bozze, invio), Contatti, Calendario, Promemoria, sveglie (launchd) e timer, file (ricerca Spotlight, sposta, copia, rinomina, cestina), WhatsApp, Note, musica (Spotify e Apple Music), notizie RSS, lettura di documenti (PDF, Word, RTF, immagini), schermate.
- **Iniziativa**: briefing del mattino, avviso 15 minuti prima degli impegni, avviso di batteria scarica.
- **Telefono**: pagina web servita dal Mac sulla rete locale, protetta da token. Va aggiunta alla schermata Home.

## Requisiti

| | |
|---|---|
| Sistema | macOS 14 Sonoma o successivo (sviluppato e provato su Apple Silicon) |
| Compilatore | Swift 5.10+ (Xcode 16 o Command Line Tools) |
| AI | [Claude Code](https://code.claude.com/docs) installato e collegato al **tuo** account (vedi sotto) |
| Account | Abbonamento Claude **Pro** o Max, oppure un account Anthropic Console con consumo a pagamento |
| Opzionali | WhatsApp per Mac, Spotify, Tailscale (per usarlo da fuori casa) |

Nessuna dipendenza di terze parti: solo framework Apple (AppKit, WebKit, EventKit, PDFKit, Speech, Network) e SQLite di sistema. Lo script di test usa solo la libreria standard di Python 3.

**Windows e Linux non sono supportati.** JARVIS usa API native di macOS (AppleScript, EventKit, launchd, WebKit) che non esistono altrove. `scripts\build.bat` lo spiega ed esce. Da un PC o da un telefono si può comunque usare la pagina web servita dal Mac.

## Account Claude (obbligatorio)

JARVIS non contiene chiavi né un proprio accesso a Claude. Usa la CLI ufficiale di Claude Code installata sul tuo Mac, con il **tuo** account: ogni persona usa il proprio abbonamento e i propri limiti. Il piano gratuito di Claude non basta: Claude Code è incluso negli abbonamenti Pro e Max.

1. Installa Claude Code seguendo la [guida ufficiale](https://code.claude.com/docs).
2. Collega l'account dal Terminale:

   ```bash
   claude auth login
   ```

   Si apre il browser per l'accesso a claude.ai. Per pagare a consumo con un account Anthropic Console usa invece `claude auth login --console`.
3. Controlla che il collegamento sia attivo:

   ```bash
   claude auth status
   ```

   Lo stato compare anche nella prima riga del menu di JARVIS (per esempio "Account Claude: Pro"). Se l'account non è collegato, la voce spiega cosa fare e copia il comando.

Il login avviene sempre nella CLI ufficiale di Anthropic, mai dentro JARVIS: l'app non vede né salva la tua password o i token di accesso. Ogni richiesta che passa da Claude consuma i limiti del tuo piano (o credito API con la Console). Le azioni frequenti gestite dal router locale non consumano nulla.

## Installazione

```bash
git clone https://github.com/tmac129/JARVIS.git
cd JARVIS
./scripts/build.sh
```

Lo script compila in modalità release, installa `/Applications/JARVIS.app` e collega il comando in `~/.local/bin/jarvis`. Se esiste un certificato "Apple Development" lo usa per la firma, altrimenti firma ad-hoc. Con un'identità stabile macOS ricorda i permessi tra una build e l'altra.

Al primo avvio macOS chiede i permessi solo quando servono:

| Permesso | Serve per |
|---|---|
| Calendari, Promemoria, Contatti | impegni, promemoria, destinatari |
| Automazione (Mail, Note, Music, Spotify, System Events, WhatsApp) | comandare le app |
| Accessibilità | luminosità, invio automatico su WhatsApp |
| Registrazione schermo | "cosa c'è sullo schermo?" |
| Microfono e Riconoscimento vocale | comandi a voce |
| Accesso completo al disco (opzionale) | lettura veloce di Mail e WhatsApp dai loro database |

## Uso

- **HUD**: ⌥Spazio, scrivi o premi MIC. ESC nasconde.
- **Terminale**: `jarvis help` mostra tutti i comandi. `jarvis chat` apre una conversazione, `jarvis ask "..."` invia una domanda singola.
- **Telefono**: menu JARVIS nella barra dei menu > "Accesso da iPhone attivo", poi "Collega iPhone (codice QR)".

Esempi: "che impegni ho domani?", "manda una mail a Marco con la relazione allegata", "sposta i pdf della scrivania nella cartella Scuola", "metti una sveglia alle 7", "briefing".

### Scegliere i moduli

Dal menu di JARVIS > **Moduli** puoi attivare o disattivare: Mail e contatti, Calendario, Promemoria, WhatsApp, Note, File e documenti, Musica, Notizie, Schermo. Sveglie, timer e comandi di sistema restano sempre attivi.

Un modulo disattivato sparisce dalle istruzioni date a Claude e dal briefing, e i suoi comandi vengono rifiutati anche quando arrivano dal telefono o dal Terminale. La scelta è salvata in `~/Library/Application Support/JARVIS/modules.json` e resta valida dopo il riavvio.

### Gmail, Google Calendar, Outlook e altri account

JARVIS lavora con le app di sistema: Mail, Calendario, Promemoria, Contatti e Note. Per usare un account Google, Microsoft o iCloud basta aggiungerlo a macOS, senza configurare nulla in JARVIS:

**Impostazioni di Sistema > Account Internet > Aggiungi account**, poi attiva le voci che vuoi condividere (Mail, Calendari, Contatti, Promemoria, Note).

Da quel momento "che impegni ho domani?" legge anche Google Calendar e "mail non lette" anche Gmail, tramite le app Apple. Ogni persona sceglie cosa collegare direttamente in macOS, e può revocarlo da lì in qualsiasi momento.

## Sicurezza e privacy

- **Conferma obbligatoria** per le azioni irreversibili o rischiose: inviare mail e WhatsApp, eliminare eventi, cestinare file, spostamenti in blocco, operazioni da o verso cartelle di sistema o nascoste, apertura di app e script. Il modello può solo *chiedere* la conferma. Il dialogo mostra il riepilogo registrato dallo strumento, non testo che il modello o una mail potrebbero falsificare.
- **Claude con permessi minimi**: il solo strumento `Bash` limitato al comando `jarvis` (in più `Read`, solo per le richieste che leggono lo schermo), nessun server MCP, `jarvis confirm` vietato. In più il binario rifiuta le conferme quando lo chiama il modello.
- **Testi non fidati**: il prompt di sistema tratta mail, chat, pagine web e documenti come dati, non come istruzioni. Resta comunque un sistema basato su un modello linguistico: leggi sempre il riepilogo prima di confermare.
- **Server per il telefono**: spento di default. Usa un token casuale a 24 caratteri e HTTP in chiaro sulla rete locale. Attivalo solo su reti fidate o tramite Tailscale, non esporre mai la porta 8787 su Internet e non condividere il link con il token.
- **Dati locali**: preferenze, log delle azioni, token e stato sono in `~/Library/Application Support/JARVIS`, mai nel repository. I testi delle richieste passano dalla CLI di Claude Code secondo le condizioni del tuo account.

Per segnalare una vulnerabilità vedi [SECURITY.md](SECURITY.md).

## Struttura

```
Sources/JarvisCore/   strumenti (Mail, Calendario, File, ...), router, prompt, bridge verso Claude
Sources/jarvis/       CLI `jarvis`
Sources/JarvisApp/    app macOS: HUD, voce, iniziativa, server per il telefono, telemetria
HUD/                  interfaccia web dell'HUD e pagina mobile
Resources/            Info.plist e icona
scripts/              build, icona, test end-to-end
```

## Test

Con JARVIS.app in esecuzione e l'accesso da iPhone attivo:

```bash
python3 scripts/test_jarvis.py
```

La suite completa crea e poi elimina eventi, note e file di prova, e verifica le conferme senza inviare nulla.

I controlli che non richiedono l'app né l'account Claude si lanciano con `python3 scripts/test_jarvis.py --solo offline`.

## Licenza

[MIT](LICENSE)
