import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import ActionItem, ActionItemStatus, Meeting
from ..schemas import RadarItemResponse
from ..services.radar import risk_score


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/radar", tags=["radar"])


@router.get("", response_model=list[RadarItemResponse])
def get_radar(db: Session = Depends(get_db)) -> list[RadarItemResponse]:
    items = db.scalars(
        select(ActionItem)
        .options(
            joinedload(ActionItem.meeting).joinedload(Meeting.participants),
            joinedload(ActionItem.history),
        )
        .where(
            ActionItem.status.in_(
                [
                    ActionItemStatus.OPEN,
                    ActionItemStatus.IN_PROGRESS,
                    ActionItemStatus.BLOCKED,
                ]
            )
        )
    ).unique().all()
    scored = [
        {
            **item.__dict__,
            **risk_score(item, datetime.utcnow()),
        }
        for item in items
    ]
    scored.sort(key=lambda result: result["score"], reverse=True)
    logger.info(
        "radar.scored",
        extra={"event": "radar.scored", "item_count": len(scored)},
    )
    return scored
