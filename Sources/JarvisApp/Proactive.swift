import EventKit
import Foundation
import IOKit.ps
import JarvisCore
import UserNotifications

/// J.A.R.V.I.S. speaking first: morning briefing, meetings in 15 minutes, low battery.
/// One check per minute, a few cheap local queries, no tokens unless the briefing runs.
final class Proactive {
    var onAlert: ((String, String) -> Void)?    // (module, text) to show/speak
    var onBriefing: (() -> Void)?
    private var timer: Timer?
    private let store = EKEventStore()
    private var alerted = Set<String>()
    private var battWarned: Int = 100
    private let prefs = UserDefaults.standard

    var meetings: Bool { get { prefs.object(forKey: "proMeetings") as? Bool ?? true } set { prefs.set(newValue, forKey: "proMeetings") } }
    var battery: Bool { get { prefs.object(forKey: "proBattery") as? Bool ?? true } set { prefs.set(newValue, forKey: "proBattery") } }
    var briefingAuto: Bool { get { prefs.object(forKey: "proBriefing") as? Bool ?? true } set { prefs.set(newValue, forKey: "proBriefing") } }
    var briefingHour: Int { get { prefs.object(forKey: "proBriefingHour") as? Int ?? 7 } set { prefs.set(newValue, forKey: "proBriefingHour") } }

    func start() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.check() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 8) { [weak self] in self?.check() }
    }

    func check() {
        if meetings && Modules.isEnabled(.calendar) { checkMeetings() }
        if battery { checkBattery() }
        if briefingAuto { checkBriefing() }
    }

    private func checkMeetings() {
        guard EKEventStore.authorizationStatus(for: .event) == .fullAccess else { return }
        let now = Date()
        let pred = store.predicateForEvents(withStart: now, end: now.addingTimeInterval(16 * 60), calendars: nil)
        for e in store.events(matching: pred) where !e.isAllDay && e.startDate > now {
            let key = "\(e.calendarItemIdentifier)|\(e.startDate.timeIntervalSince1970)"
            guard !alerted.contains(key) else { continue }
            alerted.insert(key)
            let mins = max(1, Int(e.startDate.timeIntervalSince(now) / 60))
            var text = "Signore, tra \(mins) minuti: \(e.title ?? "un impegno")"
            if let l = e.location, !l.isEmpty { text += ", \(l)" }
            notify("Impegno tra \(mins) minuti", e.title ?? "")
            onAlert?("CALENDAR_SYNC", text + ".")
        }
    }

    private func checkBattery() {
        guard let info = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
              let list = IOPSCopyPowerSourcesList(info)?.takeRetainedValue() as? [CFTypeRef],
              let ps = list.first,
              let d = IOPSGetPowerSourceDescription(info, ps)?.takeUnretainedValue() as? [String: Any] else { return }
        let pct = d[kIOPSCurrentCapacityKey] as? Int ?? 100
        let onAC = (d[kIOPSPowerSourceStateKey] as? String) == kIOPSACPowerValue
        if onAC { battWarned = 100; return }
        for threshold in [20, 10, 5] where pct <= threshold && battWarned > threshold {
            battWarned = threshold
            notify("Batteria al \(pct)%", "Collega l'alimentatore.")
            onAlert?("POWER", "Signore, la batteria è al \(pct) per cento. Le consiglio di collegare l'alimentatore.")
            break
        }
    }

    private func checkBriefing() {
        let cal = Calendar.current
        let h = cal.component(.hour, from: Date())
        guard h >= briefingHour, h < 12 else { return }
        let today = ISO8601DateFormatter.string(from: Date(), timeZone: .current, formatOptions: [.withFullDate])
        guard prefs.string(forKey: "proBriefingDone") != today else { return }
        prefs.set(today, forKey: "proBriefingDone")
        onBriefing?()
    }

    func notify(_ title: String, _ body: String) {
        let c = UNMutableNotificationContent()
        c.title = "J.A.R.V.I.S. · " + title
        c.body = body
        c.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
    }
}
