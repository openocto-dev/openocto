"""Tests for the event bus."""

import asyncio

import pytest

from openocto.event_bus import EventBus, EventType


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    bus = EventBus()
    queue = bus.subscribe(EventType.STT_RESULT)
    await bus.publish(EventType.STT_RESULT, {"text": "hello"})
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event.type == EventType.STT_RESULT
    assert event.data["text"] == "hello"


@pytest.mark.asyncio
async def test_global_subscriber_receives_all():
    bus = EventBus()
    queue = bus.subscribe(None)  # global
    await bus.publish(EventType.STT_RESULT, {"text": "a"})
    await bus.publish(EventType.AI_RESPONSE, {"text": "b"})
    e1 = await asyncio.wait_for(queue.get(), timeout=1.0)
    e2 = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert e1.type == EventType.STT_RESULT
    assert e2.type == EventType.AI_RESPONSE


@pytest.mark.asyncio
async def test_typed_subscriber_ignores_other_types():
    bus = EventBus()
    queue = bus.subscribe(EventType.STT_RESULT)
    await bus.publish(EventType.AI_RESPONSE, {"text": "ignored"})
    assert queue.empty()


@pytest.mark.asyncio
async def test_unsubscribe():
    bus = EventBus()
    queue = bus.subscribe(EventType.STT_RESULT)
    bus.unsubscribe(queue, EventType.STT_RESULT)
    await bus.publish(EventType.STT_RESULT, {"text": "hello"})
    assert queue.empty()


@pytest.mark.asyncio
async def test_publish_sync():
    bus = EventBus()
    queue = bus.subscribe(EventType.ERROR)
    bus.publish_sync(EventType.ERROR, {"message": "test error"})
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event.type == EventType.ERROR
    assert event.data["message"] == "test error"


@pytest.mark.asyncio
async def test_multiple_subscribers():
    bus = EventBus()
    q1 = bus.subscribe(EventType.STT_RESULT)
    q2 = bus.subscribe(EventType.STT_RESULT)
    await bus.publish(EventType.STT_RESULT, {"text": "hello"})
    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert e1.data["text"] == "hello"
    assert e2.data["text"] == "hello"
