from __future__ import annotations

from livekit_interaction_model_demo.runtime.interaction_runtime import InteractionRuntime


class InteractionAgent:
    """Thin foreground agent wrapper around InteractionRuntime."""

    name = "interaction_agent"

    def __init__(self, runtime: InteractionRuntime) -> None:
        self.runtime = runtime

    async def on_partial_transcript(self, text: str) -> None:
        await self.runtime.ingest_partial(text)

    async def on_final_transcript(self, text: str) -> None:
        await self.runtime.ingest_final(text)


try:
    from livekit.agents import Agent as _LiveKitAgent
except Exception:  # pragma: no cover - optional dependency path
    _LiveKitAgent = None


if _LiveKitAgent is not None:  # pragma: no cover - exercised only with LiveKit installed

    class LiveKitInteractionAgent(_LiveKitAgent):
        def __init__(self, runtime: InteractionRuntime) -> None:
            super().__init__(
                instructions=(
                    "You are a foreground interaction agent. Do not perform ordinary turn-based chat; "
                    "forward transcripts into InteractionRuntime and let it manage floor/actions."
                )
            )
            self.runtime = runtime

else:

    class LiveKitInteractionAgent:
        def __init__(self, runtime: InteractionRuntime) -> None:
            self.runtime = runtime

