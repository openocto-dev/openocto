"""Simple async publish-subscribe event bus."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    STATE_CHANGED = "state.changed"
    AUDIO_RECORDED = "audio.recorded"
    STT_RESULT = "stt.result"
    AI_RESPONSE = "ai.response"
    AI_CHUNK = "ai.chunk"
    TTS_STARTED = "tts.started"
    TTS_FINISHED = "tts.finished"
    ERROR = "error"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """Async event bus with pub/sub support."""

    def __init__(self) -> None:
        self._subscribers: dict[EventType | None, list[asyncio.Queue[Event]]] = {}

    def subscribe(self, event_type: EventType | None = None) -> asyncio.Queue[Event]:
        """Subscribe to events. If event_type is None, subscribe to all events."""
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.setdefault(event_type, []).append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event], event_type: EventType | None = None) -> None:
        """Remove a subscription."""
        subscribers = self._subscribers.get(event_type, [])
        if queue in subscribers:
            subscribers.remove(queue)

    async def publish(self, event_type: EventType, data: dict[str, Any] | None = None) -> None:
        """Publish an event to all matching subscribers."""
        event = Event(type=event_type, data=data or {})

        # Notify type-specific subscribers
        for queue in self._subscribers.get(event_type, []):
            await queue.put(event)

        # Notify global subscribers (subscribed with None)
        for queue in self._subscribers.get(None, []):
            await queue.put(event)

    def publish_sync(self, event_type: EventType, data: dict[str, Any] | None = None) -> None:
        """Non-async publish for use from non-async contexts (e.g., audio callbacks)."""
        event = Event(type=event_type, data=data or {})

        for queue in self._subscribers.get(event_type, []):
            queue.put_nowait(event)

        for queue in self._subscribers.get(None, []):
            queue.put_nowait(event)
