import json
from pathlib import Path

from livekit_interaction_model_demo.context.timeline import SharedContextTimeline
from livekit_interaction_model_demo.runtime.partial_transcript_buffer import PartialTranscriptBuffer


def test_timeline_writes_jsonl_events(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    timeline = SharedContextTimeline(path, run_id="test-run")
    event = timeline.write_event("partial_transcript", actor="user", payload={"text": "hello"})

    assert event["seq"] == 1
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["run_id"] == "test-run"
    assert parsed["event_type"] == "partial_transcript"
    assert parsed["payload"]["text"] == "hello"
    assert timeline.snapshot()[0]["seq"] == 1


def test_partial_transcript_buffer_builds_short_lived_snapshot() -> None:
    buffer = PartialTranscriptBuffer(window_s=5.0)
    buffer.add_partial("1+1=3", source="test", now=100.0)
    buffer.add_partial("1+1=3 然后继续", source="test", now=101.0)
    buffer.mark_barge_in_triggered()

    snapshot = buffer.build_snapshot(now=102.0)

    assert snapshot["current_partial"] == "1+1=3 然后继续"
    assert snapshot["user_speaking"]
    assert snapshot["utterance_elapsed_s"] == 2.0
    assert snapshot["barge_in_already_triggered"]
    assert len(snapshot["recent_partials"]) == 2
