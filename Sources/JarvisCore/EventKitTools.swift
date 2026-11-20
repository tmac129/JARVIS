import EventKit
import Foundation

/// Calendar + Reminders via EventKit: fast, and expands recurring events correctly.
enum EK {
    static let store = EKEventStore()

    static func ensure(_ type: EKEntityType, write: Bool = false) throws {
        let st = EKEventStore.authorizationStatus(for: type)
        if st == .fullAccess || (write && st == .writeOnly) { return }
        if st == .notDetermined || (st == .writeOnly && !write) {
            let sem = DispatchSemaphore(value: 0)
            var ok = false
            let done: (Bool, Error?) -> Void = { granted, _ in ok = granted; sem.signal() }
            if type == .event { store.requestFullAccessToEvents(completion: done) }
            else { store.requestFullAccessToReminders(completion: done) }
            _ = sem.wait(timeout: .now() + 60)
            if ok { return }
        }
        let name = type == .event ? "Calendari" : "Promemoria"
        throw ToolError("Accesso a \(name) negato: abilitalo in Impostazioni > Privacy e sicurezza > \(name) (accesso completo).")
    }

    static func calendar(named name: String?, for type: EKEntityType) throws -> EKCalendar {
        let cals = store.calendars(for: type).filter { $0.allowsContentModifications }
        if let n = name?.lowercased(), !n.isEmpty {
            if let c = cals.first(where: { $0.title.lowercased() == n }) ?? cals.first(where: { $0.title.lowercased().contains(n) }) {
                return c
            }
            throw ToolError("\(type == .event ? "Calendario" : "Lista") \"\(name!)\" non trovato. Disponibili: \(cals.map(\.title).joined(separator: ", "))")
        }
        let def = type == .event ? store.defaultCalendarForNewEvents : store.defaultCalendarForNewReminders()
        guard let c = def ?? cals.first else { throw ToolError("Nessun calendario scrivibile.") }
        return c
    }
}

