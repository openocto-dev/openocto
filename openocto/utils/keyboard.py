"""Push-to-talk keyboard listener."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Callable

from pynput import keyboard

logger = logging.getLogger(__name__)

# Default push-to-talk key
DEFAULT_PTT_KEY = keyboard.Key.space


class PushToTalkListener:
    """Listens for a key hold and fires callbacks on press/release.

    Runs in a background thread. Bridges to asyncio via loop callbacks.
    """

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        ptt_key: keyboard.Key = DEFAULT_PTT_KEY,
    ) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._ptt_key = ptt_key
        self._listener: keyboard.Listener | None = None
        self._pressed = False

    def _handle_press(self, key: keyboard.Key) -> None:
        if key == self._ptt_key and not self._pressed:
            self._pressed = True
            logger.debug("PTT key pressed")
            self._on_press()

    def _handle_release(self, key: keyboard.Key) -> None:
        if key == self._ptt_key and self._pressed:
            self._pressed = False
            logger.debug("PTT key released")
            self._on_release()

    def start(self) -> None:
        """Start listening in a background thread."""
        self._listener = keyboard.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
        )
        self._listener.start()
        logger.debug("PTT listener started (key: %s)", self._ptt_key)

    def stop(self) -> None:
        """Stop the listener."""
        if self._listener:
            self._listener.stop()
            self._listener = None


class AsyncPushToTalkListener:
    """Async wrapper for PushToTalkListener.

    Bridges keyboard callbacks to asyncio coroutines.
    """

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        ptt_key: keyboard.Key = DEFAULT_PTT_KEY,
    ) -> None:
        self._loop = asyncio.get_event_loop()
        self._sync_listener = PushToTalkListener(
            on_press=lambda: self._loop.call_soon_threadsafe(on_press),
            on_release=lambda: self._loop.call_soon_threadsafe(on_release),
            ptt_key=ptt_key,
        )

    def start(self) -> None:
        self._sync_listener.start()

    def stop(self) -> None:
        self._sync_listener.stop()
