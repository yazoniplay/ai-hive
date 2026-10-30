"""Regression tests for role routing, agent presence, and SQLite migrations."""
import os
import sqlite3
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TEST_DIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = ""
os.environ["AI_HIVE_DB_PATH"] = os.path.join(_TEST_DIR.name, "ai_hive_test.sqlite3")

import storage


class RoleRoutingTests(unittest.TestCase):
    def setUp(self):
        with storage.connection() as (conn, is_postgres):
            conn.execute("DELETE FROM hive_work_items")
            conn.execute("DELETE FROM hive_agents")

    def test_role_leader_cannot_claim_another_roles_task(self):
        task = storage.create_work_item("room", "Fix the parser", "Implement parser fix", 10, role="coding")
        self.assertIsNone(storage.claim_work_item("room", "marketing-agent", 11, role="marketing"))
        claimed = storage.claim_work_item("room", "coding-agent", 12, role="coding")
        self.assertEqual(claimed["id"], task["id"])
        self.assertEqual(claimed["role"], "coding")
        self.assertEqual(claimed["assigned_to"], "coding-agent")

    def test_role_leader_can_claim_generic_work(self):
        task = storage.create_work_item("room", "Review roadmap", "Review the roadmap", 10, role="any")
        claimed = storage.claim_work_item("room", "research-agent", 11, role="research")
        self.assertEqual(claimed["id"], task["id"])
        self.assertEqual(claimed["role"], "any")

    def test_generic_agent_only_claims_generic_work(self):
        storage.create_work_item("room", "Marketing plan", "Plan campaign", 10, role="marketing")
        self.assertIsNone(storage.claim_work_item("room", "generic-agent", 11, role="any"))

    def test_heartbeat_becomes_stale_without_fabricating_offline_telemetry(self):
        storage.heartbeat_agent("room", "research-agent", "research", "working",
                                "Investigating", "Checking source evidence", 1000)
        fresh = storage.list_agents("room", now=1100, stale_after_seconds=900)
        stale = storage.list_agents("room", now=2000, stale_after_seconds=900)
        self.assertEqual(fresh[0]["effective_status"], "working")
        self.assertEqual(stale[0]["effective_status"], "stale")
        self.assertEqual(stale[0]["seconds_since_seen"], 1000)

    def test_invalid_role_is_rejected(self):
        with self.assertRaises(ValueError):
            storage.create_work_item("room", "Bad task", "Invalid role", 1, role="chief")

    def test_legacy_sqlite_schema_migrates_existing_tasks_to_any_role(self):
        legacy_path = os.path.join(_TEST_DIR.name, "legacy.sqlite3")
        with sqlite3.connect(legacy_path) as conn:
            conn.execute("""CREATE TABLE hive_work_items (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
                description TEXT NOT NULL, status TEXT NOT NULL, assigned_to TEXT NOT NULL,
                result TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL
            )""")
            conn.execute("""INSERT INTO hive_work_items
                (id, project_id, title, description, status, assigned_to, result, created_at, updated_at)
                VALUES ('legacy-1', 'room', 'Old task', 'Before roles', 'queued', '', '', 1, 1)""")
        old_path = storage.SQLITE_PATH
        try:
            storage.SQLITE_PATH = legacy_path
            storage.init_db()
            tasks = storage.list_work_items("room")
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["role"], "any")
        finally:
            storage.SQLITE_PATH = old_path


if __name__ == "__main__":
    unittest.main()
