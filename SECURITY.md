# Sicurezza

JARVIS controlla il Mac per conto dell'utente (mail, messaggi, file), quindi le vulnerabilità contano.

## Segnalare un problema

Non aprire una issue pubblica. Usa **Security > Report a vulnerability** nella pagina GitHub del repository (segnalazione privata) con:

- versione o commit;
- passi per riprodurre;
- impatto (per esempio: azione eseguita senza conferma, accesso al server del telefono senza token, crash).

## Modello di minaccia

Sono considerati problemi di sicurezza:

- un'azione protetta da conferma (invio, eliminazione, cestino, apertura di eseguibili, scrittura in cartelle di sistema) eseguita senza il consenso dell'utente;
- testo letto da mail, chat, pagine web o documenti che riesce a far eseguire azioni non richieste;
- accesso al server HTTP del telefono (porta 8787) senza token valido, oppure un crash provocato dall'esterno;
- credenziali (token del telefono, credenziali di qualsiasi tipo) scritte in log, output o file del repository.

Non rientrano: chi ha già accesso all'account macOS dell'utente, l'uso del server del telefono su reti non fidate contro le indicazioni del README, i limiti intrinseci dei modelli linguistici quando l'utente conferma un'azione dopo averne letto il riepilogo.
