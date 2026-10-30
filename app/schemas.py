from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import AttendanceStatus, MeetingType


class MeetingStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    HELD = "held"
    CLOSED = "closed"


class ParticipantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
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
