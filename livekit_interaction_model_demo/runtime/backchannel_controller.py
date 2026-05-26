from __future__ import annotations

import time
from typing import Any

from livekit_interaction_model_demo.context.timeline import SharedContextTimeline
from livekit_interaction_model_demo.runtime.actions import ActionType, InteractionAction
from livekit_interaction_model_demo.runtime.audio import AudioRuntime


class BackchannelController:
    """Limits and executes short, non-memory backchannels."""

    def __init__(
        self,
        *,
        audio: AudioRuntime,
        timeline: SharedContextTimeline,
        min_interval_s: float = 3.0,
        min_user_speech_s: float = 3.0,
    ) -> None:
        self.audio = audio
        self.timeline = timeline
        self.min_interval_s = min_interval_s
        self.min_user_speech_s = min_user_speech_s
        self._last_backchannel_at = 0.0

    @property
    def elapsed_since_last_s(self) -> float:
        return time.monotonic() - self._last_backchannel_at

    def can_backchannel(self, snapshot: dict[str, Any]) -> tuple[bool, str]:
        if not snapshot.get("user_speaking"):
            return False, "user is not speaking"
        if snapshot.get("assistant_speaking"):
            return False, "assistant is speaking"
        if float(snapshot.get("utterance_elapsed_s", 0.0)) < self.min_user_speech_s:
            return False, "user speech has not been continuous long enough"
        if self.elapsed_since_last_s < self.min_interval_s:
            return False, "backchannel interval has not elapsed"
        return True, "backchannel allowed"

    async def handle(
        self,
        action: InteractionAction,
        *,
        snapshot: dict[str, Any],
        scene_context: dict[str, Any] | None = None,
    ) -> bool:
        if action.type is not ActionType.BACKCHANNEL:
            return False

        allowed, reason = self.can_backchannel(snapshot)
        if not allowed:
            self.timeline.write_event(
                "backchannel_skipped",
                actor="assistant",
                payload={"reason": reason, "action": action.to_json_dict()},
            )
            return False

        payload = action.to_json_dict()
        payload["utterance_id"] = snapshot.get("current_utterance_id")
        self.timeline.write_event("backchannel", actor="assistant", payload=payload)
        await self.audio.backchannel(action.text or "嗯，我在听。", scene_context=scene_context)
        self._last_backchannel_at = time.monotonic()
        return True

