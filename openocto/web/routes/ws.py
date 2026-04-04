"""WebSocket endpoint for real-time pipeline state updates."""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


@routes.get("/ws")
async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    octo = request.app["octo"]
    queue = octo._event_bus.subscribe(None)  # subscribe to all events

    try:
        # Send current state immediately
        state = octo._state_machine.state.value if octo._state_machine else "idle"
        await ws.send_json({"type": "state", "data": {"state": state}})

        while not ws.closed:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                await ws.send_json({
                    "type": event.type.value,
                    "data": event.data,
                })
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                await ws.ping()
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        octo._event_bus.unsubscribe(queue, None)

    return ws
