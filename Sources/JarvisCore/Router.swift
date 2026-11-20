import Foundation

public enum Tier: String, CaseIterable {
    case haiku, sonnet, opus, fable

    /// Value passed to `claude --model`. Default: the CLI alias (`claude --help`: "an alias for the latest model
    /// (e.g. 'fable', 'opus', or 'sonnet') or a model's full name"), i.e. always the latest of each family.
    /// Override per tier with JARVIS_MODEL_HAIKU / _SONNET / _OPUS / _FABLE (e.g. a full model ID to pin a version).
    public var model: String {
        let v = ProcessInfo.processInfo.environment["JARVIS_MODEL_\(rawValue.uppercased())"]?.trimmingCharacters(in: .whitespaces) ?? ""
        return v.isEmpty ? rawValue : v
    }
    public var effort: String {
        switch self {
        case .haiku: return "low"
        case .sonnet: return "medium"
        case .opus, .fable: return "high"
        }
    }
    public var label: String {
        switch self {
        case .haiku: return "HAIKU [LOW-TOKEN MODE]"
        case .sonnet: return "SONNET [ANALYSIS MODE]"
        case .opus: return "OPUS [DEEP REASONING]"
        case .fable: return "FABLE [MAX CAPABILITY]"
        }
    }
}

public enum Route: Equatable {
    case local(argv: [String], reply: String?)   // run a tool directly, zero tokens
    case answer(String)                          // instant reply, zero tokens
    case model(Tier, String)                     // send (cleaned) text to Claude
}

/// Zero-token router: regex fast path for trivial commands, keyword escalation to bigger models.
public enum Router {
    /// Text longer than this (characters) goes to Sonnet.
    /// TODO(taratura): soglia e hint invariati di proposito finché turns.jsonl non mostra quanti turni salgono a Sonnet
    /// e con quale costo/qualità. Misure utili: quota di turni sonnet vs haiku, token medi per tier, turni sonnet nati
    /// dalla sola lunghezza (> sonnetMinChars) e non dagli hint, risposte haiku giudicate insufficienti.
    static let sonnetMinChars = 600
    /// "Deep reasoning" requests: they used to start Opus automatically; now they escalate only to Sonnet.
    /// Opus/Fable start only with an explicit "/opus" or "/fable" prefix.
    static let opusHints = /(ragiona(re)? a fondo|in profondit|approfondit|strategi|piano dettagliato|dimostra(zione)?|architettura|pensaci bene)/
    static let sonnetHints = /(codice|script|programm|funzione|debug|\bbug\b|refactor|analizz|analisi|confronta|spiegami|spiega in dettaglio|riassumi|riassunto|traduci|scrivi (un|una) (testo|saggio|articolo|tema|lettera|relazione)|correggi (il|questo) testo|calcola)/

