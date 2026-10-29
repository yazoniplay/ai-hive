import uuid

import pytest

import mcp_server as hive
from storage import get_room, list_work_items


def test_health():
    response = hive.app
    assert response.title == "AI Hive MCP"


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
