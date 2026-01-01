import Foundation
import Network

/// Service for discovering Wormhole daemons via Bonjour/mDNS
final class BonjourDiscoveryService: @unchecked Sendable {
    private let serviceType = "_wormhole._tcp"
    private var browser: NWBrowser?
    private var discoveredMachines: [String: Machine] = [:]
    private let onMachinesUpdated: @Sendable ([Machine]) -> Void

    init(onMachinesUpdated: @escaping @Sendable ([Machine]) -> Void) {
        self.onMachinesUpdated = onMachinesUpdated
    }

    func startBrowsing() {
        let parameters = NWParameters()
        parameters.includePeerToPeer = true

        browser = NWBrowser(for: .bonjour(type: serviceType, domain: nil), using: parameters)

        browser?.browseResultsChangedHandler = { [weak self] results, changes in
            self?.handleBrowseResults(results, changes: changes)
        }

        browser?.stateUpdateHandler = { state in
            switch state {
            case .ready:
                print("Bonjour browser ready")
            case .failed(let error):
                print("Bonjour browser failed: \(error)")
            case .cancelled:
                print("Bonjour browser cancelled")
            default:
                break
            }
        }

        browser?.start(queue: .main)
    }

    func stopBrowsing() {
        browser?.cancel()
        browser = nil
        discoveredMachines.removeAll()
    }

    private func handleBrowseResults(_ results: Set<NWBrowser.Result>, changes: Set<NWBrowser.Result.Change>) {
        for change in changes {
            switch change {
            case .added(let result):
                resolveService(result)
            case .removed(let result):
                removeService(result)
            case .changed(_, let newResult, _):
                resolveService(newResult)
            case .identical:
                break
            @unknown default:
                break
            }
        }
    }

    private func resolveService(_ result: NWBrowser.Result) {
        guard case .service(let name, _, _, _) = result.endpoint else {
            return
        }

        let connection = NWConnection(to: result.endpoint, using: .tcp)

        connection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                if let path = connection.currentPath,
                   let endpoint = path.remoteEndpoint,
                   case .hostPort(let host, let port) = endpoint {

                    let hostString: String
                    switch host {
                    case .ipv4(let addr):
                        hostString = "\(addr)"
                    case .ipv6(let addr):
                        hostString = "\(addr)"
                    case .name(let hostname, _):
                        hostString = hostname
                    @unknown default:
                        hostString = "unknown"
                    }

                    let machine = Machine(
                        id: name,
                        name: name,
                        host: hostString,
                        port: Int(port.rawValue),
                        isManual: false
                    )

                    self?.discoveredMachines[name] = machine
                    self?.notifyMachinesUpdated()
                }
                connection.cancel()

            case .failed, .cancelled:
                connection.cancel()

            default:
                break
            }
        }

        connection.start(queue: .main)

        // Timeout after 5 seconds
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) {
            if connection.state != .ready && connection.state != .cancelled {
                connection.cancel()
            }
        }
    }

    private func removeService(_ result: NWBrowser.Result) {
        guard case .service(let name, _, _, _) = result.endpoint else {
            return
        }
        discoveredMachines.removeValue(forKey: name)
        notifyMachinesUpdated()
    }

    private func notifyMachinesUpdated() {
        let machines = Array(discoveredMachines.values)
        onMachinesUpdated(machines)
    }
}
