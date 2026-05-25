from __future__ import annotations

import asyncio
import io
import os
import wave

from livekit_interaction_model_demo.providers.tts import TTSResult


def _pcm_to_wav_bytes(pcm: bytes, *, channels: int = 1, sample_rate_hz: int = 24000, sample_width: int = 2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate_hz)
        wav.writeframes(pcm)
    return buffer.getvalue()


class GeminiTTSProvider:
    """Gemini TTS adapter hidden behind the TTSProvider interface.

    By default the provider runs in mock mode so the demo and tests work
    without credentials. Set GEMINI_TTS_MOCK=0 and GEMINI_API_KEY to make
    real Gemini calls.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        voice: str | None = None,
        mock: bool | None = None,
        sample_rate_hz: int = 24000,
    ) -> None:
        self.model = model or os.getenv("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")
        self.voice = voice or os.getenv("GEMINI_TTS_VOICE", "Kore")
        env_mock = os.getenv("GEMINI_TTS_MOCK", "1").lower() in {"1", "true", "yes"}
        self.mock = env_mock if mock is None else mock
        self.sample_rate_hz = sample_rate_hz

    async def synthesize(self, text: str, *, voice: str | None = None, style: str | None = None) -> TTSResult:
        selected_voice = voice or self.voice
        if self.mock or not os.getenv("GEMINI_API_KEY"):
            await asyncio.sleep(min(0.08, max(0.01, len(text) / 1000)))
            fake_pcm = f"MOCK_GEMINI_TTS:{selected_voice}:{style or 'neutral'}:{text}".encode("utf-8")
            return TTSResult(
                text=text,
                audio=fake_pcm,
                mime_type="audio/mock",
                sample_rate_hz=self.sample_rate_hz,
                voice=selected_voice,
                provider="gemini",
                mocked=True,
            )

        return await asyncio.to_thread(self._synthesize_blocking, text, selected_voice, style)

    def _synthesize_blocking(self, text: str, voice: str, style: str | None) -> TTSResult:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("Install google-genai to use real Gemini TTS") from exc

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        prompt = text if not style else f"Say in a {style} style: {text}"
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    )
                ),
            ),
        )

        part = response.candidates[0].content.parts[0]
        inline_data = part.inline_data
        audio = inline_data.data
        mime_type = inline_data.mime_type or "audio/L16"
        if mime_type.lower() in {"audio/l16", "audio/pcm", "audio/raw"}:
            audio = _pcm_to_wav_bytes(audio, sample_rate_hz=self.sample_rate_hz)
            mime_type = "audio/wav"

        return TTSResult(
            text=text,
            audio=audio,
            mime_type=mime_type,
            sample_rate_hz=self.sample_rate_hz,
            voice=voice,
            provider="gemini",
            mocked=False,
        )

