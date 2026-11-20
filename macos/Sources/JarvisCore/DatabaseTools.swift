import Foundation
import SQLite3

/// Read-only SQLite access to app databases (Mail, WhatsApp). Needs Full Disk Access for JARVIS.
final class SQLiteRO {
    private var db: OpaquePointer?

    init(_ path: String) throws {
        guard FileManager.default.isReadableFile(atPath: path) else { throw SQLiteRO.noAccess }
        let uri = "file:" + (path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? path) + "?mode=ro"
        if sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) != SQLITE_OK {
            sqlite3_close(db); db = nil
            throw SQLiteRO.noAccess
        }
        sqlite3_busy_timeout(db, 3000)
    }

    deinit { sqlite3_close(db) }

    static let noAccess = ToolError("serve l'Accesso completo al disco per JARVIS (Impostazioni > Privacy e sicurezza > Accesso completo al disco)")

    func query(_ sql: String, _ params: [Any] = []) throws -> [[String: Any]] {
        var st: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &st, nil) == SQLITE_OK else {
            throw ToolError("query fallita: \(String(cString: sqlite3_errmsg(db)))")
        }
        defer { sqlite3_finalize(st) }
        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
        for (i, p) in params.enumerated() {
            let idx = Int32(i + 1)
            switch p {
            case let v as Int: sqlite3_bind_int64(st, idx, Int64(v))
            case let v as Int64: sqlite3_bind_int64(st, idx, v)
            case let v as Double: sqlite3_bind_double(st, idx, v)
            case let v as String: sqlite3_bind_text(st, idx, v, -1, transient)
            default: sqlite3_bind_null(st, idx)
            }
        }
        var rows: [[String: Any]] = []
        while sqlite3_step(st) == SQLITE_ROW {
            var r: [String: Any] = [:]
            for c in 0..<sqlite3_column_count(st) {
                let name = String(cString: sqlite3_column_name(st, c))
                switch sqlite3_column_type(st, c) {
                case SQLITE_INTEGER: r[name] = sqlite3_column_int64(st, c)
                case SQLITE_FLOAT: r[name] = sqlite3_column_double(st, c)
                case SQLITE_TEXT: r[name] = String(cString: sqlite3_column_text(st, c))
                default: break
                }
            }
            rows.append(r)
        }
        return rows
    }

    func columns(_ table: String) -> Set<String> {
        Set(((try? query("PRAGMA table_info(\(table))")) ?? []).compactMap { $0["name"] as? String })
    }

    func hasTable(_ t: String) -> Bool {
        !((try? query("SELECT name FROM sqlite_master WHERE type='table' AND name=?", [t])) ?? []).isEmpty
    }
}

func int(_ v: Any?) -> Int64 { (v as? Int64) ?? Int64((v as? Double) ?? 0) }
func str(_ v: Any?) -> String { (v as? String) ?? "" }

/// Converts a stored timestamp (Unix or Apple 2001 epoch) to Date.
func dbDate(_ v: Any?) -> Date {
    let d = (v as? Double) ?? Double(int(v))
    return d > 1_200_000_000 ? Date(timeIntervalSince1970: d) : Date(timeIntervalSinceReferenceDate: d)
}

/// Developer diagnostics: `jarvis _dbinfo mail|wa` (schema only, no message contents).
enum DBInfo {
    static func run(_ which: String) throws -> String {
        let db = try SQLiteRO(which.hasPrefix("wa") ? WhatsAppTool.dbPath : (MailDB.path() ?? ""))
        var out: [String] = []
        if which.hasSuffix("tables") {
            for r in try db.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") {
                let t = str(r["name"])
                let n = int(try db.query("SELECT COUNT(*) AS c FROM \"\(t)\"").first?["c"])
                out.append("\(t) (\(n)): " + db.columns(t).sorted().joined(separator: ","))
            }
            return out.joined(separator: "\n")
        }
        if which == "wa" {
            out.append("ZWACHATSESSION: " + db.columns("ZWACHATSESSION").sorted().joined(separator: ","))
            out.append("ZWAMESSAGE: " + db.columns("ZWAMESSAGE").sorted().joined(separator: ","))
            for r in try db.query("SELECT ZCONTACTJID AS j, ZSESSIONTYPE AS t FROM ZWACHATSESSION ORDER BY ZLASTMESSAGEDATE DESC LIMIT 8") {
                out.append("jid=\(str(r["j"]).replacing(/^[0-9]+/) { _ in "N" }) type=\(int(r["t"]))")
            }
        } else {
            out.append("messages: " + db.columns("messages").sorted().joined(separator: ","))
            out.append("mailboxes: " + db.columns("mailboxes").sorted().joined(separator: ","))
            for r in try db.query("SELECT mb.url AS u, COUNT(*) AS c FROM messages m JOIN mailboxes mb ON mb.ROWID = m.mailbox GROUP BY mb.url ORDER BY c DESC LIMIT 12") {
                out.append("\(int(r["c"]))  \(str(r["u"]).replacing(/\/\/[^\/]+@/) { _ in "//*@" })")
            }
            for r in try db.query("SELECT m.ROWID AS id, m.date_received AS d, m.read AS rd, m.flags AS f FROM messages m ORDER BY m.date_received DESC LIMIT 3") {
                out.append("id=\(int(r["id"])) date=\(int(r["d"])) read=\(int(r["rd"])) flags=\(int(r["f"]))")
            }
        }
        return out.joined(separator: "\n")
    }
}

