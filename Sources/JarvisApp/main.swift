import AppKit
import Darwin
import JarvisCore

// Writing to a pipe whose reader died (e.g. the claude process) must return an error, not kill the app.
signal(SIGPIPE, SIG_IGN)

// Self-test hook: run a tool *as JARVIS.app* (its own privacy permissions) and write the result.
//   open -n -a JARVIS --args --run mail unread 3   ->  ~/Library/Application Support/JARVIS/selftest.txt
if let i = CommandLine.arguments.firstIndex(of: "--run") {
    let (out, code) = CLI.run(Array(CommandLine.arguments[(i + 1)...]))
    try? "exit \(code)\n\(out)\n".write(to: Paths.file("selftest.txt"), atomically: true, encoding: .utf8)
    exit(code)
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular) // Dock icon + menu bar item
app.run()
