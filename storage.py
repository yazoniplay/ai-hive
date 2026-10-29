"""Durable storage for AI Hive rooms and queued work items.

PostgreSQL (DATABASE_URL) is required for durability across Render deploys/restarts.
SQLite is a local/development fallback and may be ephemeral on hosted platforms.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_PATH = os.getenv("AI_HIVE_DB_PATH", "ai_hive.sqlite3")


def database_mode() -> str:
    return "postgresql" if DATABASE_URL.startswith(("postgres://", "postgresql://")) else "sqlite"


@contextmanager
def connection():
    if database_mode() == "postgresql":
        import psycopg
        from psycopg.rows import dict_row

        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        conn = psycopg.connect(url, row_factory=dict_row, connect_timeout=8)
        try:
            yield conn, True
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(SQLITE_PATH, timeout=8)
        conn.row_factory = sqlite3.Row
        try:
            yield conn, False
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _execute(conn, is_postgres: bool, sql: str, params=()):
    return conn.execute(sql.replace("?", "%s") if is_postgres else sql, params)


def init_db() -> None:
    with connection() as (conn, is_postgres):
        _execute(conn, is_postgres, """
            CREATE TABLE IF NOT EXISTS hive_rooms (
                room_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL
            )
        """)
        _execute(conn, is_postgres, """
            CREATE TABLE IF NOT EXISTS hive_work_items (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                assigned_to TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL
            )
        """)


def save_room(room: dict[str, Any]) -> None:
    payload = json.dumps(room, ensure_ascii=False, separators=(",", ":"))
    with connection() as (conn, is_postgres):
        _execute(conn, is_postgres, """
            INSERT INTO hive_rooms(room_id, payload, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(room_id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at
        """, (room["room_id"], payload, float(room["updated_at"])))


def get_room(room_id: str) -> dict[str, Any] | None:
    with connection() as (conn, is_postgres):
        row = _execute(conn, is_postgres,
                       "SELECT payload FROM hive_rooms WHERE room_id = ?", (room_id,)).fetchone()
    if not row:
        return None
    return json.loads(row["payload"] if is_postgres else row["payload"])


def list_rooms(limit: int = 10) -> list[dict[str, Any]]:
    with connection() as (conn, is_postgres):
        rows = _execute(conn, is_postgres,
                        "SELECT payload FROM hive_rooms ORDER BY updated_at DESC LIMIT ?",
                        (max(1, min(int(limit), 30)),)).fetchall()
    return [json.loads(row["payload"] if is_postgres else row["payload"]) for row in rows]


def create_work_item(project_id: str, title: str, description: str, now: float) -> dict[str, Any]:
    import uuid
    item = {
        "id": uuid.uuid4().hex,
        "project_id": project_id,
        "title": title.strip()[:160],
        "description": description.strip()[:12000],
        "status": "queued",
        "assigned_to": "",
        "result": "",
        "created_at": now,
        "updated_at": now,
    }
    with connection() as (conn, is_postgres):
        _execute(conn, is_postgres, """
            INSERT INTO hive_work_items
            (id, project_id, title, description, status, assigned_to, result, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (item["id"], item["project_id"], item["title"], item["description"],
              item["status"], item["assigned_to"], item["result"], now, now))
    return item


def _work_item(row, is_postgres: bool) -> dict[str, Any]:
    keys = ("id", "project_id", "title", "description", "status", "assigned_to",
            "result", "created_at", "updated_at")
    return {key: (row[key] if is_postgres else row[index]) for index, key in enumerate(keys)}


def list_work_items(project_id: str) -> list[dict[str, Any]]:
    with connection() as (conn, is_postgres):
        rows = _execute(conn, is_postgres, """
            SELECT id, project_id, title, description, status, assigned_to, result, created_at, updated_at
            FROM hive_work_items WHERE project_id = ? ORDER BY created_at ASC
        """, (project_id,)).fetchall()
    return [_work_item(row, is_postgres) for row in rows]


def claim_work_item(project_id: str, assistant: str, now: float) -> dict[str, Any] | None:
    assistant = assistant.strip()[:80]
    if not assistant:
        raise ValueError("assistant alias is required")
    with connection() as (conn, is_postgres):
        if not is_postgres:
            conn.execute("BEGIN IMMEDIATE")
        if is_postgres:
            row = _execute(conn, True, """
                SELECT id, project_id, title, description, status, assigned_to, result, created_at, updated_at
                FROM hive_work_items WHERE project_id = ? AND status = 'queued'
                ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED
            """, (project_id,)).fetchone()
        else:
            row = _execute(conn, False, """
                SELECT id, project_id, title, description, status, assigned_to, result, created_at, updated_at
                FROM hive_work_items WHERE project_id = ? AND status = 'queued'
                ORDER BY created_at ASC LIMIT 1
            """, (project_id,)).fetchone()
        if not row:
            return None
        item = _work_item(row, is_postgres)
        _execute(conn, is_postgres, """
            UPDATE hive_work_items SET status = 'in_progress', assigned_to = ?, updated_at = ?
            WHERE id = ? AND status = 'queued'
        """, (assistant, now, item["id"]))
        item.update({"status": "in_progress", "assigned_to": assistant, "updated_at": now})
        return item


def update_work_item(project_id: str, item_id: str, status: str, assistant: str,
                     result: str, now: float) -> dict[str, Any]:
    allowed = {"queued", "in_progress", "blocked", "completed", "failed"}
    if status not in allowed:
        raise ValueError("status must be queued, in_progress, blocked, completed, or failed")
    with connection() as (conn, is_postgres):
        row = _execute(conn, is_postgres, """
            SELECT id, project_id, title, description, status, assigned_to, result, created_at, updated_at
            FROM hive_work_items WHERE id = ? AND project_id = ?
        """, (item_id, project_id)).fetchone()
        if not row:
            raise ValueError("Work item not found in this project")
        item = _work_item(row, is_postgres)
        if not item["assigned_to"] or assistant.strip() != item["assigned_to"]:
            raise ValueError("Claim this work item first; only its assigned assistant alias may update it")
        _execute(conn, is_postgres, """
            UPDATE hive_work_items SET status = ?, result = ?, updated_at = ?
            WHERE id = ? AND project_id = ?
        """, (status, result.strip()[:30000], now, item_id, project_id))
        item.update({"status": status, "result": result.strip()[:30000], "updated_at": now})
        return item


init_db()
