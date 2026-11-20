import Darwin
import Foundation
import JarvisCore

signal(SIGPIPE, SIG_IGN)
let argv = Array(CommandLine.arguments.dropFirst())

// Defense in depth: when the model runs `jarvis` (JARVIS_AGENT is set by ClaudeBridge) it can never confirm
// its own critical actions, even if a command slipped past Claude Code's --disallowedTools patterns.
if ProcessInfo.processInfo.environment["JARVIS_AGENT"] != nil, let c = argv.first, ["confirm", "cancel"].contains(c) {
    print("ERRORE: le conferme arrivano solo dall'interfaccia utente.")
    exit(1)
}

func printTurn(_ r: TurnResult) {
    if r.local {
        print("JARVIS [LOCALE, 0 token]: \(r.text)")
    } else {
        print("JARVIS [\(r.tier.rawValue)]: \(r.text)")
        let ctx = r.inputTokens + r.cacheRead + r.cacheWrite
        print(String(format: "   %.1fs | contesto %d tok (cache letta %d, scritta %d) | output %d tok | $%.5f",
                     Double(r.durationMs) / 1000, ctx, r.cacheRead, r.cacheWrite, r.outputTokens, r.costUSD))
    }
    if r.pendingConfirm != nil { print("   >> Azione critica in attesa: rispondi \"sì\" per confermare o \"no\" per annullare.") }
}

func converse(_ brain: JarvisBrain, _ text: String) {
    let sem = DispatchSemaphore(value: 0)
    brain.handle(text) { ev in
        switch ev {
        case .thinking(let t): print("   ... \(t.label)")
        case .tool(let c): print("   $ \(c)")
        case .toolResult(let t) where ProcessInfo.processInfo.environment["JARVIS_DEBUG"] != nil:
            print(t.split(separator: "\n").map { "     | " + $0 }.joined(separator: "\n"))
        case .done(let r): printTurn(r); sem.signal()
        default: break
        }
    }
    sem.wait()
}

switch argv.first {
case "ask":
    let brain = JarvisBrain()
    converse(brain, argv.dropFirst().joined(separator: " "))
    brain.shutdown()
case "chat":
    let brain = JarvisBrain()
    brain.prewarm()
    print("J.A.R.V.I.S. online. Scrivi un comando (vuoto per uscire). /sonnet, /opus o /fable per forzare il modello.")
    while true {
        print("> ", terminator: "")
        fflush(stdout)
        guard let line = readLine(), !line.trimmingCharacters(in: .whitespaces).isEmpty else { break }
        converse(brain, line)
    }
    brain.shutdown()
case "route":
    print(Router.route(argv.dropFirst().joined(separator: " ")))
default:
    let (out, code) = CLI.run(argv)
    // Output read by the model: cap its size (JARVIS_TOOL_OUTPUT_MAX, default 6 KB) to save input tokens.
    let shown = ProcessInfo.processInfo.environment["JARVIS_AGENT"] != nil ? OutputCap.apply(out) : out
    if !shown.isEmpty { print(shown) }
    exit(code)
}
