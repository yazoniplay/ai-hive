"""AI Hive: OAuth-protected shared workspace for MCP-enabled AI clients."""
import base64
import hashlib
import html
import os
import secrets
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from contextlib import asynccontextmanager

PUBLIC_BASE = os.getenv("AI_HIVE_PUBLIC_URL", "https://ai-hive.onrender.com").rstrip("/")
MCP_URL = PUBLIC_BASE + "/mcp"
AUTH_ISSUER = PUBLIC_BASE
LOGIN_PASSWORD = os.getenv("AI_HIVE_LOGIN_PASSWORD", "")

rooms: dict[str, dict[str, Any]] = {}
oauth_clients: dict[str, dict[str, Any]] = {}
authorization_codes: dict[str, dict[str, Any]] = {}
access_tokens: dict[str, dict[str, Any]] = {}
refresh_tokens: dict[str, dict[str, Any]] = {}
browser_sessions: dict[str, float] = {}

mcp = FastMCP(
    "AI Hive",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["ai-hive.onrender.com", "ai-hive.onrender.com:*"],
        allowed_origins=["https://ai-hive.onrender.com"],
    ),
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
    """Create a shared room. Share the returned room_id only with trusted participants."""
    if not title.strip() or not goal.strip():
        raise ValueError("title and goal are required")
    room_id = uuid.uuid4().hex
    room = {
        "room_id": room_id, "title": title.strip()[:160], "goal": goal.strip()[:12000],
        "created_at": time.time(), "updated_at": time.time(), "messages": [],
    }
    rooms[room_id] = room
    return room


@mcp.tool()
def post_message(room_id: str, assistant: str, message: str, kind: str = "contribution") -> dict[str, Any]:
    """Post an answer, critique, question, or summary to a shared room."""
    room = _room(room_id)
    if not assistant.strip() or not message.strip():
        raise ValueError("assistant and message are required")
    if kind not in {"contribution", "critique", "question", "summary"}:
        raise ValueError("kind must be contribution, critique, question, or summary")
    entry = {
        "id": uuid.uuid4().hex[:12], "assistant": assistant.strip()[:80],
        "kind": kind, "message": message.strip()[:30000], "created_at": time.time(),
    }
    room["messages"].append(entry)
    room["updated_at"] = time.time()
    return {"room_id": room_id, "posted": entry, "message_count": len(room["messages"])}


@mcp.tool()
def read_room(room_id: str, after_id: str = "", limit: int = 30) -> dict[str, Any]:
    """Read the shared task and messages. Use after_id to read messages after a known message ID."""
    room = _room(room_id)
    messages = room["messages"]
    if after_id:
        indices = [i for i, item in enumerate(messages) if item["id"] == after_id]
        if not indices:
            raise ValueError("after_id was not found in this room")
        messages = messages[indices[0] + 1:]
    limit = max(1, min(int(limit), 100))
    return {
        "room_id": room["room_id"], "title": room["title"], "goal": room["goal"],
        "created_at": room["created_at"], "updated_at": room["updated_at"],
        "total_messages": len(room["messages"]), "messages": messages[-limit:],
    }


@mcp.tool()
def list_my_rooms(limit: int = 10) -> list[dict[str, Any]]:
    """List recent rooms in this server process; room IDs grant access to their contents."""
    limit = max(1, min(int(limit), 30))
    return [
        {"room_id": room["room_id"], "title": room["title"],
         "message_count": len(room["messages"]), "updated_at": room["updated_at"]}
        for room in sorted(rooms.values(), key=lambda x: x["updated_at"], reverse=True)[:limit]
    ]


@mcp.tool()
def get_connection_info() -> dict[str, Any]:
    """Explain how to connect an MCP client and the limits of API-key-free collaboration."""
    return {
        "mcp_endpoint": MCP_URL, "transport": "Streamable HTTP",
        "authentication": "OAuth 2.1 authorization code with PKCE",
        "model_api_keys_required": False, "provider_api_calls": False,
        "workflow": [
            "Connect this remote MCP server in each AI app that supports custom remote MCP servers.",
            "Create a room from one connected assistant and copy its room_id.",
            "Ask each connected assistant to read_room, work on the goal, then post_message.",
            "Ask assistants to read the other contributions and post critiques or a final summary.",
        ],
        "important_limits": [
            "This server does not log into ChatGPT, Claude, or Gemini on your behalf.",
            "Each provider must support custom remote MCP connections in the app/account you use.",
            "Room IDs grant access to room contents; share them only with trusted participants.",
            "Rooms are in-memory and disappear when Render restarts the service.",
        ],
    }


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="AI Hive MCP", version="0.6.0", lifespan=lifespan)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _valid_client_redirect(client_id: str, redirect_uri: str) -> bool:
    client = oauth_clients.get(client_id)
    return bool(client and redirect_uri in client["redirect_uris"])


