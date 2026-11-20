import Foundation

/// Per-turn token log, local only: one JSON line per Claude turn in
/// ~/Library/Application Support/JARVIS/turns.jsonl. Nothing is sent over the network.
/// Written from ClaudeSession, so turns from both the HUD app and `jarvis chat` are counted.
/// Disable with JARVIS_TURN_LOG=0.
public enum TurnLog {
    public static var url: URL { Paths.file("turns.jsonl") }
    static var enabled: Bool { ProcessInfo.processInfo.environment["JARVIS_TURN_LOG"] != "0" }
    private static let lock = NSLock()

    /// `resolvedModel` is the model ID reported by the CLI's init event (what the alias actually resolved to).
    static func record(_ r: TurnResult, model: String, resolvedModel: String?, effort: String, vision: Bool, sessionTurn: Int) {
        guard enabled else { return }
        var line: [String: Any] = [
            "ts": ISO8601DateFormatter().string(from: Date()),
            "tier": r.tier.rawValue,
            "model": model,
            "effort": effort,
            "vision": vision,
            "input_tokens": r.inputTokens,
            "output_tokens": r.outputTokens,
            "cache_read_tokens": r.cacheRead,
            "cache_write_tokens": r.cacheWrite,
            "cost_usd": r.costUSD,
            "duration_ms": r.durationMs,
            "session_turn": sessionTurn,
            "max_turns": ClaudeSession.maxTurns,
            "is_error": r.isError,
        ]
        if let m = resolvedModel { line["resolved_model"] = m }
        guard let d = try? JSONSerialization.data(withJSONObject: line, options: [.sortedKeys]),
              let s = String(data: d, encoding: .utf8) else { return }
        lock.lock(); defer { lock.unlock() }
        try? s.appendLine(to: url)
    }
}

/// Caps the output of a `jarvis` command before it goes back to the model (applied only when
/// JARVIS_AGENT is set, i.e. the command was run by Claude). Limit in bytes: JARVIS_TOOL_OUTPUT_MAX, default 6 KB; 0 = no limit.
public enum OutputCap {
    public static let defaultBytes = 6 * 1024

    public static var limit: Int {
        guard let v = ProcessInfo.processInfo.environment["JARVIS_TOOL_OUTPUT_MAX"], let n = Int(v), n >= 0 else { return defaultBytes }
        return n
    }

    /// Keeps the head of `s` within `limit` UTF-8 bytes (cut on a line break when one is close),
    /// then appends a truncation notice. A pending-confirmation line is always kept.
    public static func apply(_ s: String, limit: Int = OutputCap.limit) -> String {
        let total = s.utf8.count
        guard limit > 0, total > limit else { return s }
        var head = ""
        var used = 0
        for ch in s {
            let n = String(ch).utf8.count
            if used + n > limit { break }
            head.append(ch); used += n
        }
        // prefer ending on a whole line if that loses at most a quarter of the budget
        if let nl = head.lastIndex(of: "\n"), head[..<nl].utf8.count >= limit * 3 / 4 {
            head = String(head[..<nl])
        }
        let dropped = total - head.utf8.count
        var out = head + "\n[OUTPUT TRONCATO: mostrati \(head.utf8.count) di \(total) byte, omessi \(dropped). Restringi la richiesta (meno elementi, --pages, filtri) se serve il resto.]"
        if !head.contains(Gate.marker), let r = s.range(of: Gate.marker) {
            let line = s[r.lowerBound...].split(separator: "\n").first.map(String.init) ?? Gate.marker
            out += "\n" + line
        }
        return out
    }
}
