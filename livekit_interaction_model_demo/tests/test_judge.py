import pytest

from livekit_interaction_model_demo.runtime.actions import ActionType, InteractionAction
from livekit_interaction_model_demo.runtime.floor import DecisionFrame
from livekit_interaction_model_demo.runtime.judge import InteractionJudge, InteractionJudgeJSONParser


def test_interaction_judge_json_parser_accepts_structured_action() -> None:
    parser = InteractionJudgeJSONParser()
    action = parser.parse('{"action":"BACKCHANNEL","text":"嗯，我在听。","priority":1}')
    assert action.type is ActionType.BACKCHANNEL
    assert action.text == "嗯，我在听。"
    assert action.priority == 1


def test_interaction_judge_json_parser_rejects_unknown_action() -> None:
    with pytest.raises(ValueError):
        InteractionAction.from_json('{"action":"TAKE_OVER"}')


def test_interaction_judge_emits_barge_in_for_wrong_math() -> None:
    judge = InteractionJudge()
    action = judge.decide(
        [],
        DecisionFrame(
            user_speaking=True,
            assistant_speaking=False,
            latest_user_text="我觉得 1+1=3，然后继续说",
        ),
    )
    assert action.type is ActionType.BARGE_IN
    assert action.priority >= 7
    assert "1+1 是 2" in action.text

