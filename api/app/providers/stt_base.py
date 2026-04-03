"""STT provider protocol and mock implementation."""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from api.app.models.compute import TranscriptionResult, TranscriptionSegment


@runtime_checkable
class STTProvider(Protocol):
    """Interface for speech-to-text providers."""

    async def transcribe(
        self,
        audio: bytes,
        language: str | None = None,
        model: str = "large-v3",
    ) -> TranscriptionResult: ...

    async def health(self) -> bool: ...

    def pricing(self) -> dict: ...


class MockSTTProvider:
    """Mock STT provider that returns fake transcription results for testing."""

    async def transcribe(
        self,
        audio: bytes,
        language: str | None = None,
        model: str = "large-v3",
    ) -> TranscriptionResult:
        # Simulate ~1 second of audio per 16KB of data
        duration = max(1.0, len(audio) / 16000.0)
        cost_cents = max(1, round(duration / 60.0 * 3.0))

        return TranscriptionResult(
            job_id=str(uuid.uuid4()),
            status="completed",
            text="This is a mock transcription of the audio file.",
            segments=[
                TranscriptionSegment(start=0.0, end=duration / 2, text="This is a mock"),
                TranscriptionSegment(
                    start=duration / 2,
                    end=duration,
                    text="transcription of the audio file.",
                ),
            ],
            language=language or "en",
            duration_seconds=duration,
            cost_cents=cost_cents,
        )

    async def health(self) -> bool:
        return True

    def pricing(self) -> dict:
        return {
            "provider": "mock",
            "model": "mock-whisper",
            "cost_per_minute_cents": 3.0,
            "markup": 1.0,
            "free_minutes_per_month": 10,
        }
