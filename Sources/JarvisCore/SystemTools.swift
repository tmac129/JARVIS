import AppKit
import Foundation
import PDFKit

// MARK: - System control

enum SysTool {
    static func run(_ a: [String]) throws -> String {
        let sub = a.first ?? ""
        let arg = a.dropFirst().joined(separator: " ").trimmingCharacters(in: .whitespaces)
        switch sub {
        case "open", "apri":
            guard !arg.isEmpty else { throw ToolError("uso: sys open <app>") }
            let r = try runProcess("/usr/bin/open", ["-a", arg])
            if r.code != 0 { throw ToolError("app \"\(arg)\" non trovata") }
            ActionLog.add("SYSTEM", "Aperta \(arg)")
            return "Aperta \(arg)."
        case "quit", "chiudi":
            guard !arg.isEmpty else { throw ToolError("uso: sys quit <app>") }
            guard let app = NSWorkspace.shared.runningApplications.first(where: {
                ($0.localizedName ?? "").localizedCaseInsensitiveCompare(arg) == .orderedSame
            }) ?? NSWorkspace.shared.runningApplications.first(where: { ($0.localizedName ?? "").localizedCaseInsensitiveContains(arg) && $0.activationPolicy == .regular })
            else { return "\(arg) non è aperta." }
            let name = app.localizedName ?? arg
            if name.localizedCaseInsensitiveContains("jarvis") { throw ToolError("non posso chiudere me stesso da qui: usa ⌘Q") }
            app.terminate()
            ActionLog.add("SYSTEM", "Chiusa \(name)")
            return "Chiusa \(name)."
        case "apps":
            let names = NSWorkspace.shared.runningApplications.filter { $0.activationPolicy == .regular }.compactMap(\.localizedName)
            return "App aperte: " + names.joined(separator: ", ")
        case "volume":
            return try volume(arg.lowercased())
        case "brightness", "luminosita", "luminosità":
            return try brightness(arg.lowercased())
        case "wifi":
            let dev = wifiDevice()
            let on = ["on", "acceso", "accendi", "attiva", "1"].contains(arg.lowercased())
            _ = try runProcess("/usr/sbin/networksetup", ["-setairportpower", dev, on ? "on" : "off"])
            ActionLog.add("SYSTEM", "Wi-Fi \(on ? "attivato" : "disattivato")")
            return "Wi-Fi \(on ? "attivato" : "disattivato")."
        case "dark", "scuro":
            let v: String
            switch arg.lowercased() {
            case "on", "attiva", "si", "sì": v = "true"
            case "off", "disattiva", "no": v = "false"
            default: v = "not dark mode"
            }
            let out = try appleScript("""
            tell application "System Events" to tell appearance preferences
              set dark mode to \(v)
              return dark mode
            end tell
            """)
            ActionLog.add("SYSTEM", "Modalità scura \(out == "true" ? "attiva" : "disattiva")")
            return "Modalità scura \(out == "true" ? "attivata" : "disattivata")."
        case "lock", "blocca":
            _ = try runProcess("/usr/bin/pmset", ["displaysleepnow"])
            ActionLog.add("SYSTEM", "Schermo bloccato")
            return "Schermo spento e bloccato."
        case "sleep", "stop":
            _ = try AlarmTool.spawnDetached(["/bin/sh", "-c", "sleep 4; /usr/bin/pmset sleepnow"])
            ActionLog.add("SYSTEM", "Stop del Mac tra 4 secondi")
            return "Metto in stop il Mac tra 4 secondi."
        case "screenshot", "schermata":
            let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd 'alle' HH.mm.ss"
            let path = Paths.expand("~/Desktop/Schermata JARVIS \(f.string(from: Date())).png")
            let r = try runProcess("/usr/sbin/screencapture", ["-x", path])
            if r.code != 0 { throw ToolError("serve il permesso Registrazione schermo per JARVIS") }
            ActionLog.add("SYSTEM", "Screenshot salvato sulla Scrivania")
            return "Screenshot salvato sulla Scrivania."
        case "battery", "batteria":
            let r = try runProcess("/usr/bin/pmset", ["-g", "batt"])
            let line = r.out.split(separator: "\n").first(where: { $0.contains("%") }).map(String.init) ?? r.out
            return "Batteria: " + (line.split(separator: "\t").last.map(String.init) ?? line)
                .replacingOccurrences(of: "discharging", with: "in scarica")
                .replacingOccurrences(of: "charging", with: "in carica")
                .replacingOccurrences(of: "charged", with: "carica")
                .replacingOccurrences(of: "remaining", with: "rimanenti")
                .replacingOccurrences(of: "present: true", with: "")
        default:
            throw ToolError("uso: sys open|quit|apps|volume|brightness|wifi|dark|lock|sleep|screenshot|battery")
        }
    }

