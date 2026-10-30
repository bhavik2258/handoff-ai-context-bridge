import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    ActionItem,
    ActionItemHistory,
    ActionItemStatus,
    AttendanceStatus,
    Decision,
    Meeting,
    MeetingParticipant,
    MeetingType,
    Participant,
    KnowledgeDoc,
)


def _history(item: ActionItem, event: str, new_value: str, timestamp: datetime) -> None:
    item.history.append(
        ActionItemHistory(
            event=event,
            old_value=None,
            new_value=new_value,
            timestamp=timestamp,
        )
    )


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(Participant.id).limit(1)) is not None:
        return

    today = datetime.utcnow().replace(hour=12, minute=0, second=0, microsecond=0)
    people = [
        Participant(name="Maya Patel", email="maya@handoff.test", role="PM"),
        Participant(name="Ethan Brooks", email="ethan@handoff.test", role="Developer"),
        Participant(name="Nora Chen", email="nora@handoff.test", role="Developer"),
        Participant(name="Luis Garcia", email="luis@handoff.test", role="QA"),
        Participant(name="Priya Shah", email="priya@handoff.test", role="DevOps"),
    ]
    db.add_all(people)
    db.flush()

    kickoff = Meeting(
        title="Payments Revamp - Kickoff",
        type=MeetingType.MEETING,
        status="closed",
        agenda="Scope, owners, risks, and delivery milestones.",
        summary="The team agreed on the first release scope and ownership.",
        scheduled_at=today - timedelta(days=28),
    )
    review = Meeting(
        title="Payments Revamp - Sprint Review",
        type=MeetingType.MEETING,
        status="held",
        agenda="Review checkout work, test readiness, and open risks.",
        summary="Checkout work is progressing; the provider migration remains risky.",
        scheduled_at=today - timedelta(days=14),
        previous_meeting=kickoff,
    )
    release = Meeting(
        title="Payments Revamp - Release Planning",
        type=MeetingType.HANDOFF,
        status="scheduled",
        agenda="Confirm release checklist and handover owners.",
        scheduled_at=today + timedelta(days=3),
        previous_meeting=review,
    )
    db.add_all([kickoff, review, release])
    db.flush()

    for meeting in (kickoff, review, release):
        for person in people:
            attendance = AttendanceStatus.ATTENDED
            if meeting is review and person is people[3]:
                attendance = AttendanceStatus.ABSENT
            if meeting is release and person is people[4]:
                attendance = AttendanceStatus.ON_LEAVE
            db.add(
                MeetingParticipant(
                    meeting_id=meeting.id,
                    participant_id=person.id,
                    attendance=attendance,
                )
            )

    db.add_all(
        [
            Decision(meeting_id=kickoff.id, text="Use the new payment provider behind a feature flag."),
            Decision(meeting_id=review.id, text="Release QA must complete the refund regression suite."),
            Decision(meeting_id=release.id, text="DevOps will prepare a rollback window before launch."),
        ]
    )

    items = [
        ActionItem(
            meeting_id=kickoff.id, owner_id=people[1].id,
            title="Define payment provider adapter", due_date=today - timedelta(days=22),
            status=ActionItemStatus.CLOSED, outcome="Adapter merged and feature-flagged.",
        ),
        ActionItem(
            meeting_id=kickoff.id, owner_id=people[2].id,
            title="Document refund edge cases", due_date=today - timedelta(days=18),
            status=ActionItemStatus.CLOSED, outcome="Refund cases added to the test plan.",
        ),
        ActionItem(
            meeting_id=review.id, owner_id=people[3].id,
            title="Run refund regression suite", due_date=today - timedelta(days=5),
            status=ActionItemStatus.IN_PROGRESS, carry_count=2,
        ),
        ActionItem(
            meeting_id=review.id, owner_id=people[4].id,
            title="Prepare deployment rollback script", due_date=today - timedelta(days=9),
            status=ActionItemStatus.BLOCKED, carry_count=3,
        ),
        ActionItem(
            meeting_id=release.id, owner_id=None,
            title="Confirm release communication owner", due_date=today + timedelta(days=2),
            status=ActionItemStatus.OPEN,
        ),
        ActionItem(
            meeting_id=release.id, owner_id=people[0].id,
            title="Send launch readiness update", due_date=today + timedelta(days=1),
            status=ActionItemStatus.OPEN,
        ),
        ActionItem(
            meeting_id=release.id, owner_id=people[1].id,
            title="Verify provider metrics dashboard", due_date=today + timedelta(days=4),
            status=ActionItemStatus.OPEN,
        ),
        ActionItem(
            meeting_id=review.id, owner_id=people[2].id,
            title="Investigate duplicate charge alert", due_date=today - timedelta(days=12),
            status=ActionItemStatus.OPEN, carry_count=2,
        ),
        ActionItem(
            meeting_id=release.id, owner_id=people[0].id,
            title="Archive sprint review notes", due_date=today - timedelta(days=2),
            status=ActionItemStatus.CLOSED, outcome="Notes archived in the project workspace.",
        ),
    ]
    db.add_all(items)
    db.flush()
    for item in items:
        _history(item, "created", item.title, today - timedelta(days=10))
        if item.carry_count:
            for count in range(1, item.carry_count + 1):
                _history(
                    item,
                    f"carried forward from meeting {item.meeting_id}",
                    f"carry {count}",
                    today - timedelta(days=10 - count),
                )

    docs = [
        (
            "Deployment Runbook",
            "doc",
            ["deployment", "rollback"],
            "Confirm the release branch is green.\nPause the payment feature flag.\nRun migrations during the approved window.\nWatch error rate and provider latency.\nRollback if charge failures exceed the agreed threshold.",
        ),
        (
            "Q3 Roadmap",
            "doc",
            ["roadmap", "payments"],
            "Payments Revamp targets the Q3 checkout release.\nThe provider adapter is the first milestone.\nRefund reliability follows the initial launch.\nFeature flags are required for staged rollout.",
        ),
        (
            "Vendor Contract Summary",
            "note",
            ["vendor", "provider"],
            "The payment provider contract renews in September.\nIncident notifications must be acknowledged within four hours.\nRate limits are listed in the service schedule.\nEscalation contacts are maintained by DevOps.",
        ),
        (
            "Onboarding Guide",
            "doc",
            ["onboarding", "engineering"],
            "Start with the Payments Revamp architecture overview.\nRun the local checkout test suite before opening a PR.\nAsk QA for refund fixtures.\nUse the team channel for release questions.",
        ),
        (
            "Incident Postmortem",
            "past_meeting",
            ["incident", "refunds"],
            "A duplicate charge alert was missed during the last release.\nThe dashboard lacked provider-level breakdowns.\nQA added a regression scenario after the incident.\nThe team agreed to review rollback signals before launch.",
        ),
    ]
    db.add_all(
        [
            KnowledgeDoc(
                title=title,
                doc_type=doc_type,
                tags=json.dumps(tags),
                content=content,
            )
            for title, doc_type, tags, content in docs
        ]
    )
    db.commit()
