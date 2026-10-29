import asyncio
import time
import uuid
from collections import deque
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="AI Hive", version="0.2.0")
started_at = time.time()
events: deque[dict[str, Any]] = deque(maxlen=1000)
tasks: dict[str, dict[str, Any]] = {}
jobs: dict[str, dict[str, Any]] = {}
agents = {k: {"name": n, "last_seen": None} for k, n in {
    "chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini"
}.items()}
sockets: set[WebSocket] = set()
AGENT_NAMES = {k: v["name"] for k, v in agents.items()}


def emit(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    event = {"id": str(uuid.uuid4()), "time": time.time(), "kind": kind, "message": message, **extra}
    events.append(event)
    return event


async def broadcast(event: dict[str, Any]) -> None:
    dead = []
    for ws in list(sockets):
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        sockets.discard(ws)


async def publish(kind: str, message: str, **extra: Any) -> None:
    await broadcast(emit(kind, message, **extra))


def make_prompt(task: dict[str, Any], agent: str, round_number: int) -> str:
    base = (
        "You are one of three independent AI collaborators in AI Hive.\n"
        "Be accurate, direct, and constructive. Never claim to have run code or verified facts unless you actually did.\n\n"
        f"SHARED GOAL\n{task['goal']}\n\n"
    )
    if round_number == 1:
        return base + (
            "ROUND 1 — INDEPENDENT PROPOSAL\n"
            "Solve the goal independently before seeing other models' answers. Include your proposed solution, reasoning, "
            "important assumptions, risks, and concrete next steps. Keep the answer useful and specific."
        )
    previous = task["rounds_data"][round_number - 2]
    others = [f"--- {AGENT_NAMES[a['agent']]} (round {round_number - 1}) ---\n{a['text']}"
              for a in previous if a["agent"] != agent and not a.get("error")]
    own = [a for a in previous if a["agent"] == agent and not a.get("error")]
    context = "\n\n".join(others) if others else "No other model responses were received in the previous round."
    own_text = own[0]["text"] if own else "Your previous response was not recorded."
    return base + (
        f"ROUND {round_number} — CROSS-REVIEW AND IMPROVEMENT\n"
        "Review the other models' previous-round responses below. Identify what is correct, what is weak or missing, "
        "and any contradictions. Do not agree just to be agreeable. Then provide your improved, best-current answer to the shared goal.\n\n"
        f"YOUR PREVIOUS ANSWER\n{own_text}\n\n"
        f"OTHER MODELS' RESPONSES\n{context}\n\n"
        "Structure your answer as: (1) critique, (2) changes made, (3) improved final proposal, (4) remaining uncertainty."
    )


def create_round_jobs(task: dict[str, Any], round_number: int) -> None:
    task["current_round"] = round_number
    task["status"] = "running"
    task["round_started_at"] = time.time()
    task["rounds_data"].append([])
    for agent in task["agents"]:
        job_id = str(uuid.uuid4())
        jobs[job_id] = {
            "id": job_id, "task_id": task["id"], "agent": agent, "round": round_number,
            "prompt": make_prompt(task, agent, round_number), "status": "queued",
            "created_at": time.time(), "claimed_at": None, "attempts": 0,
        }


async def finish_round_if_ready(task: dict[str, Any]) -> None:
    responses = task["rounds_data"][task["current_round"] - 1]
    finished_agents = {r["agent"] for r in responses}
    if not all(a in finished_agents for a in task["agents"]):
        return
    if task["current_round"] < task["max_rounds"]:
        await publish("round", f"Round {task['current_round']} complete. Starting cross-review round {task['current_round'] + 1}.",
                      task_id=task["id"], round=task["current_round"])
        create_round_jobs(task, task["current_round"] + 1)
    else:
        task["status"] = "completed"
        task["completed_at"] = time.time()
        final = task["rounds_data"][-1] if task["rounds_data"] else []
        task["final_responses"] = final
        await publish("completed", f"Collaboration completed: {task['goal']}", task_id=task["id"],
                      round=task["current_round"], final_responses=final)


class RegisterBody(BaseModel):
    agent: str


class MessageBody(BaseModel):
    agent: str
    text: str = Field(min_length=1, max_length=30000)
    task_id: str | None = None
    kind: str = "message"


class StartBody(BaseModel):
    goal: str = Field(min_length=1, max_length=10000)
    rounds: int = Field(default=3, ge=1, le=5)
    agents: list[str] = Field(default_factory=lambda: ["chatgpt", "claude", "gemini"])


class JobResultBody(BaseModel):
    agent: str
    text: str = Field(min_length=1, max_length=30000)
    error: bool = False


@app.get("/health")
def health():
    return {"ok": True, "version": "0.2.0", "uptime_seconds": round(time.time() - started_at, 1)}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    try:
        with open("static/index.html", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>AI Hive dashboard missing</h1>", status_code=500)


def state_snapshot():
    now = time.time()
    visible_agents = {
        key: {**value, "online": bool(value["last_seen"] and now - value["last_seen"] < 100)}
        for key, value in agents.items()
    }
    return {
        "version": "0.2.0", "agents": visible_agents, "events": list(events)[-150:],
        "tasks": list(tasks.values())[-30:], "uptime_seconds": round(now - started_at, 1),
        "warning": "Free-host restarts clear in-memory tasks and history. Keep the browser connector running during a collaboration."
    }


@app.get("/api/state")
def state():
    return state_snapshot()


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    return task


@app.post("/api/register")
async def register(body: RegisterBody):
    key = body.agent.lower()
    if key not in agents:
        raise HTTPException(400, "agent must be chatgpt, claude, or gemini")
    agents[key]["last_seen"] = time.time()
    await publish("status", f"{agents[key]['name']} connector checked in", agent=key)
    return {"ok": True}


@app.post("/api/message")
async def receive_message(body: MessageBody):
    key = body.agent.lower()
    if key not in agents:
        raise HTTPException(400, "unknown agent")
    agents[key]["last_seen"] = time.time()
    await publish(body.kind, body.text, agent=key, task_id=body.task_id)
    return {"ok": True}


@app.post("/api/tasks")
async def create_task(body: StartBody):
    chosen = list(dict.fromkeys(a.lower() for a in body.agents))
    if not chosen or any(a not in agents for a in chosen):
        raise HTTPException(400, "Select one or more valid agents")
    if len(chosen) < 2 and body.rounds > 1:
        # A single model can still self-review, but it cannot cross-review another model.
        pass
    now = time.time()
    task_id = str(uuid.uuid4())
    task = {
        "id": task_id, "goal": body.goal.strip(), "agents": chosen, "max_rounds": body.rounds,
        "current_round": 0, "status": "queued", "created_at": now, "updated_at": now,
        "rounds_data": [], "final_responses": []
    }
    tasks[task_id] = task
    create_round_jobs(task, 1)
    await publish("task", f"Collaboration queued: {task['goal']}", task_id=task_id, agents=chosen,
                  rounds=body.rounds)
    await publish("round", "Round 1 started: independent proposals", task_id=task_id, round=1)
    return {"ok": True, "task": task}


@app.get("/api/jobs/{agent}")
def get_jobs(agent: str):
    key = agent.lower()
    if key not in agents:
        raise HTTPException(400, "unknown agent")
    now = time.time()
    pending = []
    for job in jobs.values():
        if job["agent"] != key or job["status"] == "completed":
            continue
        if job["status"] == "claimed" and now - (job["claimed_at"] or 0) < 180:
            continue
        job["status"] = "claimed"
        job["claimed_at"] = now
        job["attempts"] += 1
        pending.append({k: job[k] for k in ("id", "task_id", "agent", "round", "prompt", "created_at", "attempts")})
    agents[key]["last_seen"] = now
    return {"jobs": pending[:5], "server_time": now}


@app.post("/api/jobs/{job_id}/result")
async def submit_job_result(job_id: str, body: JobResultBody):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if body.agent.lower() != job["agent"]:
        raise HTTPException(403, "job belongs to a different agent")
    if job["status"] == "completed":
        return {"ok": True, "duplicate": True}
    task = tasks.get(job["task_id"])
    if not task:
        raise HTTPException(404, "task no longer exists")
    job["status"] = "completed"
    job["completed_at"] = time.time()
    text = body.text.strip()
    response = {"agent": job["agent"], "name": AGENT_NAMES[job["agent"]], "text": text,
                "round": job["round"], "time": time.time(), "error": body.error}
    while len(task["rounds_data"]) < job["round"]:
        task["rounds_data"].append([])
    current = task["rounds_data"][job["round"] - 1]
    if not any(r["agent"] == job["agent"] for r in current):
        current.append(response)
    task["updated_at"] = time.time()
    await publish("response", f"{AGENT_NAMES[job['agent']]} finished round {job['round']}" +
                  (" with an error" if body.error else ""), agent=job["agent"], task_id=task["id"],
                  round=job["round"], response=text, error=body.error)
    await finish_round_if_ready(task)
    return {"ok": True, "task_status": task["status"], "current_round": task["current_round"]}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    sockets.add(ws)
    await ws.send_json({"kind": "snapshot", **state_snapshot()})
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        sockets.discard(ws)
