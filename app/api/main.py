"""FastAPI server exposing CodePilot autonomous coding endpoints, task lifecycle, and human review."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Security, status
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.agent.controller import CodePilotAgent
from app.api.schemas import (
    ApprovalRequest,
    ApprovalResponse,
    CreateTaskRequest,
    ExecutionSummary,
    HealthResponse,
    PatchSummary,
    TaskResponse,
)
from app.core.config import settings
from app.core.models import CodingTask, ExecutionResult, PatchResult, TaskStatus
from app.repository.worktree import IsolatedWorkspace
from app.sandbox.runner import SandboxRunner, SandboxSecurityException

app = FastAPI(
    title="CodePilot API",
    version=__version__,
    description="Autonomous Coding Agent with Secure Sandbox and Bounded Self-Correction",
)

# Static files for Apple HIG frontend
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", tags=["UI"], include_in_schema=False)
def serve_ui():
    """Serves Apple HIG frontend interface."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "CodePilot API active. Static UI not built."}


# Security: API Key verification
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> Optional[str]:
    """Validates X-API-Key header against configured settings.API_KEY."""
    if settings.API_KEY:
        if not api_key or api_key != settings.API_KEY:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing X-API-Key authentication header",
            )
    return api_key


# Database lock and in-memory caches
DB_LOCK = threading.RLock()
TASKS_DB: Dict[str, CodingTask] = {}
APPROVALS_DB: Dict[str, Dict] = {}
ACTIVE_WORKSPACES: Dict[str, IsolatedWorkspace] = {}


def _init_sqlite_db() -> None:
    """Initializes SQLite schema for task persistence."""
    with DB_LOCK:
        try:
            with sqlite3.connect(settings.TASK_DB_PATH) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS coding_tasks (
                        task_id TEXT PRIMARY KEY,
                        description TEXT NOT NULL,
                        repo_path TEXT NOT NULL,
                        test_command TEXT NOT NULL,
                        status TEXT NOT NULL,
                        plan_json TEXT NOT NULL,
                        patches_json TEXT NOT NULL,
                        execution_history_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        metadata_json TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
        except Exception:
            pass


def _persist_task(task: CodingTask) -> None:
    """Persists a CodingTask to SQLite."""
    with DB_LOCK:
        try:
            with sqlite3.connect(settings.TASK_DB_PATH) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO coding_tasks (
                        task_id, description, repo_path, test_command, status,
                        plan_json, patches_json, execution_history_json,
                        created_at, updated_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.task_id,
                        task.description,
                        task.repo_path,
                        task.test_command,
                        task.status.value,
                        json.dumps(task.plan),
                        json.dumps([p.model_dump(mode="json") for p in task.patches]),
                        json.dumps([e.model_dump(mode="json") for e in task.execution_history]),
                        task.created_at.isoformat(),
                        task.updated_at.isoformat(),
                        json.dumps(task.metadata),
                    ),
                )
                conn.commit()
        except Exception:
            pass


def _load_tasks_from_db() -> None:
    """Loads tasks from SQLite on startup."""
    with DB_LOCK:
        try:
            with sqlite3.connect(settings.TASK_DB_PATH) as conn:
                cursor = conn.execute(
                    "SELECT task_id, description, repo_path, test_command, status, plan_json, patches_json, execution_history_json, created_at, updated_at, metadata_json FROM coding_tasks"
                )
                for row in cursor.fetchall():
                    task = CodingTask(
                        task_id=row[0],
                        description=row[1],
                        repo_path=row[2],
                        test_command=row[3],
                        status=TaskStatus(row[4]),
                        plan=json.loads(row[5]) if row[5] else [],
                        patches=[PatchResult(**p) for p in json.loads(row[6])] if row[6] else [],
                        execution_history=[ExecutionResult(**e) for e in json.loads(row[7])] if row[7] else [],
                        created_at=datetime.fromisoformat(row[8]),
                        updated_at=datetime.fromisoformat(row[9]),
                        metadata=json.loads(row[10]) if row[10] else {},
                    )
                    TASKS_DB[task.task_id] = task
        except Exception:
            pass


_init_sqlite_db()
_load_tasks_from_db()


def format_task_response(task: CodingTask) -> TaskResponse:
    return TaskResponse(
        task_id=task.task_id,
        status=task.status.value,
        description=task.description,
        repo_path=task.repo_path,
        plan=task.plan,
        patches=[
            PatchSummary(
                file_path=p.file_path,
                applied=p.applied,
                diff=p.diff,
                message=p.message,
            )
            for p in task.patches
        ],
        execution_history=[
            ExecutionSummary(
                command=e.command,
                exit_code=e.exit_code,
                duration_seconds=e.duration_seconds,
                passed=e.passed,
                timed_out=e.timed_out,
                failure_signature=e.failure_signature,
            )
            for e in task.execution_history
        ],
        approved=task.metadata.get("approved", False),
        created_at=task.created_at,
        updated_at=task.updated_at,
        metadata=task.metadata,
    )


