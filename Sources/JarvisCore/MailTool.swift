import Foundation

/// Apple Mail via AppleScript. Inbox-focused, results capped to keep output (and tokens) small.
enum MailTool {
    static let listScript = """
    on run argv
      set mode to item 1 of argv
      set q to item 2 of argv
      set n to (item 3 of argv) as integer
      set scan to (item 4 of argv) as integer
      set out to ""
      tell application "Mail"
        set total to count of messages of inbox
        if scan > total then set scan to total
        if scan is 0 then return "0" & linefeed
        -- Mail charges ~20ms per property per message: scan one cheap property, then fetch details only for hits.
        set hits to {}
        if mode is "unread" then
          set c to unread count of inbox
          set rds to read status of messages 1 thru scan of inbox
          repeat with i from 1 to scan
            if not (item i of rds) then set end of hits to i
            if (count of hits) ≥ n then exit repeat
          end repeat
        else
          set {snds, subs} to {sender, subject} of messages 1 thru scan of inbox
          repeat with i from 1 to scan
            if ((item i of snds) contains q) or ((item i of subs) contains q) then set end of hits to i
          end repeat
          set c to count of hits
        end if
        set k to 0
        repeat with i in hits
          set k to k + 1
          if k > n then exit repeat
          set m to message i of inbox
          set d to date received of m
          set ds to (year of d as string) & "-" & text -2 thru -1 of ("0" & ((month of d) as integer)) & "-" & text -2 thru -1 of ("0" & day of d) & " " & text -2 thru -1 of ("0" & hours of d) & ":" & text -2 thru -1 of ("0" & minutes of d)
          set out to out & (id of m) & tab & (sender of m) & tab & (subject of m) & tab & ds & linefeed
        end repeat
      end tell
      return (c as string) & linefeed & out
    end run
    """

    static let readScript = """
    on run argv
      set mid to (item 1 of argv) as integer
      tell application "Mail"
        set m to first message of inbox whose id is mid
        set read status of m to true
        set atts to ""
        repeat with a in mail attachments of m
          set atts to atts & (name of a) & "; "
        end repeat
        return (sender of m) & linefeed & (subject of m) & linefeed & atts & linefeed & (content of m)
      end tell
    end run
    """

    // argv: mode, subject, body, nTo, to..., attachments...
    static let composeScript = """
    on run argv
      set mode to item 1 of argv
      set subj to item 2 of argv
      set bod to item 3 of argv
      set nTo to (item 4 of argv) as integer
      tell application "Mail"
        set msg to make new outgoing message with properties {subject:subj, content:bod & return & return, visible:(mode is "draft")}
        tell msg
          repeat with i from 5 to (4 + nTo)
            make new to recipient at end of to recipients with properties {address:(item i of argv)}
          end repeat
        end tell
        set nAtt to 0
        repeat with i from (5 + nTo) to (count of argv)
          set f to (POSIX file (item i of argv)) as alias
          tell content of msg to make new attachment with properties {file name:f} at after last paragraph
          set nAtt to nAtt + 1
        end repeat
        if mode is "send" then
          if nAtt > 0 then delay 2
          send msg
        else
          activate
        end if
      end tell
      return "ok"
    end run
    """

