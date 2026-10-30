from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import ActionItem, KnowledgeDoc, Meeting, Participant
from app.seed import seed_if_empty


def test_seeding_twice_is_idempotent_and_creates_high_risk_radar(client):
    with SessionLocal() as db:
        seed_if_empty(db)
        first_counts = (
            db.scalar(select(func.count()).select_from(Participant)),
            db.scalar(select(func.count()).select_from(Meeting)),
            db.scalar(select(func.count()).select_from(ActionItem)),
            db.scalar(select(func.count()).select_from(KnowledgeDoc)),
        )
        seed_if_empty(db)
        second_counts = (
            db.scalar(select(func.count()).select_from(Participant)),
            db.scalar(select(func.count()).select_from(Meeting)),
            db.scalar(select(func.count()).select_from(ActionItem)),
            db.scalar(select(func.count()).select_from(KnowledgeDoc)),
        )
    assert first_counts == (5, 3, 9, 5)
    assert second_counts == first_counts

    radar = client.get("/api/radar")
    assert radar.status_code == 200
    assert any(item["level"] == "high" for item in radar.json())