// MARK: - Mail: Envelope Index (instant listing)

enum MailDB {
    static func path() -> String? {
        let base = Paths.expand("~/Library/Mail")
        let vs = ((try? FileManager.default.contentsOfDirectory(atPath: base)) ?? []).filter { $0.hasPrefix("V") }
            .sorted { $0.compare($1, options: .numeric) == .orderedDescending }
        for v in vs {
            let p = "\(base)/\(v)/MailData/Envelope Index"
            if FileManager.default.fileExists(atPath: p) { return p }
        }
        return nil
    }

    /// Returns (total matching, rows [id, sender, subject, date]) or throws if the DB is not readable.
    static func list(unread: Bool, query q: String, limit: Int) throws -> (Int, [(String, String, String, Date)]) {
        guard let p = path() else { throw SQLiteRO.noAccess }
        let db = try SQLiteRO(p)
        let cols = db.columns("messages")
        guard cols.contains("mailbox"), cols.contains("sender"), cols.contains("subject") else { throw ToolError("schema Mail inatteso") }
        // Inbox = messages stored in an INBOX mailbox or (Gmail) labelled INBOX while stored in "All Mail".
        let inbox = "(SELECT ROWID FROM mailboxes WHERE url LIKE '%/INBOX' OR url LIKE '%/INBOX/')"
        var conds = ["(m.mailbox IN \(inbox) OR m.ROWID IN (SELECT message_id FROM labels WHERE mailbox_id IN \(inbox)))"]
        if cols.contains("deleted") { conds.append("m.deleted = 0") }
        if unread { conds.append(cols.contains("read") ? "m.read = 0" : "(m.flags & 1) = 0") }
        var params: [Any] = []
        if !q.isEmpty {
            conds.append("(s.subject LIKE ? OR a.address LIKE ? OR a.comment LIKE ?)")
            params += Array(repeating: "%\(q)%", count: 3)
        }
        let from = """
        FROM messages m JOIN mailboxes mb ON mb.ROWID = m.mailbox
        LEFT JOIN addresses a ON a.ROWID = m.sender LEFT JOIN subjects s ON s.ROWID = m.subject
        WHERE \(conds.joined(separator: " AND "))
        """
        let total = int(try db.query("SELECT COUNT(*) AS c \(from)", params).first?["c"])
        let rows = try db.query("SELECT m.ROWID AS id, a.address AS addr, a.comment AS name, s.subject AS subj, m.date_received AS d \(from) ORDER BY m.date_received DESC LIMIT ?", params + [limit])
        return (Int(total), rows.map { r in
            let name = str(r["name"]).isEmpty ? str(r["addr"]) : str(r["name"])
            return (String(int(r["id"])), name, str(r["subj"]), dbDate(r["d"]))
        })
    }
}

// MARK: - WhatsApp (reads the desktop app's local database, sends via whatsapp:// + Return)

enum WhatsAppTool {
    static var dbPath: String { Paths.expand("~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite") }

    struct Chat { let pk: Int64; let name: String; let jid: String; let unread: Int64; let last: Date; let lastText: String }

