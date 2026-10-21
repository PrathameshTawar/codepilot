"""Pydantic and dataclass domain models for CodePilot tasks and execution state."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Lifecycle status of an autonomous coding task."""

    PENDING = "pending"
    ANALYZING = "analyzing"
    PATCHING = "patching"
    TESTING = "testing"
    REPAIRING = "repairing"
    SUCCESS = "success"
    FAILED = "failed"
    APPROVAL_REQUIRED = "approval_required"


class PatchResult(BaseModel):
    """Result of generating or applying a code patch."""

    file_path: str
    diff: str
    applied: bool = False
    message: str = ""
    patched_content: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionResult(BaseModel):
    """Result of running a command or test suite in the sandbox."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    passed: bool = False
    failure_signature: Optional[str] = None


class CodingTask(BaseModel):
    """Represents an autonomous coding task assigned to CodePilot."""

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    repo_path: str
    test_command: str = "pytest"
    status: TaskStatus = TaskStatus.PENDING
    plan: List[str] = Field(default_factory=list)
    patches: List[PatchResult] = Field(default_factory=list)
    execution_history: List[ExecutionResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)
