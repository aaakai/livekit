from __future__ import annotations

from typing import Any

from livekit_interaction_model_demo.context.timeline import SharedContextTimeline
from livekit_interaction_model_demo.runtime.actions import ActionType, InteractionAction
from livekit_interaction_model_demo.runtime.audio import AudioRuntime
from livekit_interaction_model_demo.runtime.floor import DecisionFrame, FloorDecision, FloorManager
from livekit_interaction_model_demo.runtime.partial_transcript_buffer import PartialTranscriptBuffer


class BargeInController:
    """Executes proactive assistant interruptions after policy checks."""

    def __init__(
        self,
        *,
        audio: AudioRuntime,
        timeline: SharedContextTimeline,
        floor_manager: FloorManager,
        transcript_buffer: PartialTranscriptBuffer,
        min_confidence: float = 0.88,
        max_priority_rank: int = 2,
    ) -> None:
        self.audio = audio
        self.timeline = timeline
        self.floor_manager = floor_manager
        self.transcript_buffer = transcript_buffer
        self.min_confidence = min_confidence
        self.max_priority_rank = max_priority_rank

    async def handle(
        self,
        action: InteractionAction,
        *,
        frame: DecisionFrame,
        snapshot: dict[str, Any],
        scene_context: dict[str, Any] | None = None,
    ) -> tuple[bool, FloorDecision]:
        if action.type is not ActionType.BARGE_IN:
            raise ValueError("BargeInController only handles BARGE_IN actions")

        confidence = self._confidence(action)
        priority_rank = self._priority_rank(action)
        if confidence < self.min_confidence:
            decision = FloorDecision(False, self.floor_manager.state, "barge-in confidence below threshold")
            self._write_decision(action, decision, confidence, priority_rank)
            return False, decision

        if priority_rank > self.max_priority_rank:
            decision = FloorDecision(False, self.floor_manager.state, "barge-in priority is lower than P2")
            self._write_decision(action, decision, confidence, priority_rank)
            return False, decision

        if snapshot.get("barge_in_already_triggered") or self.transcript_buffer.has_barge_in_for_current_utterance():
            decision = FloorDecision(False, self.floor_manager.state, "current utterance already had a barge-in")
            self._write_decision(action, decision, confidence, priority_rank)
            return False, decision

        decision = self.floor_manager.authorize(action, frame)
        self._write_decision(action, decision, confidence, priority_rank)
        if not decision.allowed:
            return False, decision

        self.transcript_buffer.mark_barge_in_triggered()
        payload = action.to_json_dict()
        payload.update(
            {
                "confidence": confidence,
                "priority_rank": priority_rank,
                "utterance_id": snapshot.get("current_utterance_id"),
            }
        )
        self.timeline.write_event("assistant_barge_in", actor="assistant", payload=payload)
        self.timeline.write_event("barge_in", actor="assistant", payload=payload)
        await self.audio.barge_in(action.text or "等一下。", scene_context=scene_context)
        return True, decision

    def _write_decision(
        self,
        action: InteractionAction,
        decision: FloorDecision,
        confidence: float,
        priority_rank: int,
    ) -> None:
        self.timeline.write_event(
            "floor_decision",
            actor="floor",
            payload={
                "allowed": decision.allowed,
                "state": decision.state.value,
                "reason": decision.reason,
                "action": action.type.value,
                "confidence": confidence,
                "priority_rank": priority_rank,
            },
        )

    def _confidence(self, action: InteractionAction) -> float:
        raw = action.metadata.get("confidence", 0.0)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    def _priority_rank(self, action: InteractionAction) -> int:
        raw = (
            action.metadata.get("priority_rank")
            or action.metadata.get("priority_band")
            or action.metadata.get("priority_label")
        )
        if isinstance(raw, str):
            normalized = raw.strip().upper()
            if normalized.startswith("P") and normalized[1:].isdigit():
                return int(normalized[1:])
        if isinstance(raw, int):
            return raw

        if action.priority >= 9:
            return 1
        if action.priority >= 7:
            return 2
        return 3