    static func chats(_ db: SQLiteRO, limit: Int, unreadOnly: Bool = false) throws -> [Chat] {
        let cols = db.columns("ZWACHATSESSION")
        guard cols.contains("ZPARTNERNAME") else { throw ToolError("schema WhatsApp inatteso") }
        // ZLASTMESSAGETEXT is an encoded key on recent versions: take the real text of the latest message
        let lastText = "(SELECT m.ZTEXT FROM ZWAMESSAGE m WHERE m.ZCHATSESSION = s.Z_PK ORDER BY m.ZMESSAGEDATE DESC LIMIT 1)"
        // people and groups only: no channels (@newsletter), status, broadcast lists
        var conds = ["ZCONTACTJID NOT LIKE '%status%'", "ZCONTACTJID NOT LIKE '%@newsletter'", "ZCONTACTJID NOT LIKE '%@broadcast'"]
        if cols.contains("ZREMOVED") { conds.append("ZREMOVED = 0") }
        if cols.contains("ZHIDDEN") { conds.append("ZHIDDEN = 0") }
        if unreadOnly { conds.append("ZUNREADCOUNT > 0") }
        let rows = try db.query("""
            SELECT Z_PK AS pk, ZPARTNERNAME AS name, ZCONTACTJID AS jid, ZUNREADCOUNT AS unread, ZLASTMESSAGEDATE AS d, \(lastText) AS t
            FROM ZWACHATSESSION s WHERE \(conds.joined(separator: " AND ")) ORDER BY ZLASTMESSAGEDATE DESC LIMIT ?
            """, [limit])
        return rows.map { Chat(pk: int($0["pk"]), name: str($0["name"]), jid: str($0["jid"]), unread: int($0["unread"]),
                               last: dbDate($0["d"]), lastText: str($0["t"])) }
    }

    static func messages(_ db: SQLiteRO, chat: Int64, limit: Int) throws -> [String] {
        let hasMembers = db.hasTable("ZWAGROUPMEMBER") && db.columns("ZWAMESSAGE").contains("ZGROUPMEMBER")
        let sql = hasMembers ? """
            SELECT m.ZISFROMME AS me, m.ZTEXT AS t, m.ZMESSAGEDATE AS d, g.ZCONTACTNAME AS who
            FROM ZWAMESSAGE m LEFT JOIN ZWAGROUPMEMBER g ON g.Z_PK = m.ZGROUPMEMBER
            WHERE m.ZCHATSESSION = ? ORDER BY m.ZMESSAGEDATE DESC LIMIT ?
            """ : "SELECT ZISFROMME AS me, ZTEXT AS t, ZMESSAGEDATE AS d FROM ZWAMESSAGE WHERE ZCHATSESSION = ? ORDER BY ZMESSAGEDATE DESC LIMIT ?"
        let rows = try db.query(sql, [chat, limit])
        let f = DateFormatter(); f.dateFormat = "dd/MM HH:mm"
        return rows.reversed().map { r in
            let who = int(r["me"]) == 1 ? "Io" : (str(r["who"]).isEmpty ? "Loro" : str(r["who"]))
            let t = str(r["t"]).isEmpty ? "[media/allegato]" : str(r["t"])
            return "\(f.string(from: dbDate(r["d"]))) \(who): \(t.count > 300 ? String(t.prefix(300)) + "..." : t)"
        }
    }

    static func findChat(_ db: SQLiteRO, _ q: String) throws -> Chat? {
        if let ref = Refs.resolve(q), let pk = Int64(ref) {
            return try chats(db, limit: 500).first { $0.pk == pk }
        }
        let all = try chats(db, limit: 500)
        if let exact = all.first(where: { $0.name.localizedCaseInsensitiveCompare(q) == .orderedSame }) { return exact }
        let partial = all.filter { $0.name.range(of: q, options: [.caseInsensitive, .diacriticInsensitive]) != nil }
        if partial.count > 1 {
            throw ToolError("più chat corrispondono a \"\(q)\": \(partial.prefix(5).map(\.name).joined(separator: ", ")). Usa wa chats e [wN].")
        }
        return partial.first
    }

