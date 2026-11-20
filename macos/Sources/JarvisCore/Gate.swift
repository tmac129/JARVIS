import Foundation

/// Confirmation gate for critical actions (send mail, delete events, trash files, bulk moves).
/// The model can only *request* these; they run when the user confirms through the UI
/// (`jarvis confirm <id>`, which the model is not allowed to call).
public enum Gate {
    struct Pending: Codable {
        let id: String
        let summary: String
        let argv: [String]
        let created: Date
    }

    static let file = "pending.json"
    static let ttl: TimeInterval = 3 * 60
    public static let marker = "IN ATTESA DI CONFERMA"

    static func all() -> [Pending] {
        (Store.load(file, [Pending].self) ?? []).filter { Date().timeIntervalSince($0.created) < ttl }
    }

    public static func request(_ summary: String, argv: [String]) -> String {
        var list = all()
        var n = 1
        while list.contains(where: { $0.id == "p\(n)" }) { n += 1 }
        let p = Pending(id: "p\(n)", summary: summary, argv: argv, created: Date())
        list.append(p)
        Store.save(file, list)
        ActionLog.add("CONFIRM", "Richiesta conferma [\(p.id)]: \(summary)")
        return "\(marker) [\(p.id)]: \(summary). Chiedi conferma all'utente; l'interfaccia esegue l'azione se conferma."
    }

    public static func list() -> String {
        let l = all()
        if l.isEmpty { return "Nessuna azione in attesa." }
        return l.map { "[\($0.id)] \($0.summary)" }.joined(separator: "\n")
    }

    public static var latestID: String? { all().last?.id }

    /// Summary of the newest pending action, from pending.json (written only by the tools): this is what
    /// the confirmation dialog shows, so text inside a mail or web page can't fake what is being confirmed.
    public static var latestSummary: String? { all().last?.summary }

    public static func confirm(_ id: String?) -> (String, Int32) {
        var l = all()
        guard let target = id ?? l.last?.id, let i = l.firstIndex(where: { $0.id == target }) else {
            return ("Nessuna azione in attesa da confermare.", 1)
        }
        let p = l.remove(at: i)
        Store.save(file, l)
        return CLI.run(p.argv, confirmed: true)
    }

    /// Drops every pending action (called on any new command that isn't a yes/no).
    public static func cancelAll() {
        let l = all()
        guard !l.isEmpty else { return }
        Store.save(file, [Pending]())
        for p in l { ActionLog.add("CONFIRM", "Scaduto senza conferma: \(p.summary)") }
    }

    public static func cancel(_ id: String?) -> String {
        var l = all()
        guard !l.isEmpty else { return "Nessuna azione in attesa." }
        let target = id ?? l.last!.id
        guard let i = l.firstIndex(where: { $0.id == target }) else { return "Azione \(target) non trovata." }
        let p = l.remove(at: i)
        Store.save(file, l)
        ActionLog.add("CONFIRM", "Annullato: \(p.summary)")
        return "Annullato: \(p.summary)."
    }
}
