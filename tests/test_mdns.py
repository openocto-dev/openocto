"""Tests for the mDNS / Bonjour publisher.

zeroconf is mocked so the tests don't bind to network interfaces.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openocto.web.mdns import MDNSPublisher, _get_lan_ip, _get_lan_ips


def _mdns_config(hostname: str = "openocto", enabled: bool = True):
    return SimpleNamespace(
        enabled=enabled,
        hostname=hostname,
        service_name="OpenOcto Voice Assistant",
    )


def _mcp_config(enabled: bool = False, port: int = 8765, require_auth: bool = True):
    return SimpleNamespace(
        enabled=enabled, host="0.0.0.0", port=port, require_auth=require_auth,
    )


class TestDefaultHostname:
    """The default mDNS hostname is derived from the system hostname so two
    instances on the same LAN don't collide on `openocto.local`."""

    def test_appends_system_hostname(self):
        from openocto.config import _default_mdns_hostname
        with patch("socket.gethostname", return_value="raspberrypi"):
            assert _default_mdns_hostname() == "openocto-raspberrypi"

    def test_handles_kitchen_pi_style_names(self):
        from openocto.config import _default_mdns_hostname
        with patch("socket.gethostname", return_value="kitchen-pi"):
            assert _default_mdns_hostname() == "openocto-kitchen-pi"

    def test_strips_local_suffix(self):
        from openocto.config import _default_mdns_hostname
        with patch("socket.gethostname", return_value="raspberrypi.local"):
            assert _default_mdns_hostname() == "openocto-raspberrypi"

    def test_strips_fqdn(self):
        from openocto.config import _default_mdns_hostname
        with patch("socket.gethostname", return_value="my-host.lan"):
            assert _default_mdns_hostname() == "openocto-my-host"

    def test_falls_back_for_localhost(self):
        from openocto.config import _default_mdns_hostname
        with patch("socket.gethostname", return_value="localhost"):
            assert _default_mdns_hostname() == "openocto"

    def test_falls_back_for_empty(self):
        from openocto.config import _default_mdns_hostname
        with patch("socket.gethostname", return_value=""):
            assert _default_mdns_hostname() == "openocto"

    def test_sanitizes_unsafe_chars(self):
        from openocto.config import _default_mdns_hostname
        with patch("socket.gethostname", return_value="My_Host!"):
            assert _default_mdns_hostname() == "openocto-my-host"


class TestLanIPDetection:
    def test_returns_string(self):
        ip = _get_lan_ip()
        assert isinstance(ip, str)
        # Either a real IP or the loopback fallback
        assert ip.count(".") == 3

    def test_get_lan_ips_returns_list(self):
        ips = _get_lan_ips()
        assert isinstance(ips, list)
        assert len(ips) >= 1

    def test_skips_docker_and_tun_interfaces(self):
        """Critical: on a host with Docker + VPN, the LAN IP must NOT be
        the docker0 / tun0 address — those are unreachable from peers."""
        fake_adapters = [
            _fake_adapter("lo", ["127.0.0.1"]),
            _fake_adapter("wlan0", ["192.168.88.248"]),
            _fake_adapter("docker0", ["172.17.0.1"]),
            _fake_adapter("tun0", ["172.19.0.1"]),
            _fake_adapter("br-abc123", ["172.20.0.1"]),
            _fake_adapter("veth1234", ["172.21.0.1"]),
        ]
        with patch("ifaddr.get_adapters", return_value=fake_adapters):
            ips = _get_lan_ips()
        assert ips == ["192.168.88.248"]

    def test_returns_multiple_real_interfaces(self):
        """Multi-homed host (Wi-Fi + Ethernet) should publish both IPs."""
        fake_adapters = [
            _fake_adapter("wlan0", ["192.168.88.248"]),
            _fake_adapter("eth0", ["10.0.0.5"]),
            _fake_adapter("docker0", ["172.17.0.1"]),
        ]
        with patch("ifaddr.get_adapters", return_value=fake_adapters):
            ips = _get_lan_ips()
        assert "192.168.88.248" in ips
        assert "10.0.0.5" in ips
        assert "172.17.0.1" not in ips
        assert len(ips) == 2

    def test_skips_link_local(self):
        fake_adapters = [
            _fake_adapter("wlan0", ["169.254.1.5"]),  # link-local — skip
            _fake_adapter("eth0", ["192.168.1.10"]),
        ]
        with patch("ifaddr.get_adapters", return_value=fake_adapters):
            ips = _get_lan_ips()
        assert ips == ["192.168.1.10"]

    def test_falls_back_to_socket_when_ifaddr_missing(self):
        with patch.dict("sys.modules", {"ifaddr": None}):
            # Should fall back to the old socket trick (or 127.0.0.1)
            ips = _get_lan_ips()
            assert isinstance(ips, list)
            assert len(ips) == 1

    def test_falls_back_to_loopback_on_socket_error(self):
        with patch("socket.socket") as mock_sock:
            mock_sock.side_effect = OSError("no network")
            from openocto.web.mdns import _get_lan_ip_fallback
            assert _get_lan_ip_fallback() == "127.0.0.1"


