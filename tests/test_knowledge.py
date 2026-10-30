from unittest.mock import patch

from app.routers.action_items import LinkSuggestions
from app.schemas import KnowledgeLinkSuggestion
from app.services.ai_client import AIUnavailableError


def setup_item(client):
    meeting = client.post("/api/meetings", json={"title": "Knowledge sync"}).json()
    item = client.post(
        "/api/action-items",
        json={"meeting_id": meeting["id"], "title": "Prepare launch plan"},
    ).json()
    return item


def test_knowledge_crud_and_validation(client):
    invalid = client.post(
        "/api/knowledge",
        json={"title": " ", "content": "content", "doc_type": "doc", "tags": []},
    )
    assert invalid.status_code == 422
    created = client.post(
        "/api/knowledge",
        json={
            "title": "Launch guide",
            "content": "Steps for launch planning",
            "doc_type": "doc",
            "tags": ["launch"],
        },
    )
    assert created.status_code == 201
    doc = created.json()
    assert client.get("/api/knowledge").status_code == 200
    assert client.get(f"/api/knowledge/{doc['id']}").json()["tags"] == ["launch"]


def test_ai_links_drop_hallucinated_document_ids(client):
    item = setup_item(client)
    doc = client.post(
        "/api/knowledge",
        json={
            "title": "Launch guide",
            "content": "Launch planning details",
            "doc_type": "doc",
            "tags": ["launch"],
        },
    ).json()
    suggestions = LinkSuggestions(
        root=[
            KnowledgeLinkSuggestion(doc_id=doc["id"], reason="Relevant", score=0.9),
            KnowledgeLinkSuggestion(doc_id=99999, reason="Hallucinated", score=1),
        ]
    )
    with patch("app.routers.action_items.call_ai_json", return_value=suggestions):
        response = client.post(f"/api/action-items/{item['id']}/ai/link")
    assert response.status_code == 200
    assert response.json()["fallback"] is False
    assert [link["doc_id"] for link in response.json()["links"]] == [doc["id"]]
    assert [link["doc_id"] for link in client.get(f"/api/action-items/{item['id']}/links").json()["links"]] == [doc["id"]]


def test_ai_links_fallback_uses_keyword_overlap(client):
    item = setup_item(client)
    doc = client.post(
        "/api/knowledge",
        json={
            "title": "Launch planning",
            "content": "launch plan checklist",
            "doc_type": "note",
            "tags": ["launch"],
        },
    ).json()
    with patch(
        "app.routers.action_items.call_ai_json",
        side_effect=AIUnavailableError(),
    ):
        response = client.post(f"/api/action-items/{item['id']}/ai/link")
    assert response.status_code == 200
    assert response.json()["fallback"] is True
    assert response.json()["links"][0]["doc_id"] == doc["id"]
