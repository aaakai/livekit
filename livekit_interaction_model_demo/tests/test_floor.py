from pathlib import Path

from livekit_interaction_model_demo.context.timeline import SharedContextTimeline
from livekit_interaction_model_demo.runtime.actions import ActionType, InteractionAction
from livekit_interaction_model_demo.runtime.floor import DecisionFrame, FloorManager, FloorState


def test_floor_state_changed_event_is_written(tmp_path: Path) -> None:
    timeline = SharedContextTimeline(tmp_path / "events.jsonl")
    floor = FloorManager(timeline=timeline)

    decision = floor.authorize(
        InteractionAction(ActionType.LISTEN),
        DecisionFrame(user_speaking=True, assistant_speaking=False, current_utterance_id=3),
    )

    assert decision.allowed
    assert decision.state is FloorState.USER_HAS_FLOOR
    state_events = [event for event in timeline.snapshot() if event["event_type"] == "floor_state_changed"]
    assert state_events
    assert state_events[-1]["payload"]["to"] == "USER_HAS_FLOOR"
    assert state_events[-1]["payload"]["utterance_id"] == 3


def test_floor_manager_allows_urgent_user_barge_in_only_when_assistant_is_not_speaking() -> None:
    floor = FloorManager()
    action = InteractionAction(ActionType.BARGE_IN, text="等一下。", priority=9)

    allowed = floor.authorize(action, DecisionFrame(user_speaking=True, assistant_speaking=False))
    assert allowed.allowed
    assert allowed.state is FloorState.BARGE_IN_PENDING

    blocked = floor.authorize(action, DecisionFrame(user_speaking=True, assistant_speaking=True))
    assert not blocked.allowed
    assert blocked.state is FloorState.OVERLAP

