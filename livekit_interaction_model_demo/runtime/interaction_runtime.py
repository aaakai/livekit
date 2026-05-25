from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from livekit_interaction_model_demo.agents.background_reasoner import BackgroundReasonerAgent, BackgroundResult
from livekit_interaction_model_demo.agents.registry import AgentRegistry
from livekit_interaction_model_demo.context.timeline import SharedContextTimeline
from livekit_interaction_model_demo.providers.gemini_tts import GeminiTTSProvider
from livekit_interaction_model_demo.providers.sound import Mock3DSoundProvider
from livekit_interaction_model_demo.runtime.actions import ActionType, InteractionAction
from livekit_interaction_model_demo.runtime.audio import AudioRuntime
from livekit_interaction_model_demo.runtime.floor import DecisionFrame, FloorManager
from livekit_interaction_model_demo.runtime.judge import InteractionJudge, InteractionJudgeJSONParser


class InteractionRuntime:
    """Realtime-ish interaction loop that runs every 500 ms by default."""

    def __init__(
        self,
        *,
        timeline: SharedContextTimeline,
        audio: AudioRuntime,
        judge: InteractionJudge | None = None,
        floor_manager: FloorManager | None = None,
        background_reasoner: BackgroundReasonerAgent | None = None,
        registry: AgentRegistry | None = None,
        judge_interval_s: float = 0.5,
    ) -> None:
        self.timeline = timeline
        self.audio = audio
        self.judge = judge or InteractionJudge()
        self.parser = InteractionJudgeJSONParser()
        self.floor_manager = floor_manager or FloorManager()
        self.background_reasoner = background_reasoner or BackgroundReasonerAgent()
        self.registry = registry or AgentRegistry()
        self.judge_interval_s = judge_interval_s
        self.latest_user_text = ""
        self.user_speaking = False
        self._last_backchannel_at = 0.0
        self._background_results: list[dict[str, Any]] = []
        self._loop_task: asyncio.Task[None] | None = None
        self._closed = asyncio.Event()

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self.timeline.write_event(
            "runtime_started",
            actor="system",
            payload={"judge_interval_s": self.judge_interval_s},
        )
        self._closed.clear()
        self._loop_task = asyncio.create_task(self._judge_loop())

    async def stop(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        await self.background_reasoner.drain()
        await self.audio.wait_until_idle()
        self._closed.set()
        self.timeline.write_event("runtime_stopped", actor="system", payload={})

    async def ingest_partial(self, text: str, *, source: str = "livekit") -> None:
        self.latest_user_text = text
        self.user_speaking = True
        self.timeline.write_event(
            "partial_transcript",
            actor="user",
            payload={"text": text, "source": source, "is_final": False},
        )

    async def ingest_final(self, text: str, *, source: str = "livekit", still_speaking: bool = False) -> None:
        self.latest_user_text = text
        self.user_speaking = still_speaking
        self.timeline.write_event(
            "final_transcript",
            actor="user",
            payload={"text": text, "source": source, "is_final": True, "still_speaking": still_speaking},
        )

    async def inject_background_result(self, result: BackgroundResult | dict[str, Any]) -> None:
        payload = result.to_json_dict() if isinstance(result, BackgroundResult) else dict(result)
        self._background_results.append(payload)
        self.timeline.write_event("background_result", actor="background", payload=payload)

    def make_frame(self) -> DecisionFrame:
        return DecisionFrame(
            user_speaking=self.user_speaking,
            assistant_speaking=self.audio.is_speaking(),
            latest_user_text=self.latest_user_text,
            elapsed_since_last_backchannel_s=time.monotonic() - self._last_backchannel_at,
            background_result=self._background_results[0] if self._background_results else None,
        )

    async def _judge_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.judge_interval_s)
                await self.tick()
        except asyncio.CancelledError:
            raise

    async def tick(self) -> InteractionAction:
        frame = self.make_frame()
        raw = self.judge.decide_json(self.timeline.snapshot(40), frame)
        action = self.parser.parse(raw)
        self.timeline.write_event(
            "judge_action",
            actor="judge",
            payload={"raw": raw, "action": action.to_json_dict()},
        )
        decision = self.floor_manager.authorize(action, frame)
        self.timeline.write_event(
            "floor_decision",
            actor="floor",
            payload={
                "allowed": decision.allowed,
                "state": decision.state.value,
                "reason": decision.reason,
                "action": action.type.value,
            },
        )
        if decision.allowed:
            await self._execute(action, frame)
        return action

    async def _execute(self, action: InteractionAction, frame: DecisionFrame) -> None:
        scene_context = {
            "floor_state": self.floor_manager.state.value,
            "latest_user_text": frame.latest_user_text,
        }
        if action.type is ActionType.LISTEN:
            return

        if action.type is ActionType.BACKCHANNEL:
            self.timeline.write_event("backchannel", actor="assistant", payload=action.to_json_dict())
            await self.audio.backchannel(action.text or "嗯，我在听。", scene_context=scene_context)
            self._last_backchannel_at = time.monotonic()
            return

        if action.type is ActionType.SHORT_REPLY:
            await self.audio.speak(action.text or "我听到了。", scene_context=scene_context)
            return

        if action.type is ActionType.BARGE_IN:
            if frame.background_result:
                self._background_results = [
                    result for result in self._background_results if result.get("id") != frame.background_result.get("id")
                ]
            self.timeline.write_event("barge_in", actor="assistant", payload=action.to_json_dict())
            await self.audio.barge_in(action.text or "等一下。", scene_context=scene_context)
            return

        if action.type is ActionType.INTERRUPT_SELF:
            await self.audio.interrupt(reason=action.reason or "interaction_judge_interrupt_self")
            return

        if action.type is ActionType.DEFER_BACKGROUND:
            task = action.background_task or self.latest_user_text
            self.timeline.write_event(
                "background_deferred",
                actor="background",
                payload={"task": task, "reason": action.reason},
            )
            self.background_reasoner.submit(
                task=task,
                context=self.timeline.snapshot(50),
                on_result=self.inject_background_result,
            )


def build_default_runtime(
    *,
    timeline_path: str | Path,
    tts_mock: bool | None = None,
    judge_interval_s: float = 0.5,
) -> InteractionRuntime:
    timeline = SharedContextTimeline(timeline_path)
    tts = GeminiTTSProvider(mock=tts_mock)
    sound = Mock3DSoundProvider()
    audio = AudioRuntime(tts_provider=tts, timeline=timeline, sound_provider=sound)
    registry = AgentRegistry()
    registry.register("interaction", object(), kind="CharacterAgent", description="Foreground interaction agent")
    registry.register("background_reasoner", object(), kind="SpecialistAgent", description="Async reasoning agent")
    return InteractionRuntime(
        timeline=timeline,
        audio=audio,
        registry=registry,
        judge_interval_s=judge_interval_s,
    )

