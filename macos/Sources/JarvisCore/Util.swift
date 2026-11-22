import Foundation

public struct ToolError: Error, CustomStringConvertible {
    public let description: String
    public init(_ s: String) { description = s }
}

// MARK: - Paths

public enum Paths {
    public static let support: URL = {
        let u = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/JARVIS")
        try? FileManager.default.createDirectory(at: u, withIntermediateDirectories: true)
        return u
    }()

    public static func file(_ name: String) -> URL { support.appendingPathComponent(name) }

    /// Absolute path of the `jarvis` CLI (symlinks resolved). Inside JARVIS.app the running binary is the HUD,
    /// so use its sibling `jarvis`: timers, launchd alarms and Claude's PATH must always point to the CLI.
    public static var executable: String {
        let p = URL(fileURLWithPath: Bundle.main.executablePath ?? CommandLine.arguments[0]).resolvingSymlinksInPath()
        if p.lastPathComponent == "jarvis" { return p.path }
        let sibling = p.deletingLastPathComponent().appendingPathComponent("jarvis").path
        return FileManager.default.isExecutableFile(atPath: sibling) ? sibling : p.path
    }

    public static func expand(_ p: String) -> String {
        var s = p.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("~") { s = (s as NSString).expandingTildeInPath }
        if !s.hasPrefix("/") {
            s = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(s).path
        }
        return (s as NSString).standardizingPath
    }

    public static func pretty(_ p: String) -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return p.hasPrefix(home) ? "~" + p.dropFirst(home.count) : p
    }
}

// MARK: - JSON state files

public enum Store {
    public static func load<T: Decodable>(_ name: String, _ type: T.Type) -> T? {
        guard let d = try? Data(contentsOf: Paths.file(name)) else { return nil }
        return try? JSONDecoder().decode(T.self, from: d)
    }

    public static func save<T: Encodable>(_ name: String, _ value: T) {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        if let d = try? enc.encode(value) { try? d.write(to: Paths.file(name), options: .atomic) }
    }
}

/// Short references ([e1], [m2], [f3]...) to items of the last listing, to keep tokens low.
public enum Refs {
    public static func assign(_ prefix: String, _ values: [String]) -> [String] {
        var all = Store.load("refs.json", [String: String].self) ?? [:]
        all = all.filter { !$0.key.hasPrefix(prefix) || Int($0.key.dropFirst(prefix.count)) == nil }
        var labels: [String] = []
        for (i, v) in values.enumerated() {
            let k = "\(prefix)\(i + 1)"
            all[k] = v
            labels.append(k)
        }
        Store.save("refs.json", all)
        return labels
    }

    /// Resolves "e1" / "[e1]" to its stored value; returns nil if it is not a known ref.
    public static func resolve(_ s: String) -> String? {
        let k = s.trimmingCharacters(in: CharacterSet(charactersIn: "[] "))
        return (Store.load("refs.json", [String: String].self) ?? [:])[k]
    }
}

// MARK: - Action feed log (tailed by the HUD)

public enum ActionLog {
    static let maxBytes = 256 * 1024

    public static func add(_ module: String, _ text: String) {
        let line: [String: Any] = ["ts": ISO8601DateFormatter().string(from: Date()), "module": module, "text": text]
        guard let d = try? JSONSerialization.data(withJSONObject: line),
              var s = String(data: d, encoding: .utf8) else { return }
        s += "\n"
        let url = Paths.file("actions.log")
        // Rotation: past maxBytes the file becomes actions.log.1 (one previous copy kept).
        if let size = (try? FileManager.default.attributesOfItem(atPath: url.path))?[.size] as? Int, size > maxBytes {
            let old = Paths.file("actions.log.1")
            try? FileManager.default.removeItem(at: old)
            try? FileManager.default.moveItem(at: url, to: old)
        }
        if let h = try? FileHandle(forWritingTo: url) {
            defer { try? h.close() }
            _ = try? h.seekToEnd(); try? h.write(contentsOf: Data(s.utf8))
        } else {
            try? s.write(to: url, atomically: true, encoding: .utf8)
        }
    }
}

