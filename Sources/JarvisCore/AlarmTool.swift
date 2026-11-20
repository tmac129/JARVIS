import Darwin
import Foundation

/// Alarms = launchd agents (survive app quit and sleep). Timers = detached background waiters.
enum AlarmTool {
    struct Alarm: Codable { let id: String; let date: Date; let label: String; let daily: Bool }
    struct Timer: Codable { let id: String; let end: Date; let label: String; let pid: Int32 }

    static let agentsDir = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents")
    static func plistURL(_ id: String) -> URL { agentsDir.appendingPathComponent("com.jarvis.alarm.\(id).plist") }
    static var uid: String { String(getuid()) }

    // MARK: alarms

    static func alarm(_ a: [String], confirmed: Bool, raw: [String]) throws -> String {
        let sub = a.first ?? "list"
        let args = Args(Array(a.dropFirst()), flags: ["daily", "ognigiorno"])
        var alarms = Store.load("alarms.json", [Alarm].self) ?? []
        switch sub {
        case "set", "add":
            let spec = ([args.o("date", "data")].compactMap { $0 } + args.pos).joined(separator: " ")
            guard let p = When.parse(spec, futureOnly: true), p.hasTime else {
                throw ToolError("orario non valido: usa alarm set HH:MM [--date DATA]")
            }
            let date = p.0
            let daily = args.has("daily") || args.has("ognigiorno")
            let label = args.o("label", "etichetta") ?? "Sveglia"
            var n = 1
            while alarms.contains(where: { $0.id == "a\(n)" }) { n += 1 }
            let al = Alarm(id: "a\(n)", date: date, label: label, daily: daily)
            try install(al)
            alarms.append(al)
            Store.save("alarms.json", alarms)
            let when = daily ? "ogni giorno alle \(When.hm(date))" : When.fmt(date)
            ActionLog.add("CLOCK", "Sveglia \(when) (\(label))")
            return "Sveglia [\(al.id)] impostata \(when)."
        case "list":
            alarms = alarms.filter { $0.daily || $0.date > Date().addingTimeInterval(-120) }
            if alarms.isEmpty { return "Nessuna sveglia attiva." }
            return alarms.map { "[\($0.id)] \($0.daily ? "ogni giorno " + When.hm($0.date) : When.fmt($0.date)) \($0.label)" }.joined(separator: "\n")
        case "cancel", "delete", "off":
            guard let id = args.pos.first?.trimmingCharacters(in: CharacterSet(charactersIn: "[]")),
                  let al = alarms.first(where: { $0.id == id }) else { throw ToolError("sveglia non trovata: usa alarm list") }
            remove(al.id)
            alarms.removeAll { $0.id == id }
            Store.save("alarms.json", alarms)
            ActionLog.add("CLOCK", "Sveglia \(When.hm(al.date)) annullata")
            return "Sveglia delle \(When.hm(al.date)) annullata."
        case "_fire":
            guard let id = args.pos.first else { return "" }
            let al = alarms.first { $0.id == id }
            ring(title: "Sveglia", message: al?.label ?? "Sveglia", speech: "Signore, sono le \(When.hm(Date())). \(al?.label == "Sveglia" ? "" : al?.label ?? "")")
            if let al, !al.daily {
                alarms.removeAll { $0.id == id }
                Store.save("alarms.json", alarms)
                remove(id) // unloads this job: must be last
            }
            return ""
        default:
            throw ToolError("sottocomando alarm sconosciuto: \(sub)")
        }
    }

    static func install(_ al: Alarm) throws {
        try FileManager.default.createDirectory(at: agentsDir, withIntermediateDirectories: true)
        let c = Calendar.current.dateComponents([.month, .day, .hour, .minute], from: al.date)
        var interval: [String: Int] = ["Hour": c.hour!, "Minute": c.minute!]
        if !al.daily { interval["Month"] = c.month!; interval["Day"] = c.day! }
        let plist: [String: Any] = [
            "Label": "com.jarvis.alarm.\(al.id)",
            "ProgramArguments": [Paths.executable, "alarm", "_fire", al.id],
            "StartCalendarInterval": interval,
            "StandardErrorPath": Paths.file("alarm.err.log").path,
        ]
        let data = try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
        try data.write(to: plistURL(al.id))
        let r = try runProcess("/bin/launchctl", ["bootstrap", "gui/\(uid)", plistURL(al.id).path])
        if r.code != 0 { throw ToolError("launchctl: \(r.err)") }
    }

