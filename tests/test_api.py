"""Integration tests for CodePilot FastAPI endpoints."""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.api.main import TASKS_DB, app
from app.core.models import CodingTask, TaskStatus

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_get_nonexistent_task():
    response = client.get("/tasks/nonexistent-uuid-1234")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_create_task_and_retrieve(tmp_path: Path):
    repo = tmp_path / "valid_project"
    repo.mkdir()
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )

    payload = {
        "description": "Verify existing calculator tests pass",
        "repo_path": str(repo),
        "test_command": "pytest",
        "max_attempts": 2,
    }

    create_res = client.post("/tasks", json=payload)
    assert create_res.status_code == 201
    task_data = create_res.json()
    assert task_data["status"] == "success"
    task_id = task_data["task_id"]

    # Verify retrieval
    get_res = client.get(f"/tasks/{task_id}")
    assert get_res.status_code == 200
    assert get_res.json()["task_id"] == task_id


def test_approval_workflow():
    # Insert dummy successful task into DB
    task = CodingTask(
        description="Sample approved fix",
        repo_path=".",
        status=TaskStatus.SUCCESS,
    )
    TASKS_DB[task.task_id] = task

    approval_payload = {
        "approved": True,
        "reviewer": "Senior-Engineer-Alice",
        "comments": "Patch looks clean and all unit tests passed.",
    }

    res = client.post(f"/tasks/{task.task_id}/approve", json=approval_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["approved"] is True
    assert "Alice" in data["message"]


def test_approval_rejected_on_unpassed_task():
    task = CodingTask(
        description="Failing fix",
        repo_path=".",
        status=TaskStatus.FAILED,
    )
    TASKS_DB[task.task_id] = task

    approval_payload = {
        "approved": True,
        "reviewer": "Alice",
    }

    res = client.post(f"/tasks/{task.task_id}/approve", json=approval_payload)
    assert res.status_code == 400
    assert "verification tests must pass first" in res.json()["detail"].lower()