    static func volume(_ v: String) throws -> String {
        let script: String
        switch v {
        case "su", "+", "alza", "up": script = "set volume output volume ((output volume of (get volume settings)) + 12)"
        case "giu", "giù", "-", "abbassa", "down": script = "set volume output volume ((output volume of (get volume settings)) - 12)"
        case "muto", "mute", "off": script = "set volume with output muted"
        case "attiva", "unmute", "on": script = "set volume without output muted"
        case "": script = ""
        default:
            guard let n = Int(v.filter(\.isNumber)) else { throw ToolError("uso: sys volume 0-100|su|giu|muto|attiva") }
            script = "set volume output volume \(min(max(n, 0), 100))"
        }
        let out = try appleScript("\(script)\nset s to get volume settings\nreturn (output volume of s as string) & \" \" & (output muted of s as string)")
        let parts = out.split(separator: " ")
        if v != "" { ActionLog.add("SYSTEM", "Volume \(parts.first ?? "")%") }
        return parts.count > 1 && parts[1] == "true" ? "Audio disattivato." : "Volume al \(parts.first ?? "?")%."
    }

    static func brightness(_ v: String) throws -> String {
        // F1/F2 brightness keys via System Events (needs Accessibility for JARVIS); 16 steps.
        var presses: [(Int, Int)] = []
        switch v {
        case "su", "+", "alza", "up": presses = [(144, 2)]
        case "giu", "giù", "-", "abbassa", "down": presses = [(145, 2)]
        default:
            guard let n = Int(v.filter(\.isNumber)) else { throw ToolError("uso: sys brightness 0-100|su|giu") }
            presses = [(145, 16), (144, Int((Double(min(max(n, 0), 100)) / 6.25).rounded()))]
        }
        let body = presses.map { "repeat \($0.1) times\nkey code \($0.0)\ndelay 0.02\nend repeat" }.joined(separator: "\n")
        do { _ = try appleScript("tell application \"System Events\"\n\(body)\nend tell") }
        catch { throw ToolError("serve il permesso Accessibilità per JARVIS (Impostazioni > Privacy e sicurezza > Accessibilità)") }
        ActionLog.add("SYSTEM", "Luminosità regolata")
        return "Luminosità regolata."
    }

    static func wifiDevice() -> String {
        guard let r = try? runProcess("/usr/sbin/networksetup", ["-listallhardwareports"]) else { return "en0" }
        let lines = r.out.split(separator: "\n").map(String.init)
        for (i, l) in lines.enumerated() where l.contains("Wi-Fi") && i + 1 < lines.count {
            return lines[i + 1].replacingOccurrences(of: "Device: ", with: "")
        }
        return "en0"
    }
}

// MARK: - Music (Spotify / Apple Music)

enum MusicTool {
    static func pickApp(_ want: String?) -> String {
        if let w = want?.lowercased() { return w.hasPrefix("spot") ? "Spotify" : "Music" }
        let running = NSWorkspace.shared.runningApplications.compactMap(\.bundleIdentifier)
        if running.contains("com.spotify.client") { return "Spotify" }
        if running.contains("com.apple.Music") { return "Music" }
        return FileManager.default.fileExists(atPath: "/Applications/Spotify.app") ? "Spotify" : "Music"
    }