enum CalendarTool {
    static func run(_ a: [String], confirmed: Bool, raw: [String]) throws -> String {
        let sub = a.first ?? "list"
        let args = Args(Array(a.dropFirst()), flags: ["all"])
        switch sub {
        case "list", "oggi", "domani", "settimana":
            try EK.ensure(.event)
            let spec = sub == "list" ? (args.pos.joined(separator: " ").isEmpty ? "oggi" : args.pos.joined(separator: " ")) : sub
            let (start, end, label) = try range(spec)
            let pred = EK.store.predicateForEvents(withStart: start, end: end, calendars: nil)
            let evs = EK.store.events(matching: pred).sorted { $0.startDate < $1.startDate }
            if evs.isEmpty { return "Nessun impegno \(label)." }
            let refs = Refs.assign("e", evs.map { "\($0.calendarItemIdentifier)|\($0.startDate.timeIntervalSince1970)" })
            let multiDay = Calendar.current.dateComponents([.day], from: start, to: end).day ?? 1 > 1
            let rows = zip(refs, evs).prefix(40).map { ref, e -> String in
                let when: String
                if e.isAllDay { when = multiDay ? When.fmt(e.startDate, time: false) + " tutto il giorno" : "tutto il giorno" }
                else { when = (multiDay ? When.fmt(e.startDate) : When.hm(e.startDate)) + "-" + When.hm(e.endDate) }
                var s = "[\(ref)] \(when) \(e.title ?? "(senza titolo)")"
                if let l = e.location, !l.isEmpty { s += " @\(l)" }
                s += " (\(e.calendar.title))"
                return s
            }
            return "\(evs.count) impegni \(label):\n" + rows.joined(separator: "\n")
        case "cals", "calendars":
            try EK.ensure(.event)
            return EK.store.calendars(for: .event).map { $0.title + ($0.allowsContentModifications ? "" : " (sola lettura)") }.joined(separator: ", ")
        case "add":
            try EK.ensure(.event, write: true)
            guard let title = args.o("title", "titolo") ?? (args.pos.isEmpty ? nil : args.pos.joined(separator: " ")) else {
                throw ToolError("uso: cal add --title T --start DATA [--end DATA|--min 60]")
            }
            guard let s = args.o("start", "inizio"), let (start, hasTime) = When.parse(s) else {
                throw ToolError("data di inizio mancante o non valida (es. --start \"domani 15:00\")")
            }
            let ev = EKEvent(eventStore: EK.store)
            ev.title = title
            ev.calendar = try EK.calendar(named: args.o("cal", "calendar"), for: .event)
            ev.startDate = start
            if !hasTime && args.o("end") == nil {
                ev.isAllDay = true
                ev.endDate = start
            } else if let e = args.o("end", "fine"), let (end, _) = When.parse(e) {
                ev.endDate = end > start ? end : Calendar.current.date(bySettingHour: Calendar.current.component(.hour, from: end), minute: Calendar.current.component(.minute, from: end), second: 0, of: start)!
            } else {
                ev.endDate = start.addingTimeInterval((Double(args.o("min", "minutes") ?? "60") ?? 60) * 60)
            }
            if let l = args.o("loc", "location", "luogo") { ev.location = l }
            if let n = args.o("notes", "note") { ev.notes = n }
            if let al = args.o("alert", "avviso"), let m = Double(al) { ev.addAlarm(EKAlarm(relativeOffset: -m * 60)) }
            try EK.store.save(ev, span: .thisEvent, commit: true)
            let when = ev.isAllDay ? When.fmt(start, time: false) + " (tutto il giorno)" : "\(When.fmt(start))-\(When.hm(ev.endDate))"
            ActionLog.add("CALENDAR_SYNC", "Creato evento \"\(title)\" \(when)")
            return "Creato \"\(title)\" \(when) in \(ev.calendar.title)."
        case "move", "sposta":
            try EK.ensure(.event)
            let ev = try find(args.pos.first)
            guard let s = args.o("start", "inizio"), let (newStart, _) = When.parse(s) else {
                throw ToolError("uso: cal move <e1> --start DATA [--end DATA]")
            }
            let dur = ev.endDate.timeIntervalSince(ev.startDate)
            ev.startDate = newStart
            if let e = args.o("end", "fine"), let (end, _) = When.parse(e) { ev.endDate = end } else { ev.endDate = newStart.addingTimeInterval(dur) }
            try EK.store.save(ev, span: .thisEvent, commit: true)
            ActionLog.add("CALENDAR_SYNC", "Spostato \"\(ev.title ?? "")\" a \(When.fmt(newStart))")
            return "Spostato \"\(ev.title ?? "")\" a \(When.fmt(newStart))-\(When.hm(ev.endDate))."
        case "delete", "elimina":
            try EK.ensure(.event)
            let ev = try find(args.pos.first)
            let desc = "\"\(ev.title ?? "")\" \(When.fmt(ev.startDate))"
            if !confirmed { return Gate.request("Eliminare l'evento \(desc)", argv: raw) }
            try EK.store.remove(ev, span: .thisEvent, commit: true)
            ActionLog.add("CALENDAR_SYNC", "Eliminato evento \(desc)")
            return "Eliminato \(desc)."
        default:
            throw ToolError("sottocomando cal sconosciuto: \(sub)")
        }
    }

    static func range(_ spec: String) throws -> (Date, Date, String) {
        let cal = Calendar.current
        let today = cal.startOfDay(for: Date())
        switch spec.lowercased() {
        case "oggi", "today": return (today, cal.date(byAdding: .day, value: 1, to: today)!, "oggi")
        case "domani", "tomorrow":
            let d = cal.date(byAdding: .day, value: 1, to: today)!
            return (d, cal.date(byAdding: .day, value: 1, to: d)!, "domani")
        case "settimana", "week", "7":
            return (today, cal.date(byAdding: .day, value: 7, to: today)!, "nei prossimi 7 giorni")
        case "mese", "month":
            return (today, cal.date(byAdding: .day, value: 31, to: today)!, "nei prossimi 30 giorni")
        default:
            guard let (d, _) = When.parse(spec) else { throw ToolError("periodo non valido: \(spec)") }
            let s = cal.startOfDay(for: d)
            return (s, cal.date(byAdding: .day, value: 1, to: s)!, When.fmt(s, time: false))
        }
    }

    static func find(_ ref: String?) throws -> EKEvent {
        guard let r = ref, let v = Refs.resolve(r) else { throw ToolError("riferimento evento mancante: usa prima `cal list` e poi [eN]") }
        let parts = v.split(separator: "|")
        guard parts.count == 2, let ts = Double(parts[1]) else { throw ToolError("riferimento non valido") }
        let start = Date(timeIntervalSince1970: ts)
        let pred = EK.store.predicateForEvents(withStart: start.addingTimeInterval(-60), end: start.addingTimeInterval(86400), calendars: nil)
        if let ev = EK.store.events(matching: pred).first(where: { $0.calendarItemIdentifier == parts[0] && abs($0.startDate.timeIntervalSince(start)) < 60 }) {
            return ev
        }
        throw ToolError("evento non trovato (forse già modificato): rifai `cal list`")
    }
}

