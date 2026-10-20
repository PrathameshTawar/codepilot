"""End-to-end integration tests for CodePilotAgent self-correction and bounded repair loops."""

from pathlib import Path
import pytest
from app.agent.controller import CodePilotAgent
from app.agent.diagnostics import DiagnosticReport
from app.core.models import CodingTask, TaskStatus


@pytest.fixture
def buggy_discount_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "discount_project"
    repo.mkdir()

    # Broken implementation: interprets discount as fixed dollar amount instead of percentage
    (repo / "discount.py").write_text(
        "def calculate_discount(price, discount):\n    return price - discount\n",
        encoding="utf-8",
    )

    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_discount.py").write_text(
        "from discount import calculate_discount\n\n"
        "def test_percentage_discount():\n"
        "    # 10% of 200 is 20 -> expected 180, but broken func returns 200 - 10 = 190\n"
        "    assert calculate_discount(200, 10) == 180\n",
        encoding="utf-8",
    )

    return repo


def test_agent_diagnoses_and_repairs_buggy_code(buggy_discount_repo: Path):
    """Simulates a repair generator providing the correct percentage calculation."""
    def mock_repair_generator(file_path: str, original: str, diagnosis: DiagnosticReport) -> str:
        assert "discount.py" in file_path
        assert "AssertionError" in (diagnosis.primary_error or "")
        return (
            "def calculate_discount(price, discount):\n"
            "    if price < 0 or discount < 0 or discount > 100:\n"
            "        raise ValueError('Invalid price or discount')\n"
            "    return price * (1 - discount / 100)\n"
        )

    agent = CodePilotAgent(buggy_discount_repo, max_attempts=3, patch_generator=mock_repair_generator)
    task = CodingTask(
        description="Fix the discount calculation to treat discount as percentage and validate inputs",
        repo_path=str(buggy_discount_repo),
        test_command="pytest",
    )

    result_task = agent.execute_task(task)

    assert result_task.status == TaskStatus.SUCCESS
    assert len(result_task.patches) == 1
    assert result_task.patches[0].applied is True
    # Initial run failed + 1 verification run passed = 2 execution history runs
    assert len(result_task.execution_history) == 2
    assert result_task.execution_history[0].passed is False
    assert result_task.execution_history[1].passed is True


def test_agent_exhausts_budget_on_failing_repairs(buggy_discount_repo: Path):
    """Simulates an unhelpful generator that produces incorrect code, exhausting the budget."""
    def bad_repair_generator(file_path: str, original: str, diagnosis: DiagnosticReport) -> str:
        # Still fails the test
        return "def calculate_discount(price, discount):\n    return price - 999\n"

    agent = CodePilotAgent(buggy_discount_repo, max_attempts=2, patch_generator=bad_repair_generator)
    task = CodingTask(
        description="Fix discount calculation",
        repo_path=str(buggy_discount_repo),
        test_command="pytest",
    )

    result_task = agent.execute_task(task)

    assert result_task.status == TaskStatus.FAILED
    assert len(result_task.patches) >= 1
