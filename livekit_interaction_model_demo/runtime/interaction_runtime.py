from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from livekit_interaction_model_demo.agents.background_reasoner import BackgroundReasonerAgent, BackgroundResult
from livekit_interaction_model_demo.agents.registry import AgentRegistry
from livekit_interaction_model_demo.context.timeline import SharedContextTimeline
from livekit_interaction_model_demo.providers.gemini_tts import GeminiTTSProvider
from livekit_interaction_model_demo.providers.sound import Mock3DSoundProvider
from livekit_interaction_model_demo.runtime.actions import ActionType, InteractionAction
from livekit_interaction_model_demo.runtime.audio import AudioRuntime
from livekit_interaction_model_demo.runtime.backchannel_controller import BackchannelController
from livekit_interaction_model_demo.runtime.barge_in_controller import BargeInController
from livekit_interaction_model_demo.runtime.floor import DecisionFrame, FloorManager
from livekit_interaction_model_demo.runtime.judge import InteractionJudge, InteractionJudgeJSONParser
from livekit_interaction_model_demo.runtime.partial_transcript_buffer import PartialTranscriptBuffer


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
        transcript_buffer: PartialTranscriptBuffer | None = None,
        backchannel_controller: BackchannelController | None = None,
        barge_in_controller: BargeInController | None = None,
        judge_interval_s: float = 0.5,
    ) -> None:
        self.timeline = timeline
        self.audio = audio
        self.judge = judge or InteractionJudge()
        self.parser = InteractionJudgeJSONParser()
        self.floor_manager = floor_manager or FloorManager(timeline=timeline)
        if self.floor_manager.timeline is None:
            self.floor_manager.timeline = timeline
        self.background_reasoner = background_reasoner or BackgroundReasonerAgent()
        self.registry = registry or AgentRegistry()
        self.transcript_buffer = transcript_buffer or PartialTranscriptBuffer(window_s=5.0)
        self.backchannel_controller = backchannel_controller or BackchannelController(
            audio=audio,
            timeline=timeline,
            min_interval_s=self.floor_manager.min_backchannel_interval_s,
        )
        self.barge_in_controller = barge_in_controller or BargeInController(
            audio=audio,
            timeline=timeline,
            floor_manager=self.floor_manager,
            transcript_buffer=self.transcript_buffer,
        )
        self.judge_interval_s = judge_interval_s
        self.latest_user_text = ""
        self.user_speaking = False
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
        self.transcript_buffer.add_partial(
            text,
            source=source,
            assistant_speaking=self.audio.is_speaking(),
        )
        self.timeline.write_event(
            "partial_transcript",
            actor="user",
            payload={"text": text, "source": source, "is_final": False},
        )

    async def ingest_final(self, text: str, *, source: str = "livekit", still_speaking: bool = False) -> None:
        self.latest_user_text = text
        self.user_speaking = still_speaking
        self.transcript_buffer.add_final(
            text,
            source=source,
            still_speaking=still_speaking,
            assistant_speaking=self.audio.is_speaking(),
        )
        self.timeline.write_event(
            "final_transcript",
            actor="user",
            payload={"text": text, "source": source, "is_final": True, "still_speaking": still_speaking},
        )

    async def inject_background_result(self, result: BackgroundResult | dict[str, Any]) -> None:
        payload = result.to_json_dict() if isinstance(result, BackgroundResult) else dict(result)
        self._background_results.append(payload)
        self.timeline.write_event("background_result", actor="background", payload=payload)

    def make_snapshot(self) -> dict[str, Any]:
        self.transcript_buffer.set_assistant_speaking(self.audio.is_speaking())
        self.transcript_buffer.user_speaking = self.user_speaking
        background_result = None
        if self._background_results:
            background_result = max(
                self._background_results,
                key=lambda result: int(result.get("priority", 0)),
            )
        snapshot = self.transcript_buffer.build_snapshot(
            background_result=background_result
        )
        snapshot["assistant_action"] = self.audio.current_action()
        snapshot["timeline_events"] = self.timeline.snapshot(40)
        return snapshot

    def make_frame(self, snapshot: dict[str, Any] | None = None) -> DecisionFrame:
        snapshot = snapshot or self.make_snapshot()
        return DecisionFrame(
            user_speaking=bool(snapshot.get("user_speaking")),
            assistant_speaking=bool(snapshot.get("assistant_speaking")),
            latest_user_text=str(snapshot.get("current_partial") or snapshot.get("last_final") or ""),
            elapsed_since_last_backchannel_s=self.backchannel_controller.elapsed_since_last_s,
            background_result=snapshot.get("background_result"),
            current_utterance_id=snapshot.get("current_utterance_id"),
        )

    async def _judge_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.judge_interval_s)
                await self.tick()
        except asyncio.CancelledError:
            raise

    async def tick(self) -> InteractionAction:
        snapshot = self.make_snapshot()
        frame = self.make_frame(snapshot)
        raw = self.judge.decide_json(snapshot)
        action = self.parser.parse(raw)
        self.timeline.write_event(
            "judge_action",
            actor="judge",
            payload={"raw": raw, "action": action.to_json_dict()},
        )

        if action.type is ActionType.BARGE_IN:
            scene_context = self._scene_context(frame, snapshot)
            handled, _decision = await self.barge_in_controller.handle(
                action,
                frame=frame,
                snapshot=snapshot,
                scene_context=scene_context,
            )
            if handled and frame.background_result:
                background_id = frame.background_result.get("id")
                self._background_results = [
                    result for result in self._background_results if result.get("id") != background_id
                ]
            return action

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
            await self._execute(action, frame, snapshot)
        return action

    async def _execute(
        self,
        action: InteractionAction,
        frame: DecisionFrame,
        snapshot: dict[str, Any],
    ) -> None:
        scene_context = self._scene_context(frame, snapshot)
        if action.type is ActionType.LISTEN:
            return

        if action.type is ActionType.BACKCHANNEL:
            await self.backchannel_controller.handle(
                action,
                snapshot=snapshot,
                scene_context=scene_context,
            )
            return

        if action.type is ActionType.SHORT_REPLY:
            await self.audio.speak(action.text or "我听到了。", scene_context=scene_context)
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

    def _scene_context(self, frame: DecisionFrame, snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "floor_state": self.floor_manager.state.value,
            "latest_user_text": frame.latest_user_text,
            "utterance_id": snapshot.get("current_utterance_id"),
            "utterance_elapsed_s": snapshot.get("utterance_elapsed_s"),
        }


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
