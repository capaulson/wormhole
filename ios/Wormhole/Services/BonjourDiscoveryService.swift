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
            print("[Bonjour] State changed: \(oldValue) -> \(state)")
        }
    }

    init() {
        print("[Bonjour] BonjourDiscoveryService initialized")
    }

    func startBrowsing() {
        print("[Bonjour] startBrowsing() called, browser exists: \(browser != nil)")
        guard browser == nil else {
            logger.debug("Browser already running")
            print("[Bonjour] Browser already running, skipping")
            return
        }

        let parameters = NWParameters()
        parameters.includePeerToPeer = true
        print("[Bonjour] Created NWParameters with includePeerToPeer=true")

        // Explicitly specify "local." domain for mDNS discovery
        let descriptor = NWBrowser.Descriptor.bonjour(type: serviceType, domain: "local.")
        print("[Bonjour] Browser descriptor: type=\(serviceType), domain=local.")

        browser = NWBrowser(for: descriptor, using: parameters)
        print("[Bonjour] Created NWBrowser")

        browser?.browseResultsChangedHandler = { [weak self] results, changes in
            print("[Bonjour] browseResultsChangedHandler called: \(results.count) results, \(changes.count) changes")
            for result in results {
                print("[Bonjour]   Result: \(result.endpoint.debugDescription)")
            }
            Task { @MainActor [weak self] in
                self?.handleBrowseResults(results, changes: changes)
            }
        }

        browser?.stateUpdateHandler = { [weak self] newState in
            print("[Bonjour] stateUpdateHandler called: \(newState)")
            Task { @MainActor [weak self] in
                self?.handleBrowserState(newState)
            }
        }

        logger.info("Starting Bonjour browser for \(self.serviceType) in domain local.")
        print("[Bonjour] Calling browser.start(queue: .main)")
        browser?.start(queue: .main)
        print("[Bonjour] browser.start() called")
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
        print("[Bonjour] handleBrowserState: \(newState)")
        switch newState {
        case .setup:
            logger.debug("Browser setup")
            print("[Bonjour] State: setup - configuring browser")
        case .ready:
            logger.info("Browser ready - scanning for services")
            print("[Bonjour] State: ready - NOW ACTIVELY SCANNING for \(serviceType) in local.")
            state = .browsing
        case .failed(let error):
            logger.error("Browser failed: \(error.localizedDescription)")
            print("[Bonjour] State: FAILED - \(error.localizedDescription)")
            print("[Bonjour] Error details: \(error)")
            state = .failed(error.localizedDescription)
        case .cancelled:
            logger.debug("Browser cancelled")
            print("[Bonjour] State: cancelled")
            state = .idle
        case .waiting(let error):
            // This often happens on simulator when network isn't ready
            logger.warning("Browser waiting: \(error.localizedDescription)")
            print("[Bonjour] State: waiting - \(error.localizedDescription)")
            print("[Bonjour] Waiting error details: \(error)")
            state = .browsing  // Still consider it as browsing, just waiting
        @unknown default:
            logger.debug("Browser unknown state")
            print("[Bonjour] State: unknown default")
        }
    }

    private func handleBrowseResults(_ results: Set<NWBrowser.Result>, changes: Set<NWBrowser.Result.Change>) {
        logger.debug("Browse results changed: \(results.count) services, \(changes.count) changes")
        print("[Bonjour] handleBrowseResults: \(results.count) total results, \(changes.count) changes")

        for change in changes {
            switch change {
            case .added(let result):
                logger.info("Service added: \(result.endpoint.debugDescription)")
                print("[Bonjour] SERVICE ADDED: \(result.endpoint.debugDescription)")
                print("[Bonjour]   Metadata: \(result.metadata)")
                print("[Bonjour]   Interfaces: \(result.interfaces)")
                resolveService(result)
            case .removed(let result):
                logger.info("Service removed: \(result.endpoint.debugDescription)")
                print("[Bonjour] SERVICE REMOVED: \(result.endpoint.debugDescription)")
                removeService(result)
            case .changed(_, let newResult, _):
                logger.debug("Service changed: \(newResult.endpoint.debugDescription)")
                print("[Bonjour] SERVICE CHANGED: \(newResult.endpoint.debugDescription)")
                resolveService(newResult)
            case .identical:
                print("[Bonjour] Change: identical")
                break
            @unknown default:
                print("[Bonjour] Change: unknown")
                break
            }
        }
    }

    private func resolveService(_ result: NWBrowser.Result) {
        guard case .service(let name, let type, let domain, _) = result.endpoint else {
            logger.warning("Unexpected endpoint type in browse result")
            print("[Bonjour] resolveService: Unexpected endpoint type: \(result.endpoint.debugDescription)")
            return
        }

        logger.debug("Resolving service: \(name) (\(type) in \(domain))")
        print("[Bonjour] resolveService: name=\(name), type=\(type), domain=\(domain)")

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
        print("[Bonjour] handleConnectionState for \(serviceName): \(connectionState)")
        switch connectionState {
        case .ready:
            if let path = connection.currentPath,
               let endpoint = path.remoteEndpoint,
               case .hostPort(let host, let port) = endpoint {

                let hostString = extractHostString(from: host)

                logger.info("Resolved \(serviceName) to \(hostString):\(port.rawValue)")
                print("[Bonjour] RESOLVED: \(serviceName) -> \(hostString):\(port.rawValue)")

                let machine = Machine(
                    id: serviceName,
                    name: serviceName,
                    host: hostString,
                    port: Int(port.rawValue),
                    isManual: false
                )
                print("[Bonjour] Created Machine: id=\(machine.id), name=\(machine.name), host=\(machine.host), port=\(machine.port)")

                discoveredMachines[serviceName] = machine
                notifyMachinesUpdated()
            } else {
                logger.warning("Could not extract endpoint for \(serviceName)")
                print("[Bonjour] WARNING: Could not extract endpoint for \(serviceName)")
                print("[Bonjour]   path: \(String(describing: connection.currentPath))")
                print("[Bonjour]   remoteEndpoint: \(String(describing: connection.currentPath?.remoteEndpoint))")
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
        let rawString: String
        switch host {
        case .ipv4(let addr):
            rawString = "\(addr)"
        case .ipv6(let addr):
            rawString = "\(addr)"
        case .name(let hostname, _):
            return hostname
        @unknown default:
            return "unknown"
        }

        // Strip interface scope identifier (e.g., "%en0") which is invalid in URLs
        if let percentIndex = rawString.firstIndex(of: "%") {
            let stripped = String(rawString[..<percentIndex])
            print("[Bonjour] Stripped interface scope: \(rawString) -> \(stripped)")
            return stripped
        }
        return rawString
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
