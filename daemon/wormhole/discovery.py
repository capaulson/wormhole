"""mDNS/Bonjour service advertisement."""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zeroconf import ServiceInfo, Zeroconf

logger = logging.getLogger(__name__)


class DiscoveryAdvertiser:
    """Advertise Wormhole service via mDNS/Bonjour."""

    SERVICE_TYPE = "_wormhole._tcp.local."

    def __init__(self, port: int = 7117, machine_name: str | None = None) -> None:
        self.port = port
        self.machine_name = machine_name or socket.gethostname()
        self._zeroconf: Zeroconf | None = None
        self._info: ServiceInfo | None = None
        self._running = False

    async def start(self) -> None:
        """Start advertising the service."""
        if self._running:
            return

        from zeroconf import ServiceInfo, Zeroconf

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

            self._zeroconf = Zeroconf()
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
            self._running = True
            logger.info("mDNS advertisement started")

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
