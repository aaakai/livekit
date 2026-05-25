from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TTSResult:
    text: str
    audio: bytes
    mime_type: str
    sample_rate_hz: int
    voice: str
    provider: str
    mocked: bool = False


class TTSProvider(Protocol):
    async def synthesize(self, text: str, *, voice: str | None = None, style: str | None = None) -> TTSResult:
        ...

