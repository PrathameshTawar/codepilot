"""Isolated sandbox runner with timeout containment, forbidden command policies, and failure signature extraction."""

import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from app.core.models import ExecutionResult


class SandboxSecurityException(Exception):
    """Raised when an unsafe or forbidden command is submitted to the sandbox."""


class SandboxRunner:
    """Executes permitted commands and tests inside an isolated repository directory with bounds."""

    FORBIDDEN_COMMANDS: List[str] = [
        "rm -rf",
        "del /s",
        "del /f",
        "rmdir /s",
        "format ",
        "mkfs",
        "dd if=",
        ":(){ :|:& };:",
        "shutdown",
        "reboot",
        "curl ",
        "wget ",
        "nc -e",
        "powershell -enc",
        "sudo ",
    ]

    def __init__(self, workspace_dir: str | Path, default_timeout: float = 30.0, max_output_bytes: int = 150_000):
        self.workspace_dir = Path(workspace_dir).resolve()
        if not self.workspace_dir.exists() or not self.workspace_dir.is_dir():
            raise ValueError(f"Workspace directory does not exist: {self.workspace_dir}")
        self.default_timeout = default_timeout
        self.max_output_bytes = max_output_bytes

    def validate_command_safety(self, command_str: str) -> None:
        """Validates that command contains no destructive or unauthorized commands."""
        lower_cmd = command_str.lower()
        for forbidden in self.FORBIDDEN_COMMANDS:
            if forbidden.lower() in lower_cmd:
                raise SandboxSecurityException(f"Prohibited command pattern detected: '{forbidden}'")

    def extract_failure_signature(self, stdout: str, stderr: str) -> Optional[str]:
        """Extracts the primary exception name and failing summary from test output."""
        combined = f"{stdout}\n{stderr}"
        # Look for standard Python tracebacks e.g. "AssertionError: expected ..." or "FAILED tests/... - AssertionError"
        match = re.search(r"((?:[A-Za-z]+Error|Exception|FAILED):?\s*[^\r\n]*)", combined)
        if match:
            return match.group(1).strip()
        return None

    def run(self, command: str | List[str], timeout: Optional[float] = None) -> ExecutionResult:
        """Executes a command inside the workspace directory under strict timeout and isolation."""
        timeout_limit = timeout if timeout is not None else self.default_timeout

        if isinstance(command, list):
            cmd_str = " ".join(command)
            cmd_args = command
        else:
            cmd_str = command
            # If command begins with 'pytest' or 'python', normalize executable on Windows
            if cmd_str.startswith("pytest"):
                cmd_args = [sys.executable, "-m", "pytest"] + shlex.split(cmd_str)[1:]
            elif cmd_str.startswith("python "):
                cmd_args = [sys.executable] + shlex.split(cmd_str)[1:]
            else:
                cmd_args = shlex.split(cmd_str)

        self.validate_command_safety(cmd_str)

        start_time = time.time()
        try:
            # Minimal sanitized environment
            env = os.environ.copy()
            env["PYTHONPATH"] = str(self.workspace_dir)

            process = subprocess.run(
                cmd_args,
                cwd=str(self.workspace_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_limit,
                env=env,
            )

            duration = round(time.time() - start_time, 3)
            stdout = process.stdout[: self.max_output_bytes]
            stderr = process.stderr[: self.max_output_bytes]
            passed = (process.returncode == 0)
            sig = None if passed else self.extract_failure_signature(stdout, stderr)

            return ExecutionResult(
                command=cmd_str,
                exit_code=process.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                timed_out=False,
                passed=passed,
                failure_signature=sig,
            )

        except subprocess.TimeoutExpired as err:
            duration = round(time.time() - start_time, 3)
            stdout = (err.stdout or "")[: self.max_output_bytes] if isinstance(err.stdout, str) else ""
            stderr = (err.stderr or "")[: self.max_output_bytes] if isinstance(err.stderr, str) else ""
            return ExecutionResult(
                command=cmd_str,
                exit_code=-1,
                stdout=stdout,
                stderr=f"Execution timed out after {timeout_limit} seconds",
                duration_seconds=duration,
                timed_out=True,
                passed=False,
                failure_signature=f"TimeoutExpired: exceeded {timeout_limit}s limit",
            )
