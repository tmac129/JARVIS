import AppKit
import Carbon.HIToolbox
import EventKit
import JarvisCore
import ServiceManagement
import WebKit

final class HUDWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

/// Transparent strip over the HUD header: drag moves the window, double-click zooms (like a title bar).
final class DragStrip: NSView {
    override func mouseDown(with e: NSEvent) {
        if e.clickCount == 2 { window?.performZoom(nil) } else { window?.performDrag(with: e) }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuDelegate, WKScriptMessageHandler, WKNavigationDelegate {
    var window: HUDWindow!
    var web: WKWebView!
    var status: NSStatusItem!
    let hotkeys = HotKeys()
    let telemetry = Telemetry()
    let brain = JarvisBrain()
    let work = DispatchQueue(label: "jarvis.work", qos: .userInitiated)
    var timer: Timer?
    var hudReady = false
    var feedOffset: UInt64 = 0
    var busy = false
    let voice = Voice()
    let proactive = Proactive()
    let remote = RemoteServer()
    var replyHandler: ((String) -> Void)?
    var lastTurn: TurnResult?
    var lastStarted = Date()
    var speakReply = true

    // session stats
    var turns = 0, cost = 0.0, lastContext = 0

    // Claude account (read-only status of the user's own Claude Code login)
    var claudeAccount: (installed: Bool, loggedIn: Bool, plan: String?)?
    var claudeAccountAt = Date.distantPast

    // MARK: launch

    func applicationDidFinishLaunching(_ n: Notification) {
        buildMenu()
        buildWindow()
        buildStatusItem()
        hotkeys.register(keyCode: kVK_Space, modifiers: optionKey, id: 1) { [weak self] in self?.toggle() }
        hotkeys.register(keyCode: kVK_ANSI_J, modifiers: cmdKey | shiftKey, id: 2) { [weak self] in self?.toggle() }
        // push-to-talk: ⌥⇧Space
        hotkeys.register(keyCode: kVK_Space, modifiers: optionKey | shiftKey, id: 3) { [weak self] in self?.show(); self?.toggleMic() }
        requestPermissions()
        setupVoice()
        setupProactive()
        setupRemote()
        refreshClaudeAccount()
        trackFrontmostApp()
        loadPrefs()
        if !brain.sessions.values.contains(where: { $0.isRunning }) { brain.prewarm() }
        show()
    }

    func applicationWillTerminate(_ n: Notification) { brain.shutdown() }

    /// Click on the Dock icon brings the HUD back.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        show(); return true
    }

    func requestPermissions() {
        // Ask once, as JARVIS.app, so the tools it launches inherit the grant.
        let store = EKEventStore()
        if EKEventStore.authorizationStatus(for: .event) != .fullAccess {
            store.requestFullAccessToEvents { _, _ in
                if EKEventStore.authorizationStatus(for: .reminder) != .fullAccess { store.requestFullAccessToReminders { _, _ in } }
            }
        } else if EKEventStore.authorizationStatus(for: .reminder) != .fullAccess {
            store.requestFullAccessToReminders { _, _ in }
        }
    }

    func buildMenu() {
        // Accessory apps still need an Edit menu for ⌘C/⌘V/⌘A inside the web view.
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Esci da J.A.R.V.I.S.", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Modifica")
        edit.addItem(withTitle: "Annulla", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Taglia", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copia", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Incolla", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Seleziona tutto", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        NSApp.mainMenu = main
    }

    func buildWindow() {
        let size = NSSize(width: 1180, height: 740)
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let w = min(size.width, screen.width - 40), h = min(size.height, screen.height - 40)
        let frame = NSRect(x: screen.midX - w / 2, y: screen.midY - h / 2, width: w, height: h)
        // Standard macOS window: close / minimize / zoom, draggable title area, own Space, Mission Control.
        window = HUDWindow(contentRect: frame, styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                           backing: .buffered, defer: false)
        window.title = "J.A.R.V.I.S."
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.minSize = NSSize(width: 980, height: 620)
        window.collectionBehavior = [.fullScreenPrimary]
        window.delegate = self
        window.setFrameAutosaveName("JarvisHUD")   // remembers position and size
        applyAlwaysOnTop()

        let fx = NSVisualEffectView(frame: NSRect(origin: .zero, size: frame.size))
        fx.material = .hudWindow
        fx.blendingMode = .behindWindow
        fx.state = .active
        fx.appearance = NSAppearance(named: .darkAqua)
        fx.autoresizingMask = [.width, .height]

        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(self, name: "jarvis")
        web = WKWebView(frame: fx.bounds, configuration: cfg)
        web.setValue(false, forKey: "drawsBackground")
        web.underPageBackgroundColor = .clear
        web.autoresizingMask = [.width, .height]
        web.navigationDelegate = self
        fx.addSubview(web)

        // Native drag strip over the HUD header: move the window from anywhere in the top bar.
        let strip = DragStrip(frame: NSRect(x: 0, y: fx.bounds.height - 74, width: fx.bounds.width, height: 74))
        strip.autoresizingMask = [.width, .minYMargin]
        fx.addSubview(strip)
        window.contentView = fx

        let dir = hudDirectory()
        web.loadFileURL(dir.appendingPathComponent("index.html"), allowingReadAccessTo: dir)
    }

    func hudDirectory() -> URL {
        if let p = ProcessInfo.processInfo.environment["JARVIS_HUD_DIR"] { return URL(fileURLWithPath: p) }
        if let r = Bundle.main.resourceURL?.appendingPathComponent("HUD"),
           FileManager.default.fileExists(atPath: r.appendingPathComponent("index.html").path) { return r }
        // dev fallback: <repo>/HUD
        return URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("HUD")
    }

    // MARK: preferences

    let prefs = UserDefaults.standard
    var alwaysOnTop: Bool {
        get { prefs.bool(forKey: "alwaysOnTop") }
        set { prefs.set(newValue, forKey: "alwaysOnTop"); applyAlwaysOnTop() }
    }
    func applyAlwaysOnTop() { window?.level = alwaysOnTop ? .floating : .normal }

    func loadPrefs() {
        brain.preferredTier = prefs.string(forKey: "tier").flatMap(Tier.init(rawValue:))
        brain.effort = prefs.string(forKey: "effort")
    }

    func modelLabel(_ t: Tier? = nil) -> String {
        let tier = t ?? brain.defaultTier
        let mode = brain.preferredTier == nil ? "AUTO" : "FISSO"
        return "\(tier.label) // \(mode) // EFFORT \((brain.effort ?? tier.effort).uppercased())"
    }

    // MARK: menu bar item

    func buildStatusItem() {
        status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let b = status.button {
            // the app icon itself, sized for the menu bar
            let icon = (NSImage(named: "AppIcon") ?? NSApp.applicationIconImage).copy() as! NSImage
            icon.size = NSSize(width: 20, height: 20)
            icon.isTemplate = false
            b.image = icon
            b.imagePosition = .imageOnly
            b.toolTip = "J.A.R.V.I.S."
        }
        let m = NSMenu()
        m.delegate = self
        m.autoenablesItems = false
        menuNeedsUpdate(m)   // an empty NSMenu never opens: fill it now, refresh on every open
        status.menu = m
    }

    /// Rebuilt every time it opens, so checkmarks and stats are always current.
    func menuNeedsUpdate(_ m: NSMenu) {
        m.removeAllItems()
        func item(_ title: String, _ sel: Selector?, key: String = "", on: Bool = false, enabled: Bool = true, tag: Int = 0, obj: Any? = nil) -> NSMenuItem {
            let i = NSMenuItem(title: title, action: sel, keyEquivalent: key)
            i.target = self; i.state = on ? .on : .off; i.isEnabled = enabled; i.tag = tag; i.representedObject = obj
            return i
        }
        let visible = window.isVisible
        let head = NSMenuItem(title: "J.A.R.V.I.S.  //  \(busy ? "in elaborazione" : "online")", action: nil, keyEquivalent: "")
        head.isEnabled = false
        m.addItem(head)
        refreshClaudeAccount()   // async, cached for a minute: the next opening shows the fresh state
        let acc: NSMenuItem
        switch claudeAccount {
        case nil: acc = item("Account Claude: verifica…", nil, enabled: false)
        case let a? where !a.installed: acc = item("Claude Code non installato…", #selector(showClaudeHelp))
        case let a? where !a.loggedIn: acc = item("Account Claude: non collegato…", #selector(showClaudeHelp))
        case let a?: acc = item("Account Claude: " + (a.plan.map { $0.prefix(1).uppercased() + $0.dropFirst() } ?? "collegato"), nil, enabled: false)
        }
        m.addItem(acc)
        m.addItem(.separator())
        let open = item("Apri J.A.R.V.I.S.", #selector(openAction), key: " ")
        open.keyEquivalentModifierMask = [.option]
        m.addItem(open)
        m.addItem(item("Nascondi finestra", #selector(hideAction), enabled: visible))
        m.addItem(.separator())

        // Model
        let models = NSMenu()
        models.addItem(item("Automatico (Haiku, sale da solo se serve)", #selector(setModel(_:)), on: brain.preferredTier == nil, obj: "auto"))
        models.addItem(.separator())
        let desc: [Tier: String] = [.haiku: "Haiku  · veloce, costo minimo", .sonnet: "Sonnet  · analisi, testi, codice", .opus: "Opus  · ragionamento profondo", .fable: "Fable  · massima capacità, costo più alto"]
        for t in Tier.allCases { models.addItem(item(desc[t]!, #selector(setModel(_:)), on: brain.preferredTier == t, obj: t.rawValue)) }
        let mi = NSMenuItem(title: "Modello:  \(brain.preferredTier.map { $0.rawValue.capitalized } ?? "Automatico")", action: nil, keyEquivalent: "")
        mi.submenu = models
        m.addItem(mi)

        // Effort
        let eff = NSMenu()
        eff.addItem(item("Automatico (low / medium / high per modello)", #selector(setEffort(_:)), on: brain.effort == nil, obj: "auto"))
        eff.addItem(.separator())
        let edesc = ["low": "low  · più veloce, meno token", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max  · massima qualità, più lento"]
        for e in JarvisBrain.efforts { eff.addItem(item(edesc[e]!, #selector(setEffort(_:)), on: brain.effort == e, obj: e)) }
        let ei = NSMenuItem(title: "Effort:  \(brain.effort ?? "Automatico")", action: nil, keyEquivalent: "")
        ei.submenu = eff
        m.addItem(ei)
        m.addItem(.separator())

        // Modules (persisted in modules.json, shared with the `jarvis` CLI)
        let mm = NSMenu()
        mm.autoenablesItems = false
        for mod in Module.allCases { mm.addItem(item(mod.label, #selector(toggleModule(_:)), on: Modules.isEnabled(mod), obj: mod.rawValue)) }
        let active = Modules.enabled.count
        let mo = NSMenuItem(title: active == Module.allCases.count ? "Moduli" : "Moduli:  \(active) di \(Module.allCases.count)", action: nil, keyEquivalent: "")
        mo.submenu = mm
        m.addItem(mo)

        // Voice
        let vm = NSMenu()
        vm.addItem(item("Parla ora  (⌥⇧Spazio)", #selector(micAction)))
        vm.addItem(item("Risposte vocali", #selector(toggleVoiceReplies), on: voiceReplies))
        vm.addItem(item("Ascolto continuo \"Jarvis\"", #selector(toggleHotword), on: voice.hotword))
        vm.addItem(.separator())
        let voices = Voice.italianVoices()
        let current = voice.voiceID ?? voices.first?.identifier
        for v in voices {
            let q = v.quality == .premium ? " (premium)" : v.quality == .enhanced ? " (avanzata)" : ""
            vm.addItem(item("Voce: \(v.name)\(q)", #selector(setVoice(_:)), on: v.identifier == current, obj: v.identifier))
        }
        vm.addItem(item("Scarica voci migliori…", #selector(openVoiceSettings)))
        let vi = NSMenuItem(title: "Voce", action: nil, keyEquivalent: ""); vi.submenu = vm; m.addItem(vi)

        // Proactive
        let pm = NSMenu()
        pm.addItem(item("Briefing adesso", #selector(briefingNow)))
        pm.addItem(item("Briefing automatico al mattino (dalle \(proactive.briefingHour):00)", #selector(toggleBriefing), on: proactive.briefingAuto))
        pm.addItem(item("Avvisa 15 minuti prima degli impegni", #selector(toggleMeetings), on: proactive.meetings))
        pm.addItem(item("Avvisa con batteria bassa", #selector(toggleBattery), on: proactive.battery))
        let pi = NSMenuItem(title: "Iniziativa", action: nil, keyEquivalent: ""); pi.submenu = pm; m.addItem(pi)

        // iPhone
        let im = NSMenu()
        im.addItem(item("Accesso da iPhone attivo", #selector(toggleRemote), on: remote.isRunning))
        im.addItem(item("Collega iPhone (codice QR)…", #selector(showRemoteInfo), enabled: remote.isRunning))
        let ii = NSMenuItem(title: "iPhone", action: nil, keyEquivalent: ""); ii.submenu = im; m.addItem(ii)

        // Permissions
        let perm = NSMenu()
        perm.addItem(item("Accesso completo al disco (Mail veloce, WhatsApp)", #selector(openPrivacy(_:)), obj: "Privacy_AllFiles"))
        perm.addItem(item("Accessibilità (invio WhatsApp, luminosità)", #selector(openPrivacy(_:)), obj: "Privacy_Accessibility"))
        perm.addItem(item("Registrazione schermo (vedere lo schermo)", #selector(openPrivacy(_:)), obj: "Privacy_ScreenCapture"))
        perm.addItem(item("Microfono", #selector(openPrivacy(_:)), obj: "Privacy_Microphone"))
        let pe = NSMenuItem(title: "Permessi", action: nil, keyEquivalent: ""); pe.submenu = perm; m.addItem(pe)
        m.addItem(.separator())

        m.addItem(item("Nuova conversazione", #selector(resetSessions)))
        m.addItem(item("Sempre in primo piano", #selector(toggleOnTop), on: alwaysOnTop))
        m.addItem(item("Avvia all'accesso", #selector(toggleLogin), on: SMAppService.mainApp.status == .enabled))
        let stats = NSMenuItem(title: String(format: "Sessione: %d turni  ·  $%.4f", turns, cost), action: nil, keyEquivalent: "")
        stats.isEnabled = false
        m.addItem(stats)
        m.addItem(.separator())
        m.addItem(item("Apri cartella dati", #selector(openDataFolder)))
        m.addItem(item("Ricarica interfaccia", #selector(reloadHUD)))
        m.addItem(.separator())
        let quit = NSMenuItem(title: "Chiudi J.A.R.V.I.S.", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        m.addItem(quit)
    }

    @objc func toggleModule(_ s: NSMenuItem) {
        guard let raw = s.representedObject as? String, let mod = Module(rawValue: raw) else { return }
        let on = !Modules.isEnabled(mod)
        Modules.set(mod, enabled: on)
        // new sessions get a system prompt with/without the module's commands
        work.async { [weak self] in self?.brain.shutdown(); self?.brain.prewarm() }
        ActionLog.add("SYS", "Modulo \(mod.label) \(on ? "attivato" : "disattivato")")
        pollFeed()
    }

    func refreshClaudeAccount() {
        guard Date().timeIntervalSince(claudeAccountAt) > 60 else { return }
        claudeAccountAt = Date()
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let st = ClaudeSession.accountStatus()
            DispatchQueue.main.async { self?.claudeAccount = st }
        }
    }

    /// JARVIS never handles the Claude login itself: it points to the official CLI.
    @objc func showClaudeHelp() {
        let installed = claudeAccount?.installed ?? true
        let a = NSAlert()
        a.messageText = installed ? "Collega il tuo account Claude" : "Installa Claude Code"
        a.informativeText = installed
            ? "JARVIS usa Claude Code con il tuo account (piano Pro, Max o Ultra, oppure Anthropic Console).\n\nApri il Terminale ed esegui:\n\nclaude auth login\n\nPoi riapri questo menu."
            : "JARVIS usa la CLI ufficiale Claude Code con il tuo account. Installala seguendo la guida su code.claude.com/docs, poi esegui nel Terminale:\n\nclaude auth login"
        a.addButton(withTitle: "Copia comando")
        a.addButton(withTitle: "Chiudi")
        NSApp.activate(ignoringOtherApps: true)
        if a.runModal() == .alertFirstButtonReturn {
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString("claude auth login", forType: .string)
        }
        claudeAccountAt = .distantPast
        refreshClaudeAccount()
    }

    @objc func openAction() { show() }
    @objc func hideAction() { hide() }
    @objc func toggleAction() { toggle() }
    @objc func reloadHUD() { hudReady = false; web.reload() }
    @objc func openDataFolder() { NSWorkspace.shared.open(Paths.support) }
    @objc func toggleOnTop() { alwaysOnTop.toggle() }

    @objc func setModel(_ sender: NSMenuItem) {
        let v = sender.representedObject as? String ?? "auto"
        prefs.set(v == "auto" ? nil : v, forKey: "tier")
        brain.preferredTier = Tier(rawValue: v)
        settingsChanged("Modello: \(brain.preferredTier.map { $0.rawValue.capitalized } ?? "automatico").")
    }

    @objc func setEffort(_ sender: NSMenuItem) {
        let v = sender.representedObject as? String ?? "auto"
        prefs.set(v == "auto" ? nil : v, forKey: "effort")
        brain.effort = v == "auto" ? nil : v
        settingsChanged("Effort: \(brain.effort ?? "automatico").")
    }

    func settingsChanged(_ msg: String) {
        send(["type": "model", "label": modelLabel()])
        send(["type": "reply", "text": msg + " Nuova conversazione avviata."])
        send(["type": "feed", "module": "SYS", "text": msg])
    }

    @objc func toggleLogin() {
        do {
            if SMAppService.mainApp.status == .enabled { try SMAppService.mainApp.unregister() }
            else { try SMAppService.mainApp.register() }
        } catch {
            let a = NSAlert()
            a.messageText = "Impossibile cambiare l'avvio all'accesso"
            a.informativeText = "\(error.localizedDescription)\nPuoi aggiungerlo da Impostazioni di Sistema > Generali > Elementi login."
            a.runModal()
        }
    }

    @objc func resetSessions() {
        brain.shutdown(); turns = 0; cost = 0; lastContext = 0
        sendStats(latency: "--")
        send(["type": "reply", "text": "Nuova conversazione avviata."])
        brain.prewarm()
    }

    // MARK: show / hide

    func toggle() { window.isVisible && window.isKeyWindow ? hide() : show() }

    func show() {
        if window.isMiniaturized { window.deminiaturize(nil) }
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(web)
        send(["type": "visible", "value": true])
        startTimer()
    }

    func hide() {
        send(["type": "visible", "value": false])
        window.orderOut(nil)
        timer?.invalidate(); timer = nil   // nothing to draw: no telemetry, no CPU
    }

    // Red close button hides (the app keeps running in the menu bar / Dock); ⌘Q quits.
    func windowShouldClose(_ sender: NSWindow) -> Bool { hide(); return false }
    func windowDidMiniaturize(_ n: Notification) { send(["type": "visible", "value": false]); timer?.invalidate(); timer = nil }
    func windowDidDeminiaturize(_ n: Notification) { send(["type": "visible", "value": true]); startTimer() }

    func startTimer() {
        guard timer == nil else { return }
        tick()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.tick() }
    }

    func tick() {
        guard hudReady else { return }
        send(telemetry.sample())
        pollFeed()
    }

    // MARK: action feed (tails actions.log written by every tool, including launchd alarms)

    func pollFeed(initial: Bool = false) {
        let url = Paths.file("actions.log")
        guard let h = try? FileHandle(forReadingFrom: url) else { return }
        defer { try? h.close() }
        let size = (try? h.seekToEnd()) ?? 0
        if initial {
            // last ~150 entries after the last CLEAR, not marked fresh (the log file itself is never deleted)
            var cleared = UInt64(max(0, UserDefaults.standard.integer(forKey: "feedClearedOffset")))
            if cleared > size { cleared = 0 }   // log was rotated or replaced
            let start = max(size > 60000 ? size - 60000 : 0, cleared)
            try? h.seek(toOffset: start)
            var chunk = String(decoding: h.readDataToEndOfFile(), as: UTF8.self)
            if start > cleared, let nl = chunk.firstIndex(of: "\n") { chunk = String(chunk[chunk.index(after: nl)...]) }  // drop partial line
            let lines = chunk.split(separator: "\n").suffix(150)
            for l in lines { if var o = parse(l) { o["fresh"] = false; send(o) } }
            feedOffset = size
            return
        }
        if size < feedOffset { feedOffset = 0 }   // log rotated or reset: read the new file from the start
        guard size > feedOffset else { return }
        try? h.seek(toOffset: feedOffset)
        let data = h.readDataToEndOfFile()
        feedOffset = size
        for l in String(decoding: data, as: UTF8.self).split(separator: "\n") { if let o = parse(l) { send(o) } }
    }

    func parse(_ l: Substring) -> [String: Any]? {
        guard var o = try? JSONSerialization.jsonObject(with: Data(l.utf8)) as? [String: Any] else { return nil }
        o["type"] = "feed"
        return o
    }

    // MARK: JS bridge

    func send(_ msg: [String: Any]) {
        guard hudReady || msg["type"] as? String == "visible",
              let d = try? JSONSerialization.data(withJSONObject: msg), let s = String(data: d, encoding: .utf8) else { return }
        DispatchQueue.main.async { self.web.evaluateJavaScript("window.HUD && HUD.recv(\(s))", completionHandler: nil) }
    }

    func userContentController(_ c: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let m = message.body as? [String: Any], let type = m["type"] as? String else { return }
        switch type {
        case "ready":
            hudReady = true
            send(["type": "model", "label": modelLabel()])
            send(["type": "native"])
            pollFeed(initial: true)
            tick()
            send(["type": "visible", "value": window.isVisible])
        case "command":
            if let t = m["text"] as? String { command(t) }
        case "confirm": resolvePending(confirm: true)
        case "cancel": resolvePending(confirm: false)
        case "hide": voice.stopSpeaking(); if voice.capturing { voice.cancelListening() } else { hide() }
        case "mic": toggleMic()
        case "stopSpeech": voice.stopSpeaking()
        case "clearFeed":
            // hide everything logged so far, also after a restart; actions.log stays on disk
            let attrs = try? FileManager.default.attributesOfItem(atPath: Paths.file("actions.log").path)
            let size = (attrs?[.size] as? NSNumber)?.intValue ?? Int(feedOffset)
            UserDefaults.standard.set(size, forKey: "feedClearedOffset")
        default: break
        }
    }

    // MARK: commands

    static func module(for cmd: String) -> String {
        let c = cmd.lowercased()
        if c.contains("jarvis mail") { return "MAIL_PROTOCOL" }
        if c.contains("jarvis cal") { return "CALENDAR_SYNC" }
        if c.contains("jarvis rem") { return "REMINDERS" }
        if c.contains("jarvis alarm") || c.contains("jarvis timer") { return "CLOCK" }
        if c.contains("jarvis file") { return "FILE_SYSTEM" }
        if c.contains("jarvis contact") { return "CONTACTS" }
        if c.contains("jarvis wa") { return "WHATSAPP" }
        if c.contains("jarvis sys") { return "SYSTEM" }
        if c.contains("jarvis music") { return "MUSIC" }
        if c.contains("jarvis note") { return "NOTES" }
        if c.contains("jarvis doc") { return "DOCUMENTS" }
        if c.contains("jarvis screen") || c.lowercased().contains("view/") { return "VISION" }
        return "NEURAL_LINK"
    }

    func command(_ text: String, speak: Bool? = nil, completion: ((String) -> Void)? = nil) {
        if busy {
            let msg = "Un momento, signore: sto ancora elaborando."
            if let completion { completion(msg) } else { send(["type": "reply", "text": msg]) }
            return
        }
        voice.stopSpeaking()
        busy = true
        replyHandler = completion
        speakReply = speak ?? voiceReplies
        send(["type": "state", "state": "thinking", "module": "NEURAL_LINK"])
        let started = Date()
        work.async { [weak self] in
            self?.brain.handle(text) { ev in DispatchQueue.main.async { self?.onEvent(ev, started: started) } }
        }
    }

    func onEvent(_ ev: BridgeEvent, started: Date) {
        switch ev {
        case .thinking(let tier):
            send(["type": "model", "label": modelLabel(tier)])
        case .tool(let cmd):
            send(["type": "state", "state": "thinking", "module": Self.module(for: cmd)])
            send(["type": "tool", "text": cmd])
        case .confirmNeeded:
            if let s = Gate.latestSummary { send(["type": "confirm", "text": s]) }
        case .done(let r):
            busy = false
            lastTurn = r; lastStarted = started
            send(["type": "reply", "text": r.text])
            replyHandler?(r.text); replyHandler = nil
            if !r.local {
                turns += 1; cost += r.costUSD; lastContext = r.inputTokens + r.cacheRead + r.cacheWrite
            }
            sendStats(latency: String(format: "%.1f s%@", Date().timeIntervalSince(started), r.local ? " (locale)" : ""))
            if r.pendingConfirm != nil, let s = Gate.latestSummary {
                send(["type": "confirm", "text": s])
            } else {
                send(["type": "confirmClear"])
                send(["type": "state", "state": "standby"])
            }
            if speakReply { voice.speak(r.text) }
            pollFeed()
        default: break
        }
    }

    static func summary(_ line: String) -> String {
        // "IN ATTESA DI CONFERMA [p1]: Inviare mail a ... . Chiedi conferma ..." -> "Inviare mail a ..."
        var s = line
        if let r = s.range(of: "]: ") { s = String(s[r.upperBound...]) }
        if let r = s.range(of: ". Chiedi conferma") { s = String(s[..<r.lowerBound]) }
        return s
    }

    func sendStats(latency: String) {
        send(["type": "stats", "turns": turns, "context": lastContext, "cost": cost, "latency": latency])
    }

    func resolvePending(confirm: Bool) {
        send(["type": "confirmClear"])
        send(["type": "state", "state": "thinking", "module": "CONFIRM"])
        work.async { [weak self] in
            let (out, _) = confirm ? CLI.run(["confirm"]) : CLI.run(["cancel"])
            self?.brain.noteOutcome(out)
            DispatchQueue.main.async {
                self?.send(["type": "reply", "text": out])
                if self?.voiceReplies == true { self?.voice.speak(out) }
                self?.send(["type": "state", "state": "standby"])
                self?.pollFeed()
            }
        }
    }

    // MARK: voice

    var voiceReplies: Bool {
        get { prefs.object(forKey: "voiceReplies") as? Bool ?? true }
        set { prefs.set(newValue, forKey: "voiceReplies") }
    }

    func setupVoice() {
        voice.voiceID = prefs.string(forKey: "voiceID")
        voice.onLevel = { [weak self] l in self?.send(["type": "level", "value": l]) }
        voice.onPartial = { [weak self] t in self?.send(["type": "user", "text": t]) }
        voice.onListening = { [weak self] on in
            guard let self else { return }
            self.send(["type": "mic", "on": on])
            if on { self.send(["type": "state", "state": "listening", "module": "AUDIO_INPUT"]) }
            else if !self.busy { self.send(["type": "state", "state": "standby"]) }
        }
        voice.onCommand = { [weak self] t in self?.send(["type": "user", "text": t]); self?.command(t, speak: true) }
        voice.onSpeaking = { [weak self] on in
            guard let self, !self.busy, !self.voice.capturing else { return }
            self.send(["type": "state", "state": on ? "speaking" : "standby"])
        }
        voice.onWake = { [weak self] in self?.show() }
        voice.onError = { [weak self] e in self?.send(["type": "reply", "text": e]); self?.send(["type": "mic", "on": false]) }
        if prefs.bool(forKey: "hotword") { voice.setHotword(true) }
    }

    func toggleMic() {
        if voice.capturing { voice.cancelListening() } else { voice.listenOnce() }
    }

    @objc func micAction() { show(); toggleMic() }
    @objc func toggleVoiceReplies() { voiceReplies.toggle(); if !voiceReplies { voice.stopSpeaking() } }
    @objc func toggleHotword() {
        let on = !voice.hotword
        voice.setHotword(on)
        prefs.set(on, forKey: "hotword")
        send(["type": "reply", "text": on ? "Ascolto continuo attivo: dica \"Jarvis\" seguito dal comando." : "Ascolto continuo disattivato."])
    }
    @objc func setVoice(_ s: NSMenuItem) {
        guard let id = s.representedObject as? String else { return }
        voice.voiceID = id; prefs.set(id, forKey: "voiceID")
        voice.speak("Questa è la mia nuova voce, signore.")
    }
    @objc func openVoiceSettings() {
        let a = NSAlert()
        a.messageText = "Voci italiane migliori"
        a.informativeText = "Impostazioni di Sistema > Accessibilità > Contenuti letti ad alta voce > Voce di sistema > Gestisci voci… > Italiano: scarica una voce \"Avanzata\" o \"Premium\" (es. Luca). Poi sceglila dal menu Voce di J.A.R.V.I.S."
        a.addButton(withTitle: "Apri Impostazioni"); a.addButton(withTitle: "Chiudi")
        if a.runModal() == .alertFirstButtonReturn {
            NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.Accessibility-Settings.extension")!)
        }
    }

    // MARK: proactive

    func setupProactive() {
        proactive.onAlert = { [weak self] module, text in
            guard let self else { return }
            ActionLog.add(module, text)
            self.send(["type": "reply", "text": text])
            if self.voiceReplies && !self.busy { self.voice.speak(text) }
            self.pollFeed()
        }
        proactive.onBriefing = { [weak self] in self?.briefingNow() }
        proactive.start()
    }

    @objc func briefingNow() {
        show()
        send(["type": "user", "text": "Briefing"])
        command(Prompt.briefing, speak: true)
    }
    @objc func toggleBriefing() { proactive.briefingAuto.toggle() }
    @objc func toggleMeetings() { proactive.meetings.toggle() }
    @objc func toggleBattery() { proactive.battery.toggle() }

    // MARK: iPhone

    func setupRemote() {
        remote.pageHTML = { [weak self] in
            guard let dir = self?.hudDirectory() else { return "" }
            return (try? String(contentsOf: dir.appendingPathComponent("mobile.html"), encoding: .utf8)) ?? "JARVIS"
        }
        remote.handler = { [weak self] text, json, reply in
            guard let self else { return reply("JARVIS non disponibile.") }
            self.send(["type": "user", "text": "IPHONE // " + text])
            if !json { ActionLog.add("IPHONE", "Comando da iPhone: \(text.prefix(60))") }
            self.command(text, speak: false) { out in
                guard json else { return reply(out) }
                // test/diagnostic format: reply + timing + token usage of this turn
                let r = self.lastTurn
                let o: [String: Any] = [
                    "reply": out, "seconds": Date().timeIntervalSince(self.lastStarted), "local": r?.local ?? true,
                    "model": r?.tier.rawValue ?? "", "cost": r?.costUSD ?? 0, "output": r?.outputTokens ?? 0,
                    "context": (r?.inputTokens ?? 0) + (r?.cacheRead ?? 0) + (r?.cacheWrite ?? 0),
                    "cacheRead": r?.cacheRead ?? 0, "pending": r?.pendingConfirm != nil,
                ]
                let d = (try? JSONSerialization.data(withJSONObject: o)) ?? Data()
                reply(String(decoding: d, as: UTF8.self))
            }
        }
        if prefs.bool(forKey: "remote") { try? remote.start() }
    }

    @objc func toggleRemote() {
        if remote.isRunning { remote.stop(); prefs.set(false, forKey: "remote") }
        else {
            do { try remote.start(); prefs.set(true, forKey: "remote"); showRemoteInfo() }
            catch { send(["type": "reply", "text": "Impossibile avviare il server iPhone: \(error.localizedDescription)"]) }
        }
    }

    @objc func showRemoteInfo() {
        let ip = RemoteServer.localAddresses().first ?? RemoteServer.bonjourName
        let url = remote.url(host: ip)
        let a = NSAlert()
        a.messageText = "Collega l'iPhone a J.A.R.V.I.S."
        a.informativeText = """
        1. iPhone sulla stessa rete Wi-Fi del Mac (con i dati cellulari non funziona).
        2. Inquadra il codice con la Fotocamera e apri il link in Safari.
        3. Condividi > Aggiungi alla schermata Home: avrai l'app JARVIS.

        Se Safari dice che non riesce a connettersi: Impostazioni di Sistema > Privacy e sicurezza > Rete locale > attiva JARVIS. Se ancora non va, la rete Wi-Fi isola i dispositivi (succede a scuola o negli hotel): usa l'hotspot dell'iPhone o Tailscale.

        Link: \(url)
        Alternativa: \(remote.url(host: RemoteServer.bonjourName))

        Per Siri crea un Comando Rapido: Detta testo > Ottieni contenuto di URL (POST http://\(ip):\(RemoteServer.port)/ask, intestazione Authorization = Bearer \(remote.token), corpo JSON text = testo dettato) > Pronuncia testo.
        Fuori casa: installa Tailscale su Mac e iPhone e usa l'indirizzo Tailscale del Mac.
        """
        if let qr = RemoteServer.qrImage(url) {
            let iv = NSImageView(frame: NSRect(x: 0, y: 0, width: 220, height: 220))
            iv.image = qr; iv.imageScaling = .scaleProportionallyUpOrDown
            a.accessoryView = iv
        }
        a.addButton(withTitle: "Copia link"); a.addButton(withTitle: "Chiudi")
        NSApp.activate(ignoringOtherApps: true)
        if a.runModal() == .alertFirstButtonReturn {
            NSPasteboard.general.clearContents(); NSPasteboard.general.setString(url, forType: .string)
        }
    }

    // MARK: permissions / screen context

    @objc func openPrivacy(_ s: NSMenuItem) {
        guard let key = s.representedObject as? String else { return }
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?\(key)")!)
    }

    /// Remember the app the user was in before JARVIS, so "cosa c'è sullo schermo" captures that window.
    func trackFrontmostApp() {
        struct Front: Codable { let pid: Int32; let name: String }
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { n in
            guard let app = n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
                  app.bundleIdentifier != Bundle.main.bundleIdentifier else { return }
            Store.save("frontmost.json", Front(pid: app.processIdentifier, name: app.localizedName ?? "app"))
        }
    }

    // keep the HUD alive if the web process dies
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { hudReady = false; webView.reload() }
}
