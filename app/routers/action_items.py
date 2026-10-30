import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    ActionItem,
    ActionItemHistory,
    ActionItemStatus,
    Meeting,
    MeetingParticipant,
    Participant,
)
from ..schemas import (
    ActionItemCreate,
    ActionItemReassign,
    ActionItemResponse,
    ActionItemStatusUpdate,
    ActionItemUpdate,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/action-items", tags=["action-items"])


def get_action_item_or_404(item_id: int, db: Session) -> ActionItem:
    item = db.get(ActionItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Action item not found")
    return item


def get_meeting_or_404(meeting_id: int, db: Session) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


def ensure_owner_is_in_meeting(
    meeting_id: int, owner_id: int, db: Session
) -> Participant:
    participant = db.get(Participant, owner_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    membership = db.scalar(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_id,
            MeetingParticipant.participant_id == owner_id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=422,
            detail="Action item owner must be a participant of the meeting",
        )
    return participant


def ensure_not_past(due_date: datetime | None) -> None:
    if due_date is not None:
        comparison_date = due_date.replace(tzinfo=None)
        if comparison_date < datetime.utcnow():
            raise HTTPException(status_code=422, detail="Due date cannot be in the past")


def ensure_closed_has_outcome(status: ActionItemStatus, outcome: str | None) -> None:
    if status == ActionItemStatus.CLOSED and not (outcome and outcome.strip()):
        raise HTTPException(
            status_code=422, detail="Closed action items require an outcome"
        )


def record_history(
    item: ActionItem,
    event: str,
    old_value: str | None,
    new_value: str | None,
) -> None:
    item.history.append(
        ActionItemHistory(
            event=event,
            old_value=old_value,
            new_value=new_value,
        )
    )


@router.post("", response_model=ActionItemResponse, status_code=201)
def create_action_item(
    payload: ActionItemCreate, db: Session = Depends(get_db)
) -> ActionItem:
    get_meeting_or_404(payload.meeting_id, db)
    ensure_not_past(payload.due_date)
    if payload.owner_id is not None:
        ensure_owner_is_in_meeting(payload.meeting_id, payload.owner_id, db)
    ensure_closed_has_outcome(payload.status, payload.outcome)

    item = ActionItem(**payload.model_dump())
    db.add(item)
    db.flush()
    record_history(item, "created", None, item.title)
    db.commit()
    db.refresh(item)
    logger.info(
        "action_item.created",
        extra={"event": "action_item.created", "action_item_id": item.id},
    )
    return item


@router.get("", response_model=list[ActionItemResponse])
def list_action_items(
    owner_id: int | None = Query(default=None),
    status: ActionItemStatus | None = Query(default=None),
    meeting_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[ActionItem]:
    statement = select(ActionItem).order_by(ActionItem.id.desc())
    if owner_id is not None:
        statement = statement.where(ActionItem.owner_id == owner_id)
    if status is not None:
        statement = statement.where(ActionItem.status == status)
    if meeting_id is not None:
        statement = statement.where(ActionItem.meeting_id == meeting_id)
    return list(db.scalars(statement).all())


@router.patch("/{item_id}", response_model=ActionItemResponse)
def update_action_item(
    item_id: int, payload: ActionItemUpdate, db: Session = Depends(get_db)
) -> ActionItem:
    item = get_action_item_or_404(item_id, db)
    changes = payload.model_dump(exclude_unset=True)
    ensure_not_past(changes.get("due_date"))
    ensure_closed_has_outcome(item.status, changes.get("outcome", item.outcome))
    for field, new_value in changes.items():
        old_value = getattr(item, field)
        setattr(item, field, new_value)
        record_history(item, field, str(old_value) if old_value is not None else None,
                       str(new_value) if new_value is not None else None)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{item_id}/reassign", response_model=ActionItemResponse)
def reassign_action_item(
    item_id: int,
    payload: ActionItemReassign,
    db: Session = Depends(get_db),
) -> ActionItem:
    item = get_action_item_or_404(item_id, db)
    ensure_owner_is_in_meeting(item.meeting_id, payload.owner_id, db)
    old_owner_id = item.owner_id
    item.owner_id = payload.owner_id
    record_history(item, "reassigned", str(old_owner_id) if old_owner_id else None,
                   str(payload.owner_id))
    db.commit()
    db.refresh(item)
    logger.info(
        "action_item.reassigned",
        extra={"event": "action_item.reassigned", "action_item_id": item.id},
    )
    return item


@router.patch("/{item_id}/status", response_model=ActionItemResponse)
def change_action_item_status(
    item_id: int,
    payload: ActionItemStatusUpdate,
    db: Session = Depends(get_db),
) -> ActionItem:
    item = get_action_item_or_404(item_id, db)
    outcome = payload.outcome if payload.outcome is not None else item.outcome
    ensure_closed_has_outcome(payload.status, outcome)
    old_status = item.status
    item.status = payload.status
    if payload.outcome is not None:
        old_outcome = item.outcome
        item.outcome = payload.outcome
        record_history(
            item,
            "outcome",
            old_outcome,
            payload.outcome,
        )
    record_history(item, "status", str(old_status), str(payload.status))
    db.commit()
    db.refresh(item)
    if payload.status == ActionItemStatus.CLOSED:
        logger.info(
            "action_item.closed",
            extra={"event": "action_item.closed", "action_item_id": item.id},
        )
    return item
