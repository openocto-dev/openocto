"""mDNS / Bonjour service publishing.

Announces OpenOcto on the local network so clients can discover it
without DNS or hardcoded IPs:

  * Web admin / JSON API → ``http://<hostname>.local:8080``
  * MCP server (if enabled) → ``http://<hostname>.local:8765/mcp``

Service type: ``_openocto._tcp.local.``

The service entry includes a TXT record with version, port, and feature
flags so service browsers (Bonjour, mobile clients) can show meaningful
metadata before connecting.

If the ``zeroconf`` package is missing the publisher silently no-ops —
mDNS is a quality-of-life feature, not a hard requirement.
"""

from __future__ import annotations

import logging
import socket
from typing import Any

logger = logging.getLogger(__name__)

_SERVICE_TYPE = "_openocto._tcp.local."

# Interface name prefixes we skip when enumerating IPs for mDNS A records.
# Docker bridges (`docker0`, `br-*`), virtual ethernet pairs (`veth*`),
# and VPN tunnels (`tun*`, `tap*`, `wg*`) all give addresses that are
# unreachable from peers on the user's actual LAN.
_SKIP_IFACE_PREFIXES = ("lo", "docker", "br-", "veth", "tun", "tap", "wg")


def _get_lan_ips() -> list[str]:
    """Enumerate all reachable IPv4 addresses for mDNS A records.

    Uses ``ifaddr`` (a transitive dep of zeroconf) to walk every network
    interface and collect non-loopback IPv4 addresses, filtering out
    Docker bridges, veth pairs, and VPN tunnels.  Returns ``[127.0.0.1]``
    only if nothing else is found, so the publisher can still register
    on a fully offline machine.

    Returns multiple addresses when the host is multi-homed (Wi-Fi +
    Ethernet) — clients will pick whichever one they can reach.
    """
    try:
        import ifaddr
    except ImportError:
        return [_get_lan_ip_fallback()]

    ips: list[str] = []
    for adapter in ifaddr.get_adapters():
        name = adapter.nice_name or adapter.name or ""
        if any(name.lower().startswith(p) for p in _SKIP_IFACE_PREFIXES):
            continue
        for ip_obj in adapter.ips:
            ip = ip_obj.ip
            # Skip IPv6 (tuple) — we only publish IPv4 A records
            if not isinstance(ip, str):
                continue
            # Skip loopback and link-local
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            ips.append(ip)

    if not ips:
        ips.append(_get_lan_ip_fallback())
    return ips


def _get_lan_ip_fallback() -> str:
    """Last-resort single-IP detection (the old behavior)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# Backwards-compat alias used by tests / other modules.
def _get_lan_ip() -> str:
    ips = _get_lan_ips()
    return ips[0] if ips else "127.0.0.1"


class MDNSPublisher:
    """Async wrapper around AsyncZeroconf — registers + unregisters on stop.

    Construct, ``await start()``, then ``await stop()`` on shutdown.
    Safe to instantiate even if zeroconf is not installed; ``start()``
    will log a warning and become a no-op.
    """

    def __init__(self, config: Any, web_port: int, mcp_config: Any | None = None) -> None:
        self._config = config
        self._web_port = web_port
        self._mcp_config = mcp_config
        self._zc: Any = None
        self._info: Any = None
        self._mcp_info: Any = None

    async def start(self) -> None:
        try:
            from zeroconf import IPVersion, ServiceInfo
            from zeroconf.asyncio import AsyncZeroconf
        except ImportError:
            logger.warning(
                "zeroconf not installed — mDNS disabled. "
                "Install with: pip install -e '.[web]'"
            )
            return

        ips = _get_lan_ips()
        addresses: list[bytes] = []
        for ip in ips:
            try:
                addresses.append(socket.inet_aton(ip))
            except OSError:
                logger.debug("Skipping invalid IP for mDNS: %s", ip)
        if not addresses:
            logger.warning("No usable IPs for mDNS — disabled")
            return

        hostname = self._config.hostname or "openocto"
        # zeroconf expects "<server>.local." with trailing dot
        server = f"{hostname}.local."

        # ── Web / JSON API service ─────────────────────────────────────
        from openocto import __version__
        properties: dict[bytes, bytes] = {
            b"version": __version__.encode(),
            b"path": b"/",
            b"api": b"/api/v1",
            b"web": b"true",
            b"mcp": b"true" if (self._mcp_config and self._mcp_config.enabled) else b"false",
        }
        instance_name = f"{self._config.service_name}.{_SERVICE_TYPE}"

        self._info = ServiceInfo(
            _SERVICE_TYPE,
            instance_name,
            addresses=addresses,
            port=self._web_port,
            properties=properties,
            server=server,
        )

        self._zc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        try:
            await self._zc.async_register_service(self._info)
        except Exception as e:
            logger.warning("mDNS registration failed: %s", e)
            await self._safe_close()
            return

        logger.info(
            "mDNS published: %s → http://%s:%d (IPs: %s)",
            server.rstrip("."), server.rstrip("."), self._web_port, ", ".join(ips),
        )

        # ── Optional secondary entry for the MCP server ────────────────
        if self._mcp_config and self._mcp_config.enabled:
            mcp_props: dict[bytes, bytes] = {
                b"version": __version__.encode(),
                b"path": b"/mcp",
                b"protocol": b"mcp-2024-11-05",
                b"auth": b"bearer" if self._mcp_config.require_auth else b"none",
            }
            mcp_instance = f"{self._config.service_name} MCP._openocto-mcp._tcp.local."
            self._mcp_info = ServiceInfo(
                "_openocto-mcp._tcp.local.",
                mcp_instance,
                addresses=addresses,
                port=self._mcp_config.port,
                properties=mcp_props,
                server=server,
            )
            try:
                await self._zc.async_register_service(self._mcp_info)
                logger.info(
                    "mDNS published MCP: %s:%d/mcp",
                    server.rstrip("."), self._mcp_config.port,
                )
            except Exception as e:
                logger.warning("mDNS MCP registration failed: %s", e)
                self._mcp_info = None

    async def stop(self) -> None:
        if not self._zc:
            return
        try:
            if self._info:
                await self._zc.async_unregister_service(self._info)
            if self._mcp_info:
                await self._zc.async_unregister_service(self._mcp_info)
        except Exception as e:
            logger.debug("mDNS unregister error: %s", e)
        await self._safe_close()
        logger.info("mDNS stopped")

    async def _safe_close(self) -> None:
        try:
            if self._zc:
                await self._zc.async_close()
        except Exception:
            pass
        self._zc = None
        self._info = None
        self._mcp_info = None
