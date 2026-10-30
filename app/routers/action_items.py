import logging
import json
import re
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
    KnowledgeDoc,
    KnowledgeLink,
    Participant,
)
from ..schemas import (
    ActionItemCreate,
    ActionItemReassign,
    ActionItemResponse,
    ActionItemStatusUpdate,
    ActionItemUpdate,
    KnowledgeLinkList,
    KnowledgeLinkResponse,
    KnowledgeLinkSuggestion,
    NudgeRequest,
    NudgeDraft,
    NudgeResponse,
)
from ..services.ai_client import AIUnavailableError, call_ai_json
from ..services.prompts import KNOWLEDGE_LINK_SYSTEM_PROMPT, NUDGE_SYSTEM_PROMPT
from pydantic import RootModel
from ..services.radar import risk_score


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/action-items", tags=["action-items"])


class LinkSuggestions(RootModel[list[KnowledgeLinkSuggestion]]):
    pass


def _keywords(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2}


def _fallback_links(item: ActionItem, docs: list[KnowledgeDoc]) -> list[KnowledgeLinkSuggestion]:
    item_words = _keywords(" ".join(filter(None, [item.title, item.source_quote, item.outcome])))
    ranked = []
    for doc in docs:
        doc_text = " ".join([doc.title, doc.tags, doc.content or ""])
        overlap = item_words & _keywords(doc_text)
        if overlap:
            score = min(1.0, len(overlap) / max(1, len(item_words)))
            ranked.append(KnowledgeLinkSuggestion(
                doc_id=doc.id,
                reason=f"Keyword overlap: {', '.join(sorted(overlap))}",
                score=score,
            ))
    return sorted(ranked, key=lambda link: link.score, reverse=True)[:3]


def _nudge_fallback(item: ActionItem, tone: str, reasons: list[str]) -> dict[str, str]:
    due_date = item.due_date.date().isoformat() if item.due_date else "no due date"
    carried = f"{item.carry_count} time(s)"
    reason_text = "; ".join(reasons) if reasons else "no current risk factors"
    if tone == "friendly":
        message = (
            f"Hi, a quick reminder about '{item.title}'. It is due {due_date} "
            f"and has been carried {carried}. Risk factors: {reason_text}."
        )
    else:
        message = (
            f"Please address '{item.title}'. It is due {due_date}, has been carried "
            f"{carried}, and has these risk factors: {reason_text}."
        )
    return {"subject": f"Reminder: {item.title}", "message": message}


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


@router.post("/{item_id}/ai/link", response_model=KnowledgeLinkList)
def link_knowledge(
    item_id: int, db: Session = Depends(get_db)
) -> KnowledgeLinkList:
    item = get_action_item_or_404(item_id, db)
    docs = list(db.scalars(select(KnowledgeDoc).order_by(KnowledgeDoc.id)).all())
    context = {
        "item": {
            "title": item.title,
            "description": item.source_quote or item.outcome or "",
        },
        "documents": [
            {
                "id": doc.id,
                "title": doc.title,
                "text": (doc.content or "")[:200],
            }
            for doc in docs
        ],
    }
    fallback = False
    try:
        suggestions = call_ai_json(
            "action_item_knowledge_links",
            KNOWLEDGE_LINK_SYSTEM_PROMPT,
            json.dumps(context),
            LinkSuggestions,
        ).root
    except AIUnavailableError:
        suggestions = _fallback_links(item, docs)
        fallback = True
        logger.warning(
            "action_item.knowledge_link_fallback",
            extra={"event": "action_item.knowledge_link_fallback", "action_item_id": item.id},
        )

    valid_docs = {doc.id: doc for doc in docs}
    suggestions = [suggestion for suggestion in suggestions if suggestion.doc_id in valid_docs]
    item.knowledge_links.clear()
    for suggestion in suggestions:
        item.knowledge_links.append(
            KnowledgeLink(
                knowledge_doc_id=suggestion.doc_id,
                action_item_id=item.id,
                relevance=suggestion.reason,
                score=suggestion.score,
            )
        )
    db.commit()
    return KnowledgeLinkList(
        links=[
            KnowledgeLinkResponse(
                doc_id=suggestion.doc_id,
                reason=suggestion.reason,
                score=suggestion.score,
                fallback=fallback,
            )
            for suggestion in suggestions
        ],
        fallback=fallback,
    )


@router.get("/{item_id}/links", response_model=KnowledgeLinkList)
def list_knowledge_links(
    item_id: int, db: Session = Depends(get_db)
) -> KnowledgeLinkList:
    item = get_action_item_or_404(item_id, db)
    return KnowledgeLinkList(
        links=[
            KnowledgeLinkResponse(
                doc_id=link.knowledge_doc_id,
                reason=link.relevance or "",
                score=link.score,
            )
            for link in item.knowledge_links
        ]
    )


@router.post("/{item_id}/ai/nudge", response_model=NudgeResponse)
def generate_nudge(
    item_id: int,
    payload: NudgeRequest,
    db: Session = Depends(get_db),
) -> NudgeResponse:
    item = get_action_item_or_404(item_id, db)
    if item.status == ActionItemStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Closed action items cannot be nudged")

    risk = risk_score(item, datetime.utcnow())
    context = {
        "tone": payload.tone,
        "owner_name": item.owner.name if item.owner else None,
        "title": item.title,
        "due_date": item.due_date.date().isoformat() if item.due_date else None,
        "carry_count": item.carry_count,
        "reasons": risk["reasons"],
    }
    fallback = False
    try:
        draft = call_ai_json(
            "action_item_nudge",
            NUDGE_SYSTEM_PROMPT,
            json.dumps(context),
            NudgeDraft,
        )
        result = {"subject": draft.subject, "message": draft.message}
    except AIUnavailableError:
        result = _nudge_fallback(item, payload.tone, risk["reasons"])
        fallback = True
    logger.info(
        "nudge.generated",
        extra={"event": "nudge.generated", "action_item_id": item.id, "fallback": fallback},
    )
    return NudgeResponse(**result, fallback=fallback)


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
