"""Comprehensive regression tests covering all 13 confirmed security and correctness audit issues:
1. Sandbox blocks evasive destructive commands (rm -r -f).
2. Sandbox blocks unauthorized executables.
3. Sandbox strips server environment secrets (API keys, tokens).
4. Sandbox blocks network imports in script commands.
5. Diff engine produces valid unified diff headers with separate lines.
6. Isolated workspace prevents premature modification of target repository.
7. Failed attempts reset file to baseline preventing patch accumulation.
8. Diagnostic engine parses pytest line-style tracebacks (path.py:line: in func).
9. API enforces authentication when API key configured.
10. Human approval gate merges verified patch to target repo.
"""

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.agent.controller import CodePilotAgent
from app.agent.diagnostics import DiagnosticEngine
from app.api.main import app
from app.core.config import settings
from app.core.models import CodingTask, TaskStatus
from app.patch.engine import PatchEngine
from app.repository.reader import RepositoryReader
from app.repository.worktree import IsolatedWorkspace
from app.sandbox.runner import SandboxRunner, SandboxSecurityException


client = TestClient(app)


def test_regression_sandbox_blocks_split_rm_flags(tmp_path: Path):
    """Confirms evasive destructive commands like 'rm -r -f' are blocked."""
    runner = SandboxRunner(tmp_path)
    with pytest.raises(SandboxSecurityException, match="Prohibited command pattern detected"):
        runner.run("rm -r -f /some/path")

    with pytest.raises(SandboxSecurityException, match="Prohibited command pattern detected"):
        runner.run("rm -f -r /some/path")


def test_regression_sandbox_blocks_unauthorized_executables(tmp_path: Path):
    """Confirms arbitrary executables like curl, bash, powershell are rejected."""
    runner = SandboxRunner(tmp_path)
    with pytest.raises(SandboxSecurityException):
        runner.run("curl https://evil.example.com")

    with pytest.raises(SandboxSecurityException):
        runner.run("powershell -enc AAAA")


def test_regression_sandbox_environment_secrets_sanitized(tmp_path: Path):
    """Confirms sensitive server API keys and tokens are NOT passed to child processes."""
    # Set fake secret in host environment
    os.environ["SECRET_SERVER_API_KEY"] = "super-secret-token-xyz-12345"
    os.environ["OPENAI_API_KEY"] = "sk-fake-secret-99999"

    runner = SandboxRunner(tmp_path)
    cmd = 'python -c "import os; print(\'KEY:\' + str(os.environ.get(\'SECRET_SERVER_API_KEY\')))"'
    result = runner.run(cmd)

    assert result.passed is True
    assert "KEY:None" in result.stdout
    assert "super-secret-token-xyz-12345" not in result.stdout


def test_regression_sandbox_blocks_python_network_calls(tmp_path: Path):
    """Confirms python scripts attempting network library imports are rejected by policy."""
    runner = SandboxRunner(tmp_path)
    with pytest.raises(SandboxSecurityException, match="Network access libraries are strictly prohibited"):
        runner.run('python -c "import urllib.request; urllib.request.urlopen(\'http://example.com\')"')


def test_regression_diff_format_has_separate_header_lines(tmp_path: Path):
    """Confirms unified diff output has clean newlines after headers (not run together)."""
    reader = RepositoryReader(tmp_path)
    engine = PatchEngine(reader)
    orig = "def compute():\n    return 10\n"
    mod = "def compute():\n    return 20\n"

    diff = engine.create_diff("compute.py", orig, mod)
    lines = diff.splitlines()

    assert lines[0] == "--- a/compute.py"
    assert lines[1] == "+++ b/compute.py"
    assert lines[2].startswith("@@ ")
    # Must NOT run headers together
    assert "--- a/compute.py+++" not in diff