    public static func route(_ input: String, hasPending: Bool = false) -> Route {
        var text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        let low = text.lowercased()

        // Explicit tier override: "/fable ...", "/opus ...", "/sonnet ...", "/haiku ..." (the only way to reach Opus/Fable)
        for t in Tier.allCases where low.hasPrefix("/\(t.rawValue)") {
            text = String(text.dropFirst(t.rawValue.count + 1)).trimmingCharacters(in: .whitespaces)
            return .model(t, text)
        }

        let clean = low.replacing(/^(ehi |hey |ok )?jarvis[,!.]?\s*/) { _ in "" }
            .trimmingCharacters(in: CharacterSet(charactersIn: " .!?"))

        // Confirmation of a pending critical action
        if hasPending {
            if clean.wholeMatch(of: /(sì|si|conferma|confermo|procedi|vai|ok|okay|invia|fallo|esegui)( pure)?/) != nil {
                return .local(argv: ["confirm"], reply: nil)
            }
            if clean.wholeMatch(of: /(no|annulla|lascia stare|ferma|stop|non farlo)/) != nil {
                return .local(argv: ["cancel"], reply: nil)
            }
        }

        if let r = fastPath(clean) { return r }

        // Briefing
        if clean.wholeMatch(of: /(fammi (il )?|dammi (il )?)?briefing( del mattino| di oggi)?|buongiorno( jarvis)?|aggiornami( sulla giornata)?/) != nil {
            return .model(.haiku, Prompt.briefing)
        }

        // Time / date
        if clean.wholeMatch(of: /(che ore sono|che ora è|dimmi l'ora|ora esatta)/) != nil {
            return .answer("Sono le \(When.hm(Date())).")
        }
        if clean.wholeMatch(of: /(che giorno è( oggi)?|che data è( oggi)?|quanti ne abbiamo( oggi)?)/) != nil {
            return .answer("Oggi è \(When.fmt(Date(), time: false)).")
        }

        // Timer: "metti un timer di 20 minuti", "timer 1 ora e 30 minuti"
        if let m = clean.wholeMatch(of: /(?:metti|imposta|avvia|fai partire)?\s*(?:un )?timer (?:di |da )?((?:\d+(?:[.,]\d+)?\s*(?:ore|ora|h|minuti|minuto|min|m|secondi|secondo|sec|s)\s*(?:e\s*)?)+)/) {
            let spec = String(m.1).replacingOccurrences(of: " e ", with: "")
            if When.duration(spec) != nil { return .local(argv: ["timer", spec], reply: nil) }
        }
        if clean.wholeMatch(of: /(annulla|ferma|stop) (il )?timer/) != nil {
            return .local(argv: ["timer", "cancel"], reply: nil)
        }

        // Escalation (Haiku -> Sonnet only; never Opus/Fable on its own)
        if clean.firstMatch(of: opusHints) != nil || clean.firstMatch(of: sonnetHints) != nil || text.count > sonnetMinChars {
            return .model(.sonnet, text)
        }
        return .model(.haiku, text)
    }

    static let visionHints = /(schermo|schermata|screen|cosa (vedi|c'è)|questa finestra|guarda (qui|questo|questa)|immagine|foto|scansion)/

    public static func needsVision(_ text: String) -> Bool { text.lowercased().firstMatch(of: visionHints) != nil }

    /// Frequent everyday commands handled locally: instant, zero tokens.
    static func fastPath(_ c: String) -> Route? {
        func run(_ argv: String...) -> Route { .local(argv: argv, reply: nil) }
        // music
        if c.wholeMatch(of: /(metti in )?pausa( la musica)?|ferma la musica|stop (alla )?musica|pausa musica/) != nil { return run("music", "pause") }
        if c.wholeMatch(of: /(riprendi|fai ripartire|continua|riavvia)( la)? musica|play|riproduci|metti (un po' di )?musica/) != nil { return run("music", "play") }
        if c.wholeMatch(of: /(prossim[ao]|(canzone|brano|traccia) successiv[ao]|salta( (la )?(canzone|brano))?|next|cambia canzone)( canzone| brano)?/) != nil { return run("music", "next") }
        if c.wholeMatch(of: /((canzone|brano|traccia) precedente|torna alla canzone precedente|indietro di una canzone)/) != nil { return run("music", "prev") }
        if c.wholeMatch(of: /(che|quale) (canzone|brano|pezzo) (è|sta suonando|suona)( questo| questa)?|cosa sta suonando|che canzone è/) != nil { return run("music", "now") }
        // volume
        if c.wholeMatch(of: /(alza|aumenta)( (un po'|il|l'))?( volume| audio)?( (un po'|di più))?/) != nil, c.contains("volume") || c.contains("audio") { return run("sys", "volume", "su") }
        if c.wholeMatch(of: /(abbassa|diminuisci)( (un po'|il|l'))?( volume| audio)?( (un po'|di più))?/) != nil, c.contains("volume") || c.contains("audio") { return run("sys", "volume", "giu") }
        if let m = c.wholeMatch(of: /(metti |imposta )?(il )?volume (a|al) (\d{1,3})( ?%| per ?cento)?/) { return run("sys", "volume", String(m.4)) }
        if c.wholeMatch(of: /(togli|disattiva|silenzia) (l'audio|il volume|l'audio del mac)|muto|silenzio|modalità muto/) != nil { return run("sys", "volume", "muto") }
        if c.wholeMatch(of: /(riattiva|rimetti) (l'audio|il volume)/) != nil { return run("sys", "volume", "attiva") }
        if c.wholeMatch(of: /(a quanto è|qual è|quanto è alto) il volume/) != nil { return run("sys", "volume") }
        // brightness
        if c.wholeMatch(of: /(alza|aumenta) (la )?luminosità/) != nil { return run("sys", "brightness", "su") }
        if c.wholeMatch(of: /(abbassa|diminuisci) (la )?luminosità/) != nil { return run("sys", "brightness", "giu") }
        if let m = c.wholeMatch(of: /(metti |imposta )?(la )?luminosità (a|al) (\d{1,3})( ?%| per ?cento)?/) { return run("sys", "brightness", String(m.4)) }
        // system
        if c.wholeMatch(of: /(quanta |livello (della |di )?|stato (della )?|com'è la |come sta la )?batteria( rimasta| residua)?/) != nil { return run("sys", "battery") }
        if c.wholeMatch(of: /blocca (lo schermo|il mac|il computer)/) != nil { return run("sys", "lock") }
        if c.wholeMatch(of: /(attiva|metti|passa a)( la)? (modalità scura|tema scuro|dark mode)/) != nil { return run("sys", "dark", "on") }
        if c.wholeMatch(of: /(attiva|metti|passa a)( la)? (modalità chiara|tema chiaro)|disattiva( la)? modalità scura/) != nil { return run("sys", "dark", "off") }
        if c.wholeMatch(of: /(fai|scatta|cattura)( uno| una)? (screenshot|schermata)/) != nil { return run("sys", "screenshot") }
        if c.wholeMatch(of: /(quanto manca|timer attivi|a che punto è il timer)( al timer)?/) != nil { return run("timer", "list") }
        if c.wholeMatch(of: /(quali |che )?sveglie( ho| attive| impostate)?/) != nil { return run("alarm", "list") }
        // alarm: "metti una sveglia alle 7:30" / "sveglia alle 7"
        if let m = c.wholeMatch(of: /(metti|imposta|punta)?( una)? ?sveglia (alle|per le|a) (\d{1,2})(?:[:.](\d{2}))?( di)?( domani)?( mattina)?/) {
            let h = Int(m.4) ?? 0, mi = m.5.flatMap { Int($0) } ?? 0
            if h < 24 && mi < 60 { return .local(argv: ["alarm", "set", String(format: "%02d:%02d", h, mi)], reply: nil) }
        }
        // apps: only when the name is a real installed/running app ("apri Safari", "chiudi Spotify")
        if let m = c.wholeMatch(of: /(apri|avvia|lancia) (l'app |l'applicazione |app )?([\p{L}0-9 .]{2,30})/), let app = installedApp(String(m.3)) {
            return run("sys", "open", app)
        }
        if let m = c.wholeMatch(of: /(chiudi|esci da) (l'app |l'applicazione |app )?([\p{L}0-9 .]{2,30})/), let app = installedApp(String(m.3)),
           !app.lowercased().contains("jarvis") {
            return run("sys", "quit", app)
        }
        return nil
    }

    static func installedApp(_ name: String) -> String? {
        let n = name.trimmingCharacters(in: .whitespaces)
        guard !n.isEmpty else { return nil }
        let fm = FileManager.default
        for dir in ["/Applications", "/System/Applications", "/System/Applications/Utilities", NSHomeDirectory() + "/Applications"] {
            guard let items = try? fm.contentsOfDirectory(atPath: dir) else { continue }
            if let hit = items.first(where: { $0.hasSuffix(".app") && ($0 as NSString).deletingPathExtension.localizedCaseInsensitiveCompare(n) == .orderedSame }) {
                return (hit as NSString).deletingPathExtension
            }
        }
        return nil
    }
}