    static func run(_ a: [String], confirmed: Bool, raw: [String]) throws -> String {
        let sub = a.first ?? "chats"
        let args = Args(Array(a.dropFirst()))
        switch sub {
        case "chats", "unread", "nonlette":
            let db = try SQLiteRO(dbPath)
            let n = Int(args.pos.first ?? "") ?? 10
            let list = try chats(db, limit: min(n, 30), unreadOnly: sub != "chats")
            if list.isEmpty { return sub == "chats" ? "Nessuna chat." : "Nessun messaggio WhatsApp non letto." }
            let refs = Refs.assign("w", list.map { String($0.pk) })
            let f = DateFormatter(); f.dateFormat = "dd/MM HH:mm"
            return zip(refs, list).map { ref, c in
                let last = c.lastText.isEmpty ? "" : ": \(c.lastText.count > 90 ? String(c.lastText.prefix(90)) + "..." : c.lastText)"
                return "[\(ref)] \(c.name)\(c.unread > 0 ? " (\(c.unread) non letti)" : "") \(f.string(from: c.last))\(last)"
            }.joined(separator: "\n")
        case "read", "leggi":
            let q = args.pos.joined(separator: " ")
            guard !q.isEmpty else { throw ToolError("uso: wa read <nome|w1> [--n 15]") }
            let db = try SQLiteRO(dbPath)
            guard let c = try findChat(db, q) else { throw ToolError("chat \"\(q)\" non trovata") }
            let msgs = try messages(db, chat: c.pk, limit: min(Int(args.o("n") ?? "") ?? 15, 50))
            ActionLog.add("WHATSAPP", "Letta chat \(c.name)")
            return "Chat \(c.name):\n" + msgs.joined(separator: "\n")
        case "send", "invia":
            guard let to = args.o("to", "a"), let text = args.o("text", "testo"), !text.isEmpty else {
                throw ToolError("uso: wa send --to <nome|numero|w1> --text \"messaggio\"")
            }
            let (name, phone) = try resolveRecipient(to)
            if !confirmed { return Gate.request("Inviare su WhatsApp a \(name): \"\(text)\"", argv: raw) }
            return try send(phone: phone, name: name, text: text)
        default:
            throw ToolError("uso: wa chats|unread|read|send")
        }
    }

    static func resolveRecipient(_ to: String) throws -> (String, String) {
        let digits = to.filter { $0.isNumber || $0 == "+" }
        if digits.count >= 8 && digits.count >= to.filter({ !$0.isWhitespace }).count - 1 {
            return (to, normalize(digits))
        }
        if let db = try? SQLiteRO(dbPath), let c = try findChat(db, to) {
            guard c.jid.hasSuffix("@s.whatsapp.net") else {
                throw ToolError("\(c.name) è un gruppo: l'invio automatico funziona solo verso singole persone")
            }
            return (c.name, String(c.jid.prefix { $0 != "@" }))
        }
        // fall back to Contacts phone numbers
        let out = try appleScript("""
        on run argv
          tell application "Contacts"
            set ps to (people whose name contains (item 1 of argv))
            if (count of ps) is 0 then return ""
            set p to item 1 of ps
            if (count of phones of p) is 0 then return (name of p) & tab
            return (name of p) & tab & (value of phone 1 of p)
          end tell
        end run
        """, [to])
        let parts = out.components(separatedBy: "\t")
        guard parts.count == 2, !parts[1].isEmpty else { throw ToolError("non trovo un numero WhatsApp per \"\(to)\"") }
        return (parts[0], normalize(parts[1]))
    }

    static func normalize(_ p: String) -> String {
        var d = p.filter { $0.isNumber || $0 == "+" }
        if d.hasPrefix("+") { d.removeFirst() } else if d.hasPrefix("00") { d.removeFirst(2) } else if d.count == 10 && d.hasPrefix("3") { d = "39" + d }
        return d
    }

    static func send(phone: String, name: String, text: String) throws -> String {
        var c = URLComponents(string: "whatsapp://send")!
        c.queryItems = [URLQueryItem(name: "phone", value: phone), URLQueryItem(name: "text", value: text)]
        guard let url = c.url else { throw ToolError("numero o testo non validi per WhatsApp") }
        _ = try runProcess("/usr/bin/open", [url.absoluteString])
        Thread.sleep(forTimeInterval: 2.5)
        do {
            _ = try appleScript("""
            tell application "WhatsApp" to activate
            delay 0.6
            tell application "System Events"
              -- the Return key goes to the frontmost app: never press it anywhere else
              if name of first application process whose frontmost is true is not "WhatsApp" then error "WhatsApp non in primo piano"
              keystroke return
            end tell
            """)
        } catch {
            return "Messaggio pronto in WhatsApp per \(name): premi Invio per mandarlo (per l'invio automatico concedi Accessibilità a JARVIS)."
        }
        ActionLog.add("WHATSAPP", "Inviato a \(name): \(text.prefix(60))")
        return "Inviato su WhatsApp a \(name)."
    }
}
