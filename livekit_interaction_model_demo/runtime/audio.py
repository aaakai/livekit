from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from livekit_interaction_model_demo.context.timeline import SharedContextTimeline
from livekit_interaction_model_demo.providers.sound import Mock3DSoundProvider
from livekit_interaction_model_demo.providers.tts import TTSProvider
from livekit_interaction_model_demo.runtime.actions import ActionType


class AudioRuntime:
    """TTS playback facade with interruptible simulated audio."""

    def __init__(
        self,
        *,
        tts_provider: TTSProvider,
        timeline: SharedContextTimeline,
        sound_provider: Mock3DSoundProvider | None = None,
        chars_per_second: float = 9.0,
    ) -> None:
        self.tts_provider = tts_provider
        self.timeline = timeline
        self.sound_provider = sound_provider or Mock3DSoundProvider()
        self.chars_per_second = chars_per_second
        self._current_task: asyncio.Task[None] | None = None
        self._current_playback_id: str | None = None
        self._current_text = ""

    def is_speaking(self) -> bool:
        return bool(self._current_task and not self._current_task.done())

    async def speak(self, text: str, *, scene_context: dict[str, Any] | None = None) -> str:
        return await self._start_playback(ActionType.SHORT_REPLY, text, scene_context=scene_context)

    async def backchannel(self, text: str = "嗯，我在听。", *, scene_context: dict[str, Any] | None = None) -> str:
        return await self._start_playback(ActionType.BACKCHANNEL, text, scene_context=scene_context, style="brief")

    async def barge_in(self, text: str, *, scene_context: dict[str, Any] | None = None) -> str:
        if self.is_speaking():
            await self.interrupt(reason="barge_in_replaces_current_audio")
        return await self._start_playback(ActionType.BARGE_IN, text, scene_context=scene_context, style="firm")

    async def interrupt(self, *, reason: str = "interrupted") -> bool:
        task = self._current_task
        playback_id = self._current_playback_id
        if not task or task.done():
            self.timeline.write_event(
                "interrupt",
                actor="assistant",
                payload={"stopped": False, "reason": reason},
            )
            return False

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        self.timeline.write_event(
            "interrupt",
            actor="assistant",
            payload={"stopped": True, "reason": reason, "playback_id": playback_id},
        )
        return True

    async def wait_until_idle(self) -> None:
        if self._current_task:
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass

    async def _start_playback(
        self,
        action: ActionType,
        text: str,
        *,
        scene_context: dict[str, Any] | None,
        style: str | None = None,
    ) -> str:
        tts_result = await self.tts_provider.synthesize(text, style=style)
        sound_plan = self.sound_provider.plan(action=action, text=text, scene_context=scene_context)
        playback_id = uuid.uuid4().hex[:10]
        self._current_playback_id = playback_id
        self._current_text = text

        self.timeline.write_event(
            "sound_plan",
            actor="audio",
            payload=sound_plan,
        )
        self.timeline.write_event(
            "assistant_speech",
            actor="assistant",
            payload={
                "playback_id": playback_id,
                "action": action.value,
                "text": text,
                "status": "start",
                "tts": {
                    "provider": tts_result.provider,
                    "voice": tts_result.voice,
                    "mime_type": tts_result.mime_type,
                    "sample_rate_hz": tts_result.sample_rate_hz,
                    "mocked": tts_result.mocked,
                    "bytes": len(tts_result.audio),
                },
            },
        )

        self._current_task = asyncio.create_task(self._playback(playback_id, text, action))
        return playback_id

    async def _playback(self, playback_id: str, text: str, action: ActionType) -> None:
        start = time.monotonic()
        duration = min(8.0, max(0.35, len(text) / self.chars_per_second))
        try:
            await asyncio.sleep(duration)
            self.timeline.write_event(
                "assistant_speech",
                actor="assistant",
                payload={
                    "playback_id": playback_id,
                    "action": action.value,
                    "text": text,
                    "status": "complete",
                    "duration_s": round(time.monotonic() - start, 3),
                },
            )
        except asyncio.CancelledError:
            self.timeline.write_event(
                "assistant_speech",
                actor="assistant",
                payload={
                    "playback_id": playback_id,
                    "action": action.value,
                    "text": text,
                    "status": "cancelled",
                    "duration_s": round(time.monotonic() - start, 3),
                },
            )
            raise
        finally:
            if self._current_playback_id == playback_id:
                self._current_task = None
                self._current_playback_id = None
                self._current_text = ""

