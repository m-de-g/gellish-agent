from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.core import ReviewQueue


def enqueue_review_item(
    db: Session,
    item_type: str,
    item_ref: str,
    reason: str,
    *,
    status: str = "open",
) -> ReviewQueue:
    if status != "open":
        row = ReviewQueue(item_type=item_type, item_ref=item_ref, reason=reason, status=status)
        db.add(row)
        db.flush()
        return row

    now = datetime.now(timezone.utc)
    existing = db.execute(
        select(ReviewQueue).where(
            ReviewQueue.item_type == item_type,
            ReviewQueue.item_ref == item_ref,
            ReviewQueue.status == "open",
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.updated_at = now
        if (existing.reason is None or not existing.reason.strip()) and reason.strip():
            existing.reason = reason
        db.flush()
        return existing

    try:
        with db.begin_nested():
            created = ReviewQueue(item_type=item_type, item_ref=item_ref, reason=reason, status="open")
            db.add(created)
            db.flush()
            return created
    except IntegrityError:
        existing = db.execute(
            select(ReviewQueue).where(
                ReviewQueue.item_type == item_type,
                ReviewQueue.item_ref == item_ref,
                ReviewQueue.status == "open",
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.updated_at = now
            if (existing.reason is None or not existing.reason.strip()) and reason.strip():
                existing.reason = reason
            db.flush()
            return existing
        raise
