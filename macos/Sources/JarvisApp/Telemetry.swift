import Darwin
import Foundation
import IOKit.ps

/// Cheap system telemetry (one sample per second, a few syscalls).
final class Telemetry {
    private var prevTicks: (UInt32, UInt32, UInt32, UInt32)?
    private var prevNet: (UInt64, UInt64, Date)?

    /// "MACOS 15.1 // APPLE SILICON": shown in the HUD telemetry title instead of a fixed machine name.
    static let osLabel: String = {
        let v = ProcessInfo.processInfo.operatingSystemVersion
        #if arch(arm64)
        let cpu = "APPLE SILICON"
        #else
        let cpu = "INTEL"
        #endif
        return "macOS \(v.majorVersion).\(v.minorVersion) // \(cpu)"
    }()

    func sample() -> [String: Any] {
        let (inRate, outRate) = network()
        let b = battery()
        return [
            "type": "telemetry",
            "cpu": cpu(),
            "ramUsed": ramUsedGB(),
            "ramTotal": Double(ProcessInfo.processInfo.physicalMemory) / 1_073_741_824,
            "batt": b.percent, "charging": b.charging, "ac": b.ac,
            "netIn": inRate, "netOut": outRate,
            "thermal": thermal(),
            "uptime": ProcessInfo.processInfo.systemUptime,
            "os": Self.osLabel,
        ]
    }

    private func cpu() -> Double {
        var load = host_cpu_load_info()
        var count = mach_msg_type_number_t(MemoryLayout<host_cpu_load_info>.stride / MemoryLayout<integer_t>.stride)
        let r = withUnsafeMutablePointer(to: &load) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                host_statistics(mach_host_self(), HOST_CPU_LOAD_INFO, $0, &count)
            }
        }
        guard r == KERN_SUCCESS else { return 0 }
        let t = load.cpu_ticks // user, system, idle, nice
        defer { prevTicks = t }
        guard let p = prevTicks else { return 0 }
        let user = Double(t.0 &- p.0), sys = Double(t.1 &- p.1), idle = Double(t.2 &- p.2), nice = Double(t.3 &- p.3)
        let total = user + sys + idle + nice
        return total > 0 ? (user + sys + nice) / total * 100 : 0
    }

    private func ramUsedGB() -> Double {
        var stats = vm_statistics64()
        var count = mach_msg_type_number_t(MemoryLayout<vm_statistics64>.stride / MemoryLayout<integer_t>.stride)
        let r = withUnsafeMutablePointer(to: &stats) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                host_statistics64(mach_host_self(), HOST_VM_INFO64, $0, &count)
            }
        }
        guard r == KERN_SUCCESS else { return 0 }
        let page = Double(vm_kernel_page_size)
        // "Memory used" as Activity Monitor: app (internal - purgeable) + wired + compressed
        let app = Double(stats.internal_page_count) - Double(stats.purgeable_count)
        return (app + Double(stats.wire_count) + Double(stats.compressor_page_count)) * page / 1_073_741_824
    }

    private func battery() -> (percent: Int, charging: Bool, ac: Bool) {
        guard let info = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
              let list = IOPSCopyPowerSourcesList(info)?.takeRetainedValue() as? [CFTypeRef] else { return (-1, false, false) }
        for ps in list {
            guard let d = IOPSGetPowerSourceDescription(info, ps)?.takeUnretainedValue() as? [String: Any] else { continue }
            let cur = d[kIOPSCurrentCapacityKey] as? Int ?? 0, max = d[kIOPSMaxCapacityKey] as? Int ?? 100
            let charging = d[kIOPSIsChargingKey] as? Bool ?? false
            let ac = (d[kIOPSPowerSourceStateKey] as? String) == kIOPSACPowerValue
            return (max > 0 ? cur * 100 / max : cur, charging, ac)
        }
        return (-1, false, false)
    }

    private func network() -> (Double, Double) {
        var ibytes: UInt64 = 0, obytes: UInt64 = 0
        var ifap: UnsafeMutablePointer<ifaddrs>?
        if getifaddrs(&ifap) == 0 {
            var p = ifap
            while let ifa = p?.pointee {
                if ifa.ifa_addr?.pointee.sa_family == UInt8(AF_LINK), let data = ifa.ifa_data,
                   String(cString: ifa.ifa_name).hasPrefix("en") {
                    let d = data.assumingMemoryBound(to: if_data.self).pointee
                    ibytes += UInt64(d.ifi_ibytes); obytes += UInt64(d.ifi_obytes)
                }
                p = ifa.ifa_next
            }
            freeifaddrs(ifap)
        }
        let now = Date()
        defer { prevNet = (ibytes, obytes, now) }
        guard let (pi, po, pt) = prevNet else { return (0, 0) }
        let dt = max(now.timeIntervalSince(pt), 0.1)
        // 32-bit counters may wrap: ignore negative deltas
        let di = ibytes >= pi ? Double(ibytes - pi) : 0, dout = obytes >= po ? Double(obytes - po) : 0
        return (di / dt, dout / dt)
    }

    private func thermal() -> String {
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: return "NOMINALE"
        case .fair: return "MODERATO"
        case .serious: return "ELEVATO"
        case .critical: return "CRITICO"
        @unknown default: return "--"
        }
    }
}
