"""Tests for the state machine."""

import pytest

from openocto.event_bus import EventBus, EventType
from openocto.state_machine import InvalidTransitionError, State, StateMachine


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def sm(bus):
    return StateMachine(bus)


@pytest.mark.asyncio
async def test_initial_state(sm):
    assert sm.state == State.IDLE


@pytest.mark.asyncio
async def test_full_cycle(sm):
    """Test the complete voice pipeline cycle."""
    assert sm.state == State.IDLE

    await sm.transition("start_recording")
    assert sm.state == State.RECORDING

    await sm.transition("stop_recording")
    assert sm.state == State.TRANSCRIBING

    await sm.transition("transcription_done")
    assert sm.state == State.PROCESSING

    await sm.transition("response_ready")
    assert sm.state == State.SPEAKING

    await sm.transition("speech_done")
    assert sm.state == State.IDLE


@pytest.mark.asyncio
async def test_invalid_transition(sm):
    with pytest.raises(InvalidTransitionError):
        await sm.transition("stop_recording")  # can't stop when IDLE


@pytest.mark.asyncio
async def test_cancel_from_recording(sm):
    await sm.transition("start_recording")
    await sm.transition("cancel")
    assert sm.state == State.IDLE


@pytest.mark.asyncio
async def test_cancel_from_processing(sm):
    await sm.transition("start_recording")
    await sm.transition("stop_recording")
    await sm.transition("transcription_done")
    await sm.transition("cancel")
    assert sm.state == State.IDLE


@pytest.mark.asyncio
async def test_error_from_any_active_state(sm):
    for trigger_sequence in [
        ["start_recording"],
        ["start_recording", "stop_recording"],
        ["start_recording", "stop_recording", "transcription_done"],
        ["start_recording", "stop_recording", "transcription_done", "response_ready"],
    ]:
        sm.reset()
        for t in trigger_sequence:
            await sm.transition(t)
        await sm.transition("error")
        assert sm.state == State.IDLE


@pytest.mark.asyncio
async def test_state_changed_events(sm, bus):
    queue = bus.subscribe(EventType.STATE_CHANGED)
    await sm.transition("start_recording")
    event = queue.get_nowait()
    assert event.data["from"] == "idle"
    assert event.data["to"] == "recording"
    assert event.data["trigger"] == "start_recording"


@pytest.mark.asyncio
async def test_reset(sm):
    await sm.transition("start_recording")
    assert sm.state == State.RECORDING
    sm.reset()
    assert sm.state == State.IDLE


@pytest.mark.asyncio
async def test_cannot_start_recording_while_recording(sm):
    await sm.transition("start_recording")
    with pytest.raises(InvalidTransitionError):
        await sm.transition("start_recording")
