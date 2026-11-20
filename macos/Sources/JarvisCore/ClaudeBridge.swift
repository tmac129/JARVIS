import Foundation

public struct TurnResult {
    public var text = ""
    public var tier: Tier = .haiku
    public var isError = false
    public var costUSD: Double = 0
    public var inputTokens = 0, outputTokens = 0, cacheRead = 0, cacheWrite = 0
    public var durationMs = 0
    public var pendingConfirm: String? = nil
    public var local = false
}

public enum BridgeEvent {
    case thinking(Tier)          // request sent
    case tool(String)            // command Claude is running
    case toolResult(String)
    case confirmNeeded(String)   // critical action waiting for the user
    case text(String)            // assistant text (partial turn)
    case done(TurnResult)
}

/// One long-lived `claude -p` process (stream-json in/out) per model tier:
/// no per-command startup cost, context kept between turns, reset when it grows or goes idle.
public final class ClaudeSession {
    public let tier: Tier
    /// Turns per process before it is restarted (short context = fewer tokens per turn). Env: JARVIS_MAX_TURNS.
    public static var maxTurns = envInt("JARVIS_MAX_TURNS", default: 8, min: 1)
    /// Idle seconds before the next turn starts a fresh process. Env: JARVIS_IDLE_RESET (seconds).
    public static var idleReset = TimeInterval(envInt("JARVIS_IDLE_RESET", default: 10 * 60, min: 0))

    static func envInt(_ key: String, default d: Int, min lo: Int) -> Int {
        guard let v = ProcessInfo.processInfo.environment[key].flatMap({ Int($0.trimmingCharacters(in: .whitespaces)) }), v >= lo else { return d }
        return v
    }

    private var proc: Process?
    private var stdin: FileHandle?
    private var buffer = Data()
    private let q = DispatchQueue(label: "jarvis.claude")
    private var onEvent: ((BridgeEvent) -> Void)?
    private var current = TurnResult()
    private var started = Date()
    private(set) public var sessionID: String?
    private(set) public var turns = 0
    private var lastUse = Date()

    public let effort: String
    /// Vision sessions also get the Read tool (to look at screenshots/images): ~1.4k extra context tokens,
    /// so plain commands use a Bash-only session.
    public let vision: Bool
    private var lastTotalCost = 0.0
    /// Model ID reported by the CLI's init event (what the alias resolved to), for the turn log.
    private var resolvedModel: String?

    public init(tier: Tier, effort: String? = nil, vision: Bool = false) {
        self.tier = tier
        self.effort = effort ?? tier.effort
        self.vision = vision
    }

    // MARK: locating claude

    public static func claudePath() -> String? {
        let fm = FileManager.default
        if let p = ProcessInfo.processInfo.environment["JARVIS_CLAUDE"], fm.isExecutableFile(atPath: p) { return p }
        let home = fm.homeDirectoryForCurrentUser.path
        for p in ["\(home)/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude", "\(home)/.claude/local/claude"]
        where fm.isExecutableFile(atPath: p) { return p }
        // Fallback: copy bundled with the Claude desktop app (newest version).
        let base = "\(home)/Library/Application Support/Claude/claude-code"
        let versions = ((try? fm.contentsOfDirectory(atPath: base)) ?? []).sorted { $0.compare($1, options: .numeric) == .orderedDescending }
        for v in versions {
            for sub in (try? fm.contentsOfDirectory(atPath: "\(base)/\(v)")) ?? [] {
                let p = "\(base)/\(v)/\(sub)/claude.app/Contents/MacOS/claude"
                if fm.isExecutableFile(atPath: p) { return p }
            }
        }
        return nil
    }

    /// Login state of the user's own Claude Code (`claude auth status --json`). Read-only: JARVIS never logs in itself.
    /// Returns nil if the CLI is missing; plan is e.g. "pro", "max", or "console" for API billing.
    public static func accountStatus() -> (installed: Bool, loggedIn: Bool, plan: String?) {
        guard let claude = claudePath() else { return (false, false, nil) }
        let env = cleanEnvironment(toolDir: (Paths.executable as NSString).deletingLastPathComponent)
        guard let r = try? runProcess(claude, ["auth", "status", "--json"], timeout: 15, environment: env),
              let o = try? JSONSerialization.jsonObject(with: Data(r.out.utf8)) as? [String: Any] else { return (true, false, nil) }
        let logged = o["loggedIn"] as? Bool ?? false
        let plan = (o["subscriptionType"] as? String) ?? (o["planTier"] as? String)
            ?? ((o["authMethod"] as? String).map { $0.contains("claude") ? "abbonamento" : "console" })
        return (true, logged, plan)
    }

