"""AWS SageMaker STT provider — Phase 2 compute backend.

Falls back from RunPod when RunPod is down or not configured.
Uses a SageMaker real-time inference endpoint running faster-whisper.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import boto3
from botocore.exceptions import ClientError

from api.app.config import settings
from api.app.models.compute import TranscriptionResult, TranscriptionSegment


class SageMakerSTTProvider:
    """AWS SageMaker STT — implements the STTProvider protocol."""

    BASE_COST_PER_MINUTE_CENTS = 1.5  # Slightly higher than RunPod

    def __init__(self) -> None:
        self._client = boto3.client(
            "sagemaker-runtime",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        self._endpoint_name = settings.sagemaker_endpoint_name
        self._markup = settings.stt_markup

    async def transcribe(
        self,
        audio: bytes,
        language: str | None = None,
        model: str = "large-v3",
    ) -> TranscriptionResult:
        """Send audio to SageMaker endpoint for transcription."""
        payload: dict[str, Any] = {
            "audio_base64": base64.b64encode(audio).decode(),
            "model": model,
        }
        if language:
            payload["language"] = language

        try:
            response = await asyncio.to_thread(
                self._client.invoke_endpoint,
                EndpointName=self._endpoint_name,
                ContentType="application/json",
                Body=json.dumps(payload),
            )
            result_body = json.loads(response["Body"].read().decode())
            return self._parse_output(result_body)
        except ClientError as e:
            return TranscriptionResult(
                job_id="",
                status="failed",
                error=f"SageMaker error: {e}",
            )

    def _parse_output(self, output: dict) -> TranscriptionResult:
        """Parse SageMaker response into our model."""
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
            job_id=output.get("job_id", ""),
            status="completed",
            text=text,
            segments=segments,
            language=output.get("language"),
            duration_seconds=duration,
            cost_cents=cost_cents,
        )

    def _calculate_cost(self, duration_seconds: float) -> int:
        minutes = duration_seconds / 60.0
        raw_cost = minutes * self.BASE_COST_PER_MINUTE_CENTS * self._markup
        return max(1, round(raw_cost))

    async def health(self) -> bool:
        if not self._endpoint_name or not settings.aws_access_key_id:
            return False
        try:
            sagemaker = boto3.client(
                "sagemaker",
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )
            resp = await asyncio.to_thread(
                sagemaker.describe_endpoint,
                EndpointName=self._endpoint_name,
            )
            return resp.get("EndpointStatus") == "InService"
        except ClientError:
            return False
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Unexpected SageMaker health check error")
            return False

    def pricing(self) -> dict:
        return {
            "provider": "sagemaker",
            "model": "faster-whisper large-v3",
            "cost_per_minute_cents": round(self.BASE_COST_PER_MINUTE_CENTS * self._markup, 2),
            "markup": self._markup,
            "free_minutes_per_month": settings.stt_free_minutes,
        }
