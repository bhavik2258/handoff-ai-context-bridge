import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Meeting, MeetingParticipant, Participant
from ..schemas import (
    AttendanceUpdate,
    MeetingCreate,
    MeetingParticipantResponse,
    MeetingResponse,
    MeetingStatus,
    MeetingUpdate,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/meetings", tags=["meetings"])
STATUS_TRANSITIONS = {
    MeetingStatus.DRAFT: MeetingStatus.SCHEDULED,
    MeetingStatus.SCHEDULED: MeetingStatus.HELD,
    MeetingStatus.HELD: MeetingStatus.CLOSED,
}


def get_meeting_or_404(meeting_id: int, db: Session) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


def get_participant_or_404(participant_id: int, db: Session) -> Participant:
    participant = db.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    return participant


@router.post("", response_model=MeetingResponse, status_code=201)
def create_meeting(payload: MeetingCreate, db: Session = Depends(get_db)) -> Meeting:
    if payload.previous_meeting_id is not None:
        get_meeting_or_404(payload.previous_meeting_id, db)
    meeting = Meeting(**payload.model_dump())
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    logger.info(
        "meeting.created",
        extra={"event": "meeting.created", "meeting_id": meeting.id},
    )
    return meeting


@router.get("", response_model=list[MeetingResponse])
def list_meetings(db: Session = Depends(get_db)) -> list[Meeting]:
    return list(db.scalars(select(Meeting).order_by(Meeting.scheduled_at.desc())).all())


@router.get("/{meeting_id}", response_model=MeetingResponse)
def get_meeting(meeting_id: int, db: Session = Depends(get_db)) -> Meeting:
    return get_meeting_or_404(meeting_id, db)


@router.patch("/{meeting_id}", response_model=MeetingResponse)
def update_meeting(
    meeting_id: int, payload: MeetingUpdate, db: Session = Depends(get_db)
) -> Meeting:
    meeting = get_meeting_or_404(meeting_id, db)
    changes = payload.model_dump(exclude_unset=True)
    next_status = changes.get("status")
    if next_status is not None:
        current_status = MeetingStatus(meeting.status)
        if next_status != current_status and STATUS_TRANSITIONS.get(current_status) != next_status:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status transition: {current_status} -> {next_status}",
            )
    if changes.get("previous_meeting_id") is not None:
        get_meeting_or_404(changes["previous_meeting_id"], db)
    for field, value in changes.items():
        setattr(meeting, field, value)
    db.commit()
    db.refresh(meeting)
    return meeting


@router.delete("/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: int, db: Session = Depends(get_db)) -> None:
    meeting = get_meeting_or_404(meeting_id, db)
    db.delete(meeting)
    db.commit()


@router.post(
    "/{meeting_id}/participants",
    response_model=MeetingParticipantResponse,
    status_code=201,
)
def add_participant(
    meeting_id: int,
    participant_id: int,
    db: Session = Depends(get_db),
) -> MeetingParticipant:
    meeting = get_meeting_or_404(meeting_id, db)
    get_participant_or_404(participant_id, db)
    existing = db.scalar(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting.id,
            MeetingParticipant.participant_id == participant_id,
        )
    )
    if existing is not None:
        return existing
    membership = MeetingParticipant(meeting_id=meeting.id, participant_id=participant_id)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


@router.patch(
    "/{meeting_id}/participants/{participant_id}",
    response_model=MeetingParticipantResponse,
)
def set_attendance(
    meeting_id: int,
    participant_id: int,
    payload: AttendanceUpdate,
    db: Session = Depends(get_db),
) -> MeetingParticipant:
    get_meeting_or_404(meeting_id, db)
    get_participant_or_404(participant_id, db)
    membership = db.scalar(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_id,
            MeetingParticipant.participant_id == participant_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Meeting participant not found")
    old_attendance = membership.attendance
    membership.attendance = payload.attendance
    db.commit()
    db.refresh(membership)
    logger.info(
        "attendance.updated",
        extra={
            "event": "attendance.updated",
            "meeting_id": meeting_id,
            "participant_id": participant_id,
            "old_value": old_attendance,
            "new_value": payload.attendance,
        },
    )
    return membership