def _run_agent_loop(task: CodingTask, max_attempts: int) -> None:
    """Executes the agent repair loop in an isolated workspace."""
    try:
        agent = CodePilotAgent(
            repo_path=task.repo_path,
            max_attempts=max_attempts,
            use_worktree=True,
        )
        task = agent.execute_task(task)
    except Exception as exc:
        task.status = TaskStatus.FAILED
        task.metadata["error"] = str(exc)
        task.updated_at = datetime.now(timezone.utc)

    TASKS_DB[task.task_id] = task
    _persist_task(task)


@app.get("/health", response_model=HealthResponse, tags=["System"])
def health_check():
    """Returns the operational status, version, and active task count."""
    return HealthResponse(status="healthy", version=__version__)


@app.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, tags=["Tasks"])
def create_task(
    payload: CreateTaskRequest,
    background_tasks: BackgroundTasks,
    _auth: Optional[str] = Depends(verify_api_key),
):
    """Submits a new coding task, validates safety boundaries, and executes the self-correction loop."""
    # 1. Path authorization check
    repo_path = Path(payload.repo_path).resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repository path does not exist or is not a directory: {payload.repo_path}",
        )

    if settings.REGISTERED_REPO_ROOTS and not settings.is_repo_allowed(repo_path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: repository '{payload.repo_path}' is outside registered repository roots",
        )

    # 2. Command safety allowlist check
    try:
        temp_runner = SandboxRunner(repo_path)
        temp_runner.validate_command_safety(payload.test_command)
    except SandboxSecurityException as sec_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Security violation in test_command: {sec_err}",
        )

    task = CodingTask(
        description=payload.description,
        repo_path=str(repo_path),
        test_command=payload.test_command,
    )
    TASKS_DB[task.task_id] = task
    _persist_task(task)

    # 3. Synchronous or Asynchronous dispatch
    if payload.run_in_background:
        background_tasks.add_task(_run_agent_loop, task, payload.max_attempts)
        return format_task_response(task)
    else:
        _run_agent_loop(task, payload.max_attempts)
        return format_task_response(task)


@app.get("/tasks/{task_id}", response_model=TaskResponse, tags=["Tasks"])
def get_task(task_id: str, _auth: Optional[str] = Depends(verify_api_key)):
    """Retrieves current state, plan, patches, and execution history for a task."""
    task = TASKS_DB.get(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    return format_task_response(task)


@app.post("/tasks/{task_id}/approve", response_model=ApprovalResponse, tags=["Review"])
def approve_task_patch(
    task_id: str,
    payload: ApprovalRequest,
    _auth: Optional[str] = Depends(verify_api_key),
):
    """Human-in-the-loop review and approval gate to authorize merging the verified patch into the target repo."""
    task = TASKS_DB.get(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    if task.status != TaskStatus.SUCCESS and payload.approved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve task in '{task.status.value}' state. All verification tests must pass first.",
        )

    task.metadata["approved"] = payload.approved
    task.metadata["reviewer"] = payload.reviewer
    task.metadata["review_comments"] = payload.comments

    # Real atomic merge to target repository on approval (Problem 4 fix)
    merged = False
    if payload.approved and task.patches:
        for patch in task.patches:
            if patch.applied:
                real_file = Path(task.repo_path) / patch.file_path
                real_file.parent.mkdir(parents=True, exist_ok=True)
                if patch.patched_content:
                    real_file.write_text(patch.patched_content, encoding="utf-8")
                    merged = True
                else:
                    workspace_id = task.metadata.get("workspace_id", task.task_id)
                    iso_dir = Path(tempfile.gettempdir()) / "codepilot_workspaces" / workspace_id
                    iso_file = iso_dir / patch.file_path
                    if iso_file.exists():
                        real_file.write_text(iso_file.read_text(encoding="utf-8"), encoding="utf-8")
                        merged = True

    task.updated_at = datetime.now(timezone.utc)
    _persist_task(task)

    APPROVALS_DB[task_id] = {
        "approved": payload.approved,
        "reviewer": payload.reviewer,
        "comments": payload.comments,
        "merged_to_target": merged,
    }

    action_msg = "Patch approved and merged into repository" if payload.approved else "Patch rejected by reviewer"
    return ApprovalResponse(
        task_id=task_id,
        status=task.status.value,
        approved=payload.approved,
        message=f"{action_msg} by {payload.reviewer}",
    )
