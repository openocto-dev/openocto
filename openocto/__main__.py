"""OpenOcto CLI entry point."""

from __future__ import annotations

import click
import yaml

from openocto import __version__
from openocto.config import load_config
from openocto.utils.icons import MIC, OK, FAIL


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="openocto")
@click.pass_context
def main(ctx: click.Context) -> None:
    """OpenOcto — personal AI assistant with voice control."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
def version() -> None:
    """Show OpenOcto version."""
    click.echo(f"openocto {__version__}")


@main.command()
@click.option("--persona", default=None, help="Persona name (default: from config)")
@click.option("--ai", default=None, help="AI backend: claude, claude-proxy, openai, etc.")
@click.option("--user", "user_name", default=None, help="User name to run as (skips prompt when multiple users exist)")
@click.option("--config", "config_path", default=None, help="Path to config file")
@click.option("--no-web", is_flag=True, default=False, help="Disable web admin panel")
def start(persona: str | None, ai: str | None, user_name: str | None, config_path: str | None, no_web: bool) -> None:
    """Start OpenOcto voice assistant."""
    import asyncio
    from openocto.app import OpenOctoApp
    from openocto.utils.logging_setup import setup_logging

    config = load_config(config_path)
    if persona:
        config.persona = persona
    if ai:
        config.ai.default_backend = ai

    setup_logging(config.logging)

    app = OpenOctoApp(config, user_name=user_name)
    asyncio.run(app.run(web_enabled=not no_web))


@main.command()
@click.option("--host", default="0.0.0.0", help="Bind address")
@click.option("--port", "-p", default=8080, help="Port number")
def web(host: str, port: int) -> None:
    """Start web admin panel only (no voice pipeline)."""
    import asyncio
    from openocto.utils.logging_setup import setup_logging
    setup_logging(load_config().logging)

    async def _run_web() -> None:
        try:
            from openocto.web import start_web_server
        except ImportError:
            click.secho("Web admin requires extra dependencies. Install with:", fg="red")
            click.echo("  pip install -e '.[web]'")
            raise SystemExit(1)

        import logging
        from openocto.web.server import create_web_app
        from aiohttp import web as aio_web

        logger = logging.getLogger(__name__)

        # Create a minimal mock-like app object for the web server
        from openocto.config import load_config, AppConfig, USER_CONFIG_PATH
        from openocto.event_bus import EventBus
        from openocto.state_machine import StateMachine
        from openocto.history import HistoryStore
        from types import SimpleNamespace

        config = load_config() if USER_CONFIG_PATH.exists() else AppConfig()
        config.web.host = host
        config.web.port = port

        from openocto.persona.manager import PersonaManager

        event_bus = EventBus()
        state_machine = StateMachine(event_bus)
        history_store = HistoryStore()
        persona_manager = PersonaManager()

        # Minimal app context for web routes
        octo = SimpleNamespace(
            _config=config,
            _event_bus=event_bus,
            _state_machine=state_machine,
            _history_store=history_store,
            _persona_manager=persona_manager,
            _current_user_id=None,
            _persona=None,
            _memory=None,
            _ai_router=None,
            _skills=None,
            _player=None,
        )

        # Resolve current user if any exist
        users = history_store.list_users()
        if users:
            default = next((u for u in users if u["is_default"]), users[0])
            octo._current_user_id = default["id"]

        # Activate default persona
        try:
            octo._persona = persona_manager.activate(config.persona)
        except (ValueError, KeyError):
            pass

        # Auto-start claude-proxy if needed
        if config.ai.default_backend == "claude-proxy":
            try:
                from openocto.utils.proxy import ensure_proxy
                if not ensure_proxy():
                    click.secho(
                        "  Claude proxy not available. Install with: "
                        "npm install -g claude-max-api-proxy",
                        fg="yellow",
                    )
                    # Remove broken proxy so router falls back to other backends
                    config.ai.providers.pop("claude-proxy", None)
            except Exception as e:
                logger.warning("Proxy start failed: %s", e)
                config.ai.providers.pop("claude-proxy", None)

        # Initialize AI router so web chat works
        try:
            from openocto.ai.router import AIRouter
            octo._ai_router = AIRouter(config.ai)
        except Exception as e:
            logger.warning("AI router not available: %s", e)

        # Initialize skills registry
        try:
            from openocto.skills import build_default_registry
            octo._skills = build_default_registry(config.skills)
        except Exception as e:
            logger.warning("Skills not available: %s", e)

        app = create_web_app(octo)
        runner = aio_web.AppRunner(app)
        await runner.setup()
        site = aio_web.TCPSite(runner, host, port)
        await site.start()

        # Start MCP server if enabled
        mcp_server = None
        if config.mcp.enabled:
            try:
                from openocto.mcp import MCPServer
                mcp_server = MCPServer(octo, config.mcp)
                await mcp_server.start()
                click.echo(f"  MCP server: http://localhost:{config.mcp.port}/mcp")
            except Exception as e:
                logger.warning("MCP server not available: %s", e)

        click.echo(f"\n  \U0001f310 Web admin: http://localhost:{port}\n")
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            if mcp_server:
                await mcp_server.stop()
            await runner.cleanup()

    asyncio.run(_run_web())


@main.command()
@click.option(
    "--from-step", "-s",
    default=1,
    type=click.IntRange(1, 8),
    help="Start from step N (1=User, 2=AI, 3=STT, 4=Voice, 5=Devices, 6=MicCalibration, 7=WakeWord, 8=Save+Download)",
    show_default=True,
)
def setup(from_step: int) -> None:
    """Interactive setup wizard for first-time configuration."""
    from openocto.setup_wizard import run_setup
    run_setup(from_step=from_step)


@main.group(name="test")
def test_group() -> None:
    """Hardware and diagnostics tests."""


@test_group.command(name="mic")
def test_mic() -> None:
    """Record a few seconds from the microphone and play it back."""
    import time
    import numpy as np
    import sounddevice as sd
    from openocto.audio.capture import AudioCapture
    from openocto.audio.player import AudioPlayer

    click.secho(f"{MIC} OpenOcto Microphone Test\n", bold=True)

    click.echo("Available audio devices:")
    click.echo(sd.query_devices())
    click.echo()

    duration = 3
    click.echo(f"Recording {duration} seconds — speak now!")

    capture = AudioCapture()
    capture.start()
    time.sleep(duration)
    capture.stop()

    audio = capture.get_recording()

    if audio.size == 0:
        click.secho(f"{FAIL} No audio captured. Check your microphone.", fg="red")
        return

    peak_db = 20 * np.log10(np.abs(audio).max() / 32768.0 + 1e-10)
    click.secho(
        f"{OK} Captured {audio.size / capture.sample_rate:.2f}s "
        f"({audio.size:,} samples, peak {peak_db:.1f} dB)",
        fg="green",
    )
    click.echo("\nPlaying back...")

    player = AudioPlayer()
    player.play(audio, capture.sample_rate)
    click.echo("Done!")


@main.group(name="user")
def user_group() -> None:
    """User management."""


@user_group.command(name="list")
def user_list() -> None:
    """Show all users."""
    from openocto.history import HistoryStore

    store = HistoryStore()
    users = store.list_users()
    if not users:
        click.echo("No users yet. Run `openocto setup` to create one.")
        return
    for u in users:
        default_mark = " (default)" if u["is_default"] else ""
        click.echo(f"  {u['id']}. {u['name']}{default_mark}")


@user_group.command(name="add")
@click.argument("name")
@click.option("--default", "is_default", is_flag=True, help="Set as default user")
def user_add(name: str, is_default: bool) -> None:
    """Add a new user."""
    from openocto.history import HistoryStore

    store = HistoryStore()
    if store.get_user_by_name(name):
        click.secho(f"User '{name}' already exists.", fg="red")
        raise SystemExit(1)
    uid = store.create_user(name, is_default=is_default)
    if is_default:
        store.set_default_user(uid)
    click.secho(f"Created user '{name}' (id={uid}).", fg="green")


@user_group.command(name="delete")
@click.argument("name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def user_delete(name: str, yes: bool) -> None:
    """Delete a user and all their data."""
    from openocto.history import HistoryStore

    store = HistoryStore()
    user = store.get_user_by_name(name)
    if not user:
        click.secho(f"User '{name}' not found.", fg="red")
        raise SystemExit(1)
    if not yes:
        click.confirm(
            f"Delete user '{user['name']}' (id={user['id']}) and all their data?",
            abort=True,
        )
    store.delete_user(user["id"])
    click.secho(f"Deleted user '{user['name']}'.", fg="green")


@user_group.command(name="default")
@click.argument("name")
def user_default(name: str) -> None:
    """Set a user as the default."""
    from openocto.history import HistoryStore

    store = HistoryStore()
    user = store.get_user_by_name(name)
    if not user:
        click.secho(f"User '{name}' not found.", fg="red")
        raise SystemExit(1)
    store.set_default_user(user["id"])
    click.secho(f"'{user['name']}' is now the default user.", fg="green")


@main.group(name="mcp")
def mcp_group() -> None:
    """MCP (Model Context Protocol) server management."""


@mcp_group.command(name="token")
@click.option("--reset", is_flag=True, help="Generate a new token (invalidates existing)")
def mcp_token(reset: bool) -> None:
    """Show (or reset) the MCP Bearer token."""
    from openocto.mcp.auth import _TOKEN_PATH, get_or_create_token

    if reset and _TOKEN_PATH.exists():
        _TOKEN_PATH.unlink()
        click.secho("Token revoked. Generating a new one...", fg="yellow")

    token = get_or_create_token()
    click.echo(f"\nMCP Bearer token:\n\n  {token}\n")
    click.secho(
        "Use this token in the Authorization header:\n"
        "  Authorization: Bearer <token>",
        fg="cyan",
    )


@mcp_group.command(name="url")
@click.option("--config", "config_path", default=None, help="Path to config file")
def mcp_url(config_path: str | None) -> None:
    """Show the MCP server URL and connection instructions."""
    import socket

    config = load_config(config_path)
    port = config.mcp.port
    enabled = config.mcp.enabled

    # Determine LAN IP for remote clients
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        lan_ip = "127.0.0.1"

    click.echo(f"\nMCP server port: {port}")
    click.echo(f"Status: {'enabled' if enabled else 'disabled (set mcp.enabled: true in config)'}\n")
    click.echo("Local URL (Pi itself):")
    click.echo(f"  http://localhost:{port}/mcp\n")
    click.echo("LAN URL (from Mac / other devices):")
    click.echo(f"  http://{lan_ip}:{port}/mcp\n")
    click.echo("Configure Claude CLI on any device:")
    click.echo(f"  claude mcp add openocto http://{lan_ip}:{port}/mcp --transport http")
    click.echo("  # Then add the bearer token when prompted, or set:")
    click.echo(f"  claude mcp add openocto http://{lan_ip}:{port}/mcp --transport http \\")
    click.echo("    --header 'Authorization: Bearer <token>'\n")
    click.echo("Get your token:")
    click.echo("  openocto mcp token\n")


@main.group(name="config")
def config_group() -> None:
    """Configuration management."""


@config_group.command(name="show")
@click.option("--config", "config_path", default=None, help="Path to config file")
def config_show(config_path: str | None) -> None:
    """Show resolved configuration."""
    config = load_config(config_path)
    data = config.model_dump()

    # Mask API keys
    ai = data.get("ai", {})
    claude_key = ai.get("claude", {}).get("api_key", "")
    if claude_key:
        ai["claude"]["api_key"] = claude_key[:8] + "..." if len(claude_key) > 8 else "***"
    for name, provider in ai.get("providers", {}).items():
        key = provider.get("api_key", "")
        if key:
            provider["api_key"] = key[:8] + "..." if len(key) > 8 else "***"

    click.echo(yaml.dump(data, default_flow_style=False, allow_unicode=True))


if __name__ == "__main__":
    main()
