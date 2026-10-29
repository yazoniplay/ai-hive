import importlib.util
from pathlib import Path
import pytest

SPEC = importlib.util.spec_from_file_location("agent_worker", Path(__file__).resolve().parents[1] / "agent_worker.py")
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)

def test_worker_uses_pseudonymous_alias():
    assert worker.ALIAS.startswith("Agent-")
    assert "Claude" not in worker.ALIAS
    assert "OpenAI" not in worker.ALIAS

@pytest.mark.parametrize("path", ["../secrets.txt", ".env", ".github/workflows/test.yml", "credentials.json", "private/id_rsa", "binary.exe"])
def test_worker_rejects_protected_paths(path):
    with pytest.raises(ValueError): worker._safe_path(path)

@pytest.mark.parametrize("path", ["README.md", "mcp_server.py", "tests/test_workflow.py", "extension/connector.js"])
def test_worker_allows_source_and_docs(path):
    assert worker._safe_path(path) == path

def test_worker_handles_blank_or_invalid_numeric_configuration(monkeypatch):
    monkeypatch.setenv("AI_HIVE_MAX_TASKS_PER_RUN", "")
    assert worker._bounded_int("AI_HIVE_MAX_TASKS_PER_RUN", 2, 1, 5) == 2
    monkeypatch.setenv("AI_HIVE_MAX_TASKS_PER_RUN", "garbage")
    assert worker._bounded_int("AI_HIVE_MAX_TASKS_PER_RUN", 2, 1, 5) == 2
    monkeypatch.setenv("AI_HIVE_MAX_TASKS_PER_RUN", "99")
    assert worker._bounded_int("AI_HIVE_MAX_TASKS_PER_RUN", 2, 1, 5) == 5
