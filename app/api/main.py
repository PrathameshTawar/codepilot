"""FastAPI server exposing CodePilot autonomous coding endpoints, task lifecycle, and human review."""

from pathlib import Path
from typing import Dict
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
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
from app.core.models import CodingTask, TaskStatus

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

# In-memory storage for tasks and human reviews
TASKS_DB: Dict[str, CodingTask] = {}
APPROVALS_DB: Dict[str, Dict] = {}


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


@app.get("/health", response_model=HealthResponse, tags=["System"])
def health_check():
    """Returns the operational status and version of CodePilot."""
    return HealthResponse(status="healthy", version=__version__)


@app.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, tags=["Tasks"])
def create_task(payload: CreateTaskRequest):
    """Submits a new coding task, launches repository analysis, and executes the self-correction loop."""
    task = CodingTask(
        description=payload.description,
        repo_path=payload.repo_path,
        test_command=payload.test_command,
    )

    try:
        agent = CodePilotAgent(
            repo_path=payload.repo_path,
            max_attempts=payload.max_attempts,
        )
        task = agent.execute_task(task)
    except Exception as exc:
        task.status = TaskStatus.FAILED
        task.metadata["error"] = str(exc)

    TASKS_DB[task.task_id] = task
    return format_task_response(task)


@app.get("/tasks/{task_id}", response_model=TaskResponse, tags=["Tasks"])
def get_task(task_id: str):
    """Retrieves current state, plan, patches, and execution history for a task."""
    task = TASKS_DB.get(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    return format_task_response(task)


@app.post("/tasks/{task_id}/approve", response_model=ApprovalResponse, tags=["Review"])
def approve_task_patch(task_id: str, payload: ApprovalRequest):
    """Human-in-the-loop review and approval gate to authorize merging the generated patch."""
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

    APPROVALS_DB[task_id] = {
        "approved": payload.approved,
        "reviewer": payload.reviewer,
        "comments": payload.comments,
    }

    action_msg = "Patch approved for merging" if payload.approved else "Patch rejected by reviewer"
    return ApprovalResponse(
        task_id=task_id,
        status=task.status.value,
        approved=payload.approved,
        message=f"{action_msg} by {payload.reviewer}",
    )
