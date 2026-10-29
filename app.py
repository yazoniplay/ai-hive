import asyncio, time, uuid
from collections import deque
from typing import Any
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="AI Hive", version="0.1.0")
started = time.time()
events = deque(maxlen=500)
tasks = {}
agents = {k: {"name": n, "last_seen": None} for k, n in {"chatgpt":"ChatGPT","claude":"Claude","gemini":"Gemini"}.items()}
sockets = set()

def emit(kind, message, **extra):
    event = {"id":str(uuid.uuid4()),"time":time.time(),"kind":kind,"message":message,**extra}
    events.append(event)
    return event

async def broadcast(event):
    dead=[]
    for ws in list(sockets):
        try: await ws.send_json(event)
        except Exception: dead.append(ws)
    for ws in dead: sockets.discard(ws)

class RegisterBody(BaseModel):
    agent: str
class MessageBody(BaseModel):
    agent: str
    text: str = Field(min_length=1, max_length=30000)
    task_id: str | None = None
    kind: str = "message"
class StartBody(BaseModel):
    goal: str = Field(min_length=1, max_length=10000)
    rounds: int = Field(default=2, ge=1, le=5)
    agents: list[str] = Field(default_factory=lambda:["chatgpt","claude","gemini"])

@app.get("/health")
def health(): return {"ok":True,"uptime_seconds":round(time.time()-started,1)}

@app.get("/", response_class=HTMLResponse)
def dashboard():
    try:
        with open("static/index.html",encoding="utf-8") as f: return f.read()
    except FileNotFoundError: return HTMLResponse("<h1>AI Hive dashboard missing</h1>",status_code=500)

def snapshot():
    now=time.time()
    return {"agents":{k:{**v,"online":bool(v["last_seen"] and now-v["last_seen"]<90)} for k,v in agents.items()},
            "events":list(events)[-100:],"tasks":list(tasks.values())[-30:],
            "uptime_seconds":round(now-started,1),
            "warning":"Prototype state is in memory and resets when the free service restarts."}

@app.get("/api/state")
def state(): return snapshot()

@app.post("/api/register")
async def register(body:RegisterBody):
    key=body.agent.lower()
    if key not in agents: raise HTTPException(400,"agent must be chatgpt, claude, or gemini")
    agents[key]["last_seen"]=time.time()
    e=emit("status",agents[key]["name"]+" connector checked in",agent=key)
    await broadcast(e)
    return {"ok":True}

@app.post("/api/message")
async def receive(body:MessageBody):
    key=body.agent.lower()
    if key not in agents: raise HTTPException(400,"unknown agent")
    agents[key]["last_seen"]=time.time()
    e=emit(body.kind,body.text,agent=key,task_id=body.task_id)
    if body.task_id in tasks:
        tasks[body.task_id]["responses"].append({"agent":key,"text":body.text,"time":e["time"]})
        tasks[body.task_id]["updated_at"]=e["time"]
    await broadcast(e)
    return {"ok":True,"event_id":e["id"]}

@app.post("/api/tasks")
async def create_task(body:StartBody):
    chosen=list(dict.fromkeys(a.lower() for a in body.agents))
    if not chosen or any(a not in agents for a in chosen): raise HTTPException(400,"Select valid agents")
    now=time.time(); tid=str(uuid.uuid4())
    task={"id":tid,"goal":body.goal,"rounds":body.rounds,"agents":chosen,"status":"queued","created_at":now,"updated_at":now,"responses":[]}
    tasks[tid]=task
    await broadcast(emit("task","New hive goal: "+body.goal,task_id=tid,agents=chosen))
    return {"ok":True,"task":task}

@app.get("/api/next/{agent}")
def next_task(agent:str,after:float=0):
    key=agent.lower()
    if key not in agents: raise HTTPException(400,"unknown agent")
    pending=[{"id":t["id"],"goal":t["goal"],"rounds":t["rounds"],"created_at":t["created_at"]} for t in tasks.values() if key in t["agents"] and t["created_at"]>after]
    return {"tasks":pending[-10:],"server_time":time.time()}

@app.websocket("/ws")
async def websocket_endpoint(ws:WebSocket):
    await ws.accept(); sockets.add(ws)
    await ws.send_json({"kind":"snapshot",**snapshot()})
    try:
        while True: await ws.receive_text()
    except (WebSocketDisconnect,Exception): sockets.discard(ws)
