import asyncio
from pathlib import Path

import pytest

from livekit_interaction_model_demo.context.timeline import SharedContextTimeline
from livekit_interaction_model_demo.providers.tts import TTSResult
from livekit_interaction_model_demo.runtime.actions import ActionType, InteractionAction
from livekit_interaction_model_demo.runtime.audio import AudioRuntime
from livekit_interaction_model_demo.runtime.barge_in_controller import BargeInController
from livekit_interaction_model_demo.runtime.floor import DecisionFrame, FloorManager
from livekit_interaction_model_demo.runtime.partial_transcript_buffer import PartialTranscriptBuffer


class FakeTTSProvider:
    async def synthesize(self, text: str, *, voice: str | None = None, style: str | None = None) -> TTSResult:
        await asyncio.sleep(0)
        return TTSResult(
            text=text,
            audio=b"fake",
            mime_type="audio/mock",
            sample_rate_hz=24000,
            voice=voice or "Fake",
            provider="fake",
            mocked=True,
        )


@pytest.mark.asyncio
async def test_barge_in_controller_requires_confidence_and_once_per_utterance(tmp_path: Path) -> None:
    timeline = SharedContextTimeline(tmp_path / "events.jsonl")
    audio = AudioRuntime(tts_provider=FakeTTSProvider(), timeline=timeline, chars_per_second=100.0)
    floor = FloorManager(timeline=timeline)
    buffer = PartialTranscriptBuffer()
    buffer.add_partial("1+1=3 然后继续说", now=100.0)
    snapshot = buffer.build_snapshot(now=100.2)
    frame = DecisionFrame(user_speaking=True, assistant_speaking=False, latest_user_text=snapshot["current_partial"])
    controller = BargeInController(
        audio=audio,
        timeline=timeline,
        floor_manager=floor,
        transcript_buffer=buffer,
    )

    low_confidence = InteractionAction(
        ActionType.BARGE_IN,
        text="等一下。",
        priority=9,
        metadata={"confidence": 0.5, "priority_band": "P1"},
    )
    handled, decision = await controller.handle(low_confidence, frame=frame, snapshot=snapshot)
    assert not handled
    assert not decision.allowed

    action = InteractionAction(
        ActionType.BARGE_IN,
        text="等一下，1+1 是 2。",
        priority=9,
        metadata={"confidence": 0.95, "priority_band": "P1"},
    )
    handled, decision = await controller.handle(action, frame=frame, snapshot=snapshot)
    assert handled
    assert decision.allowed
    await audio.wait_until_idle()

    handled_again, decision_again = await controller.handle(action, frame=frame, snapshot=snapshot)
    assert not handled_again
    assert not decision_again.allowed

    event_types = [event["event_type"] for event in timeline.snapshot()]
    assert event_types.count("assistant_barge_in") == 1

