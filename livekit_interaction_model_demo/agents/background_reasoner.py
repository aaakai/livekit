from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class BackgroundResult:
    id: str
    task: str
    text: str
    priority: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "text": self.text,
            "priority": self.priority,
            "metadata": self.metadata,
        }


class BackgroundReasonerAgent:
    """Async background worker for slow reasoning."""

    def __init__(self, *, delay_s: float = 0.8) -> None:
        self.delay_s = delay_s
        self._tasks: set[asyncio.Task[None]] = set()

    def submit(
        self,
        *,
        task: str,
        context: list[dict[str, Any]],
        on_result: Callable[[BackgroundResult], Awaitable[None]],
    ) -> asyncio.Task[None]:
        async def runner() -> None:
            result = await self.reason(task=task, context=context)
            await on_result(result)

        handle = asyncio.create_task(runner())
        self._tasks.add(handle)
        handle.add_done_callback(self._tasks.discard)
        return handle

    async def reason(self, *, task: str, context: list[dict[str, Any]]) -> BackgroundResult:
        await asyncio.sleep(self.delay_s)
        priority = 9 if ("高优先级" in task or "urgent" in task.lower()) else 5
        if priority >= 8:
            text = "后台推理有高优先级发现：这里可能影响当前结论，建议先暂停确认。"
        else:
            text = "后台推理完成：我已经把补充结论写入共享上下文。"
        return BackgroundResult(
            id=uuid.uuid4().hex[:10],
            task=task,
            text=text,
            priority=priority,
            metadata={"context_events": len(context), "agent": "BackgroundReasonerAgent"},
        )

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