    static func cleanEnvironment(toolDir: String) -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        // When launched from inside Claude Code, drop the host session's variables:
        // the child must use the user's own login, not the parent's proxy. No API keys either.
        for k in env.keys where k.hasPrefix("CLAUDE_CODE_") || k.hasPrefix("CLAUDE_AGENT_SDK") || k.hasPrefix("ANTHROPIC_") || k == "CLAUDECODE" {
            env.removeValue(forKey: k)
        }
        env["PATH"] = "\(toolDir):/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
        env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"     // don't load CLAUDE.md files: fewer tokens
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        env["DISABLE_AUTOUPDATER"] = "1"
        env["JARVIS_AGENT"] = "1"                        // `jarvis confirm` refuses to run for the model
        return env
    }

    // MARK: lifecycle

    public var isRunning: Bool { proc?.isRunning == true }

    public func start(resume: String? = nil) throws {
        guard let claude = Self.claudePath() else {
            throw ToolError("CLI claude non trovata: installala con il comando ufficiale e fai il login.")
        }
        let toolDir = (Paths.executable as NSString).deletingLastPathComponent
        var args = [
            "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--model", tier.model, "--effort", effort,
            "--system-prompt", Prompt.system,
            "--tools", ProcessInfo.processInfo.environment["JARVIS_TOOLS"] ?? (vision ? "Bash,Read" : "Bash"),
            "--allowedTools", "Bash(jarvis:*)",
            "--disallowedTools", "Bash(jarvis confirm:*)", "Bash(jarvis cancel:*)",
            "--permission-mode", "dontAsk",
            "--strict-mcp-config",
        ]
        if let resume { args += ["--resume", resume] }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: claude)
        p.arguments = args
        p.environment = Self.cleanEnvironment(toolDir: toolDir)
        p.currentDirectoryURL = Paths.support
        let inPipe = Pipe(), outPipe = Pipe(), errPipe = Pipe()
        p.standardInput = inPipe
        p.standardOutput = outPipe
        p.standardError = errPipe
        outPipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            self?.q.async { self?.consume(d) }
        }
        errPipe.fileHandleForReading.readabilityHandler = { h in
            let d = h.availableData
            if !d.isEmpty { try? (String(decoding: d, as: UTF8.self)).appendLine(to: Paths.file("claude.err.log")) }
        }
        p.terminationHandler = { [weak self] proc in
            self?.q.async {
                // only the live process may end a turn (an old one being recycled must not)
                guard let self, self.onEvent != nil, self.proc === proc else { return }
                self.current.isError = true
                if self.current.text.isEmpty { self.current.text = "Il modulo \(self.tier.rawValue) si è interrotto (codice \(proc.terminationStatus))." }
                self.finish()
            }
        }
        try p.run()
        proc = p
        stdin = inPipe.fileHandleForWriting
        turns = 0
        lastTotalCost = 0
        resolvedModel = nil
        lastUse = Date()
    }

    public func stop() {
        let old = proc
        proc = nil
        if let p = old, p.isRunning { p.terminate() }
        stdin = nil
        sessionID = nil
    }

    // MARK: sending

    /// Sends one user turn. Events are delivered on a background queue; `.done` closes the turn.
    public func send(_ text: String, onEvent: @escaping (BridgeEvent) -> Void) {
        q.async { [self] in
            if isRunning, turns >= Self.maxTurns || Date().timeIntervalSince(lastUse) > Self.idleReset { stop() }
            do { if !isRunning { try start() } } catch {
                onEvent(.done(TurnResult(text: "\(error)", tier: tier, isError: true))); return
            }
            self.onEvent = onEvent
            current = TurnResult(tier: tier)
            started = Date()
            turns += 1
            lastUse = Date()
            let stamped = "(ora attuale: \(When.fmt(Date())))\n\(text)"
            let msg: [String: Any] = ["type": "user", "message": ["role": "user", "content": [["type": "text", "text": stamped]]]]
            guard let d = try? JSONSerialization.data(withJSONObject: msg) else {
                self.onEvent = nil
                onEvent(.done(TurnResult(text: "Messaggio non codificabile.", tier: tier, isError: true))); return
            }
            onEvent(.thinking(tier))
            do { try stdin?.write(contentsOf: d + Data([0x0A])) } catch {
                // the claude process died between turns: report it instead of crashing on a broken pipe
                self.onEvent = nil
                stop()
                onEvent(.done(TurnResult(text: "Il modulo \(tier.rawValue) non risponde: riprova.", tier: tier, isError: true)))
            }
        }
    }

    public func sendSync(_ text: String, timeout: TimeInterval = 180, onEvent: ((BridgeEvent) -> Void)? = nil) -> TurnResult {
        let sem = DispatchSemaphore(value: 0)
        var result = TurnResult(text: "Timeout", tier: tier, isError: true)
        send(text) { ev in
            onEvent?(ev)
            if case .done(let r) = ev { result = r; sem.signal() }
        }
        _ = sem.wait(timeout: .now() + timeout)
        return result
    }

    // MARK: parsing stream-json

    private func consume(_ d: Data) {
        guard !d.isEmpty else { return }
        buffer.append(d)
        while let nl = buffer.firstIndex(of: 0x0A) {
            let line = buffer.subdata(in: buffer.startIndex..<nl)
            buffer.removeSubrange(buffer.startIndex...nl)
            if let obj = try? JSONSerialization.jsonObject(with: line) as? [String: Any] { handle(obj) }
        }
    }

    private func handle(_ o: [String: Any]) {
        let type = o["type"] as? String
        if let sid = o["session_id"] as? String { sessionID = sid }
        switch type {
        case "system":
            if o["subtype"] as? String == "init", let m = o["model"] as? String { resolvedModel = m }
        case "assistant":
            let content = ((o["message"] as? [String: Any])?["content"] as? [[String: Any]]) ?? []
            for b in content {
                if b["type"] as? String == "text", let t = b["text"] as? String, !t.isEmpty { onEvent?(.text(t)) }
                if b["type"] as? String == "tool_use" {
                    let cmd = ((b["input"] as? [String: Any])?["command"] as? String) ?? (b["name"] as? String ?? "")
                    onEvent?(.tool(cmd))
                }
            }
        case "user":
            let content = ((o["message"] as? [String: Any])?["content"] as? [[String: Any]]) ?? []
            for b in content where b["type"] as? String == "tool_result" {
                let text: String
                if let s = b["content"] as? String { text = s }
                else { text = ((b["content"] as? [[String: Any]]) ?? []).compactMap { $0["text"] as? String }.joined(separator: "\n") }
                onEvent?(.toolResult(text))
                if let r = text.range(of: Gate.marker) {
                    let line = text[r.lowerBound...].split(separator: "\n").first.map(String.init) ?? text
                    current.pendingConfirm = line
                    onEvent?(.confirmNeeded(line))
                }
            }
        case "result":
            current.text = (o["result"] as? String) ?? current.text
            // defensive: drop an echoed "(ora attuale: ...)" anywhere, or a leading "[mar 17 nov 20:09]"
            current.text = current.text.replacing(/\s*\(ora attuale:[^)]*\)\s*/) { _ in " " }
                .replacing(/^\s*\[[^\]]{3,30}\]\s*/) { _ in "" }
                .trimmingCharacters(in: .whitespacesAndNewlines)
            current.isError = (o["is_error"] as? Bool) ?? false
            // total_cost_usd is cumulative for the process: keep only this turn's share
            let total = (o["total_cost_usd"] as? Double) ?? lastTotalCost
            current.costUSD = max(0, total - lastTotalCost)
            lastTotalCost = total
            current.durationMs = (o["duration_ms"] as? Int) ?? Int(Date().timeIntervalSince(started) * 1000)
            if let u = o["usage"] as? [String: Any] {
                current.inputTokens = u["input_tokens"] as? Int ?? 0
                current.outputTokens = u["output_tokens"] as? Int ?? 0
                current.cacheRead = u["cache_read_input_tokens"] as? Int ?? 0
                current.cacheWrite = u["cache_creation_input_tokens"] as? Int ?? 0
            }
            finish()
        default:
            break
        }
    }

    private func finish() {
        let cb = onEvent
        onEvent = nil
        if cb != nil {
            TurnLog.record(current, model: tier.model, resolvedModel: resolvedModel, effort: effort, vision: vision, sessionTurn: turns)
        }
        cb?(.done(current))
    }
}

