from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PartialTranscriptRecord:
    text: str
    ts: float
    source: str
    is_final: bool = False

    def to_json_dict(self, *, now: float) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source,
            "is_final": self.is_final,
            "age_s": round(max(0.0, now - self.ts), 3),
        }


class PartialTranscriptBuffer:
    """Short-lived speech state for the foreground interaction loop.

    This buffer is intentionally not long-term memory. It keeps just enough
    recent partial transcript context for a low-latency InteractionJudge to
    decide whether to listen, backchannel, interrupt itself, or barge in.
    """

    def __init__(self, *, window_s: float = 5.0) -> None:
        self.window_s = window_s
        self.current_partial = ""
        self.recent_partials: list[PartialTranscriptRecord] = []
        self.last_final = ""
        self.user_speaking = False
        self.assistant_speaking = False
        self.current_utterance_id = 0
        self._utterance_started_at: float | None = None
        self._barge_in_utterance_ids: set[int] = set()

    def add_partial(
        self,
        text: str,
        *,
        source: str = "livekit",
        assistant_speaking: bool | None = None,
        now: float | None = None,
    ) -> None:
        now = now or time.monotonic()
        if not self.user_speaking:
            self.current_utterance_id += 1
            self._utterance_started_at = now
        if assistant_speaking is not None:
            self.assistant_speaking = assistant_speaking

        self.user_speaking = True
        self.current_partial = text
        self.recent_partials.append(PartialTranscriptRecord(text=text, ts=now, source=source))
        self._prune(now)

    def add_final(
        self,
        text: str,
        *,
        source: str = "livekit",
        still_speaking: bool = False,
        assistant_speaking: bool | None = None,
        now: float | None = None,
    ) -> None:
        now = now or time.monotonic()
        if self.current_utterance_id == 0:
            self.current_utterance_id = 1
            self._utterance_started_at = now
        if assistant_speaking is not None:
            self.assistant_speaking = assistant_speaking

        self.last_final = text
        self.current_partial = text
        self.user_speaking = still_speaking
        self.recent_partials.append(
            PartialTranscriptRecord(text=text, ts=now, source=source, is_final=True)
        )
        if not still_speaking:
            self._utterance_started_at = None
        self._prune(now)

    def set_user_speaking(self, value: bool, *, now: float | None = None) -> None:
        now = now or time.monotonic()
        if value and not self.user_speaking:
            self.current_utterance_id += 1
            self._utterance_started_at = now
        if not value:
            self._utterance_started_at = None
        self.user_speaking = value

    def set_assistant_speaking(self, value: bool) -> None:
        self.assistant_speaking = value

    def mark_barge_in_triggered(self) -> None:
        if self.current_utterance_id:
            self._barge_in_utterance_ids.add(self.current_utterance_id)

    def has_barge_in_for_current_utterance(self) -> bool:
        return self.current_utterance_id in self._barge_in_utterance_ids

    def build_snapshot(
        self,
        *,
        background_result: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        now = now or time.monotonic()
        self._prune(now)
        utterance_elapsed_s = 0.0
        if self.user_speaking and self._utterance_started_at is not None:
            utterance_elapsed_s = max(0.0, now - self._utterance_started_at)

        return {
            "current_partial": self.current_partial,
            "recent_partials": [record.to_json_dict(now=now) for record in self.recent_partials],
            "last_final": self.last_final,
            "user_speaking": self.user_speaking,
            "assistant_speaking": self.assistant_speaking,
            "current_utterance_id": self.current_utterance_id,
            "utterance_elapsed_s": round(utterance_elapsed_s, 3),
            "barge_in_already_triggered": self.has_barge_in_for_current_utterance(),
            "background_result": background_result,
        }

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        self.recent_partials = [record for record in self.recent_partials if record.ts >= cutoff]

