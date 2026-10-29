"""AI Hive remote MCP server with official provider API authentication.

Configure OPENAI_API_KEY, ANTHROPIC_API_KEY, and GEMINI_API_KEY as Render secrets.
These are API credentials, not consumer-account passwords or browser cookies.
"""
import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

PROVIDERS = {
    "chatgpt": {
        "name": "ChatGPT / OpenAI",
        "key_env": "OPENAI_API_KEY",
        "model_env": "OPENAI_MODEL",
        "default_model": "gpt-4.1-mini",
    },
    "claude": {
        "name": "Claude / Anthropic",
        "key_env": "ANTHROPIC_API_KEY",
        "model_env": "ANTHROPIC_MODEL",
        "default_model": "claude-sonnet-4-5",
    },
    "gemini": {
        "name": "Gemini / Google",
        "key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-2.5-flash",
    },
}
collaborations: dict[str, dict[str, Any]] = {}

mcp = FastMCP(
    "AI Hive",
    instructions=(
        "Send one prompt to ChatGPT/OpenAI, Claude/Anthropic, and Gemini/Google through "
        "their official APIs. Provider API keys must be configured on the AI Hive server. "
        "Consumer subscriptions alone do not authenticate third-party API calls."
    ),
)


def provider_status() -> dict[str, Any]:
    result = {}
    for key, info in PROVIDERS.items():
        configured = bool(os.getenv(info["key_env"]))
        result[key] = {
            "name": info["name"],
            "authenticated": configured,
            "model": os.getenv(info["model_env"], info["default_model"]),
            "key_setting": info["key_env"],
        }
    return result


async def call_provider(agent: str, prompt: str) -> str:
    info = PROVIDERS[agent]
    api_key = os.getenv(info["key_env"])
    if not api_key:
        raise RuntimeError(f"{info['key_env']} is not configured in the server environment.")
    model = os.getenv(info["model_env"], info["default_model"])
    timeout = httpx.Timeout(90.0, connect=15.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        if agent == "chatgpt":
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                },
            )
            if response.is_error:
                raise RuntimeError(f"OpenAI API HTTP {response.status_code}: {response.text[:700]}")
            data = response.json()
            return data["choices"][0]["message"]["content"]

        if agent == "claude":
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            if response.is_error:
                raise RuntimeError(f"Anthropic API HTTP {response.status_code}: {response.text[:700]}")
            data = response.json()
            return "\n".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")

        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
            },
        )
        if response.is_error:
            raise RuntimeError(f"Gemini API HTTP {response.status_code}: {response.text[:700]}")
        data = response.json()
        return "\n".join(
            part.get("text", "")
            for candidate in data.get("candidates", [])
            for part in candidate.get("content", {}).get("parts", [])
            if part.get("text")
        )


def make_round_prompt(message: str, agent: str, round_number: int, prior: dict[str, str]) -> str:
    if round_number == 1:
        return (
            "You are one of three independent AI collaborators. Answer the user's request accurately and directly. "
            "State assumptions and uncertainty, and do not claim to have performed actions you did not perform.\n\n"
            f"USER REQUEST:\n{message}"
        )
    others = "\n\n".join(
        f"--- {PROVIDERS[name]['name']} ---\n{text}"
        for name, text in prior.items() if name != agent
    )
    own = prior.get(agent, "No prior answer recorded.")
    return (
        "Review your previous answer and the other models' answers. Correct errors, identify contradictions, "
        "and improve the answer rather than agreeing automatically.\n\n"
        f"USER REQUEST:\n{message}\n\nYOUR PREVIOUS ANSWER:\n{own}\n\n"
        f"OTHER MODELS' ANSWERS:\n{others}\n\n"
        "Return your improved answer and briefly mention any important remaining uncertainty."
    )


@mcp.tool()
def list_models() -> dict[str, Any]:
    """Show provider API authentication status and configured model names. Never returns API keys."""
    return {
        "models": provider_status(),
        "ready_count": sum(1 for x in provider_status().values() if x["authenticated"]),
        "required_setup": "Add provider API keys as Render environment secrets; never put keys in chat or GitHub.",
    }


@mcp.tool()
async def start_collaboration(
    message: str,
    agents: list[str] | None = None,
    rounds: int = 1,
) -> dict[str, Any]:
    """Send one prompt to selected providers and return their responses in one result.

    Args:
        message: The request to send to all selected AI models.
        agents: Any combination of chatgpt, claude, gemini. Defaults to all three.
        rounds: 1 for independent answers, 2-5 for cross-review and refinement.
    """
    if not message.strip():
        raise ValueError("message must not be empty")
    chosen = list(dict.fromkeys(a.lower() for a in (agents or list(PROVIDERS))))
    if not chosen or any(a not in PROVIDERS for a in chosen):
        raise ValueError("agents must be chosen from chatgpt, claude, gemini")
    if not 1 <= rounds <= 5:
        raise ValueError("rounds must be between 1 and 5")

    missing = [PROVIDERS[a]["key_env"] for a in chosen if not os.getenv(PROVIDERS[a]["key_env"])]
    if missing:
        raise ValueError("Missing provider authentication: " + ", ".join(missing) +
                         ". Add these as environment secrets on the AI Hive Render service.")

    task_id = str(uuid.uuid4())
    task: dict[str, Any] = {
        "task_id": task_id, "message": message, "status": "running", "models": chosen,
        "rounds": rounds, "current_round": 0, "round_results": [], "created_at": time.time(),
    }
    collaborations[task_id] = task

    try:
        prior: dict[str, str] = {}
        for round_number in range(1, rounds + 1):
            task["current_round"] = round_number
            prompts = {a: make_round_prompt(message, a, round_number, prior) for a in chosen}
            results = await asyncio.gather(
                *(call_provider(a, prompts[a]) for a in chosen),
                return_exceptions=True,
            )
            current: dict[str, str] = {}
            errors: dict[str, str] = {}
            for agent, result in zip(chosen, results):
                if isinstance(result, Exception):
                    errors[agent] = str(result)
                else:
                    current[agent] = result
            task["round_results"].append({
                "round": round_number,
                "responses": current,
                "errors": errors,
                "completed_at": time.time(),
            })
            if current:
                prior = {**prior, **current}
            if errors and not current:
                task["status"] = "failed"
                break
        if task["status"] != "failed":
            task["status"] = "completed" if not task["round_results"][-1]["errors"] else "partial"
        task["completed_at"] = time.time()
    except Exception as exc:
        task["status"] = "failed"
        task["error"] = str(exc)

    return task


@mcp.tool()
def get_collaboration(task_id: str) -> dict[str, Any]:
    """Retrieve results for a collaboration started in the current server process."""
    task = collaborations.get(task_id)
    if not task:
        raise ValueError("Collaboration not found. It may have expired after a server restart.")
    return task


@mcp.tool()
def list_recent_collaborations(limit: int = 10) -> list[dict[str, Any]]:
    """List recent collaborations, newest first."""
    limit = max(1, min(int(limit), 30))
    return [
        {
            "task_id": task["task_id"],
            "message": task["message"][:300],
            "status": task["status"],
            "models": task["models"],
            "current_round": task["current_round"],
            "rounds": task["rounds"],
            "created_at": task["created_at"],
        }
        for task in list(collaborations.values())[-limit:][::-1]
    ]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="AI Hive MCP", version="0.4.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True, "service": "AI Hive MCP", "version": "0.4.0", "providers": provider_status()}


app.mount("/mcp", mcp.streamable_http_app())
