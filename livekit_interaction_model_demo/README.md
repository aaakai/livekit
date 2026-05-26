# LiveKit Interaction Model Demo

一个独立的 Python demo，用 LiveKit Agents 的 worker 入口模拟 Thinking Machines 风格 interaction model 的核心能力：partial transcript 驱动、可打断、可主动插话、backchannel、后台 reasoning、共享 timeline context。它不是普通 turn-based agent；前台 runtime 每 500ms 基于短窗口语音状态做一次结构化 action 判断，再由 FloorManager 和 controller 决定能否执行。

## 目录

```text
livekit_interaction_model_demo/
  main.py                 # CLI 场景 runner + 浏览器 demo server
  agent_worker.py         # LiveKit Agents worker skeleton
  runtime/                # Interaction Runtime、Buffer、Controllers、Floor、Judge、Audio
  agents/                 # InteractionAgent、BackgroundReasonerAgent、AgentRegistry
  providers/              # GeminiTTSProvider、Mock3DSoundProvider
  context/timeline.py     # events.jsonl append-only timeline
  frontend/               # 浏览器 demo
  tests/                  # 最小测试
```

## 环境变量

复制配置：

```bash
cp livekit_interaction_model_demo/.env.example livekit_interaction_model_demo/.env
```

关键变量：

```text
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret

GEMINI_TTS_MOCK=1
GEMINI_API_KEY=
GEMINI_TTS_MODEL=gemini-3.1-flash-tts-preview
GEMINI_TTS_VOICE=Kore

LIVEKIT_STT_MODEL=
LIVEKIT_STT_LANGUAGE=multi
```

默认 `GEMINI_TTS_MOCK=1`，`speak/backchannel/barge_in` 仍经过 `GeminiTTSProvider`，但不请求外部 API。要调用真实 Gemini TTS，设置 `GEMINI_TTS_MOCK=0` 并配置 `GEMINI_API_KEY`。

`LIVEKIT_STT_MODEL` 为空时，worker 主要接收 LiveKit text input 和 scripted demo transcript。要用真实音频转写，可配置 LiveKit Inference STT 模型，例如你账号可用的 STT model id。

## 安装

从项目根目录执行：

```bash
python -m venv livekit_interaction_model_demo/.venv
source livekit_interaction_model_demo/.venv/bin/activate
pip install -r livekit_interaction_model_demo/requirements.txt
```

## 启动 LiveKit

可以使用 LiveKit Cloud，填入 `.env` 里的 `LIVEKIT_URL`、`LIVEKIT_API_KEY`、`LIVEKIT_API_SECRET`。

本地开发也可以启动 LiveKit server：

```bash
docker run --rm \
  -p 7880:7880 \
  -p 7881:7881 \
  -p 7882:7882/udp \
  -e LIVEKIT_KEYS="devkey: secret" \
  livekit/livekit-server --dev --bind 0.0.0.0
```

本地 server 对应：

```text
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
```

## 启动 agent worker

```bash
source livekit_interaction_model_demo/.venv/bin/activate
python -m livekit_interaction_model_demo.agent_worker dev
```

`agent_worker.py` 使用 Python LiveKit Agents 的 `AgentServer` / `AgentSession` worker 入口，监听 `user_input_transcribed` 的 partial/final transcript，并转发给 `InteractionRuntime`。它也通过 `RoomOptions(text_input=TextInputOptions(...))` 接收 LiveKit text stream。当前 demo 的 Gemini TTS 播放层会写 timeline 和 mock sound plan；把音频 bytes 发布回 LiveKit room 可以作为下一步扩展。

## 进入浏览器 demo

```bash
source livekit_interaction_model_demo/.venv/bin/activate
python -m livekit_interaction_model_demo.main web --port 8008
```

打开：

```text
http://127.0.0.1:8008
```

浏览器按钮会调用 Python runtime 跑四个脚本场景，并轮询 `events.jsonl`。命令行/日志版是优先路径，也可以直接用 CLI：

```bash
python -m livekit_interaction_model_demo.main scenario A
python -m livekit_interaction_model_demo.main scenario B
python -m livekit_interaction_model_demo.main scenario C
python -m livekit_interaction_model_demo.main scenario D
```

timeline 写入：

```text
livekit_interaction_model_demo/events.jsonl
```

## 四个场景

- A：assistant 正在说话，用户插嘴；`InteractionJudge` 输出 `INTERRUPT_SELF`，`AudioRuntime.interrupt()` 停止当前 assistant 播放。
- B：用户在 partial 阶段说出 `1+1=3` 后继续说；judge 输出 `BARGE_IN`，`BargeInController` 检查 confidence、priority 和同一 utterance 去重后，assistant 插话：`等一下，1+1 是 2。`
- C：用户连续说话 3-5 秒；judge 输出 `BACKCHANNEL`，`BackchannelController` 做 3 秒限流后播放：`嗯，我在听。`
- D：后台 reasoner 异步返回高优先级结果；系统输出 `BARGE_IN`，或者对低优先级结果只写入 context。

