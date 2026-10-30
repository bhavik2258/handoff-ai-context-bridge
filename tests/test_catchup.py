from unittest.mock import patch

from app.schemas import CatchupData


def setup_missed_meeting(client):
    person = client.post(
        "/api/participants",
        json={"name": "Returning Teammate", "email": "returning@example.com"},
    ).json()
    colleague = client.post(
        "/api/participants",
        json={"name": "Colleague", "email": "colleague@example.com"},
    ).json()
    meeting = client.post("/api/meetings", json={"title": "Project sync"}).json()
    for participant in (person, colleague):
        client.post(
            f"/api/meetings/{meeting['id']}/participants",
            params={"participant_id": participant["id"]},
        )
    client.patch(
        f"/api/meetings/{meeting['id']}/participants/{person['id']}",
        json={"attendance": "absent"},
    )
    return person, colleague, meeting


def test_catchup_uses_gathered_data_with_mocked_ai(client):
    person, _, meeting = setup_missed_meeting(client)
    with patch(
        "app.routers.participants.call_ai_json",
        return_value=CatchupData(
            what_happened="The project sync happened.",
            decisions=["Use the new plan."],
            what_you_owe=["Review the plan."],
            urgent=["Resolve the blocked task."],
            who_to_talk_to=["Colleague"],
        ),
    ) as call_ai:
        response = client.get(f"/api/participants/{person['id']}/catchup")
    assert response.status_code == 200
    assert response.json()["fallback"] is False
    assert response.json()["decisions"] == ["Use the new plan."]
    assert call_ai.call_args.args[0] == "participant_catchup"
    assert "Project sync" in call_ai.call_args.args[2]
    assert meeting["title"] in call_ai.call_args.args[2]


def test_catchup_falls_back_to_plain_data(client):
    person, colleague, meeting = setup_missed_meeting(client)
    from app.database import SessionLocal
    from app.models import ActionItem, ActionItemStatus, Decision

    with SessionLocal() as db:
        db.add(Decision(meeting_id=meeting["id"], text="Ship on Friday"))
        db.add(
            ActionItem(
                meeting_id=meeting["id"],
                owner_id=person["id"],
                title="Review release",
                status=ActionItemStatus.OPEN,
            )
        )
        db.commit()

    from app.services.ai_client import AIUnavailableError

    with patch(
        "app.routers.participants.call_ai_json",
        side_effect=AIUnavailableError(),
    ):
        response = client.get(f"/api/participants/{person['id']}/catchup")
    assert response.status_code == 200
    body = response.json()
    assert body["fallback"] is True
    assert body["what_happened"] == "Project sync"
    assert body["decisions"] == ["Ship on Friday"]
    assert body["what_you_owe"] == ["Review release"]
    assert body["who_to_talk_to"] == [colleague["name"]]


def test_catchup_unknown_participant_returns_404(client):
    assert client.get("/api/participants/99999/catchup").status_code == 404
