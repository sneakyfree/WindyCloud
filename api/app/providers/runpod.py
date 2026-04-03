"""RunPod Serverless STT provider.

Sends audio to a RunPod serverless endpoint running faster-whisper,
returns transcription results. Pay-per-second, no idle costs.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from api.app.config import settings
from api.app.models.compute import TranscriptionResult, TranscriptionSegment


class RunPodSTTProvider:
    """RunPod Serverless STT — implements the STTProvider protocol."""

    BASE_URL = "https://api.runpod.ai/v2"
    # RunPod base cost per minute, markup applied on top
    BASE_COST_PER_MINUTE_CENTS = 1.0  # ~$0.01/min at RunPod serverless rates

    def __init__(self) -> None:
        self._api_key = settings.runpod_api_key
        self._endpoint_id = settings.runpod_endpoint_id
        self._markup = settings.stt_markup

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    @property
    def endpoint_url(self) -> str:
        return f"{self.BASE_URL}/{self._endpoint_id}"

    async def transcribe(
        self,
        audio: bytes,
        language: str | None = None,
        model: str = "large-v3",
    ) -> TranscriptionResult:
        """Send audio to RunPod for transcription.

        RunPod serverless expects base64-encoded audio in the input payload.
        """
        import base64

        payload: dict[str, Any] = {
            "input": {
                "audio_base64": base64.b64encode(audio).decode(),
                "model": model,
            }
        }
        if language:
            payload["input"]["language"] = language

        async with httpx.AsyncClient(timeout=300) as client:
            # Submit job
            resp = await client.post(
                f"{self.endpoint_url}/runsync",
                json=payload,
                headers=self._headers,
            )

            if resp.status_code != 200:
                return TranscriptionResult(
                    job_id="",
                    status="failed",
                    error=f"RunPod API error: {resp.status_code} {resp.text}",
                )

            data = resp.json()
            job_id = data.get("id", "")
            status = data.get("status", "")

            # runsync returns completed results directly
            if status == "COMPLETED":
                output = data.get("output", {})
                return self._parse_output(job_id, output)

            # If IN_QUEUE or IN_PROGRESS, poll for result
            if status in ("IN_QUEUE", "IN_PROGRESS"):
                return await self._poll_job(client, job_id)

            return TranscriptionResult(
                job_id=job_id,
                status="failed",
                error=f"Unexpected RunPod status: {status}",
            )

    async def _poll_job(
        self, client: httpx.AsyncClient, job_id: str, max_wait: int = 120
    ) -> TranscriptionResult:
        """Poll RunPod for job completion."""
        start = time.monotonic()
        while (time.monotonic() - start) < max_wait:
            resp = await client.get(
                f"{self.endpoint_url}/status/{job_id}",
                headers=self._headers,
            )
            if resp.status_code != 200:
                await asyncio.sleep(2)
                continue

            data = resp.json()
            status = data.get("status", "")

            if status == "COMPLETED":
                return self._parse_output(job_id, data.get("output", {}))
            if status == "FAILED":
                return TranscriptionResult(
                    job_id=job_id,
                    status="failed",
                    error=data.get("error", "RunPod job failed"),
                )
            await asyncio.sleep(2)

        return TranscriptionResult(
            job_id=job_id,
            status="failed",
            error="Job timed out waiting for RunPod",
        )

    def _parse_output(self, job_id: str, output: dict) -> TranscriptionResult:
        """Parse RunPod faster-whisper output into our model."""
        text = output.get("text", "")
        duration = output.get("duration", 0.0)
        segments_raw = output.get("segments", [])

        segments = [
            TranscriptionSegment(
                start=s.get("start", 0),
                end=s.get("end", 0),
                text=s.get("text", ""),
            )
            for s in segments_raw
        ]

        cost_cents = self._calculate_cost(duration)

        return TranscriptionResult(
            job_id=job_id,
            status="completed",
            text=text,
            segments=segments,
            language=output.get("language"),
            duration_seconds=duration,
            cost_cents=cost_cents,
        )

    def _calculate_cost(self, duration_seconds: float) -> int:
        """Calculate cost in cents for a given audio duration."""
        minutes = duration_seconds / 60.0
        raw_cost = minutes * self.BASE_COST_PER_MINUTE_CENTS * self._markup
        return max(1, round(raw_cost))  # Minimum 1 cent per job

    async def health(self) -> bool:
        if not self._api_key or not self._endpoint_id:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.endpoint_url}/health",
                    headers=self._headers,
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Unexpected RunPod health check error")
            return False

    def pricing(self) -> dict:
        return {
            "provider": "runpod",
            "model": "faster-whisper large-v3",
            "cost_per_minute_cents": round(self.BASE_COST_PER_MINUTE_CENTS * self._markup, 2),
            "markup": self._markup,
            "free_minutes_per_month": settings.stt_free_minutes,
        }
