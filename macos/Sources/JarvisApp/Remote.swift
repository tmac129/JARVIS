import AppKit
import CoreImage
import Foundation
import JarvisCore
import Network

/// Tiny HTTP server on the local network so the iPhone can talk to JARVIS:
///  - GET  /?token=...     mobile web app (add it to the Home Screen)
///  - POST /ask            body: text or {"text": "..."}; header "Authorization: Bearer <token>" or ?token=
/// Same brain, same confirmation gate. Off unless enabled from the menu.
final class RemoteServer {
    static let port: UInt16 = 8787
    private var listener: NWListener?
    private let q = DispatchQueue(label: "jarvis.remote")
    let token: String
    var handler: ((String, Bool, @escaping (String) -> Void) -> Void)?
    var pageHTML: () -> String = { "" }

    init() {
        struct Cfg: Codable { let token: String }
        if let c = Store.load("remote.json", Cfg.self) { token = c.token }
        else {
            let chars = Array("abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789")
            token = String((0..<24).map { _ in chars.randomElement()! })
            Store.save("remote.json", Cfg(token: token))
        }
    }

    var isRunning: Bool { listener != nil }

    func start() throws {
        guard listener == nil else { return }
        let l = try NWListener(using: .tcp, on: NWEndpoint.Port(rawValue: Self.port)!)
        // Advertising on Bonjour makes macOS ask for the "Local Network" permission (Info.plist
        // NSLocalNetworkUsageDescription). Without that permission the iPhone connects but never gets an answer.
        l.service = NWListener.Service(name: "JARVIS", type: "_jarvis._tcp")
        l.newConnectionHandler = { [weak self] c in
            guard let self else { return }
            c.start(queue: self.q)
            self.receive(c, Data())
            // no connection may stay open forever (slow or idle clients); long model turns fit well within this
            self.q.asyncAfter(deadline: .now() + 300) { if c.state != .cancelled { c.cancel() } }
        }
        l.start(queue: q)
        listener = l
    }

    func stop() { listener?.cancel(); listener = nil }

    // MARK: addresses