    static func run(_ a: [String]) throws -> String {
        let args = Args(a)
        let sub = args.pos.first ?? "now"
        let query = args.pos.dropFirst().joined(separator: " ")
        let app = pickApp(args.o("app"))
        let pretty = app == "Music" ? "Apple Music" : "Spotify"
        func tell(_ cmd: String) throws -> String { try appleScript("tell application \"\(app)\"\n\(cmd)\nend tell") }
        let nowScript = "if player state is playing then\nreturn (name of current track) & \" - \" & (artist of current track)\nelse\nreturn \"\"\nend if"
        switch sub {
        case "play", "riproduci", "metti":
            if query.isEmpty {
                _ = try tell("play")
                ActionLog.add("MUSIC", "Riproduzione su \(pretty)")
                return "Riproduzione avviata su \(pretty)."
            }
            if app == "Spotify" {
                let q = query.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? query
                _ = try runProcess("/usr/bin/open", ["spotify:search:\(q)"])
                return "Spotify non permette di avviare un brano per nome: ho aperto la ricerca di \"\(query)\". Con Apple Music posso avviarlo direttamente (--app music)."
            }
            let out = try appleScript("""
            on run argv
              set q to item 1 of argv
              tell application "Music"
                try
                  play playlist q
                  return "playlist " & q
                end try
                set r to (every track of library playlist 1 whose name contains q or artist contains q or album contains q)
                if (count of r) is 0 then return "NOTFOUND"
                play item 1 of r
                return (name of item 1 of r) & " - " & (artist of item 1 of r)
              end tell
            end run
            """, [query])
            if out == "NOTFOUND" { return "Nessun brano trovato per \"\(query)\" nella libreria di Apple Music." }
            ActionLog.add("MUSIC", "In riproduzione: \(out)")
            return "In riproduzione: \(out)."
        case "pause", "pausa", "stop":
            _ = try tell("pause"); ActionLog.add("MUSIC", "Pausa"); return "Musica in pausa."
        case "toggle":
            _ = try tell("playpause"); return "Fatto."
        case "next", "avanti", "successivo":
            _ = try tell("next track"); Thread.sleep(forTimeInterval: 0.6)
            let n = try tell(nowScript); return n.isEmpty ? "Brano successivo." : "Ora: \(n)."
        case "prev", "indietro", "precedente":
            _ = try tell("previous track"); Thread.sleep(forTimeInterval: 0.6)
            let n = try tell(nowScript); return n.isEmpty ? "Brano precedente." : "Ora: \(n)."
        case "now", "cosa", "brano":
            let n = try tell(nowScript)
            return n.isEmpty ? "Nessun brano in riproduzione su \(pretty)." : "In riproduzione su \(pretty): \(n)."
        default:
            throw ToolError("uso: music play [testo]|pause|next|prev|now [--app spotify|music]")
        }
    }
}

// MARK: - Apple Notes

enum NotesTool {
    static func html(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\\n", with: "\n")
            .replacingOccurrences(of: "\n", with: "<br>")
    }

