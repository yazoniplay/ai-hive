"""Remote MCP server for AI Hive.

Expose AI Hive collaboration as standard MCP tools over Streamable HTTP at /mcp.
The model sessions still need a connector to deliver responses; MCP itself does not
grant access to private consumer subscriptions.
"""
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

import app as hive

mcp = FastMCP(
    "AI Hive",
    instructions=(
        "AI Hive coordinates ChatGPT, Claude, and Gemini in one collaboration. "
        "Use start_collaboration to send a goal to selected agents, then get_collaboration "
        "to inspect progress and final responses. The connected agent sessions must be online."
    ),
)


@mcp.tool()
def list_models() -> dict[str, Any]:
    """List ChatGPT, Claude, and Gemini session status."""
    snapshot = hive.state_snapshot()
    return {"models": snapshot["agents"], "note": snapshot["warning"]}


@mcp.tool()
async def start_collaboration(
    message: str,
    agents: list[str] | None = None,
    rounds: int = 1,
) -> dict[str, Any]:
    """Send one message to multiple AI Hive models.

    Args:
        message: The user's request to send to the selected models.
        agents: Any combination of chatgpt, claude, gemini. Defaults to all three.
        rounds: 1 for independent answers, 2-5 for cross-review and refinement.
    """
    chosen = agents or ["chatgpt", "claude", "gemini"]
    body = hive.StartBody(goal=message, agents=chosen, rounds=rounds)
    result = await hive.create_task(body)
    task = result["task"]
    return {
        "task_id": task["id"],
        "status": task["status"],
        "models": task["agents"],
        "rounds": task["max_rounds"],
        "message": "Collaboration created. Call get_collaboration with task_id to check progress and retrieve answers.",
    }


@mcp.tool()
def get_collaboration(task_id: str) -> dict[str, Any]:
    """Get collaboration status, model responses, and final answers by task ID."""
    return hive.get_task(task_id)


@mcp.tool()
def list_recent_collaborations(limit: int = 10) -> list[dict[str, Any]]:
    """List recent collaborations and their current status."""
    limit = max(1, min(int(limit), 30))
    rows = []
    for task in list(hive.tasks.values())[-limit:][::-1]:
        rows.append({
            "task_id": task["id"],
            "message": task["goal"],
            "status": task["status"],
            "models": task["agents"],
            "current_round": task["current_round"],
            "rounds": task["max_rounds"],
            "created_at": task["created_at"],
        })
    return rows


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="AI Hive + MCP", version="0.3.0", lifespan=lifespan)
app.mount("/mcp", mcp.streamable_http_app())
app.mount("/", hive.app)
