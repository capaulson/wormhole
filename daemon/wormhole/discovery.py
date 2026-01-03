"""mDNS/Bonjour service advertisement."""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import TYPE_CHECKING

from wormhole.platform import check_mdns_support, is_linux

if TYPE_CHECKING:
    from zeroconf import ServiceInfo, Zeroconf

logger = logging.getLogger(__name__)


class DiscoveryAdvertiser:
    """Advertise Wormhole service via mDNS/Bonjour."""

    # Service type must end with .local. for zeroconf
    SERVICE_TYPE = "_wormhole._tcp.local."

    def __init__(self, port: int = 7117, machine_name: str | None = None) -> None:
        self.port = port
        # Get hostname and strip domain suffixes (.local, .localdomain, etc.)
        raw_hostname = machine_name or socket.gethostname()
        # Take only the first component (before any dots)
        self.machine_name = raw_hostname.split(".")[0]
        self._zeroconf: Zeroconf | None = None
        self._info: ServiceInfo | None = None
        self._running = False

    async def start(self) -> None:
        """Start advertising the service."""
        if self._running:
            return

        from zeroconf import IPVersion, ServiceInfo, Zeroconf

        # Check platform mDNS support
        mdns_ok, mdns_msg = check_mdns_support()
        if not mdns_ok:
            logger.warning(f"mDNS may not work: {mdns_msg}")
            if is_linux():
                logger.warning(
                    "On Linux, install and start Avahi for device discovery: "
                    "sudo apt install avahi-daemon && sudo systemctl enable --now avahi-daemon"
                )

        try:
            local_ip = self._get_local_ip()
            logger.info(
                "Starting mDNS advertisement",
                extra={
                    "machine_name": self.machine_name,
                    "port": self.port,
                    "local_ip": local_ip,
                },
            )

            # Bind to specific interface to avoid issues with link-local addresses
            # on other interfaces (169.254.x.x) that can break mDNS registration
            self._zeroconf = Zeroconf(interfaces=[local_ip], ip_version=IPVersion.V4Only)
            self._info = ServiceInfo(
                self.SERVICE_TYPE,
                f"{self.machine_name}.{self.SERVICE_TYPE}",
                addresses=[socket.inet_aton(local_ip)],
                port=self.port,
                properties={
                    "version": "0.1.0",
                    "machine_name": self.machine_name,
                },
            )

            # Run registration in thread pool since zeroconf is blocking
            await asyncio.get_event_loop().run_in_executor(
                None, self._zeroconf.register_service, self._info
            )

            # Verify registration succeeded by querying for our own service
            check_info = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._zeroconf.get_service_info(  # type: ignore[union-attr]
                    self.SERVICE_TYPE, self._info.name  # type: ignore[union-attr]
                )
            )
            if check_info:
                logger.info(
                    "mDNS advertisement started and verified",
                    extra={"service_name": self._info.name},
                )
            else:
                logger.warning(
                    "mDNS registration may have failed - service not found after registration"
                )

            self._running = True

        except Exception as e:
            logger.error("Failed to start mDNS advertisement", exc_info=e)
            raise

    async def stop(self) -> None:
        """Stop advertising the service."""
        if not self._running:
            return

        logger.info("Stopping mDNS advertisement")

        if self._zeroconf and self._info:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._zeroconf.unregister_service, self._info
                )
                await asyncio.get_event_loop().run_in_executor(
                    None, self._zeroconf.close
                )
            except Exception as e:
                logger.warning("Error stopping mDNS advertisement", exc_info=e)

        self._zeroconf = None
        self._info = None
        self._running = False
        logger.info("mDNS advertisement stopped")

    def _get_local_ip(self) -> str:
        """Get local IP address for advertising."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Connect to external address to determine local IP
            # This doesn't actually send data
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            # Fallback to localhost if no network
            logger.warning("Could not determine local IP, using localhost")
            return "127.0.0.1"
        finally:
            s.close()

    @property
    def is_running(self) -> bool:
        """Check if discovery is running."""
        return self._running
