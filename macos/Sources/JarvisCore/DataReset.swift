import Darwin
import Foundation

/// `jarvis reset`: deletes everything JARVIS stored on this Mac (preferences, logs, chat history,
/// phone token, alarms and timers). Only from an interactive terminal: never from the model, the HUD
/// or the phone, so it is handled in the `jarvis` binary and not in `CLI.run`.
public enum DataReset {
    /// What gets removed, shown before asking for confirmation.
    public static var summary: String {
        let alarms = alarmPlists().count
        return """
        Verranno eliminati:
          - la cartella dati \(Paths.support.path)
            (preferenze, moduli, log delle azioni e dei turni, cronologia, token del telefono, stato)
          - \(alarms) sveglie programmate (launchd) e i timer in corso
        Restano: l'app in /Applications, il comando jarvis, l'accesso a Claude Code (claude auth logout)
        e i permessi di macOS (Impostazioni di Sistema > Privacy e sicurezza).
        """
    }

    static func alarmPlists() -> [URL] {
        let dir = AlarmTool.agentsDir
        let names = (try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []
        return names.filter { $0.hasPrefix("com.jarvis.alarm.") && $0.hasSuffix(".plist") }.map { dir.appendingPathComponent($0) }
    }

    /// Removes alarms, stops timers, then deletes the data folder. Returns a short report.
    public static func run() -> String {
        var removed = 0
        for url in alarmPlists() {
            let label = url.deletingPathExtension().lastPathComponent
            _ = try? runProcess("/bin/launchctl", ["bootout", "gui/\(getuid())/\(label)"])
            do { try FileManager.default.removeItem(at: url); removed += 1 } catch {}
        }
        struct T: Codable { let pid: Int32 }
        for t in Store.load("timers.json", [T].self) ?? [] where t.pid > 0 { kill(t.pid, SIGTERM) }
        let fm = FileManager.default
        let items = (try? fm.contentsOfDirectory(at: Paths.support, includingPropertiesForKeys: nil)) ?? []
        var failed: [String] = []
        for u in items {
            do { try fm.removeItem(at: u) } catch { failed.append(u.lastPathComponent) }
        }
        try? fm.removeItem(at: Paths.support)
        var out = "Dati di JARVIS eliminati (\(items.count) file o cartelle, \(removed) sveglie)."
        if !failed.isEmpty { out += "\nNon eliminati: \(failed.joined(separator: ", "))" }
        return out
    }
}