    static func run(_ a: [String]) throws -> String {
        let sub = a.first ?? "list"
        let args = Args(Array(a.dropFirst()))
        switch sub {
        case "add", "nuova", "crea":
            guard let title = args.o("title", "titolo") ?? (args.pos.isEmpty ? nil : args.pos.joined(separator: " ")) else {
                throw ToolError("uso: note add --title T [--body testo] [--folder F]")
            }
            let body = "<div><h1>\(html(title))</h1></div><div>\(html(args.o("body", "testo") ?? ""))</div>"
            _ = try appleScript("""
            on run argv
              tell application "Notes"
                set f to default folder of default account
                if (item 2 of argv) is not "" then
                  try
                    set f to folder (item 2 of argv) of default account
                  end try
                end if
                make new note at f with properties {body:(item 1 of argv)}
              end tell
            end run
            """, [body, args.o("folder", "cartella") ?? ""])
            ActionLog.add("NOTES", "Creata nota \"\(title)\"")
            return "Nota \"\(title)\" creata."
        case "list", "search", "cerca":
            let q = sub == "list" ? "" : args.pos.joined(separator: " ")
            let out = try appleScript("""
            on run argv
              set q to item 1 of argv
              set ids to {}
              set nms to {}
              set dts to {}
              tell application "Notes"
                -- skip "Recently Deleted": deleted notes stay in the account for 30 days
                repeat with f in (every folder of default account)
                  if name of f is not in {"Recently Deleted", "Eliminati di recente"} then
                    if q is "" then
                      set {i2, n2, d2} to {id, name, modification date} of every note of f
                    else
                      set ns to (every note of f whose name contains q)
                      if (count of ns) is 0 then set ns to (every note of f whose plaintext contains q)
                      set {i2, n2, d2} to {{}, {}, {}}
                      repeat with n in ns
                        set end of i2 to id of n
                        set end of n2 to name of n
                        set end of d2 to modification date of n
                      end repeat
                    end if
                    set ids to ids & i2
                    set nms to nms & n2
                    set dts to dts & d2
                  end if
                end repeat
              end tell
              set out to ""
              repeat with i from 1 to count of ids
                set d to item i of dts
                set out to out & (item i of ids) & tab & (item i of nms) & tab & ((d - (date "1/1/2001")) as integer) & linefeed
              end repeat
              return out
            end run
            """, [q], timeout: 40)
            var rows = out.split(separator: "\n").map { $0.components(separatedBy: "\t") }.filter { $0.count == 3 }
            rows.sort { (Double($0[2]) ?? 0) > (Double($1[2]) ?? 0) }
            if rows.isEmpty { return q.isEmpty ? "Nessuna nota." : "Nessuna nota trovata per \"\(q)\"." }
            let shown = Array(rows.prefix(12))
            let refs = Refs.assign("nt", shown.map { $0[0] })
            return "\(rows.count) note:\n" + zip(refs, shown).map { ref, r in "[\(ref)] \(r[1])" }.joined(separator: "\n")
        case "read", "leggi":
            guard let r = args.pos.first, let id = Refs.resolve(r) else { throw ToolError("uso: note read <nt1>") }
            let txt = try appleScript("on run argv\ntell application \"Notes\" to return plaintext of note id (item 1 of argv)\nend run", [id])
            return txt.count > 4000 ? String(txt.prefix(4000)) + " [...]" : txt
        case "append", "aggiungi":
            guard let r = args.pos.first, let id = Refs.resolve(r), let t = args.o("text", "testo") else {
                throw ToolError("uso: note append <nt1> --text T")
            }
            _ = try appleScript("""
            on run argv
              tell application "Notes"
                set n to note id (item 1 of argv)
                set body of n to (body of n) & "<div>" & (item 2 of argv) & "</div>"
                return name of n
              end tell
            end run
            """, [id, html(t)])
            ActionLog.add("NOTES", "Aggiornata nota")
            return "Testo aggiunto alla nota."
        default:
            throw ToolError("uso: note add|list|search|read|append")
        }
    }
}

// MARK: - News (RSS: Italian headlines + finance)

enum NewsTool {
    static let feeds: [String: [(String, String)]] = [
        "italia": [("ANSA", "https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml"),
                   ("Sole 24 Ore", "https://www.ilsole24ore.com/rss/italia.xml")],
        "finanza": [("Sole 24 Ore", "https://www.ilsole24ore.com/rss/finanza.xml"),
                    ("ANSA Economia", "https://www.ansa.it/sito/notizie/economia/economia_rss.xml")],
    ]

    struct Item { let source: String; let title: String; let link: String; let date: Date; let desc: String }

    final class Parser: NSObject, XMLParserDelegate {
        var items: [(title: String, link: String, date: String, desc: String)] = []
        var cur: [String: String]? = nil
        var text = ""
        func parser(_ p: XMLParser, didStartElement e: String, namespaceURI: String?, qualifiedName: String?, attributes: [String: String] = [:]) {
            if e == "item" { cur = [:] }
            text = ""
        }
        func parser(_ p: XMLParser, foundCharacters s: String) { text += s }
        func parser(_ p: XMLParser, foundCDATA d: Data) { text += String(decoding: d, as: UTF8.self) }
        func parser(_ p: XMLParser, didEndElement e: String, namespaceURI: String?, qualifiedName: String?) {
            if e == "item", let c = cur {
                items.append((c["title"] ?? "", c["link"] ?? "", c["pubDate"] ?? "", c["description"] ?? ""))
                cur = nil
            } else if cur != nil, ["title", "link", "pubDate", "description"].contains(e) {
                cur?[e] = text.trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }
    }