// MARK: - Processes

public struct ProcResult { public let out: String; public let err: String; public let code: Int32 }

@discardableResult
public func runProcess(_ exe: String, _ args: [String], stdin: String? = nil, timeout: TimeInterval = 60,
                       environment: [String: String]? = nil) throws -> ProcResult {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    if let environment { p.environment = environment }
    let o = Pipe(), e = Pipe()
    p.standardOutput = o
    p.standardError = e
    let inPipe = Pipe()
    p.standardInput = stdin != nil ? inPipe : FileHandle.nullDevice
    try p.run()
    if let s = stdin {
        inPipe.fileHandleForWriting.write(s.data(using: .utf8)!)
        try? inPipe.fileHandleForWriting.close()
    }
    var errData = Data()
    let g = DispatchGroup()
    g.enter()
    DispatchQueue.global().async { errData = e.fileHandleForReading.readDataToEndOfFile(); g.leave() }
    let killer = DispatchWorkItem { if p.isRunning { p.terminate() } }
    DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: killer)
    let outData = o.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    g.wait()
    killer.cancel()
    return ProcResult(out: String(decoding: outData, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines),
                      err: String(decoding: errData, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines),
                      code: p.terminationStatus)
}

/// Runs an AppleScript (`on run argv ... end run`). User data travels only via argv, never interpolated.
public func appleScript(_ source: String, _ argv: [String] = [], timeout: TimeInterval = 60) throws -> String {
    let r = try runProcess("/usr/bin/osascript", ["-"] + argv, stdin: source, timeout: timeout)
    if r.code != 0 {
        if r.err.contains("-1743") || r.err.contains("Not authorized") {
            throw ToolError("Permesso Automazione negato: abilitalo in Impostazioni > Privacy e sicurezza > Automazione.")
        }
        throw ToolError(r.err.isEmpty ? "AppleScript fallito (\(r.code))" : r.err)
    }
    return r.out
}

// MARK: - Argument parsing

public struct Args {
    public var pos: [String] = []
    public var opts: [String: [String]] = [:]
    public var flags: Set<String> = []

    public init(_ a: [String], flags known: Set<String> = []) {
        var i = 0
        while i < a.count {
            let s = a[i]
            if s.hasPrefix("--") && s.count > 2 {
                let k = String(s.dropFirst(2))
                if known.contains(k) || i + 1 >= a.count {
                    flags.insert(k)
                } else {
                    opts[k, default: []].append(a[i + 1]); i += 1
                }
            } else {
                pos.append(s)
            }
            i += 1
        }
    }

    public func o(_ k: String...) -> String? {
        for key in k { if let v = opts[key]?.last { return v } }
        return nil
    }

    public func list(_ k: String...) -> [String] {
        k.flatMap { opts[$0] ?? [] }
            .flatMap { $0.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) } }
            .filter { !$0.isEmpty }
    }

    public func has(_ k: String) -> Bool { flags.contains(k) }
}

// MARK: - Dates

public enum When {
    static let cal = Calendar.current

    static let weekdays: [String: Int] = [
        "domenica": 1, "lunedi": 2, "lunedì": 2, "martedi": 3, "martedì": 3, "mercoledi": 4, "mercoledì": 4,
        "giovedi": 5, "giovedì": 5, "venerdi": 6, "venerdì": 6, "sabato": 7,
        "sunday": 1, "monday": 2, "tuesday": 3, "wednesday": 4, "thursday": 5, "friday": 6, "saturday": 7,
    ]

