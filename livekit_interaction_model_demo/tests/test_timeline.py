import json
from pathlib import Path

from livekit_interaction_model_demo.context.timeline import SharedContextTimeline


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

