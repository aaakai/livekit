from livekit_interaction_model_demo.runtime.actions import ActionType, InteractionAction
from livekit_interaction_model_demo.runtime.floor import DecisionFrame, FloorManager, FloorState


def test_floor_manager_basic_state_flow() -> None:
    floor = FloorManager(min_backchannel_interval_s=3.0)

    listen = floor.authorize(
        InteractionAction(ActionType.LISTEN),
        DecisionFrame(user_speaking=True, assistant_speaking=False),
    )
    assert listen.allowed
    assert listen.state is FloorState.USER_HAS_FLOOR

    backchannel = floor.authorize(
        InteractionAction(ActionType.BACKCHANNEL, text="嗯，我在听。"),
        DecisionFrame(
            user_speaking=True,
            assistant_speaking=False,
            elapsed_since_last_backchannel_s=3.5,
        ),
    )
    assert backchannel.allowed
    assert backchannel.state is FloorState.BACKCHANNELING

    interrupted = floor.authorize(
        InteractionAction(ActionType.INTERRUPT_SELF, reason="user overlap"),
        DecisionFrame(user_speaking=True, assistant_speaking=True),
    )
    assert interrupted.allowed
    assert interrupted.state is FloorState.USER_HAS_FLOOR


def test_floor_manager_blocks_nonurgent_barge_in() -> None:
    floor = FloorManager(barge_in_priority_threshold=7)
    decision = floor.authorize(
        InteractionAction(ActionType.BARGE_IN, text="等一下。", priority=2),
        DecisionFrame(user_speaking=True, assistant_speaking=False),
    )
    assert not decision.allowed
    assert decision.state is FloorState.USER_HAS_FLOOR

