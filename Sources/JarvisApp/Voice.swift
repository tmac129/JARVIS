import AVFoundation
import Foundation
import Speech

/// Voice I/O: on-device Italian speech recognition (push-to-talk or "Jarvis" hotword) and interruptible TTS.
final class Voice: NSObject, AVSpeechSynthesizerDelegate {
    // callbacks (main thread)
    var onLevel: ((Double) -> Void)?
    var onPartial: ((String) -> Void)?
    var onCommand: ((String) -> Void)?
    var onListening: ((Bool) -> Void)?
    var onSpeaking: ((Bool) -> Void)?
    var onWake: (() -> Void)?
    var onError: ((String) -> Void)?

    private let synth = AVSpeechSynthesizer()
    private let engine = AVAudioEngine()
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "it-IT"))
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var tick: Timer?
    private var taskStarted = Date()
    private var lastChange = Date()
    private var captureStart = Date()
    private var heard = ""          // full transcript of the current task
    private var command = ""        // text after the wake word / whole utterance in PTT
    private var lastLevelSent = Date.distantPast

    private(set) var capturing = false
    private(set) var hotword = false
    var voiceID: String?

    static let wakeWords = ["jarvis", "jarvi", "giarvis", "gervis", "jervis", "jarvys", "charvis", "jarbis"]

    override init() {
        super.init()
        synth.delegate = self
    }

    // MARK: permissions

    func authorize(_ done: @escaping (Bool) -> Void) {
        SFSpeechRecognizer.requestAuthorization { st in
            AVCaptureDevice.requestAccess(for: .audio) { mic in
                DispatchQueue.main.async { done(st == .authorized && mic) }
            }
        }
    }

    // MARK: listening

    /// Push-to-talk: listen for one command, stop after a pause.
    func listenOnce() {
        stopSpeaking()
        authorize { [weak self] ok in
            guard let self else { return }
            guard ok else { self.onError?("Servono i permessi Microfono e Riconoscimento vocale per JARVIS."); return }
            do {
                try self.ensureEngine()
                self.restartTask()
                self.beginCapture(initial: "")
            } catch { self.onError?("Microfono non disponibile: \(error.localizedDescription)") }
        }
    }

    func cancelListening() {
        capturing = false
        onListening?(false)
        if !hotword { stopEngine() } else { restartTask() }
    }

    /// Continuous wake-word listening ("Jarvis, ..."). On-device, so nothing leaves the Mac.
    func setHotword(_ on: Bool) {
        hotword = on
        if on {
            authorize { [weak self] ok in
                guard let self else { return }
                guard ok else { self.hotword = false; self.onError?("Servono i permessi Microfono e Riconoscimento vocale."); return }
                do { try self.ensureEngine(); self.restartTask() } catch { self.onError?("Microfono non disponibile.") }
            }
        } else if !capturing {
            stopEngine()
        }
    }

    private func ensureEngine() throws {
        guard !engine.isRunning else { return }
        let input = engine.inputNode
        let fmt = input.outputFormat(forBus: 0)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: fmt) { [weak self] buf, _ in
            self?.request?.append(buf)
            self?.meter(buf)
        }
        engine.prepare()
        try engine.start()
        tick?.invalidate()
        tick = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in self?.check() }
    }

    private func stopEngine() {
        tick?.invalidate(); tick = nil
        task?.cancel(); task = nil
        request?.endAudio(); request = nil
        if engine.isRunning { engine.stop() }
        engine.inputNode.removeTap(onBus: 0)
        onLevel?(0)
    }

    private func restartTask() {
        task?.cancel()
        request?.endAudio()
        heard = ""
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        if recognizer?.supportsOnDeviceRecognition == true { req.requiresOnDeviceRecognition = true }
        req.contextualStrings = ["Jarvis", "WhatsApp", "Spotify", "promemoria", "sveglia"]
        request = req
        taskStarted = Date()
        task = recognizer?.recognitionTask(with: req) { [weak self] res, err in
            DispatchQueue.main.async { self?.handle(res, err) }
        }
    }

    private func handle(_ res: SFSpeechRecognitionResult?, _ err: Error?) {
        if synth.isSpeaking && !capturing { return }   // don't hear ourselves
        guard let res else {
            if err != nil, hotword, !capturing { restartTask() }
            return
        }
        let text = res.bestTranscription.formattedString
        guard text != heard else { return }
        heard = text
        lastChange = Date()
        if capturing {
            command = afterWake(text) ?? (hotword ? command : text)
            onPartial?(command)
        } else if hotword, let rest = afterWake(text) {
            onWake?()
            stopSpeaking()
            beginCapture(initial: rest)
        }
    }

    private func beginCapture(initial: String) {
        capturing = true
        command = initial
        captureStart = Date()
        lastChange = Date()
        onListening?(true)
        if !initial.isEmpty { onPartial?(initial) }
    }

    /// Text after the last wake word, or nil if no wake word was said.
    private func afterWake(_ text: String) -> String? {
        let low = text.lowercased()
        var best: Range<String.Index>? = nil
        for w in Self.wakeWords {
            if let r = low.range(of: w, options: .backwards), best == nil || r.lowerBound > best!.lowerBound { best = r }
        }
        guard let r = best else { return nil }
        let rest = String(text[r.upperBound...]).trimmingCharacters(in: CharacterSet(charactersIn: " ,.!?"))
        return rest
    }

    private func check() {
        if capturing {
            let silence = Date().timeIntervalSince(lastChange)
            let total = Date().timeIntervalSince(captureStart)
            let cmd = command.trimmingCharacters(in: .whitespaces)
            if (!cmd.isEmpty && silence > 1.4) || total > 20 {
                capturing = false
                onListening?(false)
                if !cmd.isEmpty { onCommand?(cmd) }
                if hotword { restartTask() } else { stopEngine() }
            } else if cmd.isEmpty && silence > 6 {
                cancelListening()
            }
        } else if hotword, Date().timeIntervalSince(taskStarted) > 50 {
            restartTask()  // recognition tasks are limited to about a minute
        }
    }

    private func meter(_ buf: AVAudioPCMBuffer) {
        guard let ch = buf.floatChannelData?[0] else { return }
        let n = Int(buf.frameLength)
        var sum: Float = 0
        for i in stride(from: 0, to: n, by: 4) { sum += ch[i] * ch[i] }
        let rms = sqrt(sum / Float(max(n / 4, 1)))
        let db = 20 * log10(max(rms, 1e-6))
        let level = Double(max(0, min(1, (db + 50) / 40)))
        DispatchQueue.main.async { [weak self] in
            guard let self, self.capturing, Date().timeIntervalSince(self.lastLevelSent) > 0.04 else { return }
            self.lastLevelSent = Date()
            self.onLevel?(level)
        }
    }

    // MARK: speaking

    static func italianVoices() -> [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices().filter { $0.language == "it-IT" }
            .sorted { a, b in
                if a.quality != b.quality { return a.quality.rawValue > b.quality.rawValue }
                if a.gender != b.gender { return a.gender == .male }
                return a.name < b.name
            }
    }

    func speak(_ text: String) {
        let clean = text.replacing(/\[[a-z]{1,2}\d+\]/) { _ in "" }
            .replacingOccurrences(of: "*", with: "").replacingOccurrences(of: "#", with: "")
            .replacingOccurrences(of: "J.A.R.V.I.S.", with: "Jarvis")
        guard !clean.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        stopSpeaking()
        let u = AVSpeechUtterance(string: clean)
        u.voice = voiceID.flatMap { AVSpeechSynthesisVoice(identifier: $0) } ?? Self.italianVoices().first
        u.rate = 0.52
        u.pitchMultiplier = 0.95
        u.postUtteranceDelay = 0.05
        synth.speak(u)
    }

    func stopSpeaking() { if synth.isSpeaking { synth.stopSpeaking(at: .immediate) } }
    var isSpeaking: Bool { synth.isSpeaking }

    func speechSynthesizer(_ s: AVSpeechSynthesizer, didStart u: AVSpeechUtterance) {
        DispatchQueue.main.async { self.onSpeaking?(true) }
    }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, willSpeakRangeOfSpeechString r: NSRange, utterance u: AVSpeechUtterance) {
        // pulse the core on every word
        let lvl = 0.45 + Double(min(r.length, 10)) / 20
        DispatchQueue.main.async { self.onLevel?(lvl) }
    }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) {
        DispatchQueue.main.async { self.onLevel?(0); self.onSpeaking?(false) }
    }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel u: AVSpeechUtterance) {
        DispatchQueue.main.async { self.onLevel?(0); self.onSpeaking?(false) }
    }
}
