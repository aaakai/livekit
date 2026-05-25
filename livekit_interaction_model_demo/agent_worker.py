from __future__ import annotations

import asyncio
import os
from pathlib import Path

from livekit_interaction_model_demo.agents.interaction_agent import LiveKitInteractionAgent
from livekit_interaction_model_demo.runtime.interaction_runtime import build_default_runtime

DEMO_DIR = Path(__file__).resolve().parent


def _runtime_for_session(room_name: str):
    events_path = DEMO_DIR / "runs" / f"{room_name or 'room'}.events.jsonl"
    return build_default_runtime(timeline_path=events_path, tts_mock=None, judge_interval_s=0.5)


try:
    from dotenv import load_dotenv
    from livekit import agents
    from livekit.agents import AgentServer, AgentSession, inference, room_io
except Exception as exc:  # pragma: no cover - optional LiveKit dependency path
    agents = None
    _IMPORT_ERROR = exc
else:  # pragma: no cover - requires livekit runtime
    load_dotenv(DEMO_DIR / ".env")
    server = AgentServer()

    @server.rtc_session()
    async def interaction_session(ctx: agents.JobContext) -> None:
        room_name = getattr(ctx.room, "name", "room")
        runtime = _runtime_for_session(room_name)
        await runtime.start()
        agent = LiveKitInteractionAgent(runtime)

        session_kwargs = {}
        stt_model = os.getenv("LIVEKIT_STT_MODEL")
        if stt_model:
            session_kwargs["stt"] = inference.STT(
                model=stt_model,
                language=os.getenv("LIVEKIT_STT_LANGUAGE", "multi"),
            )
        session = AgentSession(**session_kwargs)

        @session.on("user_input_transcribed")
        def _on_transcript(event) -> None:
            text = getattr(event, "transcript", None) or getattr(event, "text", "")
            is_final = bool(getattr(event, "is_final", False))
            if not text:
                return
            if is_final:
                asyncio.create_task(runtime.ingest_final(text, source="livekit"))
            else:
                asyncio.create_task(runtime.ingest_partial(text, source="livekit"))

        def _text_input_cb(_session: AgentSession, event: room_io.TextInputEvent) -> None:
            message = getattr(event, "text", "")
            if message:
                asyncio.create_task(runtime.ingest_final(message, source="livekit_text"))

        await session.start(
            agent=agent,
            room=ctx.room,
            room_options=room_io.RoomOptions(
                text_input=room_io.TextInputOptions(text_input_cb=_text_input_cb),
                text_output=room_io.TextOutputOptions(sync_transcription=False),
            ),
        )

        try:
            await asyncio.Future()
        finally:
            await runtime.stop()


if __name__ == "__main__":
    if agents is None:
        raise SystemExit(
            "LiveKit Agents dependencies are not installed. Run: pip install -r requirements.txt\n"
            f"Import error: {_IMPORT_ERROR}"
        )
    agents.cli.run_app(server)