    static func isWebLink(_ s: String) -> Bool {
        guard let u = URL(string: s), let scheme = u.scheme?.lowercased() else { return false }
        return scheme == "http" || scheme == "https"
    }

    static func fetch(_ url: String, timeout: TimeInterval = 8) -> Data? {
        guard isWebLink(url), let u = URL(string: url) else { return nil }
        var req = URLRequest(url: u, timeoutInterval: timeout)
        req.setValue("Mozilla/5.0 (Macintosh) JARVIS", forHTTPHeaderField: "User-Agent")
        let sem = DispatchSemaphore(value: 0)
        var out: Data?
        URLSession.shared.dataTask(with: req) { d, r, _ in
            if (r as? HTTPURLResponse)?.statusCode == 200 { out = d }
            sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + timeout + 1)
        return out
    }

    static func strip(_ s: String) -> String {
        var t = s.replacing(/<[^>]+>/) { _ in " " }
        for (k, v) in ["&amp;": "&", "&quot;": "\"", "&#39;": "'", "&apos;": "'", "&lt;": "<", "&gt;": ">", "&nbsp;": " ",
                       "&egrave;": "è", "&eacute;": "é", "&agrave;": "à", "&ograve;": "ò", "&ugrave;": "ù", "&igrave;": "ì", "&rsquo;": "'", "&#8217;": "'", "&euro;": "€", "&laquo;": "«", "&raquo;": "»"] {
            t = t.replacingOccurrences(of: k, with: v)
        }
        return t.replacing(/\s+/) { _ in " " }.trimmingCharacters(in: .whitespaces)
    }

    static func load(_ cats: [String]) -> [Item] {
        let df = DateFormatter()
        df.locale = Locale(identifier: "en_US_POSIX")
        df.dateFormat = "EEE, dd MMM yyyy HH:mm:ss Z"
        var all: [Item] = []
        let lock = NSLock()
        let g = DispatchGroup()
        for c in cats { for (src, url) in feeds[c] ?? [] {
            g.enter()
            DispatchQueue.global().async {
                defer { g.leave() }
                guard let d = fetch(url) else { return }
                let p = Parser(); let xp = XMLParser(data: d); xp.delegate = p; xp.parse()
                let items = p.items.map { Item(source: src, title: strip($0.title), link: $0.link,
                                              date: df.date(from: $0.date) ?? .distantPast, desc: strip($0.desc)) }
                lock.lock(); all += items; lock.unlock()
            }
        } }
        g.wait()
        var seen = Set<String>()
        return all.sorted { $0.date > $1.date }.filter { seen.insert($0.title.lowercased()).inserted && !$0.title.isEmpty }
    }