    /// Parses "2026-11-18 16:00", "18/11 16:00", "domani 16", "16:30", "lunedì 9:00", "oggi".
    /// Returns the date and whether a time of day was given.
    public static func parse(_ input: String, futureOnly: Bool = false) -> (Date, hasTime: Bool)? {
        let s = input.lowercased()
            .replacing(/(\d)t(\d)/) { "\($0.1) \($0.2)" }   // ISO "2026-11-18T16:00"
            .replacing(/\b(alle|ore|h)\b/) { _ in " " }
        let now = Date()
        var day: Date? = nil
        var hour: Int? = nil, minute = 0

        for raw in s.split(separator: " ") {
            let tok = String(raw)
            if let m = tok.firstMatch(of: /^(\d{4})-(\d{1,2})-(\d{1,2})$/) {
                day = cal.date(from: DateComponents(year: Int(m.1), month: Int(m.2), day: Int(m.3)))
            } else if let m = tok.firstMatch(of: /^(\d{1,2})\/(\d{1,2})(?:\/(\d{2,4}))?$/) {
                var y = m.3.flatMap { Int($0) } ?? cal.component(.year, from: now)
                if y < 100 { y += 2000 }
                day = cal.date(from: DateComponents(year: y, month: Int(m.2), day: Int(m.1)))
            } else if let m = tok.firstMatch(of: /^(\d{1,2})(?:[:.](\d{2}))?$/), day != nil || hour == nil {
                hour = Int(m.1); minute = m.2.flatMap { Int($0) } ?? 0
            } else if ["oggi", "today", "stasera", "stamattina"].contains(tok) {
                day = cal.startOfDay(for: now)
                if tok == "stasera" && hour == nil { hour = 20 }
            } else if ["domani", "tomorrow"].contains(tok) {
                day = cal.date(byAdding: .day, value: 1, to: cal.startOfDay(for: now))
            } else if tok == "dopodomani" {
                day = cal.date(byAdding: .day, value: 2, to: cal.startOfDay(for: now))
            } else if let wd = weekdays[tok] {
                let today = cal.component(.weekday, from: now)
                var diff = (wd - today + 7) % 7
                if diff == 0 { diff = 7 }
                day = cal.date(byAdding: .day, value: diff, to: cal.startOfDay(for: now))
            }
        }
        guard day != nil || hour != nil else { return nil }
        if let h = hour, h > 23 || minute > 59 { return nil }
        let base = day ?? cal.startOfDay(for: now)
        guard var d = cal.date(bySettingHour: hour ?? 0, minute: minute, second: 0, of: base) else { return nil }
        if futureOnly, day == nil, d <= now { d = cal.date(byAdding: .day, value: 1, to: d)! }
        return (d, hour != nil)
    }

    /// "20m", "90s", "1h30m", "20", "20 minuti", "1 ora" -> seconds
    public static func duration(_ input: String) -> TimeInterval? {
        let s = input.lowercased().replacingOccurrences(of: " ", with: "")
        if let n = Double(s) { return n * 60 }
        var total: Double = 0, found = false
        for m in s.matches(of: /(\d+(?:[.,]\d+)?)(ore|ora|h|minuti|minuto|min|m|secondi|secondo|sec|s)/) {
            let v = Double(m.1.replacingOccurrences(of: ",", with: ".")) ?? 0
            switch m.2 {
            case "ore", "ora", "h": total += v * 3600
            case "secondi", "secondo", "sec", "s": total += v
            default: total += v * 60
            }
            found = true
        }
        return found && total > 0 ? total : nil
    }

    public static func fmt(_ d: Date, time: Bool = true) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "it_IT")
        f.dateFormat = time ? "EEE d MMM HH:mm" : "EEE d MMM"
        return f.string(from: d)
    }

    public static func hm(_ d: Date) -> String {
        let f = DateFormatter(); f.dateFormat = "HH:mm"; return f.string(from: d)
    }

    public static func durationText(_ s: TimeInterval) -> String {
        let t = Int(s.rounded())
        let h = t / 3600, m = (t % 3600) / 60, sec = t % 60
        var parts: [String] = []
        if h > 0 { parts.append(h == 1 ? "1 ora" : "\(h) ore") }
        if m > 0 { parts.append(m == 1 ? "1 minuto" : "\(m) minuti") }
        if sec > 0 { parts.append(sec == 1 ? "1 secondo" : "\(sec) secondi") }
        return parts.joined(separator: " e ")
    }
}