def _parse_form(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def _oauth_error(error: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status_code, headers={"Cache-Control": "no-store"})


@app.middleware("http")
async def require_mcp_bearer_token(request: Request, call_next):
    if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
        auth_header = request.headers.get("authorization", "")
        token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
        record = access_tokens.get(token)
        if not record or record["expires_at"] <= time.time():
            metadata = PUBLIC_BASE + "/.well-known/oauth-protected-resource/mcp"
            return JSONResponse(
                {"error": "invalid_token", "error_description": "Sign in to AI Hive to use its tools."},
                status_code=401,
                headers={"WWW-Authenticate": f'Bearer resource_metadata="{metadata}"', "Cache-Control": "no-store"},
            )
    return await call_next(request)


@app.get("/")
def dashboard():
    return FileResponse("static/manual.html")


@app.get("/health")
def health():
    return {"ok": True, "service": "AI Hive MCP", "version": "0.6.0", "authentication": "oauth-pkce"}


@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource_metadata():
    return {
        "resource": MCP_URL,
        "authorization_servers": [AUTH_ISSUER],
        "scopes_supported": ["mcp:tools"],
        "bearer_methods_supported": ["header"],
    }


@app.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata():
    return {
        "issuer": AUTH_ISSUER,
        "authorization_endpoint": PUBLIC_BASE + "/oauth/authorize",
        "token_endpoint": PUBLIC_BASE + "/oauth/token",
        "registration_endpoint": PUBLIC_BASE + "/oauth/register",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["mcp:tools"],
    }


@app.post("/oauth/register")
async def oauth_register(request: Request):
    try:
        data = await request.json()
    except Exception:
        return _oauth_error("invalid_client_metadata")
    redirect_uris = data.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return _oauth_error("invalid_redirect_uri")
    valid_uris = []
    for uri in redirect_uris:
        if not isinstance(uri, str):
            return _oauth_error("invalid_redirect_uri")
        parsed = urlparse(uri)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            return _oauth_error("invalid_redirect_uri")
        valid_uris.append(uri)
    client_id = secrets.token_urlsafe(24)
    client_name = data.get("client_name", "MCP client")
    oauth_clients[client_id] = {
        "client_name": str(client_name)[:160],
        "redirect_uris": valid_uris,
        "token_endpoint_auth_method": "none",
    }
    return JSONResponse({
        "client_id": client_id,
        "client_name": str(client_name)[:160],
        "redirect_uris": valid_uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": "mcp:tools",
    }, status_code=201, headers={"Cache-Control": "no-store"})


@app.get("/oauth/authorize")
async def oauth_authorize(request: Request):
    q = request.query_params
    client_id = q.get("client_id", "")
    redirect_uri = q.get("redirect_uri", "")
    response_type = q.get("response_type", "")
    challenge = q.get("code_challenge", "")
    challenge_method = q.get("code_challenge_method", "")
    if not _valid_client_redirect(client_id, redirect_uri):
        return _oauth_error("invalid_client_or_redirect_uri")
    if response_type != "code" or not challenge or challenge_method != "S256":
        return _oauth_error("invalid_request_pkce_required")
    if q.get("resource") and q.get("resource") != MCP_URL:
        return _oauth_error("invalid_target")
    session = request.cookies.get("ai_hive_session", "")
    if not browser_sessions.get(session, 0) > time.time():
        return_to = PUBLIC_BASE + request.url.path + ("?" + request.url.query if request.url.query else "")
        return RedirectResponse("/login?" + urlencode({"return_to": return_to}), status_code=303)
    code = secrets.token_urlsafe(32)
    authorization_codes[code] = {
        "client_id": client_id, "redirect_uri": redirect_uri,
        "code_challenge": challenge, "scope": "mcp:tools",
        "resource": MCP_URL, "expires_at": time.time() + 300,
    }
    redirect_params = {"code": code}
    if q.get("state"):
        redirect_params["state"] = q.get("state")
    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(redirect_uri + separator + urlencode(redirect_params), status_code=302)


@app.get("/login", response_class=HTMLResponse)
def login_page(return_to: str = ""):
    if not return_to.startswith(PUBLIC_BASE + "/oauth/authorize?"):
        return HTMLResponse("Invalid sign-in request.", status_code=400)
    safe_return = html.escape(return_to, quote=True)
    return HTMLResponse(
        "<!doctype html><html lang='en'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Sign in · AI Hive</title><style>"
        "body{margin:0;background:#f5f5f2;color:#171717;font:16px system-ui;display:grid;min-height:100vh;place-items:center}"
        "main{box-sizing:border-box;width:min(420px,calc(100% - 32px));padding:30px;background:white;border:1px solid #ddd;border-radius:18px}"
        "h1{font-size:26px;letter-spacing:-.04em;margin:0 0 8px}p{color:#555;line-height:1.5}"
        "input{box-sizing:border-box;width:100%;padding:13px;border:1px solid #bbb;border-radius:9px;font:inherit;margin:8px 0 14px}"
        "button{width:100%;padding:13px;border:0;border-radius:9px;background:#171717;color:white;font:inherit;font-weight:600}"
        ".hint{font-size:13px}</style><main><h1>AI Hive</h1><p>Sign in to authorize Claude to use your AI Hive workspace.</p>"
        "<form method='post' action='/login'><input type='hidden' name='return_to' value='" + safe_return + "'>"
        "<label for='password'>Workspace password</label><input id='password' name='password' type='password' "
        "autocomplete='current-password' required autofocus><button type='submit'>Sign in and connect</button></form>"
        "<p class='hint'>This grants the connected AI client access to AI Hive workspace tools.</p></main></html>"
    )


@app.post("/login")
async def login_submit(request: Request):
    if not LOGIN_PASSWORD:
        return HTMLResponse("AI Hive sign-in is not configured. Contact the server owner.", status_code=503)
    form = await request.form()
    return_to = str(form.get("return_to", ""))
    password = str(form.get("password", ""))
    if not return_to.startswith(PUBLIC_BASE + "/oauth/authorize?"):
        return HTMLResponse("Invalid sign-in request.", status_code=400)
    if not secrets.compare_digest(password, LOGIN_PASSWORD):
        safe_return = html.escape(return_to, quote=True)
        return HTMLResponse(
            "<!doctype html><html><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<body style='font:16px system-ui;max-width:420px;margin:12vh auto;padding:20px'>"
            "<h1>Incorrect password</h1><p>Try again.</p><form method='post' action='/login'>"
            "<input type='hidden' name='return_to' value='" + safe_return + "'>"
            "<input name='password' type='password' required autofocus placeholder='Workspace password' "
            "style='box-sizing:border-box;width:100%;padding:12px;margin:12px 0'>"
            "<button style='padding:12px;width:100%'>Sign in</button></form></body></html>",
            status_code=401,
        )
    session = secrets.token_urlsafe(32)
    browser_sessions[session] = time.time() + 86400 * 30
    response = RedirectResponse(return_to, status_code=303)
    response.set_cookie(
        "ai_hive_session", session, max_age=86400 * 30, httponly=True,
        secure=True, samesite="lax", path="/",
    )
    return response


@app.post("/oauth/token")
async def oauth_token(request: Request):
    form = _parse_form(await request.body())
    grant_type = form.get("grant_type", "")
    if grant_type == "authorization_code":
        code = form.get("code", "")
        record = authorization_codes.pop(code, None)
        if not record or record["expires_at"] <= time.time():
            return _oauth_error("invalid_grant")
        client_id = form.get("client_id", "")
        if client_id != record["client_id"] or form.get("redirect_uri", "") != record["redirect_uri"]:
            return _oauth_error("invalid_grant")
        verifier = form.get("code_verifier", "")
        digest = _b64url(hashlib.sha256(verifier.encode()).digest())
        if not secrets.compare_digest(digest, record["code_challenge"]):
            return _oauth_error("invalid_grant")
        token = secrets.token_urlsafe(40)
        refresh = secrets.token_urlsafe(40)
        expires_in = 86400
        access_tokens[token] = {
            "client_id": client_id, "scope": record["scope"],
            "resource": record["resource"], "expires_at": time.time() + expires_in,
        }
        refresh_tokens[refresh] = {"client_id": client_id, "scope": record["scope"], "resource": record["resource"]}
        return JSONResponse({
            "access_token": token, "token_type": "Bearer", "expires_in": expires_in,
            "refresh_token": refresh, "scope": record["scope"],
        }, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
    if grant_type == "refresh_token":
        old_refresh = form.get("refresh_token", "")
        old = refresh_tokens.pop(old_refresh, None)
        if not old or old["client_id"] != form.get("client_id", ""):
            return _oauth_error("invalid_grant")
        token = secrets.token_urlsafe(40)
        refresh = secrets.token_urlsafe(40)
        expires_in = 86400
        access_tokens[token] = {
            "client_id": old["client_id"], "scope": old["scope"],
            "resource": old["resource"], "expires_at": time.time() + expires_in,
        }
        refresh_tokens[refresh] = old
        return JSONResponse({
            "access_token": token, "token_type": "Bearer", "expires_in": expires_in,
            "refresh_token": refresh, "scope": old["scope"],
        }, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
    return _oauth_error("unsupported_grant_type")


# The SDK app already serves its protocol endpoint at /mcp; mount at root to avoid /mcp/mcp.
app.mount("/", mcp.streamable_http_app())