    static func run(_ a: [String]) throws -> String {
        let args = Args(a)
        let first = args.pos.first ?? "tutte"
        switch first {
        case "read", "leggi", "open", "apri":
            guard let r = args.pos.dropFirst().first, let stored = Refs.resolve(r) else { throw ToolError("uso: news read <n1>") }
            let parts = stored.components(separatedBy: "\u{1}")
            let link = parts[0], summary = parts.count > 2 ? "\(parts[1]). \(parts[2])" : ""
            if first == "open" || first == "apri" {
                guard isWebLink(link) else { throw ToolError("link non valido: apro solo indirizzi http/https") }
                _ = try runProcess("/usr/bin/open", [link]); return "Articolo aperto nel browser."
            }
            // ANSA serves a consent wall to non-browser clients: its RSS summary is the reliable text.
            if link.contains("ansa.it") { return summary.isEmpty ? "Sommario non disponibile." : "Sommario ANSA: \(summary)" }
            guard let d = fetch(link, timeout: 10) else { throw ToolError("articolo non raggiungibile") }
            let page = String(decoding: d, as: UTF8.self)
            let boiler = /(?i)cookie|abbonament|privacy|consentless|condizioni generali|newsletter|accedi|registrati|riproduzione riservata|contenuti ogni|domande più frequenti|numero verde|email.*protected|siti internazionali|translated by ai/
            let paras = page.matches(of: /<p[^>]*>([\s\S]*?)<\/p>/).map { strip(String($0.1)) }
                .filter { $0.count > 120 && $0.firstMatch(of: boiler) == nil }
            let text = paras.joined(separator: "\n")
            if paras.count < 2 || text.count < 400 {
                return summary.isEmpty ? "Testo completo non disponibile (paywall): con news open lo apro nel browser." :
                    "Testo completo non disponibile (paywall). Sommario: \(summary)"
            }
            if text.count < 200 { return "Il sito non rende disponibile il testo completo (paywall o cookie): resta il sommario del titolo; con news open lo apro nel browser." }
            return text.count > 3500 ? String(text.prefix(3500)) + " [...]" : text
        default:
            let cats: [String]
            switch first {
            case "finanza", "economia", "borsa", "mercati": cats = ["finanza"]
            case "italia", "cronaca", "politica": cats = ["italia"]
            default: cats = ["italia", "finanza"]
            }
            let n = Int(args.pos.dropFirst().first ?? args.o("n") ?? "") ?? 8
            let items = load(cats)
            if items.isEmpty { throw ToolError("nessuna notizia: fonti non raggiungibili") }
            let shown = Array(items.prefix(min(n, 20)))
            let refs = Refs.assign("n", shown.map { "\($0.link)\u{1}\($0.title)\u{1}\($0.desc)" })
            let tf = DateFormatter(); tf.dateFormat = "HH:mm"
            return zip(refs, shown).map { ref, it in
                let d = it.desc.count > 130 ? String(it.desc.prefix(130)) + "..." : it.desc
                return "[\(ref)] \(tf.string(from: it.date)) \(it.source): \(it.title)\(d.isEmpty || d == it.title ? "" : " | " + d)"
            }.joined(separator: "\n")
        }
    }
}

// MARK: - Documents (PDF, Word, RTF, text, images)

enum DocTool {
    static var viewDir: URL {
        let u = Paths.support.appendingPathComponent("view")
        try? FileManager.default.createDirectory(at: u, withIntermediateDirectories: true)
        // keep it small: drop files older than 2 hours
        for f in (try? FileManager.default.contentsOfDirectory(at: u, includingPropertiesForKeys: [.contentModificationDateKey])) ?? [] {
            if let d = try? f.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate, Date().timeIntervalSince(d) > 7200 {
                try? FileManager.default.removeItem(at: f)
            }
        }
        return u
    }