/// Router + sessions: the single "brain" API used by the CLI chat and, later, the HUD app.
public final class JarvisBrain {
    public var sessions: [String: ClaudeSession] { lock.lock(); defer { lock.unlock() }; return _sessions }
    private var _sessions: [String: ClaudeSession] = [:]
    private let lock = NSLock()   // sessions are touched from the main thread and the work queue
    /// nil = automatic routing (Haiku by default, escalation by keywords)
    public var preferredTier: Tier? { didSet { if oldValue != preferredTier { shutdown(); prewarm() } } }
    /// nil = automatic effort per tier (haiku low, sonnet medium, opus high)
    public var effort: String? { didSet { if oldValue != effort { shutdown(); prewarm() } } }
    public static let efforts = ["low", "medium", "high", "xhigh", "max"]
    /// Outcome of a yes/no handled locally, told to Claude on the next turn so it doesn't think it's still pending.
    private var outcomeNote: String?

    public func noteOutcome(_ s: String) { outcomeNote = s }

    public init(preferredTier: Tier? = nil, effort: String? = nil) {
        self.preferredTier = preferredTier
        self.effort = effort
    }

    public var defaultTier: Tier { preferredTier ?? .haiku }

    public func session(_ t: Tier, vision: Bool = false) -> ClaudeSession {
        let key = t.rawValue + (vision ? "+vision" : "")
        lock.lock(); defer { lock.unlock() }
        if let s = _sessions[key] { return s }
        let s = ClaudeSession(tier: t, effort: effort, vision: vision)
        _sessions[key] = s
        return s
    }

