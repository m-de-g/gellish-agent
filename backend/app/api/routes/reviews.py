from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.core import ReviewQueue

router = APIRouter(prefix="/reviews", tags=["reviews"])


class ReviewItemOut(BaseModel):
    id: int
    item_type: str
    item_ref: str
    reason: str | None
    status: str
    resolution: str | None
    notes: str | None
    dismissed_reason: str | None
    created_at: Any
    resolved_at: Any | None
    dismissed_at: Any | None


class ResolveReviewIn(BaseModel):
    resolution: str = Field(..., min_length=1)
    notes: str | None = None


class DismissReviewIn(BaseModel):
    reason: str | None = None


@router.get("", response_model=list[ReviewItemOut])
def list_reviews(
    status: str = Query("open", min_length=1),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[ReviewItemOut]:
    rows = db.execute(
        select(ReviewQueue)
        .where(ReviewQueue.status == status)
        .order_by(ReviewQueue.created_at.asc(), ReviewQueue.id.asc())
        .limit(limit)
    ).scalars().all()

    return [
        ReviewItemOut(
            id=row.id,
            item_type=row.item_type,
            item_ref=row.item_ref,
            reason=row.reason,
            status=row.status,
            resolution=row.resolution,
            notes=row.notes,
            dismissed_reason=row.dismissed_reason,
            created_at=row.created_at,
            resolved_at=row.resolved_at,
            dismissed_at=row.dismissed_at,
        )
        for row in rows
    ]


@router.post("/{review_id}/resolve", response_model=ReviewItemOut)
def resolve_review(
    review_id: int,
    payload: ResolveReviewIn,
    db: Session = Depends(get_db),
) -> ReviewItemOut:
    row = db.get(ReviewQueue, review_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Review item not found")

    row.status = "resolved"
    row.resolution = payload.resolution
    row.notes = payload.notes
    row.dismissed_reason = None
    row.dismissed_at = None
    row.resolved_at = datetime.now(timezone.utc)
    db.commit()

    return ReviewItemOut(
        id=row.id,
        item_type=row.item_type,
        item_ref=row.item_ref,
        reason=row.reason,
        status=row.status,
        resolution=row.resolution,
        notes=row.notes,
        dismissed_reason=row.dismissed_reason,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
        dismissed_at=row.dismissed_at,
    )


@router.post("/{review_id}/dismiss", response_model=ReviewItemOut)
def dismiss_review(
    review_id: int,
    payload: DismissReviewIn,
    db: Session = Depends(get_db),
) -> ReviewItemOut:
    row = db.get(ReviewQueue, review_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Review item not found")

    row.status = "dismissed"
    row.dismissed_reason = payload.reason
    row.resolution = None
    row.resolved_at = None
    row.dismissed_at = datetime.now(timezone.utc)
    db.commit()

    return ReviewItemOut(
        id=row.id,
        item_type=row.item_type,
        item_ref=row.item_ref,
        reason=row.reason,
        status=row.status,
        resolution=row.resolution,
        notes=row.notes,
        dismissed_reason=row.dismissed_reason,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
        dismissed_at=row.dismissed_at,
    )