    static func remove(_ id: String) {
        let url = plistURL(id)
        try? FileManager.default.removeItem(at: url)
        _ = try? runProcess("/bin/launchctl", ["bootout", "gui/\(uid)/com.jarvis.alarm.\(id)"])
    }

    // MARK: timers

    static func timer(_ a: [String]) throws -> String {
        var timers = (Store.load("timers.json", [Timer].self) ?? []).filter { $0.end > Date() && kill($0.pid, 0) == 0 }
        let args = Args(a)
        let first = args.pos.first ?? "list"
        switch first {
        case "list", "timers":
            Store.save("timers.json", timers)
            if timers.isEmpty { return "Nessun timer attivo." }
            return timers.map { "[\($0.id)] \($0.label): mancano \(When.durationText($0.end.timeIntervalSinceNow))" }.joined(separator: "\n")
        case "cancel", "stop", "off":
            let id = args.pos.dropFirst().first?.trimmingCharacters(in: CharacterSet(charactersIn: "[]")) ?? timers.last?.id
            guard let id, let t = timers.first(where: { $0.id == id }) else { throw ToolError("nessun timer da annullare") }
            kill(t.pid, SIGTERM)
            timers.removeAll { $0.id == id }
            Store.save("timers.json", timers)
            ActionLog.add("CLOCK", "Timer \(t.label) annullato")
            return "Timer \(t.label) annullato."
        case "_wait":
            guard args.pos.count >= 2, let secs = Double(args.pos[1]) else { return "" }
            let label = args.pos.dropFirst(2).joined(separator: " ")
            Thread.sleep(forTimeInterval: secs)
            ring(title: "Timer", message: label.isEmpty ? "Tempo scaduto" : label,
                 speech: "Signore, il timer \(label.isEmpty ? "" : label + " ")è scaduto.")
            return ""
        default:
            guard let secs = When.duration(args.pos.joined(separator: " ")) else {
                throw ToolError("durata non valida: usa timer 20m | 90s | 1h30m")
            }
            // Int(secs) traps on nan/inf/huge values ("99999999999999999999h")
            guard secs.isFinite, secs <= 7 * 86400 else { throw ToolError("durata troppo lunga: massimo 7 giorni") }
            let label = args.o("label", "etichetta") ?? When.durationText(secs)
            var n = 1
            while timers.contains(where: { $0.id == "t\(n)" }) { n += 1 }
            let pid = try spawnDetached([Paths.executable, "timer", "_wait", String(Int(secs)), label])
            let t = Timer(id: "t\(n)", end: Date().addingTimeInterval(secs), label: label, pid: pid)
            timers.append(t)
            Store.save("timers.json", timers)
            ActionLog.add("CLOCK", "Timer \(When.durationText(secs)) avviato")
            return "Timer [\(t.id)] di \(When.durationText(secs)) avviato, scade alle \(When.hm(t.end))."
        }
    }

    /// Starts a process in its own session so it outlives the caller (and the Bash tool).
    static func spawnDetached(_ argv: [String]) throws -> Int32 {
        var attr: posix_spawnattr_t?
        posix_spawnattr_init(&attr)
        defer { posix_spawnattr_destroy(&attr) }
        posix_spawnattr_setflags(&attr, Int16(POSIX_SPAWN_SETSID))
        var fa: posix_spawn_file_actions_t?
        posix_spawn_file_actions_init(&fa)
        defer { posix_spawn_file_actions_destroy(&fa) }
        for fd: Int32 in [0, 1, 2] { posix_spawn_file_actions_addopen(&fa, fd, "/dev/null", fd == 0 ? O_RDONLY : O_WRONLY, 0) }
        var pid: pid_t = 0
        let cargs = argv.map { strdup($0) } + [nil]
        defer { cargs.forEach { free($0) } }
        let rc = posix_spawn(&pid, argv[0], &fa, &attr, cargs, environ)
        if rc != 0 { throw ToolError("impossibile avviare il timer (\(rc))") }
        return pid
    }

    // MARK: ring

    /// Sound + notification + voice. If the JARVIS app is running it also receives the action-log event.
    static func ring(title: String, message: String, speech: String) {
        ActionLog.add("CLOCK", "\(title): \(message)")
        _ = try? appleScript("on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv) sound name \"Glass\"\nend run",
                             ["J.A.R.V.I.S. \(title)", message], timeout: 10)
        for _ in 0..<3 { _ = try? runProcess("/usr/bin/afplay", ["/System/Library/Sounds/Glass.aiff"], timeout: 5) }
        _ = try? runProcess("/usr/bin/say", [speech], timeout: 30)
    }
}
