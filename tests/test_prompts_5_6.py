from datetime import datetime, timedelta

from sqlalchemy import select


def create_participant(client, name: str, email: str) -> dict:
    response = client.post(
        "/api/participants",
        json={"name": name, "email": email},
    )
    assert response.status_code == 201
    return response.json()


def create_meeting(client, title: str = "Planning sync") -> dict:
    response = client.post("/api/meetings", json={"title": title})
    assert response.status_code == 201
    return response.json()


def add_participant(client, meeting_id: int, participant_id: int) -> None:
    response = client.post(
        f"/api/meetings/{meeting_id}/participants",
        params={"participant_id": participant_id},
    )
    assert response.status_code == 201


def create_action_item(
    client,
    meeting_id: int,
    title: str,
    *,
    owner_id: int | None = None,
    status: str = "open",
    outcome: str | None = None,
) -> dict:
    response = client.post(
        "/api/action-items",
        json={
            "meeting_id": meeting_id,
            "title": title,
            "owner_id": owner_id,
            "status": status,
            "outcome": outcome,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_action_item_owner_and_due_date_validation(client):
    meeting = create_meeting(client)
    participant = create_participant(client, "Owner", "owner@example.com")

    not_a_member = client.post(
        "/api/action-items",
        json={
            "meeting_id": meeting["id"],
            "title": "Invalid owner",
            "owner_id": participant["id"],
        },
    )
    assert not_a_member.status_code == 422

    add_participant(client, meeting["id"], participant["id"])
    past_due = client.post(
        "/api/action-items",
        json={
            "meeting_id": meeting["id"],
            "title": "Late item",
            "owner_id": participant["id"],
            "due_date": (datetime.utcnow() - timedelta(days=1)).isoformat(),
        },
    )
    assert past_due.status_code == 422

    valid = client.post(
        "/api/action-items",
        json={
            "meeting_id": meeting["id"],
            "title": "Valid item",
            "owner_id": participant["id"],
            "due_date": (datetime.utcnow() + timedelta(days=1)).isoformat(),
        },
    )
    assert valid.status_code == 201


def test_action_item_closing_requires_outcome(client):
    meeting = create_meeting(client)
    item = create_action_item(client, meeting["id"], "Prepare recap")

    without_outcome = client.patch(
        f"/api/action-items/{item['id']}/status",
        json={"status": "closed"},
    )
    assert without_outcome.status_code == 422

    with_outcome = client.patch(
        f"/api/action-items/{item['id']}/status",
        json={"status": "closed", "outcome": "Recap sent to the team"},
    )
    assert with_outcome.status_code == 200
    assert with_outcome.json()["status"] == "closed"
    assert with_outcome.json()["outcome"] == "Recap sent to the team"


def test_reassigning_action_item_writes_history(client):
    meeting = create_meeting(client)
    first = create_participant(client, "First owner", "first@example.com")
    second = create_participant(client, "Second owner", "second@example.com")
    add_participant(client, meeting["id"], first["id"])
    add_participant(client, meeting["id"], second["id"])
    item = create_action_item(
        client, meeting["id"], "Update roadmap", owner_id=first["id"]
    )

    response = client.patch(
        f"/api/action-items/{item['id']}/reassign",
        json={"owner_id": second["id"]},
    )
    assert response.status_code == 200
    assert response.json()["owner_id"] == second["id"]

    from app.database import SessionLocal
    from app.models import ActionItemHistory

    with SessionLocal() as db:
        history = db.scalar(
            select(ActionItemHistory).where(
                ActionItemHistory.action_item_id == item["id"],
                ActionItemHistory.event == "reassigned",
            )
        )
        assert history is not None
        assert history.old_value == str(first["id"])
        assert history.new_value == str(second["id"])


def test_carry_forward_moves_open_and_blocked_items_only(client):
    meeting = create_meeting(client, "Handoff sync")
    participant = create_participant(client, "Attendee", "attendee@example.com")
    add_participant(client, meeting["id"], participant["id"])
    open_item = create_action_item(
        client, meeting["id"], "Open work", owner_id=participant["id"]
    )
    blocked_item = create_action_item(
        client, meeting["id"], "Blocked work", status="blocked"
    )
    closed_item = create_action_item(
        client,
        meeting["id"],
        "Completed work",
        status="closed",
        outcome="Already complete",
    )

    response = client.post(f"/api/meetings/{meeting['id']}/carry-forward")
    assert response.status_code == 200
    summary = response.json()
    next_meeting_id = summary["next_meeting_id"]
    assert summary["carried_action_item_count"] == 2
    assert summary["closed_action_item_count"] == 1
    assert summary["participant_count"] == 1

    carried_items = client.get(
        "/api/action-items",
        params={"meeting_id": next_meeting_id},
    ).json()
    assert {item["id"] for item in carried_items} == {
        open_item["id"],
        blocked_item["id"],
    }
    assert all(item["carry_count"] == 1 for item in carried_items)

    original_items = client.get(
        "/api/action-items",
        params={"meeting_id": meeting["id"]},
    ).json()
    assert {item["id"] for item in original_items} == {closed_item["id"]}

    next_meeting = client.get(f"/api/meetings/{next_meeting_id}").json()
    assert next_meeting["previous_meeting_id"] == meeting["id"]
    assert len(next_meeting["participants"]) == 1

    from app.database import SessionLocal
    from app.models import ActionItemHistory

    with SessionLocal() as db:
        history = db.scalars(
            select(ActionItemHistory).where(
                ActionItemHistory.event
                == f"carried forward from meeting {meeting['id']}"
            )
        ).all()
        assert len(history) == 2