    static func localAddresses() -> [String] {
        var out: [String] = [], names: [String] = []
        var ifap: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifap) == 0 else { return out }
        var p = ifap
        while let ifa = p?.pointee {
            let name = String(cString: ifa.ifa_name)
            if ifa.ifa_addr.pointee.sa_family == UInt8(AF_INET), name.hasPrefix("en") || name.hasPrefix("utun") {
                var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                getnameinfo(ifa.ifa_addr, socklen_t(ifa.ifa_addr.pointee.sa_len), &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST)
                let ip = String(cString: host)
                if !ip.hasPrefix("127.") && !ip.hasPrefix("169.254") { out.append(ip); names.append(name) }
            }
            p = ifa.ifa_next
        }
        freeifaddrs(ifap)
        // Wi-Fi / Ethernet first (what the iPhone on the same network can reach), then VPN (Tailscale 100.x)
        return out.enumerated().sorted { a, b in
            let ra = names[a.offset].hasPrefix("en") ? 0 : 1, rb = names[b.offset].hasPrefix("en") ? 0 : 1
            return ra != rb ? ra < rb : a.offset < b.offset
        }.map(\.element)
    }

    static var bonjourName: String {
        ((try? runProcess("/usr/sbin/scutil", ["--get", "LocalHostName"]).out) ?? "mac") + ".local"
    }

    func url(host: String) -> String { "http://\(host):\(Self.port)/?token=\(token)" }

    static func qrImage(_ text: String) -> NSImage? {
        guard let f = CIFilter(name: "CIQRCodeGenerator") else { return nil }
        f.setValue(Data(text.utf8), forKey: "inputMessage")
        f.setValue("M", forKey: "inputCorrectionLevel")
        guard let ci = f.outputImage?.transformed(by: CGAffineTransform(scaleX: 8, y: 8)) else { return nil }
        let rep = NSCIImageRep(ciImage: ci)
        let img = NSImage(size: rep.size)
        img.addRepresentation(rep)
        return img
    }

    // MARK: HTTP

    private func receive(_ c: NWConnection, _ buf: Data) {
        c.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, done, err in
            guard let self else { return }
            var b = buf
            if let data { b.append(data) }
            if let req = Self.parse(b) { self.route(req, c) }
            else if done || err != nil || b.count > 1_000_000 { c.cancel() }
            else { self.receive(c, b) }
        }
    }

    struct Request { let method: String; let path: String; let query: [String: String]; let headers: [String: String]; let body: Data }

    static let maxBody = 1_000_000

    /// Constant-time comparison: the token check must not leak how many characters matched.
    static func sameToken(_ a: String?, _ b: String) -> Bool {
        guard let a else { return false }
        let x = Array(a.utf8), y = Array(b.utf8)
        var diff = x.count ^ y.count
        for i in 0..<max(x.count, y.count) { diff |= Int((i < x.count ? x[i] : 0) ^ (i < y.count ? y[i] : 0)) }
        return diff == 0
    }

    /// Returns nil while the request is incomplete; method "BAD" for a malformed one (answered 400 before auth).
    static func parse(_ d: Data) -> Request? {
        guard let sep = d.range(of: Data("\r\n\r\n".utf8)) else { return nil }
        let head = String(decoding: d[..<sep.lowerBound], as: UTF8.self).components(separatedBy: "\r\n")
        let first = head.first?.split(separator: " ") ?? []
        guard first.count >= 2 else { return nil }
        var headers: [String: String] = [:]
        for l in head.dropFirst() {
            if let i = l.firstIndex(of: ":") { headers[l[..<i].lowercased()] = l[l.index(after: i)...].trimmingCharacters(in: .whitespaces) }
        }
        let body = d[sep.upperBound...]
        // a negative or huge Content-Length used to crash the app (Data.prefix with a negative length)
        guard let len = Int(headers["content-length"] ?? "0"), len >= 0, len <= maxBody else {
            return Request(method: "BAD", path: "", query: [:], headers: [:], body: Data())
        }
        guard body.count >= len else { return nil }
        let comps = URLComponents(string: String(first[1]))
        var q: [String: String] = [:]
        for it in comps?.queryItems ?? [] { q[it.name] = it.value ?? "" }
        return Request(method: String(first[0]), path: comps?.path ?? "/", query: q, headers: headers, body: Data(body.prefix(len)))
    }

    private func route(_ r: Request, _ c: NWConnection) {
        if r.method == "BAD" { return respond(c, 400, "text/plain", "Richiesta non valida.") }
        // Home Screen icon: Safari asks for it without the token, and it contains nothing private
        if r.method == "GET", r.path == "/apple-touch-icon.png" || r.path == "/apple-touch-icon-precomposed.png" {
            return respondData(c, 200, "image/png", Self.iconPNG)
        }
        let auth = r.query["token"] ?? r.headers["authorization"]?.replacingOccurrences(of: "Bearer ", with: "")
        guard Self.sameToken(auth, token) else { return respond(c, 401, "text/plain", "Token mancante o errato.") }
        switch (r.method, r.path) {
        case ("GET", "/ping"):
            respond(c, 200, "text/plain", "ok")
        case ("GET", "/"):
            respond(c, 200, "text/html; charset=utf-8", pageHTML().replacingOccurrences(of: "__TOKEN__", with: token))
        case ("POST", "/ask"), ("POST", "/ask.json"):
            var text = String(decoding: r.body, as: UTF8.self)
            if let o = try? JSONSerialization.jsonObject(with: r.body) as? [String: Any], let t = o["text"] as? String { text = t }
            text = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else { return respond(c, 400, "text/plain", "Testo vuoto.") }
            DispatchQueue.main.async {
                let json = r.path.hasSuffix(".json")
                self.handler?(text, json) { reply in
                    self.q.async { self.respond(c, 200, json ? "application/json" : "text/plain; charset=utf-8", reply) }
                }
            }
        default:
            respond(c, 404, "text/plain", "Non trovato.")
        }
    }

    static let iconPNG: Data = {
        guard let url = Bundle.main.url(forResource: "AppIcon", withExtension: "icns"), let img = NSImage(contentsOf: url) else { return Data() }
        let px = 180
        guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8, samplesPerPixel: 4,
                                         hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return Data() }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        NSColor(red: 0.012, green: 0.031, blue: 0.067, alpha: 1).setFill()
        NSRect(x: 0, y: 0, width: px, height: px).fill()
        img.draw(in: NSRect(x: 0, y: 0, width: px, height: px))
        NSGraphicsContext.restoreGraphicsState()
        return rep.representation(using: .png, properties: [:]) ?? Data()
    }()

    private func respond(_ c: NWConnection, _ code: Int, _ type: String, _ body: String) {
        respondData(c, code, type, Data(body.utf8))
    }

    private func respondData(_ c: NWConnection, _ code: Int, _ type: String, _ b: Data) {
        let status = [200: "OK", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found"][code] ?? "OK"
        let head = "HTTP/1.1 \(code) \(status)\r\nContent-Type: \(type)\r\nContent-Length: \(b.count)\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"
        c.send(content: Data(head.utf8) + b, completion: .contentProcessed { _ in c.cancel() })
    }
}

