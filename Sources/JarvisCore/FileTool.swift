import Foundation

/// Finder & file system: find (Spotlight), list, move, copy, rename, mkdir, open, trash.
enum FileTool {
    static let fm = FileManager.default
    static let bulkLimit = 25

    static func run(_ a: [String], confirmed: Bool, raw: [String]) throws -> String {
        guard let sub = a.first else { throw ToolError("uso: file find|ls|move|copy|rename|mkdir|open|reveal|trash") }
        let args = Args(Array(a.dropFirst()), flags: ["dirs", "all"])
        switch sub {
        case "find", "cerca":
            let q = args.pos.joined(separator: " ")
            let dir = args.o("in", "dir").map(Paths.expand) ?? fm.homeDirectoryForCurrentUser.path
            let ext = args.o("ext")?.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "."))
            // Int(days) below traps on nan/inf/huge values: accept only a sane finite range
            let days = args.o("days", "giorni").flatMap { Double($0) }.flatMap { $0.isFinite && $0 >= 0 && $0 < 36500 ? $0 : nil }
            let limit = Int(args.o("n", "max") ?? "") ?? 15
            var query: [String] = []
            if !q.isEmpty { query.append("kMDItemFSName == \"*\(q.replacingOccurrences(of: "\"", with: ""))*\"cd") }
            if let ext { query.append("kMDItemFSName == \"*.\(ext)\"c") }
            if let days { query.append("kMDItemFSContentChangeDate >= $time.today(-\(Int(days)))") }
            if args.has("dirs") { query.append("kMDItemContentType == \"public.folder\"") }
            guard !query.isEmpty else { throw ToolError("uso: file find <nome> [--ext pdf] [--in DIR] [--days N] [--dirs]") }
            let r = try runProcess("/usr/bin/mdfind", ["-onlyin", dir, query.joined(separator: " && ")], timeout: 20)
            var paths = r.out.split(separator: "\n").map(String.init).filter { p in
                !p.contains("/Library/") && !p.contains("/.") && !p.contains(".app/") && !p.contains("/node_modules/")
            }
            paths = paths.map { ($0, mtime($0)) }.sorted { $0.1 > $1.1 }.map(\.0)
            if paths.isEmpty && dir != fm.homeDirectoryForCurrentUser.path {
                // Spotlight may lag on fresh files or skip unindexed folders: bounded direct walk.
                paths = walk(dir, name: q, ext: ext, days: days, dirsOnly: args.has("dirs"))
            }
            if paths.isEmpty { return "Nessun file trovato." }
            let shown = Array(paths.prefix(limit))
            return "\(paths.count) trovati\(paths.count > shown.count ? " (mostro \(shown.count))" : ""):\n" + describe(shown, prefix: "f")
        case "ls", "list":
            let dir = Paths.expand(args.pos.first ?? "~/Desktop")
            let ext = args.o("ext")?.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "."))
            var items = try fm.contentsOfDirectory(atPath: dir).filter { !$0.hasPrefix(".") }
            if let ext { items = items.filter { ($0 as NSString).pathExtension.lowercased() == ext } }
            let paths = items.map { (dir as NSString).appendingPathComponent($0) }.sorted { mtime($0) > mtime($1) }
            if paths.isEmpty { return "\(Paths.pretty(dir)) è vuota\(ext != nil ? " (per .\(ext!))" : "")." }
            let shown = Array(paths.prefix(args.has("all") ? 200 : 40))
            return "\(Paths.pretty(dir)): \(paths.count) elementi\(paths.count > shown.count ? " (mostro \(shown.count))" : ""):\n" + describe(shown, prefix: "f")
        case "move", "mv", "sposta", "copy", "cp", "copia":
            let copy = ["copy", "cp", "copia"].contains(sub)
            guard let destRaw = args.o("to", "in", "dest") else { throw ToolError("manca --to <cartella>") }
            let dest = resolve(destRaw)
            var isDir: ObjCBool = false
            guard fm.fileExists(atPath: dest, isDirectory: &isDir), isDir.boolValue else {
                throw ToolError("la cartella \(Paths.pretty(dest)) non esiste: creala con `file mkdir` o cercala con `file find <nome> --dirs`")
            }
            let sources = try expandSources(args.pos)
            guard !sources.isEmpty else { throw ToolError("nessun file corrisponde") }
            let verb = copy ? "Copiare" : "Spostare"
            let hidden = sources.contains { ($0 as NSString).lastPathComponent.hasPrefix(".") }
            // also when the files come FROM a system/config folder (e.g. copying ~/.ssh/id_ed25519 to the Desktop)
            let fromSensitive = sources.contains { isSensitive(($0 as NSString).deletingLastPathComponent) }
            if (sources.count > bulkLimit || isSensitive(dest) || fromSensitive || hidden) && !confirmed {
                let why = isSensitive(dest) || fromSensitive ? " (cartella di sistema o di configurazione)" : hidden ? " (file nascosti)" : ""
                return Gate.request("\(verb) \(sources.count) elementi in \(Paths.pretty(dest))\(why)", argv: raw)
            }
            var done: [String] = []
            for s in sources {
                let target = unique((dest as NSString).appendingPathComponent((s as NSString).lastPathComponent))
                if copy { try fm.copyItem(atPath: s, toPath: target) } else { try fm.moveItem(atPath: s, toPath: target) }
                done.append((target as NSString).lastPathComponent)
            }
            let what = done.count == 1 ? done[0] : "\(done.count) elementi"
            ActionLog.add("FILE_SYSTEM", "\(copy ? "Copiato" : "Spostato") \(what) in \(Paths.pretty(dest))")
            return "\(copy ? "Copiat" : "Spostat")\(done.count == 1 ? "o" : "i") \(what) in \(Paths.pretty(dest))."
        case "rename", "rinomina":
            guard args.pos.count >= 2 else { throw ToolError("uso: file rename <SRC> <nuovo nome>") }
            let src = try resolveExisting(args.pos[0])
            var newName = args.pos.dropFirst().joined(separator: " ")
            if (newName as NSString).pathExtension.isEmpty, !(src as NSString).pathExtension.isEmpty {
                newName += "." + (src as NSString).pathExtension
            }
            guard !newName.contains("/") else { throw ToolError("il nuovo nome non può contenere /") }
            let newExt = (newName as NSString).pathExtension.lowercased()
            if (newName.hasPrefix(".") || isSensitive((src as NSString).deletingLastPathComponent)
                || (riskyExt.contains(newExt) && newExt != (src as NSString).pathExtension.lowercased())) && !confirmed {
                return Gate.request("Rinominare \((src as NSString).lastPathComponent) in \(newName)", argv: raw)
            }
            let target = ((src as NSString).deletingLastPathComponent as NSString).appendingPathComponent(newName)
            guard !fm.fileExists(atPath: target) else { throw ToolError("esiste già \(newName)") }
            try fm.moveItem(atPath: src, toPath: target)
            ActionLog.add("FILE_SYSTEM", "Rinominato \((src as NSString).lastPathComponent) in \(newName)")
            return "Rinominato in \(newName)."
        case "mkdir", "crea":
            guard let p = args.pos.first else { throw ToolError("uso: file mkdir <percorso>") }
            let path = Paths.expand(args.pos.joined(separator: " "))
            try fm.createDirectory(atPath: path, withIntermediateDirectories: true)
            ActionLog.add("FILE_SYSTEM", "Creata cartella \(Paths.pretty(path))")
            _ = p
            return "Creata \(Paths.pretty(path))."
        case "open", "apri", "reveal", "mostra":
            let src = try resolveExisting(args.pos.joined(separator: " "))
            let reveal = ["reveal", "mostra"].contains(sub)
            if !reveal && isRisky(src) && !confirmed {
                return Gate.request("Aprire \((src as NSString).lastPathComponent) (app, script o file eseguibile)", argv: raw)
            }
            _ = try runProcess("/usr/bin/open", reveal ? ["-R", src] : [src])
            ActionLog.add("FILE_SYSTEM", "\(reveal ? "Mostrato" : "Aperto") \((src as NSString).lastPathComponent)")
            return "\(reveal ? "Mostrato nel Finder" : "Aperto") \((src as NSString).lastPathComponent)."
        case "trash", "cestina":
            let sources = try expandSources(args.pos)
            guard !sources.isEmpty else { throw ToolError("nessun file corrisponde") }
            let names = sources.prefix(5).map { ($0 as NSString).lastPathComponent }.joined(separator: ", ") + (sources.count > 5 ? "..." : "")
            if !confirmed { return Gate.request(sources.count == 1 ? "Spostare nel Cestino \(names)" : "Spostare nel Cestino \(sources.count) elementi (\(names))", argv: raw) }
            for s in sources { try fm.trashItem(at: URL(fileURLWithPath: s), resultingItemURL: nil) }
            ActionLog.add("FILE_SYSTEM", "Cestinati \(sources.count) elementi")
            return sources.count == 1 ? "Spostato nel Cestino \((sources[0] as NSString).lastPathComponent)." : "Spostati nel Cestino \(sources.count) elementi."
        default:
            throw ToolError("sottocomando file sconosciuto: \(sub)")
        }
    }

    // MARK: safety (the model also reads untrusted text: mail, chats, web pages, documents)

    /// Opening these runs code: app bundles, scripts, installers, automation and configuration profiles.
    static let riskyExt: Set<String> = [
        "app", "command", "sh", "zsh", "bash", "csh", "ksh", "fish", "tool", "terminal", "workflow", "action",
        "scpt", "scptd", "applescript", "pkg", "mpkg", "dmg", "jar", "py", "rb", "pl", "php", "js", "jsx",
        "prefpane", "kext", "plugin", "bundle", "osax", "fileloc", "webloc", "inetloc", "shortcut",
        "mobileconfig", "configprofile", "saver", "qlgenerator", "mdimporter",
    ]

    static func isRisky(_ path: String) -> Bool {
        if riskyExt.contains((path as NSString).pathExtension.lowercased()) { return true }
        var isDir: ObjCBool = false
        return fm.fileExists(atPath: path, isDirectory: &isDir) && !isDir.boolValue && fm.isExecutableFile(atPath: path)
    }

    /// System folders, ~/Library (LaunchAgents = persistence) and hidden folders such as ~/.ssh.
    static func isSensitive(_ dir: String) -> Bool {
        let home = fm.homeDirectoryForCurrentUser.resolvingSymlinksInPath().path
        let p = URL(fileURLWithPath: dir).resolvingSymlinksInPath().path
        let roots = ["/Library", "/System", "/usr", "/bin", "/sbin", "/etc", "/private/etc", "/opt", "/Applications",
                     home + "/Library", home + "/Applications"]
        if roots.contains(where: { p == $0 || p.hasPrefix($0 + "/") }) { return true }
        if p.hasPrefix(home + "/") { return p.dropFirst(home.count + 1).split(separator: "/").contains { $0.hasPrefix(".") } }
        return false
    }

    // MARK: helpers

    static func resolve(_ s: String) -> String {
        if let r = Refs.resolve(s) { return r }
        return Paths.expand(s)
    }

    static func resolveExisting(_ s: String) throws -> String {
        let p = resolve(s)
        guard fm.fileExists(atPath: p) else { throw ToolError("file non trovato: \(s)") }
        return p
    }

    static func expandSources(_ items: [String]) throws -> [String] {
        var out: [String] = []
        for it in items {
            if let r = Refs.resolve(it) { out.append(r); continue }
            let p = Paths.expand(it)
            if p.contains("*") || p.contains("?") {
                var g = glob_t()
                defer { globfree(&g) }
                if glob(p, GLOB_TILDE, nil, &g) == 0 {
                    for i in 0..<Int(g.gl_matchc) { if let c = g.gl_pathv[i] { out.append(String(cString: c)) } }
                }
            } else if fm.fileExists(atPath: p) {
                out.append(p)
            } else {
                throw ToolError("non trovato: \(it)")
            }
        }
        return out
    }

    static func unique(_ path: String) -> String {
        guard fm.fileExists(atPath: path) else { return path }
        let ns = path as NSString
        let ext = ns.pathExtension, base = (ns.deletingPathExtension as NSString)
        var i = 2
        while true {
            let cand = base.appendingFormat(" %d", i) as String + (ext.isEmpty ? "" : "." + ext)
            if !fm.fileExists(atPath: cand) { return cand }
            i += 1
        }
    }

    static func walk(_ root: String, name: String, ext: String?, days: Double?, dirsOnly: Bool, cap: Int = 20000) -> [String] {
        guard let en = fm.enumerator(at: URL(fileURLWithPath: root), includingPropertiesForKeys: [.isDirectoryKey, .contentModificationDateKey],
                                     options: [.skipsHiddenFiles, .skipsPackageDescendants]) else { return [] }
        let since = days.map { Date().addingTimeInterval(-$0 * 86400) }
        var out: [String] = [], seen = 0
        for case let u as URL in en {
            seen += 1
            if seen > cap { break }
            let v = try? u.resourceValues(forKeys: [.isDirectoryKey, .contentModificationDateKey])
            let isDir = v?.isDirectory ?? false
            if dirsOnly && !isDir { continue }
            let n = u.lastPathComponent
            if !name.isEmpty && n.range(of: name, options: [.caseInsensitive, .diacriticInsensitive]) == nil { continue }
            if let ext, u.pathExtension.lowercased() != ext { continue }
            if let since, (v?.contentModificationDate ?? .distantPast) < since { continue }
            out.append(u.path)
        }
        return out.sorted { mtime($0) > mtime($1) }
    }

    static func mtime(_ p: String) -> Date {
        ((try? fm.attributesOfItem(atPath: p))?[.modificationDate] as? Date) ?? .distantPast
    }

    static func describe(_ paths: [String], prefix: String) -> String {
        let refs = Refs.assign(prefix, paths)
        let f = ByteCountFormatter()
        f.countStyle = .file
        let df = DateFormatter()
        df.dateFormat = "yyyy-MM-dd"
        return zip(refs, paths).map { ref, p in
            var isDir: ObjCBool = false
            fm.fileExists(atPath: p, isDirectory: &isDir)
            let size = isDir.boolValue ? "cartella" : f.string(fromByteCount: Int64(((try? fm.attributesOfItem(atPath: p))?[.size] as? NSNumber)?.int64Value ?? 0))
            return "[\(ref)] \(Paths.pretty(p)) (\(size), \(df.string(from: mtime(p))))"
        }.joined(separator: "\n")
    }
}
