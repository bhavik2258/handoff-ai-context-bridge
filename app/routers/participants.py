import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ActionItem, ActionItemStatus, AttendanceStatus, Decision, Meeting, MeetingParticipant, Participant
from ..schemas import CatchupData, CatchupResponse, ParticipantCreate, ParticipantResponse
from ..services.ai_client import AIUnavailableError, call_ai_json
from ..services.prompts import CATCHUP_SYSTEM_PROMPT


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/participants", tags=["participants"])


def _fallback_catchup(
    meetings: list[Meeting],
    decisions: list[Decision],
    action_items: list[ActionItem],
    people: list[Participant],
) -> CatchupData:
    owe = [
        f"{item.title} (due {item.due_date.date().isoformat()})"
        if item.due_date
        else item.title
        for item in action_items
    ]
    return CatchupData(
        what_happened="; ".join(meeting.title for meeting in meetings)
        or "No missed meetings found.",
        decisions=[decision.text for decision in decisions],
        what_you_owe=owe,
        urgent=[item.title for item in action_items if item.status == ActionItemStatus.BLOCKED],
        who_to_talk_to=[person.name for person in people],
    )


@router.post("", response_model=ParticipantResponse, status_code=201)
def create_participant(
    payload: ParticipantCreate, db: Session = Depends(get_db)
) -> Participant:
    if payload.email and db.scalar(
        select(Participant).where(Participant.email == payload.email)
    ):
        raise HTTPException(status_code=409, detail="Participant email already exists")
    participant = Participant(**payload.model_dump())
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


@router.get("", response_model=list[ParticipantResponse])
def list_participants(db: Session = Depends(get_db)) -> list[Participant]:
    return list(db.scalars(select(Participant).order_by(Participant.name)).all())


@router.get("/{participant_id}", response_model=ParticipantResponse)
def get_participant(participant_id: int, db: Session = Depends(get_db)) -> Participant:
    participant = db.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    return participant


@router.patch("/{participant_id}", response_model=ParticipantResponse)
def update_participant(
    participant_id: int, payload: ParticipantCreate, db: Session = Depends(get_db)
) -> Participant:
    participant = db.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    if payload.email and db.scalar(
        select(Participant).where(
            Participant.email == payload.email,
            Participant.id != participant_id,
        )
    ):
        raise HTTPException(status_code=409, detail="Participant email already exists")
    participant.name = payload.name
    participant.email = payload.email
    participant.role = payload.role
    db.commit()
    db.refresh(participant)
    return participant


@router.delete("/{participant_id}", status_code=204)
def delete_participant(participant_id: int, db: Session = Depends(get_db)) -> None:
    participant = db.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    db.delete(participant)
    db.commit()


@router.get("/{participant_id}/catchup", response_model=CatchupResponse)
def participant_catchup(
    participant_id: int, db: Session = Depends(get_db)
) -> CatchupResponse:
    participant = db.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found")

    missed_meetings = list(
        db.scalars(
            select(Meeting)
            .join(MeetingParticipant)
            .where(
                MeetingParticipant.participant_id == participant_id,
                MeetingParticipant.attendance.in_(
                    [
                        AttendanceStatus.ABSENT,
                        AttendanceStatus.NO_RESPONSE,
                        AttendanceStatus.ON_LEAVE,
                    ]
                ),
            )
        ).all()
    )
    meeting_ids = [meeting.id for meeting in missed_meetings]
    decisions = (
        list(db.scalars(select(Decision).where(Decision.meeting_id.in_(meeting_ids))).all())
        if meeting_ids
        else []
    )
    open_statuses = {
        ActionItemStatus.OPEN,
        ActionItemStatus.IN_PROGRESS,
        ActionItemStatus.BLOCKED,
    }
    action_items = list(
        db.scalars(
            select(ActionItem).where(
                ActionItem.owner_id == participant_id,
                ActionItem.status.in_(open_statuses),
            )
        ).all()
    )
    other_people = list(
        db.scalars(
            select(Participant)
            .join(MeetingParticipant)
            .where(
                MeetingParticipant.meeting_id.in_(meeting_ids),
                Participant.id != participant_id,
            )
        ).unique().all()
    ) if meeting_ids else []
    gathered = {
        "meetings": [meeting.title for meeting in missed_meetings],
        "decisions": [decision.text for decision in decisions],
        "action_items": [
            {
                "title": item.title,
                "status": item.status,
                "due_date": item.due_date.date().isoformat() if item.due_date else None,
            }
            for item in action_items
        ],
        "people": [person.name for person in other_people],
    }
    try:
        result = call_ai_json(
            "participant_catchup",
            CATCHUP_SYSTEM_PROMPT,
            str(gathered),
            CatchupData,
        )
        fallback = False
    except AIUnavailableError:
        logger.warning(
            "catchup.fallback",
            extra={"event": "catchup.fallback", "participant_id": participant_id},
        )
        result = _fallback_catchup(missed_meetings, decisions, action_items, other_people)
        fallback = True
    logger.info(
        "catchup.generated",
        extra={"event": "catchup.generated", "participant_id": participant_id},
    )
    return CatchupResponse(**result.model_dump(), fallback=fallback)
