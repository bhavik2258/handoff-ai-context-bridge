from datetime import datetime, timedelta
from unittest.mock import patch

from app.services.ai_client import AIUnavailableError
from app.services.radar import risk_score


def create_item(client, **item_data):
    meeting = client.post("/api/meetings", json={"title": "Radar meeting"}).json()
    payload = {"meeting_id": meeting["id"], "title": "Prepare report", **item_data}
    return client.post("/api/action-items", json=payload).json()


def test_clean_item_scores_low(client):
    item = create_item(client)
    response = client.get("/api/radar")
    assert response.status_code == 200
    scored = next(result for result in response.json() if result["id"] == item["id"])
    assert scored["score"] <= 5
    assert scored["level"] == "low"
    assert scored["reasons"] == ["no owner"]


def test_overdue_blocked_item_carried_three_times_scores_high(client):
    item = create_item(client)
    from app.database import get_db
    from app.models import ActionItem, ActionItemStatus

    db = next(get_db())
    database_item = db.get(ActionItem, item["id"])
    database_item.status = ActionItemStatus.BLOCKED
    database_item.carry_count = 3
    database_item.due_date = datetime.utcnow() - timedelta(days=10)
    db.commit()
    response = client.get("/api/radar")
    assert response.status_code == 200
    scored = next(result for result in response.json() if result["id"] == item["id"])
    assert scored["score"] >= 24
    assert scored["level"] == "high"


def test_nudge_fallback(client):
    item = create_item(client, due_date=(datetime.utcnow() + timedelta(days=2)).isoformat())
    with patch(
        "app.routers.action_items.call_ai_json",
        side_effect=AIUnavailableError(),
    ):
        response = client.post(
            f"/api/action-items/{item['id']}/ai/nudge",
            json={"tone": "friendly"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["fallback"] is True
    assert item["title"] in body["message"]
    assert "carried 0 time(s)" in body["message"]
