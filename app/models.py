from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class MeetingType(StrEnum):
    MEETING = "meeting"
    HANDOFF = "handoff"


class AttendanceStatus(StrEnum):
    ATTENDED = "attended"
    ABSENT = "absent"
    NO_RESPONSE = "no_response"
    ON_LEAVE = "on_leave"


class ActionItemStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    CLOSED = "closed"
    DROPPED = "dropped"


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    role: Mapped[str] = mapped_column(String(40), default="", nullable=False)

    meeting_participation: Mapped[list["MeetingParticipant"]] = relationship(
        back_populates="participant", cascade="all, delete-orphan"
    )
    owned_action_items: Mapped[list["ActionItem"]] = relationship(
        back_populates="owner"
    )


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[MeetingType] = mapped_column(
        Enum(MeetingType, native_enum=False), default=MeetingType.MEETING, nullable=False
    )
    agenda: Mapped[str] = mapped_column(Text, default="", nullable=False)
    notes_raw: Mapped[str] = mapped_column(Text, default="", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="scheduled", nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    previous_meeting_id: Mapped[int | None] = mapped_column(
        ForeignKey("meetings.id"), nullable=True
    )

    previous_meeting: Mapped["Meeting | None"] = relationship(
        remote_side="Meeting.id", back_populates="follow_up_meetings"
    )
    follow_up_meetings: Mapped[list["Meeting"]] = relationship(
        back_populates="previous_meeting"
    )
    participants: Mapped[list["MeetingParticipant"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    action_items: Mapped[list["ActionItem"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    knowledge_links: Mapped[list["KnowledgeLink"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )


class MeetingParticipant(Base):
    __tablename__ = "meeting_participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), nullable=False)
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("participants.id"), nullable=False
    )
    attendance: Mapped[AttendanceStatus] = mapped_column(
        Enum(AttendanceStatus, native_enum=False),
        default=AttendanceStatus.NO_RESPONSE,
        nullable=False,
    )

    meeting: Mapped[Meeting] = relationship(back_populates="participants")
    participant: Mapped[Participant] = relationship(
        back_populates="meeting_participation"
    )


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    meeting: Mapped[Meeting] = relationship(back_populates="decisions")


class ActionItem(Base):
    __tablename__ = "action_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), nullable=False)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("participants.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[ActionItemStatus] = mapped_column(
        Enum(ActionItemStatus, native_enum=False),
        default=ActionItemStatus.OPEN,
        nullable=False,
    )
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    carry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    carried_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("action_items.id"), nullable=True
    )
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)

    meeting: Mapped[Meeting] = relationship(back_populates="action_items")
    owner: Mapped[Participant | None] = relationship(back_populates="owned_action_items")
    carried_from: Mapped["ActionItem | None"] = relationship(
        remote_side="ActionItem.id", back_populates="carried_items"
    )
    carried_items: Mapped[list["ActionItem"]] = relationship(
        back_populates="carried_from"
    )
    history: Mapped[list["ActionItemHistory"]] = relationship(
        back_populates="action_item", cascade="all, delete-orphan"
    )
    knowledge_links: Mapped[list["KnowledgeLink"]] = relationship(
        back_populates="action_item", cascade="all, delete-orphan"
    )


class ActionItemHistory(Base):
    __tablename__ = "action_item_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    action_item_id: Mapped[int] = mapped_column(
        ForeignKey("action_items.id"), nullable=False
    )
    event: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    action_item: Mapped[ActionItem] = relationship(back_populates="history")


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False)
    tags: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    links: Mapped[list["KnowledgeLink"]] = relationship(
        back_populates="knowledge_doc", cascade="all, delete-orphan"
    )


class KnowledgeLink(Base):
    __tablename__ = "knowledge_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_doc_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_docs.id"), nullable=False
    )
    meeting_id: Mapped[int | None] = mapped_column(
        ForeignKey("meetings.id"), nullable=True
    )
    action_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("action_items.id"), nullable=True
    )
    relevance: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float] = mapped_column(default=0, nullable=False)

    knowledge_doc: Mapped[KnowledgeDoc] = relationship(back_populates="links")
    meeting: Mapped[Meeting | None] = relationship(back_populates="knowledge_links")
    action_item: Mapped[ActionItem | None] = relationship(
        back_populates="knowledge_links"
    )
