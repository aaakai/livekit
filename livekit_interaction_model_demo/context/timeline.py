from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class SharedContextTimeline:
    """Append-only shared context written as JSONL."""

    def __init__(self, path: str | Path, *, run_id: str | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self._lock = threading.Lock()
        self._seq = 0
        self._events: list[dict[str, Any]] = []

    def reset(self) -> None:
        with self._lock:
            self._seq = 0
            self._events.clear()
            self.path.write_text("", encoding="utf-8")

    def write_event(
        self,
        event_type: str,
        *,
        actor: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            event = {
                "ts": time.time(),
                "run_id": self.run_id,
                "seq": self._seq,
                "event_type": event_type,
                "actor": actor,
                "payload": payload or {},
            }
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            self._events.append(event)
            return event

    def snapshot(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if limit is None:
                return list(self._events)
            return list(self._events[-limit:])

