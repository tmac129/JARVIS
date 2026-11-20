// Renders the J.A.R.V.I.S. app icon (arc-core style) into an .iconset. Usage: swift make_icon.swift <out.iconset>
import AppKit

func render(_ px: Int) -> Data {
    let s = CGFloat(px)
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8, samplesPerPixel: 4,
                               hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let ctx = NSGraphicsContext.current!.cgContext
    let cyan = NSColor(red: 0, green: 0.9, blue: 1, alpha: 1)
    // rounded-square plate (macOS grid: 824/1024 content)
    let inset = s * 0.098, r = NSRect(x: inset, y: inset, width: s - 2 * inset, height: s - 2 * inset)
    let plate = NSBezierPath(roundedRect: r, xRadius: r.width * 0.225, yRadius: r.width * 0.225)
    NSGradient(colors: [NSColor(red: 0.04, green: 0.09, blue: 0.16, alpha: 1), NSColor(red: 0.01, green: 0.03, blue: 0.07, alpha: 1)])!
        .draw(in: plate, angle: -90)
    plate.addClip()
    let c = NSPoint(x: s / 2, y: s / 2), R = r.width * 0.36
    // glow
    NSGradient(colors: [cyan.withAlphaComponent(0.45), cyan.withAlphaComponent(0)])!
        .draw(fromCenter: c, radius: 0, toCenter: c, radius: R * 1.5, options: [])
    ctx.setLineCap(.butt)
    func arc(_ rad: CGFloat, _ w: CGFloat, _ a: CGFloat, _ segs: [(CGFloat, CGFloat)]) {
        ctx.setStrokeColor(cyan.withAlphaComponent(a).cgColor); ctx.setLineWidth(w)
        for (st, len) in segs {
            ctx.addArc(center: c, radius: rad, startAngle: st * .pi * 2, endAngle: (st + len) * .pi * 2, clockwise: false)
            ctx.strokePath()
        }
    }
    arc(R * 1.18, s * 0.006, 0.5, [(0, 1)])
    arc(R * 1.05, s * 0.022, 0.9, [(0.02, 0.2), (0.27, 0.2), (0.52, 0.2), (0.77, 0.2)])
    arc(R * 0.86, s * 0.008, 0.6, [(0.1, 0.35), (0.6, 0.35)])
    // ticks
    ctx.setStrokeColor(cyan.withAlphaComponent(0.55).cgColor); ctx.setLineWidth(s * 0.004)
    for i in 0..<60 {
        let a = CGFloat(i) / 60 * .pi * 2, r1 = R * 1.26, r2 = r1 + (i % 5 == 0 ? s * 0.03 : s * 0.014)
        ctx.move(to: CGPoint(x: c.x + cos(a) * r1, y: c.y + sin(a) * r1)); ctx.addLine(to: CGPoint(x: c.x + cos(a) * r2, y: c.y + sin(a) * r2))
    }
    ctx.strokePath()
    // reactor segments
    arc(R * 0.55, s * 0.05, 0.85, (0..<10).map { (CGFloat($0) / 10 + 0.01, 0.07) })
    // core
    NSGradient(colors: [.white, cyan, cyan.withAlphaComponent(0)], atLocations: [0, 0.35, 1], colorSpace: .deviceRGB)!
        .draw(fromCenter: c, radius: 0, toCenter: c, radius: R * 0.42, options: [])
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

let out = CommandLine.arguments[1]
try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)
for (name, px) in [("16x16", 16), ("16x16@2x", 32), ("32x32", 32), ("32x32@2x", 64), ("128x128", 128), ("128x128@2x", 256),
                   ("256x256", 256), ("256x256@2x", 512), ("512x512", 512), ("512x512@2x", 1024)] {
    try! render(px).write(to: URL(fileURLWithPath: "\(out)/icon_\(name).png"))
}
