import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

import mcp_server as hive
from storage import get_oauth_client, get_room, list_work_items, save_oauth_client


def test_health():
    response = TestClient(hive.app).get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["version"] == "0.7.0"


def test_room_messages_persist():
    suffix = uuid.uuid4().hex
    room = hive.create_room("Persistence " + suffix, "Test durable room messages")
    room_id = room["room_id"]

    posted = hive.post_message(room_id, "Claude", "Review this implementation.", "contribution")
    assert posted["message_count"] == 1

    saved = get_room(room_id)
    assert saved is not None
    assert saved["room_id"] == room_id
    assert saved["messages"][0]["assistant"] == "Claude"
    assert saved["messages"][0]["message"] == "Review this implementation."

    read = hive.read_room(room_id)
    assert read["total_messages"] == 1
    assert read["messages"][0]["id"] == posted["posted"]["id"]


def test_work_queue_is_shared_and_assignment_is_enforced():
    suffix = uuid.uuid4().hex
    room = hive.create_room("Work queue " + suffix, "Test shared queued work")
    room_id = room["room_id"]

    created = hive.create_work_item(room_id, "Review code", "Check input validation and errors")
    assert created["status"] == "queued"

    claimed = hive.claim_next_work_item(room_id, "Claude")
    assert claimed["id"] == created["id"]
    assert claimed["status"] == "in_progress"
    assert claimed["assigned_to"] == "Claude"

    empty = hive.claim_next_work_item(room_id, "ChatGPT")
    assert empty["available"] is False

    with pytest.raises(ValueError):
        hive.update_work_item(room_id, created["id"], "completed", "ChatGPT", "Wrong agent")

    updated = hive.update_work_item(
        room_id, created["id"], "completed", "Claude", "Review passed with one minor note."
    )
    assert updated["status"] == "completed"
    assert updated["result"] == "Review passed with one minor note."

    items = list_work_items(room_id)
    assert len(items) == 1
    assert items[0]["status"] == "completed"


def test_room_ids_are_required_for_work_items():
    with pytest.raises(ValueError):
        hive.create_work_item("not-a-room", "Task", "Description")


def test_oauth_client_registration_persists():
    client_id = "test-client-" + uuid.uuid4().hex
    record = {
        "client_name": "Test MCP client",
        "redirect_uris": ["https://example.com/callback"],
        "token_endpoint_auth_method": "none",
    }
    save_oauth_client(client_id, record)
    assert get_oauth_client(client_id) == record
    assert hive._valid_client_redirect(client_id, "https://example.com/callback") is True
    assert hive._valid_client_redirect(client_id, "https://evil.example/callback") is False


def test_dashboard_requires_password_and_can_create_mission(monkeypatch):
    monkeypatch.setattr(hive, "LOGIN_PASSWORD", "dashboard-test-password")
    client = TestClient(hive.app, base_url="https://testserver")

    assert client.get("/dashboard/api/rooms").status_code == 401
    login = client.post("/dashboard/api/login", json={"password": "dashboard-test-password"})
    assert login.status_code == 200
    assert login.json()["ok"] is True

    created = client.post("/dashboard/api/rooms", json={
        "title": "Dashboard test mission",
        "goal": "Use anonymous aliases and report progress."
    })
    assert created.status_code == 200
    room_id = created.json()["room"]["room_id"]

    room_response = client.get(f"/dashboard/api/rooms/{room_id}")
    assert room_response.status_code == 200
    assert room_response.json()["room"]["messages"][0]["assistant"] == "Coordinator"

    task = client.post(f"/dashboard/api/rooms/{room_id}/tasks", json={
        "title": "Test task",
        "description": "Post a short progress report."
    })
    assert task.status_code == 200
    assert task.json()["task"]["status"] == "queued"
