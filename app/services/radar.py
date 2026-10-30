from datetime import datetime

from ..models import ActionItem, ActionItemStatus, AttendanceStatus


def risk_score(item: ActionItem, now: datetime) -> dict:
    score = 0
    reasons: list[str] = []

    if item.due_date is not None and item.due_date < now and item.status != ActionItemStatus.CLOSED:
        days_overdue = max(1, (now.date() - item.due_date.date()).days)
        overdue_points = min(days_overdue, 10)
        score += overdue_points
        reasons.append(f"{days_overdue} day(s) overdue")

    if item.carry_count:
        score += item.carry_count * 3
        reasons.append(f"carried {item.carry_count} time(s)")

    if item.status == ActionItemStatus.BLOCKED:
        score += 5
        reasons.append("status is blocked")

    if item.owner_id is not None:
        membership = next(
            (
                membership
                for membership in item.meeting.participants
                if membership.participant_id == item.owner_id
            ),
            None,
        )
        if membership is not None and membership.attendance == AttendanceStatus.ON_LEAVE:
            score += 5
            reasons.append("owner is on leave")
    else:
        score += 3
        reasons.append("no owner")

    latest_update = max((history.timestamp for history in item.history), default=None)
    if latest_update is None or (now - latest_update).days >= 7:
        score += 3
        reasons.append("no history update in 7+ days")

    level = "low" if score <= 5 else "medium" if score <= 11 else "high"
    return {"score": score, "level": level, "reasons": reasons}
