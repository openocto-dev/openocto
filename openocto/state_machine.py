"""State machine for the OpenOcto voice pipeline."""

from __future__ import annotations

import logging
from enum import Enum

from openocto.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)


class State(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    PROCESSING = "processing"
    SPEAKING = "speaking"


# Valid transitions: (from_state, trigger) -> to_state
_TRANSITIONS: dict[tuple[State, str], State] = {
    (State.IDLE, "start_recording"): State.RECORDING,
    (State.RECORDING, "stop_recording"): State.TRANSCRIBING,
    (State.TRANSCRIBING, "transcription_done"): State.PROCESSING,
    (State.PROCESSING, "response_ready"): State.SPEAKING,
    (State.SPEAKING, "speech_done"): State.IDLE,
    # Cancel / error from any active state -> IDLE
    (State.RECORDING, "cancel"): State.IDLE,
    (State.RECORDING, "error"): State.IDLE,
    (State.TRANSCRIBING, "cancel"): State.IDLE,
    (State.TRANSCRIBING, "error"): State.IDLE,
    (State.PROCESSING, "cancel"): State.IDLE,
    (State.PROCESSING, "error"): State.IDLE,
    (State.SPEAKING, "cancel"): State.IDLE,
    (State.SPEAKING, "error"): State.IDLE,
}


class InvalidTransitionError(Exception):
    pass


class StateMachine:
    """Manages the voice pipeline state transitions."""

    def __init__(self, event_bus: EventBus) -> None:
        self._state = State.IDLE
        self._event_bus = event_bus

    @property
    def state(self) -> State:
        return self._state

    async def transition(self, trigger: str) -> State:
        """Attempt a state transition. Raises InvalidTransitionError if invalid."""
        key = (self._state, trigger)
        new_state = _TRANSITIONS.get(key)

        if new_state is None:
            raise InvalidTransitionError(
                f"Invalid transition: {self._state.value} + {trigger}"
            )

        old_state = self._state
        self._state = new_state
        logger.debug("State: %s -> %s (trigger: %s)", old_state.value, new_state.value, trigger)

        await self._event_bus.publish(
            EventType.STATE_CHANGED,
            {"from": old_state.value, "to": new_state.value, "trigger": trigger},
        )

        return new_state

    def reset(self) -> None:
        """Force reset to IDLE state (for error recovery)."""
        self._state = State.IDLE
