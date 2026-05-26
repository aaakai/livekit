from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from livekit_interaction_model_demo.runtime.actions import ActionType, InteractionAction
from livekit_interaction_model_demo.runtime.floor import DecisionFrame


class InteractionJudgeJSONParser:
    def parse(self, payload: str | dict[str, Any]) -> InteractionAction:
        try:
            return InteractionAction.from_json(payload)
        except ValueError as exc:
            return InteractionAction(
                type=ActionType.LISTEN,
                reason="judge_parse_failed",
                metadata={"error": str(exc), "raw": str(payload)[:500]},
            )


@dataclass
class InteractionJudge:
    """Small policy-model stand-in.

    Production code can swap this class for a small model call that returns
    only the same structured action JSON.
    """

    backchannel_text: str = "嗯，我在听。"
    correction_text: str = "等一下，1+1 是 2。"
    _sent_facts: set[str] = field(default_factory=set)
    _deferred_tasks: set[str] = field(default_factory=set)
    _deferred_utterance_ids: set[int] = field(default_factory=set)

    def decide_json(
        self,
        snapshot_or_events: dict[str, Any] | list[dict[str, Any]],
        frame: DecisionFrame | None = None,
    ) -> str:
        action = self.decide(snapshot_or_events, frame)
        return json.dumps(action.to_json_dict(), ensure_ascii=False)

    def decide(
        self,
        snapshot_or_events: dict[str, Any] | list[dict[str, Any]],
        frame: DecisionFrame | None = None,
    ) -> InteractionAction:
        snapshot = self._coerce_snapshot(snapshot_or_events, frame)
        timeline_events = snapshot.get("timeline_events", [])
        latest_text = (
            str(snapshot.get("current_partial") or "")
            or str(snapshot.get("last_final") or "")
            or self._latest_user_text(timeline_events)
        )
        normalized = latest_text.replace(" ", "")
        user_speaking = bool(snapshot.get("user_speaking"))
        assistant_speaking = bool(snapshot.get("assistant_speaking"))
        assistant_action = snapshot.get("assistant_action")
        background_result = snapshot.get("background_result")

        if assistant_speaking and user_speaking and assistant_action not in {"BARGE_IN", "BACKCHANNEL"}:
            return InteractionAction(
                type=ActionType.INTERRUPT_SELF,
                reason="user started speaking while assistant was speaking",
                priority=6,
                metadata={"confidence": 0.96, "priority_band": "P1"},
            )

        if isinstance(background_result, dict):
            priority = int(background_result.get("priority", 0))
            result_text = str(background_result.get("text", "后台任务完成了。"))
            if priority >= 8:
                return InteractionAction(
                    type=ActionType.BARGE_IN,
                    text=result_text,
                    reason="high-priority background result",
                    priority=priority,
                    metadata={
                        "background_result_id": background_result.get("id"),
                        "confidence": 0.93,
                        "priority_band": "P1",
                    },
                )
            return InteractionAction(
                type=ActionType.LISTEN,
                reason="background result stored in context without foreground interruption",
            )

        if (
            user_speaking
            and "1+1=3" in normalized
            and "one_plus_one" not in self._sent_facts
            and not snapshot.get("barge_in_already_triggered")
        ):
            self._sent_facts.add("one_plus_one")
            return InteractionAction(
                type=ActionType.BARGE_IN,
                text=self.correction_text,
                reason="factual correction while user continues",
                priority=9,
                metadata={"confidence": 0.95, "priority_band": "P1"},
            )

        if user_speaking and float(snapshot.get("utterance_elapsed_s", 0.0)) >= 3.0:
            return InteractionAction(
                type=ActionType.BACKCHANNEL,
                text=self.backchannel_text,
                reason="long continuous user speech",
                priority=1,
                metadata={"confidence": 0.9, "priority_band": "P4"},
            )

        if self._should_defer(latest_text):
            utterance_id = snapshot.get("current_utterance_id")
            if isinstance(utterance_id, int) and utterance_id in self._deferred_utterance_ids:
                return InteractionAction(type=ActionType.LISTEN, reason="background reasoning already deferred")
            task_key = latest_text[:120]
            if task_key not in self._deferred_tasks:
                self._deferred_tasks.add(task_key)
                if isinstance(utterance_id, int):
                    self._deferred_utterance_ids.add(utterance_id)
                return InteractionAction(
                    type=ActionType.DEFER_BACKGROUND,
                    reason="complex request should not block the foreground interaction",
                    priority=3,
                    background_task=latest_text,
                )

        if not user_speaking and not assistant_speaking and self._has_unanswered_final(timeline_events):
            return InteractionAction(
                type=ActionType.SHORT_REPLY,
                text="我先记下这个点，我们继续。",
                reason="brief acknowledgement after final transcript",
                priority=2,
                metadata={"confidence": 0.75, "priority_band": "P4"},
            )

        return InteractionAction(type=ActionType.LISTEN, reason="default foreground action")

    def _coerce_snapshot(
        self,
        snapshot_or_events: dict[str, Any] | list[dict[str, Any]],
        frame: DecisionFrame | None,
    ) -> dict[str, Any]:
        if isinstance(snapshot_or_events, dict):
            return dict(snapshot_or_events)
        events = list(snapshot_or_events)
        if frame is None:
            return {
                "current_partial": self._latest_user_text(events),
                "last_final": "",
                "user_speaking": False,
                "assistant_speaking": False,
                "assistant_action": None,
                "utterance_elapsed_s": 0.0,
                "background_result": None,
                "barge_in_already_triggered": False,
                "timeline_events": events,
            }
        return {
            "current_partial": frame.latest_user_text,
            "last_final": "",
            "user_speaking": frame.user_speaking,
            "assistant_speaking": frame.assistant_speaking,
            "assistant_action": None,
            "utterance_elapsed_s": frame.elapsed_since_last_backchannel_s,
            "background_result": frame.background_result,
            "barge_in_already_triggered": False,
            "timeline_events": events,
        }

    def _latest_user_text(self, events: list[dict[str, Any]]) -> str:
        for event in reversed(events):
            if event.get("actor") == "user" and event.get("event_type") in {"partial_transcript", "final_transcript"}:
                return str(event.get("payload", {}).get("text", ""))
        return ""

    def _should_defer(self, text: str) -> bool:
        triggers = ("分析", "推理", "规划", "复杂", "后台", "research", "reason")
        return any(trigger in text for trigger in triggers)

    def _has_unanswered_final(self, events: list[dict[str, Any]]) -> bool:
        last_final_seq = -1
        last_assistant_seq = -1
        for event in events:
            if event.get("event_type") == "final_transcript" and event.get("actor") == "user":
                last_final_seq = int(event.get("seq", -1))
            if event.get("event_type") in {
                "assistant_speech",
                "assistant_speech_started",
                "assistant_speech_finished",
            } and event.get("actor") == "assistant":
                last_assistant_seq = int(event.get("seq", -1))
        return last_final_seq > last_assistant_seq
