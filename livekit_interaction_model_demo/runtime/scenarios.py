from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from livekit_interaction_model_demo.agents.background_reasoner import BackgroundResult
from livekit_interaction_model_demo.runtime.interaction_runtime import InteractionRuntime, build_default_runtime

ScenarioName = Literal["A", "B", "C", "D"]


def create_runtime_for_demo(*, events_path: str | Path, judge_interval_s: float = 0.5) -> InteractionRuntime:
    return build_default_runtime(timeline_path=events_path, tts_mock=True, judge_interval_s=judge_interval_s)


async def stream_text(
    runtime: InteractionRuntime,
    text: str,
    *,
    delay_s: float = 0.18,
    final: bool = True,
    still_speaking_after_final: bool = False,
) -> None:
    step = max(1, len(text) // 8)
    for end in range(step, len(text) + step, step):
        await runtime.ingest_partial(text[: min(end, len(text))], source="scenario")
        await asyncio.sleep(delay_s)
    if final:
        await runtime.ingest_final(text, source="scenario", still_speaking=still_speaking_after_final)


async def run_scenario(runtime: InteractionRuntime, scenario: ScenarioName) -> None:
    runtime.timeline.write_event("scenario_started", actor="demo", payload={"scenario": scenario})
    await runtime.start()
    if scenario == "A":
        await _scenario_a(runtime)
    elif scenario == "B":
        await _scenario_b(runtime)
    elif scenario == "C":
        await _scenario_c(runtime)
    elif scenario == "D":
        await _scenario_d(runtime)
    else:
        raise ValueError(f"Unknown scenario {scenario!r}")
    await asyncio.sleep(1.0)
    await runtime.stop()
    runtime.timeline.write_event("scenario_finished", actor="demo", payload={"scenario": scenario})


async def _scenario_a(runtime: InteractionRuntime) -> None:
    await runtime.audio.speak(
        "我现在正在解释这个实时交互模型：它需要把说话权、上下文和后台推理拆开处理。",
        scene_context={"scenario": "A"},
    )
    await asyncio.sleep(0.35)
    await stream_text(runtime, "我插一句，先停一下。", delay_s=0.12)


async def _scenario_b(runtime: InteractionRuntime) -> None:
    await stream_text(
        runtime,
        "我们先假设 1+1=3，然后继续往下说这个计划的第二步。",
        delay_s=0.12,
        final=True,
        still_speaking_after_final=True,
    )
    await asyncio.sleep(1.0)
    await runtime.ingest_final("然后我继续补充后面的内容。", source="scenario")


async def _scenario_c(runtime: InteractionRuntime) -> None:
    phrases = [
        "我想连续描述一个比较长的需求，",
        "先讲用户在会议里的发言节奏，",
        "然后讲 assistant 如何保持存在感，",
        "最后再讲为什么 backchannel 不能太频繁。",
    ]
    running = ""
    for phrase in phrases:
        running += phrase
        await runtime.ingest_partial(running, source="scenario")
        await asyncio.sleep(1.15)
    await runtime.ingest_final(running, source="scenario")


async def _scenario_d(runtime: InteractionRuntime) -> None:
    await stream_text(
        runtime,
        "请在后台分析这个复杂方案，如果有高优先级风险就立刻告诉我。",
        delay_s=0.11,
    )
    await asyncio.sleep(0.7)
    await runtime.inject_background_result(
        BackgroundResult(
            id="manual-high-priority",
            task="高优先级后台推理结果",
            text="后台推理有高优先级发现：1+1 的错误假设会污染后续推导，需要先修正。",
            priority=9,
            metadata={"scenario": "D", "source": "manual_injection"},
        )
    )
    await asyncio.sleep(1.0)

