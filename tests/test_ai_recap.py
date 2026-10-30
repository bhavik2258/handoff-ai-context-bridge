from unittest.mock import patch

from app.schemas import RecapData


def create_meeting_with_participant(client):
    participant = client.post(
        "/api/participants",
        json={"name": "Alice Smith", "email": "alice-recap@example.com"},
    ).json()
    meeting = client.post("/api/meetings", json={"title": "Recap meeting"}).json()
    client.post(
        f"/api/meetings/{meeting['id']}/participants",
        params={"participant_id": participant["id"]},
    )
    return meeting, participant


def test_ai_recap_preview_fuzzy_matches_owner_and_does_not_save(client):
    meeting, participant = create_meeting_with_participant(client)
    ai_result = RecapData.model_validate(
        {
            "summary": "The team agreed to ship.",
            "decisions": [{"text": "Ship it", "rationale": "Ready"}],
            "action_items": [
                {
                    "title": "Prepare release",
                    "owner_name": "Alic Smith",
                    "due_date": None,
                    "source_quote": "Alice will prepare release",
                    "confidence": 0.9,
                }
            ],
            "open_questions": ["What is the launch time?"],
        }
    )
    with patch("app.routers.meetings.call_ai_json", return_value=ai_result):
        response = client.post(
            f"/api/meetings/{meeting['id']}/ai/recap",
            json={"notes": "Alice will prepare release"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["fallback"] is False
    assert body["action_items"][0]["owner_id"] == participant["id"]
    assert body["action_items"][0]["needs_review"] is False
    assert client.get("/api/action-items", params={"meeting_id": meeting["id"]}).json() == []
    assert client.get(f"/api/meetings/{meeting['id']}").json()["summary"] is None


def test_ai_recap_falls_back_for_unavailable_ai(client):
    meeting, _ = create_meeting_with_participant(client)
    with patch(
        "app.routers.meetings.call_ai_json",
        side_effect=__import__("app.services.ai_client", fromlist=["AIUnavailableError"]).AIUnavailableError(),
    ):
        response = client.post(
            f"/api/meetings/{meeting['id']}/ai/recap",
            json={"notes": "TODO send the recap\nRandom context"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["fallback"] is True
    assert body["action_items"][0]["title"] == "send the recap"


def test_recap_rejects_blank_and_oversized_notes(client):
    meeting, _ = create_meeting_with_participant(client)
    assert client.post(
        f"/api/meetings/{meeting['id']}/ai/recap", json={"notes": " "}
    ).status_code == 422
    assert client.post(
        f"/api/meetings/{meeting['id']}/ai/recap", json={"notes": "x" * 20001}
    ).status_code == 422


def test_confirm_recap_saves_summary_decisions_actions_and_history(client):
    meeting, participant = create_meeting_with_participant(client)
    preview = {
        "fallback": False,
        "summary": "Confirmed summary",
        "decisions": [{"text": "Use the new plan", "rationale": "Simpler"}],
        "action_items": [
            {
                "title": "Write plan",
                "owner_name": "Alice Smith",
                "owner_id": participant["id"],
                "needs_review": False,
                "due_date": None,
                "source_quote": "Alice will write plan",
                "confidence": 0.8,
            }
        ],
        "open_questions": [],
    }
    response = client.post(
        f"/api/meetings/{meeting['id']}/recap/confirm",
        json=preview,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["decision_ids"]) == 1
    assert len(body["action_item_ids"]) == 1
    assert client.get(f"/api/meetings/{meeting['id']}").json()["summary"] == "Confirmed summary"
    assert client.get("/api/action-items", params={"meeting_id": meeting["id"]}).json()[0]["owner_id"] == participant["id"]
