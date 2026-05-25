from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from livekit_interaction_model_demo.runtime.actions import ActionType, InteractionAction
from livekit_interaction_model_demo.runtime.floor import DecisionFrame


class InteractionJudgeJSONParser:
    def parse(self, payload: str | dict[str, Any]) -> InteractionAction:
        return InteractionAction.from_json(payload)


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

    def decide_json(self, timeline_events: list[dict[str, Any]], frame: DecisionFrame) -> str:
        action = self.decide(timeline_events, frame)
        return json.dumps(action.to_json_dict(), ensure_ascii=False)

    def decide(self, timeline_events: list[dict[str, Any]], frame: DecisionFrame) -> InteractionAction:
        latest_text = frame.latest_user_text or self._latest_user_text(timeline_events)
        normalized = latest_text.replace(" ", "")

        if frame.assistant_speaking and frame.user_speaking:
            return InteractionAction(
                type=ActionType.INTERRUPT_SELF,
                reason="user started speaking while assistant was speaking",
                priority=6,
            )

        if frame.background_result:
            priority = int(frame.background_result.get("priority", 0))
            result_text = str(frame.background_result.get("text", "后台任务完成了。"))
            if priority >= 8:
                return InteractionAction(
                    type=ActionType.BARGE_IN,
                    text=result_text,
                    reason="high-priority background result",
                    priority=priority,
                    metadata={"background_result_id": frame.background_result.get("id")},
                )
            return InteractionAction(
                type=ActionType.LISTEN,
                reason="background result stored in context without foreground interruption",
            )

        if frame.user_speaking and "1+1=3" in normalized and "one_plus_one" not in self._sent_facts:
            self._sent_facts.add("one_plus_one")
            return InteractionAction(
                type=ActionType.BARGE_IN,
                text=self.correction_text,
                reason="factual correction while user continues",
                priority=9,
            )

        if frame.user_speaking and frame.elapsed_since_last_backchannel_s >= 3.0:
            return InteractionAction(
                type=ActionType.BACKCHANNEL,
                text=self.backchannel_text,
                reason="long continuous user speech",
                priority=1,
            )

        if self._should_defer(latest_text):
            task_key = latest_text[:120]
            if task_key not in self._deferred_tasks:
                self._deferred_tasks.add(task_key)
                return InteractionAction(
                    type=ActionType.DEFER_BACKGROUND,
                    reason="complex request should not block the foreground interaction",
                    priority=3,
                    background_task=latest_text,
                )

        if not frame.user_speaking and not frame.assistant_speaking and self._has_unanswered_final(timeline_events):
            return InteractionAction(
                type=ActionType.SHORT_REPLY,
                text="我先记下这个点，我们继续。",
                reason="brief acknowledgement after final transcript",
                priority=2,
            )

        return InteractionAction(type=ActionType.LISTEN, reason="default foreground action")

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
            if event.get("event_type") == "assistant_speech" and event.get("actor") == "assistant":
                last_assistant_seq = int(event.get("seq", -1))
        return last_final_seq > last_assistant_seq