    static func run(_ a: [String]) throws -> String {
        let args = Args(Array(a.dropFirst()))
        guard a.first == "read" || a.first == "leggi", let src = args.pos.first else {
            throw ToolError("uso: doc read <f1|percorso> [--pages 1-5]")
        }
        let path = try FileTool.resolveExisting(args.pos.joined(separator: " "))
        let ext = (path as NSString).pathExtension.lowercased()
        let maxChars = Int(args.o("max") ?? "") ?? 12000
        _ = src
        var text = ""
        switch ext {
        case "pdf":
            guard let doc = PDFDocument(url: URL(fileURLWithPath: path)) else { throw ToolError("PDF non leggibile") }
            var (from, to) = (1, doc.pageCount)
            if let p = args.o("pages", "pagine") {
                let parts = p.split(separator: "-").compactMap { Int($0) }
                if let f = parts.first { from = max(1, f); to = min(doc.pageCount, parts.count > 1 ? parts[1] : f) }
            }
            for i in (from - 1)..<to {
                if let s = doc.page(at: i)?.string, !s.isEmpty { text += "\n--- pagina \(i + 1) ---\n" + s }
                if text.count > maxChars { break }
            }
            if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                // scanned PDF: render pages to images for vision
                var outs: [String] = []
                for i in (from - 1)..<min(to, from + 2) {
                    guard let page = doc.page(at: i) else { continue }
                    let img = page.thumbnail(of: NSSize(width: 1400, height: 1800), for: .mediaBox)
                    let u = viewDir.appendingPathComponent("pdf-\(i + 1)-\(Int(Date().timeIntervalSince1970)).jpg")
                    if let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                       let jpg = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.7]) {
                        try jpg.write(to: u); outs.append(u.path)
                    }
                }
                return "PDF scansionato senza testo (\(doc.pageCount) pagine). Immagini delle pagine: \(outs.joined(separator: " ")). Guardale con lo strumento Read."
            }
            text = "PDF di \(doc.pageCount) pagine" + text
        case "png", "jpg", "jpeg", "heic", "gif", "tiff", "webp":
            let u = viewDir.appendingPathComponent("img-\(Int(Date().timeIntervalSince1970)).jpg")
            _ = try runProcess("/usr/bin/sips", ["-s", "format", "jpeg", "-Z", "1600", path, "--out", u.path])
            return "Immagine pronta: \(u.path). Guardala con lo strumento Read."
        case "txt", "md", "csv", "json", "swift", "py", "js", "html", "xml", "log":
            text = (try? String(contentsOfFile: path, encoding: .utf8)) ?? (try? String(contentsOfFile: path, encoding: .isoLatin1)) ?? ""
        default:
            // doc, docx, rtf, odt, pages(partial), webarchive...
            let r = try runProcess("/usr/bin/textutil", ["-convert", "txt", "-stdout", path], timeout: 30)
            if r.code != 0 || r.out.isEmpty { throw ToolError("formato .\(ext) non supportato") }
            text = r.out
        }
        ActionLog.add("DOCUMENTS", "Letto \((path as NSString).lastPathComponent)")
        let clean = text.replacing(/\n{3,}/) { _ in "\n\n" }
        return clean.count > maxChars ? String(clean.prefix(maxChars)) + "\n[... troncato: usa --pages per altre parti]" : clean
    }
}

// MARK: - Screen (what the user is looking at)

enum ScreenTool {
    static func run(_ a: [String]) throws -> String {
        let args = Args(a, flags: ["full", "tutto"])
        let u = DocTool.viewDir.appendingPathComponent("screen-\(Int(Date().timeIntervalSince1970)).jpg")
        var what = "schermo intero"
        var cmd = ["-x", "-t", "jpg"]
        if !args.has("full") && !args.has("tutto"), let (wid, name) = frontWindow() {
            cmd += ["-o", "-l", String(wid)]
            what = "finestra di \(name)"
        }
        let r = try runProcess("/usr/sbin/screencapture", cmd + [u.path])
        guard r.code == 0, FileManager.default.fileExists(atPath: u.path) else {
            throw ToolError("serve il permesso Registrazione schermo per JARVIS (Impostazioni > Privacy e sicurezza > Registrazione schermo e audio)")
        }
        _ = try? runProcess("/usr/bin/sips", ["-Z", "1600", u.path])
        ActionLog.add("VISION", "Acquisita \(what)")
        return "Acquisita \(what): \(u.path). Guardala con lo strumento Read e rispondi alla domanda dell'utente."
    }

    /// Frontmost window of the app the user was using before JARVIS (written by the app in frontmost.json).
    static func frontWindow() -> (Int, String)? {
        struct Front: Codable { let pid: Int32; let name: String }
        let front = Store.load("frontmost.json", Front.self)
        let pid = front?.pid ?? NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0
        guard let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else { return nil }
        for w in list {
            guard (w[kCGWindowOwnerPID as String] as? Int32) == pid, (w[kCGWindowLayer as String] as? Int) == 0,
                  let b = w[kCGWindowBounds as String] as? [String: Double], (b["Width"] ?? 0) > 200, (b["Height"] ?? 0) > 150,
                  let id = w[kCGWindowNumber as String] as? Int else { continue }
            return (id, front?.name ?? (w[kCGWindowOwnerName as String] as? String ?? "app"))
        }
        return nil
    }
}
