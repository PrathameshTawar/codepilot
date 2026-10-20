"""Pydantic API request and response schemas for CodePilot REST endpoints."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CreateTaskRequest(BaseModel):
    """Payload to submit a new autonomous coding task."""

    description: str = Field(..., description="Problem description or GitHub issue text")
    repo_path: str = Field(..., description="Absolute or relative path to the local repository")
    test_command: str = Field(default="pytest", description="Command used to run verification tests")
    max_attempts: int = Field(default=3, ge=1, le=10, description="Maximum bounded self-correction attempts")


class PatchSummary(BaseModel):
    file_path: str
    applied: bool
    diff: str
    message: str


class ExecutionSummary(BaseModel):
    command: str
    exit_code: int
    duration_seconds: float
    passed: bool
    timed_out: bool
    failure_signature: Optional[str] = None


class TaskResponse(BaseModel):
    """Full status and audit deliverable for a coding task."""

    task_id: str
    status: str
    description: str
    repo_path: str
    plan: List[str]
    patches: List[PatchSummary]
    execution_history: List[ExecutionSummary]
    approved: bool = False
    created_at: datetime
    updated_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    """Payload to authorize or reject applying/merging the final patch."""

    approved: bool = Field(..., description="True if human reviewer authorizes the patch")
    reviewer: str = Field(..., description="Identifier or name of human reviewer")
    comments: Optional[str] = Field(default=None, description="Optional review notes")


class ApprovalResponse(BaseModel):
    task_id: str
    status: str
    approved: bool
    message: str


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