    /// Starts the Haiku process in advance so the first command doesn't pay the startup cost.
    public func prewarm() { try? session(defaultTier).start() }

    public func handle(_ text: String, onEvent: @escaping (BridgeEvent) -> Void) {
        let route = Router.route(text, hasPending: Gate.latestID != nil)
        // Safety: a pending critical action can be confirmed only by the message right after it.
        // Anything else discards it, so a later "sì" can never confirm a stale request.
        if case .local(let argv, _) = route, argv.first == "confirm" || argv.first == "cancel" {} else { Gate.cancelAll() }
        switch route {
        case .answer(let s):
            onEvent(.done(TurnResult(text: s, local: true)))
        case .local(let argv, let reply):
            let (out, code) = CLI.run(argv)
            if argv.first == "confirm" || argv.first == "cancel" { outcomeNote = out }
            onEvent(.tool("jarvis " + argv.joined(separator: " ")))
            var r = TurnResult(text: reply ?? out, isError: code != 0, local: true)
            if out.contains(Gate.marker) { r.pendingConfirm = out }
            onEvent(.done(r))
        case .model(let routed, let t):
            // explicit "/opus ..." always wins; otherwise a fixed preferred model overrides the router
            let explicit = text.trimmingCharacters(in: .whitespaces).hasPrefix("/")
            let tier = explicit ? routed : (preferredTier ?? routed)
            var msg = t
            if let n = outcomeNote { msg = "(esito della conferma precedente: \(n))\n" + t; outcomeNote = nil }
            session(tier, vision: Router.needsVision(t)).send(msg, onEvent: onEvent)
        }
    }

    public func shutdown() {
        lock.lock(); let all = _sessions.values; _sessions = [:]; lock.unlock()
        all.forEach { $0.stop() }
    }
}

extension String {
    func appendLine(to url: URL) throws {
        let s = self.hasSuffix("\n") ? self : self + "\n"
        if let h = try? FileHandle(forWritingTo: url) {
            defer { try? h.close() }
            _ = try h.seekToEnd(); try h.write(contentsOf: Data(s.utf8))
        } else {
            try s.write(to: url, atomically: true, encoding: .utf8)
        }
    }
}
