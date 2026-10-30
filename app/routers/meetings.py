import logging
import difflib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..models import (
    ActionItem,
    ActionItemHistory,
    ActionItemStatus,
    Decision,
    Meeting,
    MeetingParticipant,
    Participant,
)
from ..services.ai_client import AIUnavailableError, call_ai_json
from ..services.prompts import AGENDA_SYSTEM_PROMPT, RECAP_SYSTEM_PROMPT
from ..schemas import (
    AttendanceUpdate,
    AgendaResponse,
    CarryForwardResponse,
    RecapConfirmResponse,
    RecapData,
    RecapPreview,
    RecapRequest,
    MeetingCreate,
    MeetingParticipantResponse,
    MeetingResponse,
    MeetingStatus,
    MeetingUpdate,
)
from .action_items import (
    ensure_closed_has_outcome,
    ensure_not_past,
    ensure_owner_is_in_meeting,
    record_history,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/meetings", tags=["meetings"])


class AgendaDraft(BaseModel):
    agenda: str
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


def _fallback_recap(notes: str) -> RecapData:
    actions = []
    for line in notes.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith(("todo", "action")) or " will " in lowered:
            title = stripped
            if lowered.startswith("todo"):
                title = title[4:].lstrip(" :")
            elif lowered.startswith("action"):
                title = title[6:].lstrip(" :")
            elif ":" in title:
                title = title.split(":", 1)[1].strip()
            actions.append(
                {
                    "title": title,
                    "owner_name": None,
                    "due_date": None,
                    "source_quote": stripped,
                    "confidence": 0.5,
                }
            )
    return RecapData(
        summary="Rule-based recap generated from the supplied notes.",
        action_items=actions,
    )


def _match_owner(owner_name: str | None, participants: list[Participant]) -> tuple[int | None, bool]:
    if not owner_name:
        return None, True
    normalized_owner = owner_name.strip().casefold()
    for participant in participants:
        participant_name = participant.name.strip().casefold()
        if (
            normalized_owner == participant_name
            or normalized_owner in participant_name.split()
            or participant_name in normalized_owner.split()
        ):
            return participant.id, False

    names = [participant.name for participant in participants]
    matches = difflib.get_close_matches(owner_name, names, n=1, cutoff=0.6)
    if not matches:
        return None, True
    return next(participant.id for participant in participants if participant.name == matches[0]), False


def _parse_due_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise HTTPException(status_code=422, detail="due_date must be YYYY-MM-DD or null") from error


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


@router.post("/{meeting_id}/ai/agenda", response_model=AgendaResponse)
def suggest_agenda(meeting_id: int, db: Session = Depends(get_db)) -> AgendaResponse:
    meeting = get_meeting_or_404(meeting_id, db)
    prompt = f"Meeting title: {meeting.title}\nExisting notes: {meeting.notes_raw}"
    try:
        draft = call_ai_json(
            "meeting_agenda",
            AGENDA_SYSTEM_PROMPT,
            prompt,
            AgendaDraft,
        )
        return AgendaResponse(agenda=draft.agenda, fallback=False)
    except AIUnavailableError:
        return AgendaResponse(
            agenda="Objectives and updates\nDecisions needed\nRisks and blockers\nActions and next steps",
            fallback=True,
        )


@router.delete("/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: int, db: Session = Depends(get_db)) -> None:
    meeting = get_meeting_or_404(meeting_id, db)
    db.delete(meeting)
    db.commit()


@router.post("/{meeting_id}/ai/recap", response_model=RecapPreview)
def preview_recap(
    meeting_id: int, payload: RecapRequest, db: Session = Depends(get_db)
) -> RecapPreview:
    meeting = get_meeting_or_404(meeting_id, db)
    participants = list(
        db.scalars(
            select(Participant)
            .join(MeetingParticipant)
            .where(MeetingParticipant.meeting_id == meeting_id)
        ).all()
    )
    try:
        recap = call_ai_json(
            "meeting_recap",
            RECAP_SYSTEM_PROMPT,
            payload.notes,
            RecapData,
        )
        fallback = False
    except AIUnavailableError:
        logger.warning("meeting.recap_fallback", extra={"event": "meeting.recap_fallback"})
        recap = _fallback_recap(payload.notes)
        fallback = True

    for action_item in recap.action_items:
        action_item.owner_id, action_item.needs_review = _match_owner(
            action_item.owner_name, participants
        )
    return RecapPreview(**recap.model_dump(), fallback=fallback)


@router.post("/{meeting_id}/recap/confirm", response_model=RecapConfirmResponse)
def confirm_recap(
    meeting_id: int, payload: RecapPreview, db: Session = Depends(get_db)
) -> RecapConfirmResponse:
    meeting = get_meeting_or_404(meeting_id, db)
    meeting.summary = payload.summary
    decision_ids: list[int] = []
    for decision in payload.decisions:
        record = Decision(meeting_id=meeting.id, text=decision.text)
        db.add(record)
        db.flush()
        decision_ids.append(record.id)

    action_item_ids: list[int] = []
    for preview_item in payload.action_items:
        due_date = _parse_due_date(preview_item.due_date)
        ensure_not_past(due_date)
        if preview_item.owner_id is not None:
            ensure_owner_is_in_meeting(meeting.id, preview_item.owner_id, db)
        item = ActionItem(
            meeting_id=meeting.id,
            owner_id=preview_item.owner_id,
            title=preview_item.title,
            due_date=due_date,
            source_quote=preview_item.source_quote,
            confidence=preview_item.confidence,
        )
        db.add(item)
        db.flush()
        record_history(item, "created", None, item.title)
        action_item_ids.append(item.id)

    db.commit()
    return RecapConfirmResponse(
        meeting_id=meeting.id,
        summary=meeting.summary,
        decision_ids=decision_ids,
        action_item_ids=action_item_ids,
    )


@router.post(
    "/{meeting_id}/carry-forward",
    response_model=CarryForwardResponse,
)
def carry_forward_meeting(
    meeting_id: int, db: Session = Depends(get_db)
) -> CarryForwardResponse:
    previous_meeting = get_meeting_or_404(meeting_id, db)
    next_meeting = Meeting(
        title=f"{previous_meeting.title} - follow-up",
        type=previous_meeting.type,
        agenda=previous_meeting.agenda,
        status=MeetingStatus.DRAFT,
        previous_meeting_id=previous_meeting.id,
    )
    db.add(next_meeting)
    db.flush()

    participant_memberships = list(previous_meeting.participants)
    for membership in participant_memberships:
        db.add(
            MeetingParticipant(
                meeting_id=next_meeting.id,
                participant_id=membership.participant_id,
                attendance=membership.attendance,
            )
        )

    carryable_statuses = {
        ActionItemStatus.OPEN,
        ActionItemStatus.IN_PROGRESS,
        ActionItemStatus.BLOCKED,
    }
    action_items = list(
        db.scalars(
            select(ActionItem).where(ActionItem.meeting_id == previous_meeting.id)
        ).all()
    )
    carried_item_ids: list[int] = []
    closed_item_count = 0
    for item in action_items:
        if item.status in carryable_statuses:
            old_meeting_id = item.meeting_id
            item.meeting_id = next_meeting.id
            item.carry_count += 1
            item.history.append(
                ActionItemHistory(
                    event=f"carried forward from meeting {previous_meeting.id}",
                    old_value=str(old_meeting_id),
                    new_value=str(next_meeting.id),
                )
            )
            carried_item_ids.append(item.id)
        elif item.status == ActionItemStatus.CLOSED:
            closed_item_count += 1

    db.commit()
    logger.info(
        "meeting.carried_forward",
        extra={
            "event": "meeting.carried_forward",
            "previous_meeting_id": previous_meeting.id,
            "next_meeting_id": next_meeting.id,
            "carried_action_item_count": len(carried_item_ids),
        },
    )
    return CarryForwardResponse(
        previous_meeting_id=previous_meeting.id,
        next_meeting_id=next_meeting.id,
        participant_count=len(participant_memberships),
        carried_action_item_count=len(carried_item_ids),
        carried_action_item_ids=carried_item_ids,
        closed_action_item_count=closed_item_count,
    )


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
        raise HTTPException(
            status_code=409, detail="Participant is already in this meeting"
        )
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
