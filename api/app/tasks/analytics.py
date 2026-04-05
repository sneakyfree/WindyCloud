"""Analytics event tracking — daily counters for key metrics."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.db.models import AnalyticsEvent


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def track_event(
    db: AsyncSession,
    event_type: str,
    product: str | None = None,
    count: int = 1,
    value: int = 0,
) -> None:
    """Increment a daily analytics counter. Creates the row if it doesn't exist."""
    date = _today()
    result = await db.execute(
        select(AnalyticsEvent).where(
            AnalyticsEvent.date == date,
            AnalyticsEvent.event_type == event_type,
            AnalyticsEvent.product == product,
        )
    )
    event = result.scalar_one_or_none()
    if event:
        event.count += count
        event.value += value
    else:
        event = AnalyticsEvent(
            date=date,
            event_type=event_type,
            product=product,
            count=count,
            value=value,
        )
        db.add(event)