    static func run(_ a: [String], confirmed: Bool, raw: [String]) throws -> String {
        guard let sub = a.first else { throw ToolError("uso: mail unread|search|read|draft|send") }
        let args = Args(Array(a.dropFirst()))
        switch sub {
        case "unread", "search":
            let q = sub == "search" ? args.pos.dropLast(args.pos.count > 1 && Int(args.pos.last!) != nil ? 1 : 0).joined(separator: " ") : ""
            if sub == "search" && q.isEmpty { throw ToolError("uso: mail search <testo> [N]") }
            let n = args.pos.last.flatMap { Int($0) } ?? 8
            // Fast path: Mail's own database (instant, whole inbox). Needs Full Disk Access; else AppleScript.
            if let (total, dbRows) = try? MailDB.list(unread: sub == "unread", query: q, limit: min(n, 25)) {
                if dbRows.isEmpty { return sub == "unread" ? "Nessuna mail non letta." : "Nessuna mail trovata per \"\(q)\"." }
                let refs = Refs.assign("m", dbRows.map(\.0))
                let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm"
                let body = zip(refs, dbRows).map { ref, r in "[\(ref)] \(f.string(from: r.3)) \(shortSender(r.1)): \(r.2)" }.joined(separator: "\n")
                return (sub == "unread" ? "\(total) non lette" : "\(total) risultati") + (total > dbRows.count ? " (mostro \(dbRows.count))" : "") + ":\n" + body
            }
            // unread: newest 80 messages; search: newest 120 (enough for voice use, keeps it a few seconds)
            let out = try appleScript(listScript, [sub, q, String(min(n, 25)), sub == "unread" ? "80" : "120"])
            var lines = out.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
            let total = lines.isEmpty ? "0" : lines.removeFirst()
            if lines.isEmpty { return sub == "unread" ? "Nessuna mail non letta." : "Nessuna mail trovata per \"\(q)\"." }
            let rows = lines.map { $0.components(separatedBy: "\t") }
            let refs = Refs.assign("m", rows.map { $0[0] })
            let body = zip(refs, rows).map { ref, r in
                "[\(ref)] \(r.count > 3 ? r[3] : "") \(shortSender(r.count > 1 ? r[1] : "")): \(r.count > 2 ? r[2] : "")"
            }.joined(separator: "\n")
            return (sub == "unread" ? "\(total) non lette" : "\(total) risultati") + (Int(total) ?? 0 > rows.count ? " (mostro \(rows.count))" : "") + ":\n" + body
        case "read":
            guard let r = args.pos.first, let id = Refs.resolve(r) ?? (Int(r) != nil ? r : nil) else {
                throw ToolError("uso: mail read <m1>")
            }
            let out = try appleScript(readScript, [id])
            let parts = out.components(separatedBy: "\n")
            let content = parts.dropFirst(3).joined(separator: "\n")
                .replacing(/\n{3,}/) { _ in "\n\n" }
            let clipped = content.count > 1800 ? String(content.prefix(1800)) + " [...]" : content
            let atts = parts.count > 2 && !parts[2].isEmpty ? "\nAllegati: \(parts[2])" : ""
            return "Da: \(parts.first ?? "")\nOggetto: \(parts.count > 1 ? parts[1] : "")\(atts)\n\n\(clipped)"
        case "draft", "send":
            let to = args.list("to")
            guard !to.isEmpty else { throw ToolError("manca --to (indirizzo email; usa `jarvis contact <nome>` se serve)") }
            if let bad = to.first(where: { !$0.contains("@") }) {
                throw ToolError("\"\(bad)\" non è un indirizzo email: usa prima `jarvis contact \(bad)`")
            }
            let subject = args.o("subject", "oggetto") ?? ""
            let body = (args.o("body", "testo") ?? "").replacingOccurrences(of: "\\n", with: "\n")
            let files = try args.list("attach", "allegato").map { try FileTool.resolveExisting($0) }
            let names = files.map { ($0 as NSString).lastPathComponent }
            let attText = files.isEmpty ? "" : " con allegat\(files.count == 1 ? "o" : "i") \(names.joined(separator: ", "))"
            if sub == "send" && !confirmed {
                let preview = body.count > 160 ? String(body.prefix(160)) + "..." : body
                return Gate.request("Inviare mail a \(to.joined(separator: ", ")), oggetto \"\(subject)\"\(attText), testo: \"\(preview)\"", argv: raw)
            }
            _ = try appleScript(composeScript, [sub, subject, body, String(to.count)] + to + files, timeout: 90)
            let what = sub == "send" ? "Inviata mail" : "Bozza pronta in Mail"
            ActionLog.add("MAIL_PROTOCOL", "\(what) a \(to.joined(separator: ", "))\(attText)")
            return "\(what) a \(to.joined(separator: ", ")), oggetto \"\(subject)\"\(attText)."
        default:
            throw ToolError("sottocomando mail sconosciuto: \(sub)")
        }
    }

    static func shortSender(_ s: String) -> String {
        // "Mario Rossi <mario@x.it>" -> "Mario Rossi"
        if let r = s.range(of: " <") { return String(s[..<r.lowerBound]).replacingOccurrences(of: "\"", with: "") }
        return s
    }
}

enum ContactTool {
    static let script = """
    on run argv
      set q to item 1 of argv
      set out to ""
      tell application "Contacts"
        set ps to (people whose name contains q)
        set c to 0
        repeat with p in ps
          set c to c + 1
          if c > 6 then exit repeat
          set ems to ""
          repeat with e in emails of p
            set ems to ems & (value of e) & " "
          end repeat
          set out to out & (name of p) & tab & ems & linefeed
        end repeat
      end tell
      return out
    end run
    """

    static func run(_ a: [String]) throws -> String {
        let q = a.joined(separator: " ")
        guard !q.isEmpty else { throw ToolError("uso: contact <nome>") }
        let out = try appleScript(script, [q])
        let rows = out.split(separator: "\n").map { $0.components(separatedBy: "\t") }
        if rows.isEmpty { return "Nessun contatto trovato per \"\(q)\"." }
        return rows.map { r in
            let em = r.count > 1 ? r[1].trimmingCharacters(in: .whitespaces) : ""
            return "\(r[0]): \(em.isEmpty ? "(nessuna email)" : em)"
        }.joined(separator: "\n")
    }
}