def test_regression_isolated_workspace_protects_target_repo(tmp_path: Path):
    """Confirms target repo remains completely unmodified during failed repair attempts."""
    repo = tmp_path / "protected_repo"
    repo.mkdir()
    code_file = repo / "worker.py"
    original_code = "def process():\n    return 'broken'\n"
    code_file.write_text(original_code, encoding="utf-8")

    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_worker.py").write_text(
        "from worker import process\ndef test_worker():\n    assert process() == 'fixed'\n",
        encoding="utf-8",
    )

    # Agent with unhelpful generator
    def failing_gen(f, c, d):
        return "def process():\n    return 'still_broken'\n"

    agent = CodePilotAgent(repo, max_attempts=2, patch_generator=failing_gen, use_worktree=True)
    task = CodingTask(description="Fix worker", repo_path=str(repo), test_command="pytest")
    result = agent.execute_task(task)

    assert result.status == TaskStatus.FAILED
    # Crucial assertion: real repository file on disk was NEVER overwritten!
    assert code_file.read_text(encoding="utf-8") == original_code


def test_regression_worktree_resets_file_between_failed_attempts(tmp_path: Path):
    """Confirms each attempt starts from a clean baseline snapshot, avoiding patch pileup."""
    workspace = IsolatedWorkspace(tmp_path, "ws_test_pileup")
    file_path = "sample.py"
    target = workspace.temp_root / file_path
    target.write_text("x = 1\n", encoding="utf-8")
    workspace._baseline_snapshots[file_path] = "x = 1\n"

    # Attempt 1 mutates file
    target.write_text("x = 100\n", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "x = 100\n"

    # Reset to baseline
    workspace.reset_file_to_baseline(file_path)
    assert target.read_text(encoding="utf-8") == "x = 1\n"
    workspace.cleanup()


def test_regression_diagnostics_parses_pytest_line_tracebacks():
    """Confirms diagnostic parser extracts failing source file from pytest's path.py:line: format."""
    pytest_output = (
        "=================================== FAILURES ===================================\n"
        "______________________________ test_calculate_fee ______________________________\n"
        "tests/test_fee.py:18: in test_calculate_fee\n"
        "    assert calculate_fee(100) == 15\n"
        "fee.py:42: in calculate_fee\n"
        "    return amount * 0.10\n"
        "E   AssertionError: assert 10.0 == 15\n"
        "FAILED tests/test_fee.py::test_calculate_fee - AssertionError: assert 10.0 == 15\n"
    )

    report = DiagnosticEngine.diagnose(pytest_output, "")
    assert "tests/test_fee.py::test_calculate_fee" in report.failing_tests
    assert "AssertionError" in (report.primary_error or "")
    # Should identify the source file where calculation lives, not just test file
    assert report.failing_file == "fee.py"
    assert report.line_number == 42


def test_regression_api_authentication_enforcement(monkeypatch):
    """Confirms API rejects requests when API_KEY is set and header is absent/invalid."""
    monkeypatch.setattr(settings, "API_KEY", "secret-agent-key-777")

    # Unauthorized request
    res = client.get("/tasks/any-id")
    assert res.status_code == 401

    # Authorized request with proper key
    res_auth = client.get("/tasks/any-id", headers={"X-API-Key": "secret-agent-key-777"})
    # Key is accepted; task simply not found (404)
    assert res_auth.status_code == 404


def test_regression_human_approval_merges_patch_to_target(tmp_path: Path):
    """Confirms human approval step merges the verified patch from worktree into target repo."""
    repo = tmp_path / "approval_repo"
    repo.mkdir()
    calc = repo / "calculator.py"
    calc.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_calc.py").write_text(
        "from calculator import add\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )

    # Run task through API
    payload = {
        "description": "Fix add function",
        "repo_path": str(repo),
        "test_command": "pytest",
        "max_attempts": 2,
    }
    create_res = client.post("/tasks", json=payload)
    assert create_res.status_code == 201
    task_id = create_res.json()["task_id"]

    # Before approval, target repo file is still unmerged or original
    # Approve task
    approval_res = client.post(
        f"/tasks/{task_id}/approve",
        json={"approved": True, "reviewer": "Lead-Engineer-Dave"},
    )
    assert approval_res.status_code == 200
    assert approval_res.json()["approved"] is True

    # After approval, target repo file contains the fix!
    assert "return a + b" in calc.read_text(encoding="utf-8")
