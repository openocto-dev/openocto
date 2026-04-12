"""Message history routes — chat-style view with send capability."""

from __future__ import annotations

import asyncio
import json
import logging

import aiohttp_jinja2
from aiohttp import web

from openocto import __version__

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()

PAGE_SIZE = 50


async def _tts_speak(octo: object, text: str) -> None:
    """Synthesize and play TTS in the background (fire-and-forget)."""
    try:
        tts_engine = None
        if hasattr(octo, '_tts_engines') and octo._tts_engines:
            # Detect language by cyrillic character ratio
            cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
            lang = "ru" if len(text) > 0 and cyrillic / len(text) > 0.2 else "en"

            if lang in octo._tts_engines:
                tts_engine = octo._tts_engines[lang]
            else:
                prefix = lang.split("_")[0]
                tts_engine = octo._tts_engines.get(
                    prefix, next(iter(octo._tts_engines.values()), None)
                )

            logger.info("TTS: detected lang=%s, engine=%s, available=%s",
                        lang, type(tts_engine).__name__ if tts_engine else None,
                        list(octo._tts_engines.keys()))

        if not tts_engine:
            return

        segment = await asyncio.to_thread(tts_engine.synthesize, text)
        if segment and segment.audio.size > 0:
            player = getattr(octo, '_player', None)
            if player is None:
                from openocto.audio.player import AudioPlayer
                player = AudioPlayer(
                    octo._config.audio if hasattr(octo._config, 'audio') else None
                )
            await player.play_async_awaitable(segment.audio, segment.sample_rate)
    except Exception as e:
        logger.warning("TTS playback error: %s", e)


@routes.get("/messages")
@aiohttp_jinja2.template("messages.html")
async def messages_page(request: web.Request) -> dict:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        return {
            "page": "messages",
            "version": __version__,
            "messages": [],
            "users": [],
            "personas": [],
            "query": "",
            "user_id": None,
            "persona": "",
        }

    # Filters from query string
    query = request.query.get("q", "").strip()
    user_id_str = request.query.get("user_id", "")
    persona = request.query.get("persona", "")
    page = max(1, int(request.query.get("page", "1")))

    from openocto.web.routes import ensure_current_user
    ensure_current_user(octo)

    user_id = int(user_id_str) if user_id_str else octo._current_user_id

    # Get user and persona lists for filter dropdowns
    users = hs.list_users()
    personas = _get_persona_names(octo)

    messages = []
    total = 0

    if user_id:
        if query:
            # FTS search
            results = hs.fts_search(query, user_id, limit=PAGE_SIZE)
            messages = results
            total = len(results)
        else:
            # Recent messages for this user+persona (oldest first — chat order)
            persona_name = persona or (octo._persona.name if octo._persona else "octo")
            raw = hs.get_recent_messages(user_id, persona_name, limit=500)
            total = len(raw)
            # Paginate from the end (latest messages last)
            offset = max(0, total - page * PAGE_SIZE)
            end = max(0, total - (page - 1) * PAGE_SIZE)
            messages = raw[offset:end]

    active_persona = persona or (octo._persona.name if octo._persona else "octo")
    flash = request.query.get("flash")

    return {
        "page": "messages",
        "version": __version__,
        "messages": messages,
        "users": users,
        "personas": personas,
        "query": query,
        "user_id": user_id,
        "persona": active_persona,
        "current_page": page,
        "total": total,
        "page_size": PAGE_SIZE,
        "has_next": total > page * PAGE_SIZE,
        "has_prev": page > 1,
        "flash": flash,
        "can_chat": octo._ai_router is not None,
    }


@routes.post("/api/messages/send")
async def send_message(request: web.Request) -> web.Response:
    """Send a message via AI and return the response."""
    octo = request.app["octo"]
    hs = octo._history_store

    if not hs:
        return web.json_response({"error": "History store not available"}, status=503)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    content = data.get("content", "").strip()
    tts_enabled = data.get("tts", False)
    user_id = data.get("user_id") or octo._current_user_id
    persona_name = data.get("persona") or (octo._persona.name if octo._persona else "octo")

    if not content:
        return web.json_response({"error": "Empty message"}, status=400)
    if not user_id:
        return web.json_response({"error": "No active user"}, status=400)

    # Save user message
    hs.add_message(user_id, persona_name, "user", content)

    # Try to get AI response
    reply = ""
    if octo._ai_router:
        try:
            # Build history for context (excluding the message we just added)
            history = hs.get_recent_messages(user_id, persona_name, limit=20)
            # Remove created_at — AI backends expect only role+content
            # Also remove the last user message (send() will add it itself)
            ai_history = [{"role": m["role"], "content": m["content"]} for m in history]
            if ai_history and ai_history[-1]["role"] == "user":
                ai_history.pop()

            # Get system prompt
            system_prompt = ""
            if octo._persona:
                system_prompt = octo._persona.system_prompt

            reply = await octo._ai_router.send(
                user_text=content,
                history=ai_history,
                system_prompt=system_prompt,
            )
        except Exception as e:
            logger.error("AI chat error: %s", e)
            err_name = type(e).__name__
            if "Connection" in err_name or "ConnectError" in str(e):
                reply = "[Error: Could not connect to AI backend. Check that the service is running.]"
            else:
                reply = f"[Error: {e}]"
    else:
        reply = "[AI backend not configured. Start OpenOcto with `openocto start` for full functionality.]"

    # Save assistant response
    hs.add_message(user_id, persona_name, "assistant", reply)

    # TTS playback — fire-and-forget so the text response arrives immediately
    if tts_enabled and reply and not reply.startswith("[Error"):
        asyncio.create_task(_tts_speak(octo, reply))

    return web.json_response({
        "role": "assistant",
        "content": reply,
    })


@routes.post("/api/messages/clear")
async def clear_messages(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        raise web.HTTPServiceUnavailable()

    data = await request.post()
    user_id = int(data.get("user_id", octo._current_user_id or 0))
    persona = data.get("persona", "").strip() or None

    if user_id:
        count = hs.clear_history(user_id, persona)
        raise web.HTTPFound(f"/messages?flash=Cleared+{count}+messages")

    raise web.HTTPFound("/messages?flash=No+user+selected&flash_type=error")


def _get_persona_names(octo) -> list[str]:
    """Get available persona names."""
    try:
        if octo._persona_manager:
            return [p["name"] for p in octo._persona_manager.list_personas()]
    except Exception:
        pass
    return ["octo"]
