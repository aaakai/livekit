from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from livekit_interaction_model_demo.runtime.actions import ActionType, InteractionAction


class FloorState(str, Enum):
    IDLE = "IDLE"
    USER_HAS_FLOOR = "USER_HAS_FLOOR"
    ASSISTANT_HAS_FLOOR = "ASSISTANT_HAS_FLOOR"
    OVERLAP = "OVERLAP"
    BACKCHANNELING = "BACKCHANNELING"
    BARGE_IN_PENDING = "BARGE_IN_PENDING"
    BACKGROUND_THINKING = "BACKGROUND_THINKING"


@dataclass(frozen=True)
class DecisionFrame:
    user_speaking: bool
    assistant_speaking: bool
    latest_user_text: str = ""
    elapsed_since_last_backchannel_s: float = 999.0
    background_result: dict[str, Any] | None = None
    now: float = 0.0

    def __post_init__(self) -> None:
        if self.now == 0.0:
            object.__setattr__(self, "now", time.monotonic())


@dataclass(frozen=True)
class FloorDecision:
    allowed: bool
    state: FloorState
    reason: str


class FloorManager:
    """Owns floor policy.

    The InteractionJudge only says what should happen. This class decides
    whether the action is legal in the current speech/floor state.
    """

    def __init__(
        self,
        *,
        min_backchannel_interval_s: float = 3.0,
        barge_in_priority_threshold: int = 7,
    ) -> None:
        self.state = FloorState.IDLE
        self.min_backchannel_interval_s = min_backchannel_interval_s
        self.barge_in_priority_threshold = barge_in_priority_threshold

    def observe(self, frame: DecisionFrame) -> FloorState:
        if frame.user_speaking and frame.assistant_speaking:
            self.state = FloorState.OVERLAP
        elif frame.user_speaking:
            self.state = FloorState.USER_HAS_FLOOR
        elif frame.assistant_speaking:
            self.state = FloorState.ASSISTANT_HAS_FLOOR
        elif self.state not in {
            FloorState.BACKGROUND_THINKING,
            FloorState.BACKCHANNELING,
            FloorState.BARGE_IN_PENDING,
        }:
            self.state = FloorState.IDLE
        return self.state

    def authorize(self, action: InteractionAction, frame: DecisionFrame) -> FloorDecision:
        observed = self.observe(frame)

        if action.type is ActionType.LISTEN:
            if frame.user_speaking:
                self.state = FloorState.USER_HAS_FLOOR
            elif frame.assistant_speaking:
                self.state = FloorState.ASSISTANT_HAS_FLOOR
            else:
                self.state = FloorState.IDLE
            return FloorDecision(True, self.state, "listening is always allowed")

        if action.type is ActionType.BACKCHANNEL:
            if frame.user_speaking and not frame.assistant_speaking:
                if frame.elapsed_since_last_backchannel_s >= self.min_backchannel_interval_s:
                    self.state = FloorState.BACKCHANNELING
                    return FloorDecision(True, self.state, "user has floor; backchannel is brief")
                return FloorDecision(False, observed, "backchannel interval has not elapsed")
            return FloorDecision(False, observed, "backchannel requires user-only floor")

        if action.type is ActionType.SHORT_REPLY:
            if not frame.user_speaking and not frame.assistant_speaking:
                self.state = FloorState.ASSISTANT_HAS_FLOOR
                return FloorDecision(True, self.state, "floor is idle")
            return FloorDecision(False, observed, "short reply requires idle floor")

        if action.type is ActionType.BARGE_IN:
            urgent_background = bool(
                frame.background_result
                and int(frame.background_result.get("priority", 0)) >= self.barge_in_priority_threshold
            )
            urgent_action = action.priority >= self.barge_in_priority_threshold
            if frame.user_speaking and (urgent_action or urgent_background):
                self.state = FloorState.BARGE_IN_PENDING
                return FloorDecision(True, self.state, "urgent assistant barge-in while user has floor")
            if not frame.user_speaking and not frame.assistant_speaking and (urgent_action or urgent_background):
                self.state = FloorState.BARGE_IN_PENDING
                return FloorDecision(True, self.state, "urgent barge-in from idle floor")
            return FloorDecision(False, observed, "barge-in requires urgency and no assistant speech")

        if action.type is ActionType.INTERRUPT_SELF:
            if frame.assistant_speaking:
                self.state = FloorState.USER_HAS_FLOOR if frame.user_speaking else FloorState.IDLE
                return FloorDecision(True, self.state, "assistant can yield its own floor")
            return FloorDecision(False, observed, "assistant is not speaking")

        if action.type is ActionType.DEFER_BACKGROUND:
            self.state = FloorState.BACKGROUND_THINKING
            return FloorDecision(True, self.state, "background reasoning is non-blocking")

        return FloorDecision(False, observed, "unknown action")