enum RemindersTool {
    static func fetch(_ pred: NSPredicate) -> [EKReminder] {
        let sem = DispatchSemaphore(value: 0)
        var res: [EKReminder] = []
        EK.store.fetchReminders(matching: pred) { r in res = r ?? []; sem.signal() }
        _ = sem.wait(timeout: .now() + 20)
        return res
    }

    static func run(_ a: [String], confirmed: Bool, raw: [String]) throws -> String {
        let sub = a.first ?? "list"
        let args = Args(Array(a.dropFirst()), flags: ["all"])
        try EK.ensure(.reminder)
        switch sub {
        case "add":
            guard let title = args.o("title", "titolo") ?? (args.pos.isEmpty ? nil : args.pos.joined(separator: " ")) else {
                throw ToolError("uso: rem add --title T [--due DATA] [--prio alta|media|bassa] [--list L]")
            }
            let r = EKReminder(eventStore: EK.store)
            r.title = title
            r.calendar = try EK.calendar(named: args.o("list", "lista"), for: .reminder)
            var dueText = ""
            if let d = args.o("due", "quando", "scadenza") {
                guard let (date, hasTime) = When.parse(d, futureOnly: true) else { throw ToolError("data non valida: \(d)") }
                var comps = Calendar.current.dateComponents([.year, .month, .day], from: date)
                if hasTime {
                    comps.hour = Calendar.current.component(.hour, from: date)
                    comps.minute = Calendar.current.component(.minute, from: date)
                    r.addAlarm(EKAlarm(absoluteDate: date))
                }
                r.dueDateComponents = comps
                dueText = " per " + When.fmt(date, time: hasTime)
            }
            switch (args.o("prio", "priority", "priorita") ?? "").lowercased() {
            case "alta", "high", "1": r.priority = 1
            case "media", "medium", "5": r.priority = 5
            case "bassa", "low", "9": r.priority = 9
            default: break
            }
            if let n = args.o("notes", "note") { r.notes = n }
            try EK.store.save(r, commit: true)
            ActionLog.add("REMINDERS", "Promemoria \"\(title)\"\(dueText)")
            return "Promemoria \"\(title)\"\(dueText) aggiunto in \(r.calendar.title)."
        case "list":
            let cals: [EKCalendar]? = try args.o("list", "lista").map { [try EK.calendar(named: $0, for: .reminder)] }
            var items = fetch(EK.store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: cals))
            items.sort { a, b in
                let da = a.dueDateComponents?.date ?? .distantFuture, db = b.dueDateComponents?.date ?? .distantFuture
                return da == db ? (a.title ?? "") < (b.title ?? "") : da < db
            }
            if items.isEmpty { return "Nessun promemoria da completare." }
            let shown = Array(items.prefix(args.has("all") ? 100 : 25))
            let refs = Refs.assign("r", shown.map { $0.calendarItemIdentifier })
            let rows = zip(refs, shown).map { ref, r -> String in
                var s = "[\(ref)] \(r.title ?? "")"
                if let c = r.dueDateComponents, let d = Calendar.current.date(from: c) { s += " (\(When.fmt(d, time: c.hour != nil)))" }
                if r.priority == 1 { s += " !" }
                return s + " {\(r.calendar.title)}"
            }
            return "\(items.count) da fare:\n" + rows.joined(separator: "\n")
        case "lists":
            return EK.store.calendars(for: .reminder).map(\.title).joined(separator: ", ")
        case "done", "fatto":
            let q = args.pos.joined(separator: " ")
            guard !q.isEmpty else { throw ToolError("uso: rem done <r1|testo>") }
            let target: EKReminder
            if let id = Refs.resolve(q), let r = EK.store.calendarItem(withIdentifier: id) as? EKReminder {
                target = r
            } else {
                let items = fetch(EK.store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: nil))
                let matches = items.filter { ($0.title ?? "").localizedCaseInsensitiveContains(q) }
                guard matches.count == 1 else {
                    throw ToolError(matches.isEmpty ? "nessun promemoria contiene \"\(q)\"" :
                        "più promemoria corrispondono: \(matches.prefix(5).compactMap(\.title).joined(separator: "; ")). Usa `rem list` e [rN].")
                }
                target = matches[0]
            }
            target.isCompleted = true
            try EK.store.save(target, commit: true)
            ActionLog.add("REMINDERS", "Completato \"\(target.title ?? "")\"")
            return "Completato \"\(target.title ?? "")\"."
        default:
            throw ToolError("sottocomando rem sconosciuto: \(sub)")
        }
    }
}
