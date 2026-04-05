"""User management routes — list, create, delete, set default."""

from __future__ import annotations

import aiohttp_jinja2
from aiohttp import web

from openocto import __version__

routes = web.RouteTableDef()


@routes.get("/users")
@aiohttp_jinja2.template("users.html")
async def users_page(request: web.Request) -> dict:
    octo = request.app["octo"]
    hs = octo._history_store

    users = hs.list_users() if hs else []
    flash = request.query.get("flash")
    flash_type = request.query.get("flash_type", "success")

    return {
        "page": "users",
        "version": __version__,
        "users": users,
        "current_user_id": octo._current_user_id,
        "flash": flash,
        "flash_type": flash_type,
    }


@routes.post("/api/users")
async def create_user(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        raise web.HTTPServiceUnavailable(text="History store not available")

    data = await request.post()
    name = data.get("name", "").strip()
    if not name:
        raise web.HTTPFound("/users?flash=Name+is+required&flash_type=error")

    existing = hs.get_user_by_name(name)
    if existing:
        raise web.HTTPFound(f"/users?flash=User+'{name}'+already+exists&flash_type=error")

    hs.create_user(name)
    raise web.HTTPFound(f"/users?flash=User+'{name}'+created")


@routes.post("/api/users/{user_id}/default")
async def set_default(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        raise web.HTTPServiceUnavailable()

    user_id = int(request.match_info["user_id"])
    hs.set_default_user(user_id)
    raise web.HTTPFound("/users?flash=Default+user+updated")


@routes.post("/api/users/{user_id}/activate")
async def activate_user(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        raise web.HTTPServiceUnavailable()

    user_id = int(request.match_info["user_id"])
    octo._current_user_id = user_id
    raise web.HTTPFound("/users?flash=Active+user+switched")


@routes.post("/api/users/{user_id}/delete")
async def delete_user(request: web.Request) -> web.Response:
    octo = request.app["octo"]
    hs = octo._history_store
    if not hs:
        raise web.HTTPServiceUnavailable()

    user_id = int(request.match_info["user_id"])

    # prevent deleting the currently active user
    if user_id == octo._current_user_id:
        raise web.HTTPFound("/users?flash=Cannot+delete+active+user&flash_type=error")

    hs.delete_user(user_id)
    raise web.HTTPFound("/users?flash=User+deleted")
