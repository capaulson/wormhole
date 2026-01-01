import Foundation
import Network
import os.log

/// Discovery state for UI feedback
enum DiscoveryState: Equatable {
    case idle
    case browsing
    case failed(String)
}

/// Service for discovering Wormhole daemons via Bonjour/mDNS
@MainActor
final class BonjourDiscoveryService {
    private let serviceType = "_wormhole._tcp"
    private var browser: NWBrowser?
    private var discoveredMachines: [String: Machine] = [:]
    private var pendingConnections: [String: NWConnection] = [:]

    private let logger = Logger(subsystem: "com.wormhole", category: "Bonjour")

    var onMachinesUpdated: (([Machine]) -> Void)?
    var onStateChanged: ((DiscoveryState) -> Void)?

    private(set) var state: DiscoveryState = .idle {
        didSet {
            onStateChanged?(state)
        }
    }

    init() {}

    func startBrowsing() {
        guard browser == nil else {
            logger.debug("Browser already running")
            return
        }

        let parameters = NWParameters()
        parameters.includePeerToPeer = true

        browser = NWBrowser(for: .bonjour(type: serviceType, domain: nil), using: parameters)

        browser?.browseResultsChangedHandler = { [weak self] results, changes in
            Task { @MainActor [weak self] in
                self?.handleBrowseResults(results, changes: changes)
            }
        }

        browser?.stateUpdateHandler = { [weak self] newState in
            Task { @MainActor [weak self] in
                self?.handleBrowserState(newState)
            }
        }

        logger.info("Starting Bonjour browser for \(self.serviceType)")
        browser?.start(queue: .main)
    }

    func stopBrowsing() {
        logger.info("Stopping Bonjour browser")
        browser?.cancel()
        browser = nil

        // Cancel all pending connections
        for (_, connection) in pendingConnections {
            connection.cancel()
        }
        pendingConnections.removeAll()
        discoveredMachines.removeAll()
        state = .idle
    }

    private func handleBrowserState(_ newState: NWBrowser.State) {
        switch newState {
        case .setup:
            logger.debug("Browser setup")
        case .ready:
            logger.info("Browser ready - scanning for services")
            state = .browsing
        case .failed(let error):
            logger.error("Browser failed: \(error.localizedDescription)")
            state = .failed(error.localizedDescription)
        case .cancelled:
            logger.debug("Browser cancelled")
            state = .idle
        case .waiting(let error):
            // This often happens on simulator when network isn't ready
            logger.warning("Browser waiting: \(error.localizedDescription)")
            state = .browsing  // Still consider it as browsing, just waiting
        @unknown default:
            logger.debug("Browser unknown state")
        }
    }

    private func handleBrowseResults(_ results: Set<NWBrowser.Result>, changes: Set<NWBrowser.Result.Change>) {
        logger.debug("Browse results changed: \(results.count) services, \(changes.count) changes")

        for change in changes {
            switch change {
            case .added(let result):
                logger.info("Service added: \(result.endpoint.debugDescription)")
                resolveService(result)
            case .removed(let result):
                logger.info("Service removed: \(result.endpoint.debugDescription)")
                removeService(result)
            case .changed(_, let newResult, _):
                logger.debug("Service changed: \(newResult.endpoint.debugDescription)")
                resolveService(newResult)
            case .identical:
                break
            @unknown default:
                break
            }
        }
    }

    private func resolveService(_ result: NWBrowser.Result) {
        guard case .service(let name, let type, let domain, _) = result.endpoint else {
            logger.warning("Unexpected endpoint type in browse result")
            return
        }

        logger.debug("Resolving service: \(name) (\(type) in \(domain))")

        // Cancel any existing connection attempt for this service
        pendingConnections[name]?.cancel()

        // Create connection to resolve the service endpoint
        let connection = NWConnection(to: result.endpoint, using: .tcp)
        pendingConnections[name] = connection

        connection.stateUpdateHandler = { [weak self] connectionState in
            Task { @MainActor [weak self] in
                self?.handleConnectionState(connectionState, serviceName: name, connection: connection)
            }
        }

        connection.start(queue: .main)

        // Timeout resolution after 10 seconds
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(10))
            guard let self = self else { return }
            if self.pendingConnections[name] === connection {
                self.logger.warning("Resolution timeout for \(name)")
                connection.cancel()
                self.pendingConnections.removeValue(forKey: name)
            }
        }
    }

    private func handleConnectionState(_ connectionState: NWConnection.State, serviceName: String, connection: NWConnection) {
        switch connectionState {
        case .ready:
            if let path = connection.currentPath,
               let endpoint = path.remoteEndpoint,
               case .hostPort(let host, let port) = endpoint {

                let hostString = extractHostString(from: host)

                logger.info("Resolved \(serviceName) to \(hostString):\(port.rawValue)")

                let machine = Machine(
                    id: serviceName,
                    name: serviceName,
                    host: hostString,
                    port: Int(port.rawValue),
                    isManual: false
                )

                discoveredMachines[serviceName] = machine
                notifyMachinesUpdated()
            } else {
                logger.warning("Could not extract endpoint for \(serviceName)")
            }

            // Clean up
            connection.cancel()
            pendingConnections.removeValue(forKey: serviceName)

        case .failed(let error):
            logger.error("Connection failed for \(serviceName): \(error.localizedDescription)")
            connection.cancel()
            pendingConnections.removeValue(forKey: serviceName)

        case .cancelled:
            pendingConnections.removeValue(forKey: serviceName)

        case .waiting(let error):
            logger.debug("Connection waiting for \(serviceName): \(error.localizedDescription)")

        default:
            break
        }
    }

    private func extractHostString(from host: NWEndpoint.Host) -> String {
        switch host {
        case .ipv4(let addr):
            return "\(addr)"
        case .ipv6(let addr):
            // For IPv6, check if it's a link-local that might be scoped
            let addrString = "\(addr)"
            // Prefer IPv4 if available, but IPv6 works too
            return addrString
        case .name(let hostname, _):
            return hostname
        @unknown default:
            return "unknown"
        }
    }

    private func removeService(_ result: NWBrowser.Result) {
        guard case .service(let name, _, _, _) = result.endpoint else {
            return
        }

        // Cancel any pending connection
        pendingConnections[name]?.cancel()
        pendingConnections.removeValue(forKey: name)

        discoveredMachines.removeValue(forKey: name)
        notifyMachinesUpdated()
    }

    private func notifyMachinesUpdated() {
        let machines = Array(discoveredMachines.values).sorted { $0.name < $1.name }
        onMachinesUpdated?(machines)
    }
}