def _fake_adapter(name: str, ips: list[str]):
    """Build a minimal ifaddr.Adapter-like object for tests."""
    fake_ips = []
    for ip in ips:
        fake_ips.append(SimpleNamespace(ip=ip))
    return SimpleNamespace(nice_name=name, name=name, ips=fake_ips)


class TestMDNSPublisher:
    """The publisher uses AsyncZeroconf — we patch it at the import site."""

    @pytest.mark.asyncio
    async def test_start_registers_service(self):
        fake_zc = AsyncMock()
        fake_zc.async_register_service = AsyncMock()
        fake_zc.async_unregister_service = AsyncMock()
        fake_zc.async_close = AsyncMock()

        with patch("zeroconf.asyncio.AsyncZeroconf", return_value=fake_zc):
            pub = MDNSPublisher(_mdns_config(), web_port=8080)
            await pub.start()

        assert pub._zc is fake_zc
        fake_zc.async_register_service.assert_awaited_once()
        info = fake_zc.async_register_service.call_args[0][0]
        # Verify the ServiceInfo carries the right hostname/port
        assert info.port == 8080
        assert info.server == "openocto.local."
        assert info.type == "_openocto._tcp.local."

    @pytest.mark.asyncio
    async def test_start_registers_mcp_when_enabled(self):
        fake_zc = AsyncMock()
        fake_zc.async_register_service = AsyncMock()
        fake_zc.async_close = AsyncMock()

        with patch("zeroconf.asyncio.AsyncZeroconf", return_value=fake_zc):
            pub = MDNSPublisher(
                _mdns_config(),
                web_port=8080,
                mcp_config=_mcp_config(enabled=True, port=8765),
            )
            await pub.start()

        # Two services registered: web + MCP
        assert fake_zc.async_register_service.await_count == 2

    @pytest.mark.asyncio
    async def test_start_skips_mcp_when_disabled(self):
        fake_zc = AsyncMock()
        fake_zc.async_register_service = AsyncMock()
        fake_zc.async_close = AsyncMock()

        with patch("zeroconf.asyncio.AsyncZeroconf", return_value=fake_zc):
            pub = MDNSPublisher(
                _mdns_config(),
                web_port=8080,
                mcp_config=_mcp_config(enabled=False),
            )
            await pub.start()

        assert fake_zc.async_register_service.await_count == 1

    @pytest.mark.asyncio
    async def test_stop_unregisters(self):
        fake_zc = AsyncMock()
        fake_zc.async_register_service = AsyncMock()
        fake_zc.async_unregister_service = AsyncMock()
        fake_zc.async_close = AsyncMock()

        with patch("zeroconf.asyncio.AsyncZeroconf", return_value=fake_zc):
            pub = MDNSPublisher(_mdns_config(), web_port=8080)
            await pub.start()
            await pub.stop()

        fake_zc.async_unregister_service.assert_awaited()
        fake_zc.async_close.assert_awaited()

    @pytest.mark.asyncio
    async def test_stop_safe_without_start(self):
        pub = MDNSPublisher(_mdns_config(), web_port=8080)
        # Should not raise even though start() was never called
        await pub.stop()

    @pytest.mark.asyncio
    async def test_no_zeroconf_installed_is_silent_noop(self):
        # Simulate ImportError by removing zeroconf from sys.modules and
        # blocking re-import.
        original = {k: v for k, v in sys.modules.items() if k.startswith("zeroconf")}
        for k in list(original):
            sys.modules[k] = None  # type: ignore[assignment]
        try:
            pub = MDNSPublisher(_mdns_config(), web_port=8080)
            await pub.start()  # should log warning, not raise
            assert pub._zc is None
        finally:
            for k, v in original.items():
                sys.modules[k] = v

    @pytest.mark.asyncio
    async def test_register_failure_cleans_up(self):
        fake_zc = AsyncMock()
        fake_zc.async_register_service = AsyncMock(side_effect=RuntimeError("boom"))
        fake_zc.async_close = AsyncMock()

        with patch("zeroconf.asyncio.AsyncZeroconf", return_value=fake_zc):
            pub = MDNSPublisher(_mdns_config(), web_port=8080)
            await pub.start()

        # On failure the publisher should close the AsyncZeroconf and clear refs
        fake_zc.async_close.assert_awaited()
        assert pub._zc is None

    @pytest.mark.asyncio
    async def test_custom_hostname(self):
        fake_zc = AsyncMock()
        fake_zc.async_register_service = AsyncMock()
        fake_zc.async_close = AsyncMock()

        with patch("zeroconf.asyncio.AsyncZeroconf", return_value=fake_zc):
            pub = MDNSPublisher(_mdns_config(hostname="kitchen-octo"), web_port=8080)
            await pub.start()

        info = fake_zc.async_register_service.call_args[0][0]
        assert info.server == "kitchen-octo.local."
