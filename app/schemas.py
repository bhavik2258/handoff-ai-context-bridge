from datetime import datetime
from enum import StrEnum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import ActionItemStatus, AttendanceStatus, MeetingType


class MeetingStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    HELD = "held"
    CLOSED = "closed"


class ParticipantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    role: str = Field(default="", max_length=40)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("email")
    @classmethod
    def email_must_be_valid(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("email must be valid")
        return value


class ParticipantResponse(ParticipantCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: MeetingType = MeetingType.MEETING
    agenda: str = ""
    notes_raw: str = ""
    status: MeetingStatus = MeetingStatus.DRAFT
    scheduled_at: datetime | None = None
    previous_meeting_id: int | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    type: MeetingType | None = None
    agenda: str | None = None
    notes_raw: str | None = None
    status: MeetingStatus | None = None
    scheduled_at: datetime | None = None
    previous_meeting_id: int | None = None

    @field_validator("title")
    @classmethod
    def optional_title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("title must not be blank")
        return value


class AttendanceUpdate(BaseModel):
    attendance: AttendanceStatus


class MeetingParticipantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    participant_id: int
    attendance: AttendanceStatus


class MeetingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    type: MeetingType
    agenda: str
    notes_raw: str
    summary: str | None
    status: str
    scheduled_at: datetime | None
    previous_meeting_id: int | None
    participants: list[MeetingParticipantResponse] = []


class CarryForwardResponse(BaseModel):
    previous_meeting_id: int
    next_meeting_id: int
    participant_count: int
    carried_action_item_count: int
    carried_action_item_ids: list[int]
    closed_action_item_count: int


class RecapRequest(BaseModel):
    notes: str = Field(min_length=1, max_length=20000)

    @field_validator("notes")
    @classmethod
    def notes_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("notes must not be blank")
        return value


class RecapDecision(BaseModel):
    text: str
    rationale: str = ""


class RecapActionItem(BaseModel):
    title: str
    owner_name: str | None = None
    due_date: str | None = None
    source_quote: str = ""
    confidence: float = Field(ge=0, le=1)
    owner_id: int | None = None
    needs_review: bool = False


class RecapData(BaseModel):
    summary: str
    decisions: list[RecapDecision] = []
    action_items: list[RecapActionItem] = []
    open_questions: list[str] = []


class RecapPreview(RecapData):
    fallback: bool


class RecapConfirmResponse(BaseModel):
    meeting_id: int
    summary: str
    decision_ids: list[int]
    action_item_ids: list[int]


class AgendaResponse(BaseModel):
    agenda: str
    fallback: bool


class CatchupData(BaseModel):
    what_happened: str
    decisions: list[str] = []
    what_you_owe: list[str] = []
    urgent: list[str] = []
    who_to_talk_to: list[str] = []


class CatchupResponse(CatchupData):
    fallback: bool


class KnowledgeDocCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1)
    doc_type: Literal["doc", "past_meeting", "note", "email"]
    tags: list[str] = []

    @field_validator("title", "content")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class KnowledgeDocResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    doc_type: str
    tags: list[str] = []


class KnowledgeLinkSuggestion(BaseModel):
    doc_id: int
    reason: str
    score: float = Field(ge=0, le=1)


class KnowledgeLinkResponse(KnowledgeLinkSuggestion):
    fallback: bool = False


class KnowledgeLinkList(BaseModel):
    links: list[KnowledgeLinkResponse]
    fallback: bool = False


class RadarItemResponse(BaseModel):
    id: int
    meeting_id: int
    title: str
    status: ActionItemStatus
    due_date: datetime | None
    carry_count: int
    score: int
    level: Literal["low", "medium", "high"]
    reasons: list[str]


class NudgeRequest(BaseModel):
    tone: Literal["friendly", "firm"]


class NudgeDraft(BaseModel):
    subject: str
    message: str


class NudgeResponse(NudgeDraft):
    fallback: bool


class ActionItemCreate(BaseModel):
    meeting_id: int
    title: str = Field(min_length=1, max_length=240)
    owner_id: int | None = None
    due_date: datetime | None = None
    status: ActionItemStatus = ActionItemStatus.OPEN
    outcome: str | None = None
    source_quote: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value


class ActionItemUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    due_date: datetime | None = None
    outcome: str | None = None
    source_quote: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("title")
    @classmethod
    def optional_title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("title must not be blank")
        return value


class ActionItemReassign(BaseModel):
    owner_id: int


class ActionItemStatusUpdate(BaseModel):
    status: ActionItemStatus
    outcome: str | None = None


class ActionItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    meeting_id: int
    owner_id: int | None
    title: str
    due_date: datetime | None
    status: ActionItemStatus
    outcome: str | None
    carry_count: int
    carried_from_id: int | None
    source_quote: str | None
    confidence: float | None


class ActionItemHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event: str
    old_value: str | None
    new_value: str | None
    timestamp: datetime
