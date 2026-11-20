import Foundation

/// Optional capabilities the user can switch off from the menu. Core commands (clock, system, now) are always on.
/// State lives in ~/Library/Application Support/JARVIS/modules.json, shared by the app and every `jarvis` process,
/// so it survives restarts and applies to commands run by Claude too.
public enum Module: String, CaseIterable, Codable {
    case mail, calendar, reminders, whatsapp, notes, files, music, news, screen

    public var label: String {
        switch self {
        case .mail: return "Mail e contatti"
        case .calendar: return "Calendario"
        case .reminders: return "Promemoria"
        case .whatsapp: return "WhatsApp"
        case .notes: return "Note"
        case .files: return "File e documenti"
        case .music: return "Musica"
        case .news: return "Notizie"
        case .screen: return "Schermo"
        }
    }

    /// CLI command names (with aliases) that belong to this module.
    var commands: Set<String> {
        switch self {
        case .mail: return ["mail", "contact", "contatto"]
        case .calendar: return ["cal", "calendar"]
        case .reminders: return ["rem", "reminder", "reminders"]
        case .whatsapp: return ["wa", "whatsapp"]
        case .notes: return ["note", "notes"]
        case .files: return ["file", "files", "doc", "docs"]
        case .music: return ["music", "musica"]
        case .news: return ["news", "notizie"]
        case .screen: return ["screen", "schermo"]
        }
    }

    public static func forCommand(_ cmd: String) -> Module? { allCases.first { $0.commands.contains(cmd) } }
}

public enum Modules {
    struct State: Codable { var disabled: [String] = [] }
    static let file = "modules.json"

    static var disabled: Set<String> { Set((Store.load(file, State.self) ?? State()).disabled) }

    public static func isEnabled(_ m: Module) -> Bool { !disabled.contains(m.rawValue) }

    public static var enabled: [Module] { let d = disabled; return Module.allCases.filter { !d.contains($0.rawValue) } }

    public static func set(_ m: Module, enabled on: Bool) {
        var d = disabled
        if on { d.remove(m.rawValue) } else { d.insert(m.rawValue) }
        Store.save(file, State(disabled: Module.allCases.map(\.rawValue).filter { d.contains($0) }))
    }

    public static func disabledMessage(_ m: Module) -> String {
        "il modulo \(m.label) è disattivato: riattivalo dal menu di JARVIS > Moduli"
    }
}