你可以用下面的命令看每个场景的关键事件：

```bash
python -B -m livekit_interaction_model_demo.main scenario B
python - <<'PY'
import json, pathlib
p = pathlib.Path("livekit_interaction_model_demo/events.jsonl")
for line in p.read_text(encoding="utf-8").splitlines():
    event = json.loads(line)
    if event["event_type"] in {"judge_action", "assistant_barge_in", "backchannel", "assistant_speech_interrupted", "background_result"}:
        print(event["seq"], event["event_type"], event["payload"])
PY
```

## Interaction Runtime 结构

- `PartialTranscriptBuffer`：维护最近 5 秒 partial transcript 窗口，记录 `current_partial`、`recent_partials`、`last_final`、`user_speaking`、`assistant_speaking`、当前 utterance id，以及同一 utterance 是否已触发过 barge-in。
- `InteractionJudge`：输入来自 `partial_transcript_buffer.build_snapshot()`，每 500ms 只输出严格结构化 action JSON。固定 action：`LISTEN`、`BACKCHANNEL`、`SHORT_REPLY`、`BARGE_IN`、`INTERRUPT_SELF`、`DEFER_BACKGROUND`。解析失败会 fallback 到 `LISTEN`。
- `FloorManager`：管理 `IDLE`、`USER_HAS_FLOOR`、`ASSISTANT_HAS_FLOOR`、`OVERLAP`、`BACKCHANNELING`、`BARGE_IN_PENDING`、`BACKGROUND_THINKING`，并写入 `floor_state_changed`。judge 决定“该不该”，FloorManager 决定“能不能”。
- `BackchannelController`：要求用户持续说话超过阈值，默认最小间隔 3 秒，不写长期 memory，只写 timeline 并调用 `AudioRuntime.backchannel()`。
- `BargeInController`：要求 `confidence >= 0.88` 且 priority 不低于 `P2`，同一 user utterance 最多主动打断一次；通过 FloorManager 后调用 `AudioRuntime.barge_in()`，并写入 `assistant_barge_in`。
- `AudioRuntime`：支持 `speak`、`backchannel`、`barge_in`、`interrupt`、`is_speaking`，播放状态写入 `assistant_speech_started`、`assistant_speech_interrupted`、`assistant_speech_finished`。
- `GeminiTTSProvider`：上层只依赖 `TTSProvider` 接口，后续可替换为自研 TTS。
- `Mock3DSoundProvider`：对 `BACKCHANNEL` 生成低优先级 plan，对 `BARGE_IN` 生成 `soft_interrupt_chime` plan，对普通 speak 返回空/background plan。
- `SharedContextTimeline`：partial/final transcript、backchannel、barge-in、interrupt、assistant speech、background result、sound plan 都进入 JSONL。
- `BackgroundReasonerAgent`：异步执行复杂任务，不阻塞前台。
- `AgentRegistry`：可继续注册 `CharacterAgent` / `SpecialistAgent`。

## 替换 TTS

上层只依赖 `providers/tts.py` 里的 `TTSProvider` 协议：

```python
class YourTTSProvider:
    async def synthesize(self, text: str, *, voice: str | None = None, style: str | None = None) -> TTSResult:
        ...
```

然后在创建 runtime 时把 provider 注入 `AudioRuntime`：

```python
timeline = SharedContextTimeline("events.jsonl")
audio = AudioRuntime(tts_provider=YourTTSProvider(), timeline=timeline)
runtime = InteractionRuntime(timeline=timeline, audio=audio)
```

`speak()`、`backchannel()`、`barge_in()` 都会走同一个 TTSProvider，因此后续替换成自研 TTS 不需要改 judge/floor/controller。

## 新增 Agent

`AgentRegistry` 用来扩展角色和专家代理：

```python
registry.register(
    "math_specialist",
    MathSpecialistAgent(),
    kind="SpecialistAgent",
    description="Handles factual/math checks",
)
registry.register(
    "host_character",
    HostCharacterAgent(),
    kind="CharacterAgent",
    description="Foreground persona",
)
```

前台 `InteractionAgent` 继续只负责把 LiveKit partial/final transcript 转入 `InteractionRuntime`。复杂任务放进 `BackgroundReasonerAgent` 或新的 `SpecialistAgent`，通过 timeline/result 回到前台，而不是阻塞 turn。

## 测试

```bash
source livekit_interaction_model_demo/.venv/bin/activate
pytest livekit_interaction_model_demo/tests
```

覆盖：

- FloorManager 状态流转
- InteractionJudge JSON 解析和 snapshot 输入
- AudioRuntime interrupt 事件
- Timeline event 写入
- PartialTranscriptBuffer 短窗口 snapshot
