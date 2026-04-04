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
def start(persona: str | None, ai: str | None, user_name: str | None, config_path: str | None) -> None:
    """Start OpenOcto voice assistant."""
    import asyncio
    from openocto.app import OpenOctoApp

    config = load_config(config_path)
    if persona:
        config.persona = persona
    if ai:
        config.ai.default_backend = ai

    app = OpenOctoApp(config, user_name=user_name)
    asyncio.run(app.run())


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
