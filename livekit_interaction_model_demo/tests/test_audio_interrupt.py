import asyncio
from pathlib import Path

import pytest

from livekit_interaction_model_demo.context.timeline import SharedContextTimeline
from livekit_interaction_model_demo.providers.tts import TTSResult
from livekit_interaction_model_demo.runtime.audio import AudioRuntime


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
async def test_interrupt_writes_started_and_interrupted_events(tmp_path: Path) -> None:
    timeline = SharedContextTimeline(tmp_path / "events.jsonl")
    audio = AudioRuntime(tts_provider=FakeTTSProvider(), timeline=timeline, chars_per_second=1.0)

    await audio.speak("this speech is deliberately long")
    await asyncio.sleep(0)
    stopped = await audio.interrupt(reason="user_overlap")

    assert stopped
    event_types = [event["event_type"] for event in timeline.snapshot()]
    assert "assistant_speech_started" in event_types
    assert "assistant_speech_interrupted" in event_types
    interrupted = [event for event in timeline.snapshot() if event["event_type"] == "assistant_speech_interrupted"]
    assert interrupted[-1]["payload"]["reason"] == "user_overlap"

