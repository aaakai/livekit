from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class ActionType(str, Enum):
    LISTEN = "LISTEN"
    BACKCHANNEL = "BACKCHANNEL"
    SHORT_REPLY = "SHORT_REPLY"
    BARGE_IN = "BARGE_IN"
    INTERRUPT_SELF = "INTERRUPT_SELF"
    DEFER_BACKGROUND = "DEFER_BACKGROUND"


ALLOWED_ACTION_TYPES = tuple(action.value for action in ActionType)


@dataclass(frozen=True)
class InteractionAction:
    """A structured action emitted by the InteractionJudge."""

    type: ActionType
    text: str = ""
    reason: str = ""
    priority: int = 0
    background_task: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, payload: str | bytes | Mapping[str, Any]) -> "InteractionAction":
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            try:
                raw = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ValueError(f"InteractionJudge did not return valid JSON: {exc}") from exc
        else:
            raw = dict(payload)

        if not isinstance(raw, dict):
            raise ValueError("InteractionJudge JSON must be an object")

        action_name = raw.get("action", raw.get("type"))
        if not isinstance(action_name, str):
            raise ValueError("InteractionJudge JSON must include an action/type string")

        try:
            action_type = ActionType(action_name)
        except ValueError as exc:
            allowed = ", ".join(ALLOWED_ACTION_TYPES)
            raise ValueError(f"Unknown InteractionJudge action {action_name!r}; allowed: {allowed}") from exc

        metadata = raw.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("InteractionJudge metadata must be an object when present")

        return cls(
            type=action_type,
            text=str(raw.get("text") or ""),
            reason=str(raw.get("reason") or ""),
            priority=int(raw.get("priority") or 0),
            background_task=raw.get("background_task") or None,
            metadata=metadata,
        )

    def to_json_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "action": self.type.value,
            "text": self.text,
            "reason": self.reason,
            "priority": self.priority,
        }
        if self.background_task:
            data["background_task"] = self.background_task
        if self.metadata:
            data["metadata"] = self.metadata
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_json_dict(), ensure_ascii=False)

