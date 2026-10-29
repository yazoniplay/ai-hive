from fastapi.testclient import TestClient
import app as hive


client = TestClient(hive.app)


def reset_state():
    hive.events.clear()
    hive.tasks.clear()
    hive.jobs.clear()
    for value in hive.agents.values():
        value["last_seen"] = None


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_task_runs_independent_and_cross_review_rounds():
    reset_state()
    created = client.post("/api/tasks", json={
        "goal": "Design a safe, testable sample project",
        "rounds": 2,
        "agents": ["chatgpt", "claude"],
    })
    assert created.status_code == 200
    task = created.json()["task"]
    task_id = task["id"]
    assert task["status"] == "running"
    assert task["current_round"] == 1

    first_jobs = {}
    for agent in ("chatgpt", "claude"):
        response = client.get(f"/api/jobs/{agent}")
        assert response.status_code == 200
        first_jobs[agent] = response.json()["jobs"][0]
        assert first_jobs[agent]["round"] == 1

    result = client.post(f"/api/jobs/{first_jobs['chatgpt']['id']}/result", json={
        "agent": "chatgpt", "text": "ChatGPT proposal: add tests and validate inputs."
    })
    assert result.status_code == 200
    assert result.json()["task_status"] == "running"

    result = client.post(f"/api/jobs/{first_jobs['claude']['id']}/result", json={
        "agent": "claude", "text": "Claude proposal: add clear error handling."
    })
    assert result.status_code == 200
    assert result.json()["current_round"] == 2

    second_jobs = {}
    for agent in ("chatgpt", "claude"):
        response = client.get(f"/api/jobs/{agent}")
        assert response.status_code == 200
        second_jobs[agent] = response.json()["jobs"][0]
        assert second_jobs[agent]["round"] == 2
        assert "cross-review" in second_jobs[agent]["prompt"].lower()
        assert "ChatGPT proposal" in second_jobs[agent]["prompt"] or "Claude proposal" in second_jobs[agent]["prompt"]

    client.post(f"/api/jobs/{second_jobs['chatgpt']['id']}/result", json={
        "agent": "chatgpt", "text": "Improved proposal with tests and error handling."
    })
    final = client.post(f"/api/jobs/{second_jobs['claude']['id']}/result", json={
        "agent": "claude", "text": "Improved proposal with validation and test coverage."
    })
    assert final.status_code == 200
    assert final.json()["task_status"] == "completed"

    saved = client.get(f"/api/tasks/{task_id}").json()
    assert len(saved["rounds_data"]) == 2
    assert saved["status"] == "completed"
    assert len(saved["final_responses"]) == 2
    assert all(response["round"] == 2 for response in saved["final_responses"])


def test_agent_poll_only_claims_one_job_at_a_time():
    reset_state()
    for goal in ("First goal", "Second goal"):
        client.post("/api/tasks", json={"goal": goal, "rounds": 1, "agents": ["chatgpt", "claude"]})
    first = client.get("/api/jobs/chatgpt").json()["jobs"]
    assert len(first) == 1
    second_poll = client.get("/api/jobs/chatgpt").json()["jobs"]
    assert second_poll == []
