"""AI Hive: API-key-free shared workspace for MCP-enabled AI clients.

This server does not call model APIs. Each connected assistant uses its own
host application's existing session/subscription and contributes through MCP tools.
Room IDs are unguessable bearer links; do not share them publicly. Rooms are in-memory
and disappear when the service restarts.
"""
import time
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from mcp.server.fastmcp import FastMCP

rooms: dict[str, dict[str, Any]] = {}

mcp = FastMCP(
    "AI Hive",
    instructions=(
        "AI Hive is a shared workspace for assistants connected through MCP. "
        "It does not call OpenAI, Anthropic, or Google APIs and does not need model API keys. "
        "Use create_room to start a collaboration, share the returned room_id only with "
        "trusted participants, post_message to contribute, and read_room to review everyone's work. "
        "Each assistant must be connected to this MCP server in its own client and asked to participate."
    ),
)


def _room(room_id: str) -> dict[str, Any]:
    room = rooms.get(room_id)
    if not room:
        raise ValueError("Room not found. Check the room_id; rooms are lost on server restart.")
    return room


@mcp.tool()
def create_room(title: str, goal: str) -> dict[str, Any]:
    """Create a private-by-unguessable-ID shared room for multiple AI assistants.

    Args:
        title: Short name for the collaboration.
        goal: The task all participating assistants should work on.
    """
    if not title.strip() or not goal.strip():
        raise ValueError("title and goal are required")
    room_id = uuid.uuid4().hex
    room = {
        "room_id": room_id,
        "title": title.strip()[:160],
        "goal": goal.strip()[:12000],
        "created_at": time.time(),
        "updated_at": time.time(),
        "messages": [],
    }
    rooms[room_id] = room
    return room


@mcp.tool()
def post_message(room_id: str, assistant: str, message: str, kind: str = "contribution") -> dict[str, Any]:
    """Post an answer, critique, question, or summary to a shared room.

    Args:
        room_id: The room ID returned by create_room.
        assistant: A label such as ChatGPT, Claude, Gemini, or the user's name.
        message: The contribution text.
        kind: One of contribution, critique, question, or summary.
    """
    room = _room(room_id)
    if not assistant.strip() or not message.strip():
        raise ValueError("assistant and message are required")
    if kind not in {"contribution", "critique", "question", "summary"}:
        raise ValueError("kind must be contribution, critique, question, or summary")
    entry = {
        "id": uuid.uuid4().hex[:12],
        "assistant": assistant.strip()[:80],
        "kind": kind,
        "message": message.strip()[:30000],
        "created_at": time.time(),
    }
    room["messages"].append(entry)
    room["updated_at"] = time.time()
    return {"room_id": room_id, "posted": entry, "message_count": len(room["messages"])}


@mcp.tool()
def read_room(room_id: str, after_id: str = "", limit: int = 30) -> dict[str, Any]:
    """Read the shared task and messages. Use after_id to read messages after a known message ID.

    Args:
        room_id: The room ID returned by create_room.
        after_id: Optional message ID; if set, only return messages after it.
        limit: Maximum messages to return (1-100).
    """
    room = _room(room_id)
    messages = room["messages"]
    if after_id:
        indices = [i for i, item in enumerate(messages) if item["id"] == after_id]
        if not indices:
            raise ValueError("after_id was not found in this room")
        messages = messages[indices[0] + 1:]
    limit = max(1, min(int(limit), 100))
    return {
        "room_id": room["room_id"],
        "title": room["title"],
        "goal": room["goal"],
        "created_at": room["created_at"],
        "updated_at": room["updated_at"],
        "total_messages": len(room["messages"]),
        "messages": messages[-limit:],
    }


@mcp.tool()
def list_my_rooms(limit: int = 10) -> list[dict[str, Any]]:
    """List recent rooms available in this running server process.

    Note: rooms are not tied to an account; anyone who knows a room ID can access it.
    """
    limit = max(1, min(int(limit), 30))
    return [
        {
            "room_id": room["room_id"],
            "title": room["title"],
            "message_count": len(room["messages"]),
            "updated_at": room["updated_at"],
        }
        for room in sorted(rooms.values(), key=lambda x: x["updated_at"], reverse=True)[:limit]
    ]


@mcp.tool()
def get_connection_info() -> dict[str, Any]:
    """Explain how to connect an MCP client and the limits of API-key-free collaboration."""
    return {
        "mcp_endpoint": "/mcp",
        "transport": "Streamable HTTP",
        "api_keys_required": False,
        "provider_api_calls": False,
        "workflow": [
            "Connect this remote MCP server in each AI app that supports custom remote MCP servers.",
            "Create a room from one connected assistant and copy its room_id.",
            "Ask each connected assistant to read_room, work on the goal, then post_message.",
            "Ask assistants to read the other contributions and post critiques or a final summary.",
        ],
        "important_limits": [
            "This server does not log into ChatGPT, Claude, or Gemini on your behalf.",
            "Each provider must support custom remote MCP connections in the app/account you use.",
            "Room IDs act like secret links; anyone who knows one can read and post.",
            "Rooms are in-memory and disappear when Render restarts the service.",
        ],
    }


from contextlib import asynccontextmanager
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="AI Hive MCP", version="0.5.0", lifespan=lifespan)


@app.get("/")
def dashboard():
    return FileResponse("static/manual.html")


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "AI Hive MCP",
        "version": "0.5.0",
        "mode": "shared-workspace-no-provider-api-keys",
    }


app.mount("/mcp", mcp.streamable_http_app())
