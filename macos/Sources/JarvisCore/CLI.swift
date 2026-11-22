import Foundation

/// Single entry point for every tool. Used by the `jarvis` binary (called by Claude via Bash)
/// and in-process by the app/router fast path.
public enum CLI {
    public static let usage = """
    jarvis mail unread [N] | search <testo> [N] | read <m1> | draft|send --to a@b[,c] --subject S --body B [--attach PATH|f1]
    jarvis contact <nome>
    jarvis cal list [oggi|domani|settimana|DATA] | add --title T --start DATA [--end DATA|--min 60] [--loc L] [--notes N] [--cal NOME] | move <e1> --start DATA | delete <e1> | cals
    jarvis rem add --title T [--due DATA] [--prio alta|media|bassa] [--list L] | list [--list L] | done <r1|testo> | lists
    jarvis alarm set HH:MM [--date DATA] [--label L] [--daily] | list | cancel <a1>
    jarvis timer <20m|90s|1h30m> [--label L] | timer list | timer cancel [t1]
    jarvis file find <nome> [--ext pdf] [--in DIR] [--days N] [--dirs] | ls DIR [--ext pdf] | move|copy <SRC...> --to DIR | rename <SRC> <NOME> | mkdir DIR | open|reveal <SRC> | trash <SRC...>
    jarvis wa unread | chats [N] | read <nome|w1> [--n 15] | send --to <nome|numero|w1> --text T   (WhatsApp)
    jarvis sys open|quit <app> | apps | volume <0-100|su|giu|muto|attiva> | brightness <0-100|su|giu> | wifi on|off | dark on|off | lock | sleep | screenshot | battery
    jarvis music play [brano|artista] | pause | next | prev | now   (Spotify)
    jarvis note add --title T [--body B] [--folder F] | list | search <testo> | read <nt1> | append <nt1> --text T
    jarvis doc read <f1|percorso> [--pages 1-5]          (PDF, Word, RTF, testo, immagini)
    jarvis screen [--full]                               (cattura la finestra che l'utente sta guardando)
    jarvis now
    jarvis pending | confirm [p1] | cancel [p1]      (solo interfaccia utente)
    jarvis reset                                     (solo interfaccia utente, da terminale: elimina tutti i dati locali)
    jarvis ask "<testo>" | chat                      (test del bridge Claude)
    """

    public static func run(_ argv: [String], confirmed: Bool = false) -> (String, Int32) {
        guard let cmd = argv.first else { return (usage, 0) }
        let rest = Array(argv.dropFirst())
        if let m = Module.forCommand(cmd), !Modules.isEnabled(m) { return ("ERRORE: \(Modules.disabledMessage(m))", 1) }
        do {
            let out: String
            switch cmd {
            case "mail": out = try MailTool.run(rest, confirmed: confirmed, raw: argv)
            case "contact", "contatto": out = try ContactTool.run(rest)
            case "cal", "calendar": out = try CalendarTool.run(rest, confirmed: confirmed, raw: argv)
            case "rem", "reminder", "reminders": out = try RemindersTool.run(rest, confirmed: confirmed, raw: argv)
            case "alarm", "sveglia": out = try AlarmTool.alarm(rest, confirmed: confirmed, raw: argv)
            case "timer", "timers": out = try AlarmTool.timer(cmd == "timers" ? ["list"] : rest)
            case "file", "files": out = try FileTool.run(rest, confirmed: confirmed, raw: argv)
            case "wa", "whatsapp": out = try WhatsAppTool.run(rest, confirmed: confirmed, raw: argv)
            case "sys", "system": out = try SysTool.run(rest, confirmed: confirmed, raw: argv)
            case "music", "musica": out = try MusicTool.run(rest)
            case "note", "notes": out = try NotesTool.run(rest)
            case "doc", "docs": out = try DocTool.run(rest)
            case "screen", "schermo": out = try ScreenTool.run(rest)
            case "now", "ora": out = When.fmt(Date())
            case "_dbinfo": out = try DBInfo.run(rest.first ?? "mail")
            case "_account":   // diagnostics: what the menu shows (no email, no tokens)
                let a = ClaudeSession.accountStatus()
                out = !a.installed ? "Claude Code non installato" : a.loggedIn ? "Account Claude: \(a.plan ?? "collegato")" : "Account Claude: non collegato"
            case "pending": out = Gate.list()
            case "confirm": return Gate.confirm(rest.first)
            case "cancel": out = Gate.cancel(rest.first)
            case "help", "-h", "--help": out = usage
            default: throw ToolError("comando sconosciuto: \(cmd)\n\(usage)")
            }
            return (out, 0)
        } catch let e as ToolError {
            return ("ERRORE: \(e.description)", 1)
        } catch {
            return ("ERRORE: \(error.localizedDescription)", 1)
        }
    }
}
