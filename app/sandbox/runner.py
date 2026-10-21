"""Hardened sandbox runner with command allowlisting, process group termination, stream bounding, and minimal environment isolation."""

import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from app.core.models import ExecutionResult


class SandboxSecurityException(Exception):
    """Raised when an unsafe, non-allowlisted, or forbidden command is submitted to the sandbox."""


class SandboxRunner:
    """Executes permitted commands and tests inside an isolated repository directory under strict bounds."""

    FORBIDDEN_COMMANDS: List[str] = [
        "rm -rf",
        "rm -r -f",
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
        "nc ",
        "powershell -enc",
        "sudo ",
    ]

    ALLOWED_EXECUTABLES = {"pytest", "python", "py"}

    def __init__(self, workspace_dir: str | Path, default_timeout: float = 30.0, max_output_bytes: int = 150_000):
        self.workspace_dir = Path(workspace_dir).resolve()
        if not self.workspace_dir.exists() or not self.workspace_dir.is_dir():
            raise ValueError(f"Workspace directory does not exist: {self.workspace_dir}")
        self.default_timeout = default_timeout
        self.max_output_bytes = max_output_bytes

    def validate_command_safety(self, command_str: str) -> List[str]:
        """Validates command against strict allowlist, blocks destructive patterns, and returns sanitized args."""
        clean_cmd = command_str.strip()
        if not clean_cmd:
            raise SandboxSecurityException("Empty command string submitted")

        lower_cmd = clean_cmd.lower()

        # Check explicit forbidden patterns (including rm -r -f and split flags)
        for forbidden in self.FORBIDDEN_COMMANDS:
            if forbidden.lower() in lower_cmd:
                raise SandboxSecurityException(f"Prohibited command pattern detected: '{forbidden}'")

        # Check regex for destructive file deletion (e.g. rm -r -f, rm -f -r, rm -rf, del /f)
        if re.search(r"\brm\s+-[a-zA-Z\s]*f", lower_cmd) or re.search(r"\bdel\s+/[a-zA-Z\s]*", lower_cmd):
            raise SandboxSecurityException("Prohibited command pattern detected: 'rm -rf'")

        try:
            tokens = shlex.split(clean_cmd)
        except Exception as err:
            raise SandboxSecurityException(f"Invalid command syntax: {err}") from err

        if not tokens:
            raise SandboxSecurityException("No executable tokens in command")

        exe = Path(tokens[0]).name.lower()
        if exe.endswith(".exe"):
            exe = exe[:-4]

        # Executable allowlist check
        if exe not in self.ALLOWED_EXECUTABLES:
            raise SandboxSecurityException(
                f"Prohibited command pattern detected: '{tokens[0]}'. Only pytest/python test runners are allowed."
            )

        # Check for shell operators in top-level tokens
        for t in tokens:
            if t in {"&&", "||", "|", "&", ">", ">>", "<"}:
                raise SandboxSecurityException(f"Command chaining or redirection operators forbidden in sandbox: '{t}'")

        # Check for forbidden network libraries or arbitrary OS execution in python -c commands
        if exe in {"python", "py"} and len(tokens) > 1 and tokens[1] == "-c":
            script = " ".join(tokens[2:]).lower()
            if any(net in script for net in ["urllib", "requests", "http.client", "socket.", "httpx."]):
                raise SandboxSecurityException("Network access libraries are strictly prohibited inside sandbox execution")
            if any(dest in script for dest in ["os.remove", "shutil.rmtree", "os.system", "subprocess."]):
                raise SandboxSecurityException("Arbitrary system invocation prohibited inside sandbox script execution")

        # Map to safe execution tokens
        if exe == "pytest":
            return [sys.executable, "-m", "pytest"] + tokens[1:]
        elif exe in {"python", "py"}:
            return [sys.executable] + tokens[1:]
        return tokens

    def get_sanitized_env(self) -> dict:
        """Constructs a clean, minimal environment containing NO server API keys or secrets."""
        allowed_keys = {
            "PATH",
            "SYSTEMROOT",
            "SYSTEMDRIVE",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "TMPDIR",
            "LC_ALL",
            "LANG",
            "HOME",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
        }
        env = {}
        for k in allowed_keys:
            if k in os.environ:
                env[k] = os.environ[k]

        env["PYTHONPATH"] = str(self.workspace_dir)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _kill_process_tree(self, pid: int) -> None:
        """Recursively terminates a child process and all of its spawned subprocesses."""
        if sys.platform == "win32":
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=5.0)
            except Exception:
                pass
        else:
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGKILL)
            except Exception:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass

    def extract_failure_signature(self, stdout: str, stderr: str) -> Optional[str]:
        """Extracts the primary exception name and failing summary from test output."""
        combined = f"{stdout}\n{stderr}"
        match = re.search(r"((?:[A-Za-z]+Error|Exception):\s*[^\r\n]*)", combined)
        if match:
            return match.group(1).strip()
        failed_match = re.search(r"(FAILED\s+[^\r\n]*)", combined)
        if failed_match:
            return failed_match.group(1).strip()
        assert_match = re.search(r"(E\s+assert\s+[^\r\n]*)", combined)
        if assert_match:
            return f"AssertionError: {assert_match.group(1).strip()}"
        return None

    def run(self, command: str | List[str], timeout: Optional[float] = None) -> ExecutionResult:
        """Executes a command inside the workspace directory under strict timeout, environment sanitization, and isolation."""
        timeout_limit = timeout if timeout is not None else self.default_timeout

        cmd_str = " ".join(command) if isinstance(command, list) else command
        cmd_args = self.validate_command_safety(cmd_str)

        start_time = time.time()
        env = self.get_sanitized_env()
        is_windows = sys.platform == "win32"

        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if is_windows else 0
        preexec = None if is_windows else os.setsid

        try:
            proc = subprocess.Popen(
                cmd_args,
                cwd=str(self.workspace_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=creation_flags,
                preexec_fn=preexec,
            )

            try:
                stdout_raw, stderr_raw = proc.communicate(timeout=timeout_limit)
                duration = round(time.time() - start_time, 3)
                stdout = (stdout_raw or "")[: self.max_output_bytes]
                stderr = (stderr_raw or "")[: self.max_output_bytes]
                passed = (proc.returncode == 0)
                sig = None if passed else self.extract_failure_signature(stdout, stderr)

                return ExecutionResult(
                    command=cmd_str,
                    exit_code=proc.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    duration_seconds=duration,
                    timed_out=False,
                    passed=passed,
                    failure_signature=sig,
                )

            except subprocess.TimeoutExpired:
                self._kill_process_tree(proc.pid)
                try:
                    stdout_raw, stderr_raw = proc.communicate(timeout=2.0)
                except Exception:
                    stdout_raw, stderr_raw = "", ""

                duration = round(time.time() - start_time, 3)
                stdout = (stdout_raw or "")[: self.max_output_bytes]
                stderr = (stderr_raw or "")[: self.max_output_bytes]
                return ExecutionResult(
                    command=cmd_str,
                    exit_code=-1,
                    stdout=stdout,
                    stderr=f"Execution timed out after {timeout_limit} seconds\n{stderr}",
                    duration_seconds=duration,
                    timed_out=True,
                    passed=False,
                    failure_signature=f"TimeoutExpired: exceeded {timeout_limit}s limit",
                )

        except SandboxSecurityException:
            raise
        except Exception as err:
            duration = round(time.time() - start_time, 3)
            return ExecutionResult(
                command=cmd_str,
                exit_code=-1,
                stdout="",
                stderr=str(err),
                duration_seconds=duration,
                timed_out=False,
                passed=False,
                failure_signature=f"ExecutionError: {err}",
            )
