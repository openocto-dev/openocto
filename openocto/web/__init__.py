"""OpenOcto web admin panel."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

from openocto.web.server import create_web_app

if TYPE_CHECKING:
    from openocto.app import OpenOctoApp

logger = logging.getLogger(__name__)


async def start_web_server(octo_app: OpenOctoApp) -> None:
    """Start the web admin server. Runs until cancelled."""
    host = octo_app._config.web.host
    port = octo_app._config.web.port

    app = create_web_app(octo_app)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    try:
        await site.start()
        logger.info("Web admin started at http://%s:%d", host, port)
        print(f"\n  \U0001f310 Web admin: http://localhost:{port}\n")
        # Keep running until cancelled
        while True:
            await __import__("asyncio").sleep(3600)
    finally:
        await runner.cleanup()
