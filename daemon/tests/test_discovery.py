"""Tests for mDNS discovery."""

from unittest.mock import MagicMock, patch

import pytest

from wormhole.discovery import DiscoveryAdvertiser


class TestDiscoveryAdvertiser:
    """Tests for DiscoveryAdvertiser."""

    def test_init_default_values(self) -> None:
        advertiser = DiscoveryAdvertiser()
        assert advertiser.port == 7117
        assert not advertiser.is_running

    def test_init_custom_port(self) -> None:
        advertiser = DiscoveryAdvertiser(port=8080)
        assert advertiser.port == 8080

    def test_init_custom_machine_name(self) -> None:
        advertiser = DiscoveryAdvertiser(machine_name="testbox")
        assert advertiser.machine_name == "testbox"

    @pytest.mark.asyncio
    async def test_start_registers_service(self) -> None:
        with (
            patch("zeroconf.Zeroconf") as mock_zeroconf_class,
            patch("zeroconf.ServiceInfo") as mock_service_info_class,
        ):
            mock_zeroconf = MagicMock()
            mock_zeroconf_class.return_value = mock_zeroconf
            mock_service_info = MagicMock()
            mock_service_info_class.return_value = mock_service_info

            advertiser = DiscoveryAdvertiser(port=7117)
            await advertiser.start()

            assert advertiser.is_running
            mock_zeroconf.register_service.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_unregisters_service(self) -> None:
        with (
            patch("zeroconf.Zeroconf") as mock_zeroconf_class,
            patch("zeroconf.ServiceInfo") as mock_service_info_class,
        ):
            mock_zeroconf = MagicMock()
            mock_zeroconf_class.return_value = mock_zeroconf
            mock_service_info = MagicMock()
            mock_service_info_class.return_value = mock_service_info

            advertiser = DiscoveryAdvertiser(port=7117)
            await advertiser.start()
            await advertiser.stop()

            assert not advertiser.is_running
            mock_zeroconf.unregister_service.assert_called_once()
            mock_zeroconf.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_when_not_running_no_error(self) -> None:
        advertiser = DiscoveryAdvertiser()
        # Should not raise
        await advertiser.stop()
        assert not advertiser.is_running

    @pytest.mark.asyncio
    async def test_start_twice_is_idempotent(self) -> None:
        with (
            patch("zeroconf.Zeroconf") as mock_zeroconf_class,
            patch("zeroconf.ServiceInfo") as mock_service_info_class,
        ):
            mock_zeroconf = MagicMock()
            mock_zeroconf_class.return_value = mock_zeroconf
            mock_service_info = MagicMock()
            mock_service_info_class.return_value = mock_service_info

            advertiser = DiscoveryAdvertiser(port=7117)
            await advertiser.start()
            await advertiser.start()  # Second call should be no-op

            assert advertiser.is_running
            # Should only be called once
            assert mock_zeroconf.register_service.call_count == 1

    def test_service_type_is_correct(self) -> None:
        assert DiscoveryAdvertiser.SERVICE_TYPE == "_wormhole._tcp.local."


class TestGetLocalIP:
    """Tests for local IP detection."""

    def test_get_local_ip_returns_string(self) -> None:
        advertiser = DiscoveryAdvertiser()
        ip = advertiser._get_local_ip()
        assert isinstance(ip, str)
        # Should be a valid IP format
        parts = ip.split(".")
        assert len(parts) == 4

    def test_get_local_ip_fallback_on_error(self) -> None:
        with patch("socket.socket") as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket_class.return_value = mock_socket
            mock_socket.connect.side_effect = OSError("No network")

            advertiser = DiscoveryAdvertiser()
            ip = advertiser._get_local_ip()
            assert ip == "127.0.0.1"
