import json
import logging

import pytest
from sqlalchemy import inspect


def participant_payload(name: str = "Maya", email: str = "maya@example.com") -> dict:
    return {"name": name, "email": email}


def meeting_payload(title: str = "Launch sync") -> dict:
    return {"title": title, "type": "meeting", "status": "draft"}


def test_health_returns_200(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_each_response_has_unique_request_id(client):
    first = client.get("/health")
    second = client.get("/health")
    assert first.headers["X-Request-ID"]
    assert second.headers["X-Request-ID"]
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


def test_404_and_422_have_consistent_error_shape(client):
    for response in (
        client.get("/api/participants/99999"),
        client.post("/api/participants", json={"name": ""}),
    ):
        assert response.status_code in (404, 422)
        assert set(response.json()) == {"error", "message", "request_id"}
        assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_meeting_creation_is_logged_as_json_with_request_id(client, log_path):
    response = client.post("/api/meetings", json=meeting_payload())
    assert response.status_code == 201

    lines = [json.loads(line) for line in log_path.read_text().splitlines()]
    request_id = response.headers["X-Request-ID"]
    assert any(line.get("request_id") == request_id for line in lines)
    assert any(line.get("event") == "meeting.created" for line in lines)


def test_logged_secret_is_redacted(client, log_path, caplog):
    secret = "sk-ant-abc1234567890xyz"
    with caplog.at_level(logging.INFO):
        logging.getLogger("test.secret").info(secret)
    client.get("/health")
    assert secret not in log_path.read_text()


def test_all_tables_exist(client):
    expected = {
        "participants",
        "meetings",
        "meeting_participants",
        "decisions",
        "action_items",
        "action_item_history",
        "knowledge_docs",
        "knowledge_links",
    }
    from app.database import engine

    assert expected.issubset(set(inspect(engine).get_table_names()))


def test_participant_crud_and_validation(client):
    created = client.post("/api/participants", json=participant_payload())
    assert created.status_code == 201
    participant = created.json()

    fetched = client.get(f"/api/participants/{participant['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Maya"

    updated = client.patch(
        f"/api/participants/{participant['id']}",
        json=participant_payload("Maya Updated", "updated@example.com"),
    )
    assert updated.status_code == 200

    listed = client.get("/api/participants")
    assert listed.status_code == 200
    assert listed.json()[0]["email"] == "updated@example.com"

    assert client.post(
        "/api/participants",
        json=participant_payload("Other", "updated@example.com"),
    ).status_code == 409
    assert client.post(
        "/api/participants", json=participant_payload(" ", "valid@example.com")
    ).status_code == 422
    assert client.post(
        "/api/participants", json=participant_payload("Invalid", "not-an-email")
    ).status_code == 422
    assert client.get("/api/participants/99999").status_code == 404

    assert client.delete(f"/api/participants/{participant['id']}").status_code == 204
    assert client.get(f"/api/participants/{participant['id']}").status_code == 404


def test_meeting_crud_and_validation(client):
    created = client.post("/api/meetings", json=meeting_payload())
    assert created.status_code == 201
    meeting = created.json()

    assert client.get(f"/api/meetings/{meeting['id']}").status_code == 200
    assert client.get("/api/meetings").status_code == 200
    assert client.patch(
        f"/api/meetings/{meeting['id']}", json={"agenda": "Discuss launch"}
    ).status_code == 200
    assert client.post("/api/meetings", json=meeting_payload(" ")).status_code == 422
    assert client.post(
        "/api/meetings", json={**meeting_payload(), "type": "invalid"}
    ).status_code == 422
    assert client.get("/api/meetings/99999").status_code == 404


def test_status_lifecycle_and_invalid_transitions(client):
    meeting = client.post("/api/meetings", json=meeting_payload()).json()
    meeting_id = meeting["id"]

    assert client.patch(f"/api/meetings/{meeting_id}", json={"status": "scheduled"}).status_code == 200
    assert client.patch(f"/api/meetings/{meeting_id}", json={"status": "held"}).status_code == 200
    assert client.patch(f"/api/meetings/{meeting_id}", json={"status": "closed"}).status_code == 200

    draft = client.post("/api/meetings", json=meeting_payload("Another")).json()
    assert client.patch(
        f"/api/meetings/{draft['id']}", json={"status": "held"}
    ).status_code >= 400
    assert client.patch(
        f"/api/meetings/{meeting_id}", json={"status": "held"}
    ).status_code >= 400


def test_meeting_participant_and_attendance(client):
    participant = client.post(
        "/api/participants", json=participant_payload()
    ).json()
    meeting = client.post("/api/meetings", json=meeting_payload()).json()
    meeting_id = meeting["id"]
    participant_id = participant["id"]

    added = client.post(
        f"/api/meetings/{meeting_id}/participants",
        params={"participant_id": participant_id},
    )
    assert added.status_code == 201
    assert client.post(
        f"/api/meetings/{meeting_id}/participants",
        params={"participant_id": participant_id},
    ).status_code >= 400
    assert client.post(
        f"/api/meetings/{meeting_id}/participants",
        params={"participant_id": 99999},
    ).status_code == 404
    assert client.post(
        "/api/meetings/99999/participants",
        params={"participant_id": participant_id},
    ).status_code == 404

    for attendance in ("attended", "absent", "no_response", "on_leave"):
        response = client.patch(
            f"/api/meetings/{meeting_id}/participants/{participant_id}",
            json={"attendance": attendance},
        )
        assert response.status_code == 200
        assert response.json()["attendance"] == attendance

    assert client.patch(
        f"/api/meetings/{meeting_id}/participants/{participant_id}",
        json={"attendance": "unknown"},
    ).status_code == 422
