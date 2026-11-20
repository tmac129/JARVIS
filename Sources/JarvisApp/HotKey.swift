import Carbon.HIToolbox
import Foundation

/// System-wide hotkeys via Carbon RegisterEventHotKey (no Accessibility permission needed).
final class HotKeys {
    private static var handlers: [UInt32: () -> Void] = [:]
    private static var installed = false
    private var refs: [EventHotKeyRef?] = []

    func register(keyCode: Int, modifiers: Int, id: UInt32, _ action: @escaping () -> Void) {
        HotKeys.installIfNeeded()
        HotKeys.handlers[id] = action
        var ref: EventHotKeyRef?
        let hkID = EventHotKeyID(signature: OSType(0x4A525653), id: id) // 'JRVS'
        RegisterEventHotKey(UInt32(keyCode), UInt32(modifiers), hkID, GetApplicationEventTarget(), 0, &ref)
        refs.append(ref)
    }

    private static func installIfNeeded() {
        guard !installed else { return }
        installed = true
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, event, _ -> OSStatus in
            var hk = EventHotKeyID()
            GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                              nil, MemoryLayout<EventHotKeyID>.size, nil, &hk)
            DispatchQueue.main.async { HotKeys.handlers[hk.id]?() }
            return noErr
        }, 1, &spec, nil, nil)
    }
}
