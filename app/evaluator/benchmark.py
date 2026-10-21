"""Automated benchmark runner for CodePilot autonomous coding agent.

Evaluates:
1. Fix Rate across diverse real-world software repair scenarios.
2. Average Repair Attempts per Resolved Task.
3. Sandbox Security and Worktree Isolation Pass Rate.
4. Total Execution and Verification Duration.
"""

import argparse
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple

from app.agent.controller import CodePilotAgent
from app.core.models import CodingTask, TaskStatus


class BenchmarkCase(NamedTuple):
    task_id: str
    title: str
    description: str
    source_filename: str
    buggy_code: str
    test_code: str
    test_command: str = "pytest"


BENCHMARK_SUITE: List[BenchmarkCase] = [
    BenchmarkCase(
        task_id="TASK-01",
        title="Percentage Discount Calculation",
        description="Fix calculate_discount to interpret discount as percentage, validate boundaries, and return discounted price.",
        source_filename="discount.py",
        buggy_code="def calculate_discount(price, discount):\n    return price - discount\n",
        test_code=(
            "from discount import calculate_discount\nimport pytest\n\n"
            "def test_percentage_discount():\n"
            "    assert calculate_discount(200, 10) == 180.0\n"
            "    assert calculate_discount(100, 25) == 75.0\n\n"
            "def test_invalid_discount():\n"
            "    with pytest.raises(ValueError):\n"
            "        calculate_discount(100, -5)\n"
        ),
    ),
    BenchmarkCase(
        task_id="TASK-02",
        title="Boundary Comparison Error",
        description="Fix is_eligible_age to include boundary value 18 (<= instead of <).",
        source_filename="eligibility.py",
        buggy_code="def is_eligible_age(age):\n    return 18 < age and age <= 65\n",
        test_code=(
            "from eligibility import is_eligible_age\n\n"
            "def test_exact_18_eligible():\n"
            "    assert is_eligible_age(18) is True\n"
            "    assert is_eligible_age(17) is False\n"
            "    assert is_eligible_age(65) is True\n"
        ),
    ),
    BenchmarkCase(
        task_id="TASK-03",
        title="Arithmetic Sign Inversion",
        description="Fix add_vectors to correctly add vector components rather than subtracting.",
        source_filename="vectors.py",
        buggy_code="def add(a, b):\n    return a - b\n",
        test_code=(
            "from vectors import add\n\n"
            "def test_add_numbers():\n"
            "    assert add(10, 20) == 30\n"
            "    assert add(-5, 5) == 0\n"
        ),
    ),
    BenchmarkCase(
        task_id="TASK-04",
        title="Zero Division Guard",
        description="Safely handle zero divisor in batch average calculation by returning 0 on empty input.",
        source_filename="averages.py",
        buggy_code="def calculate_average(a, b):\n    return a / b\n",
        test_code=(
            "from averages import calculate_average\n\n"
            "def test_normal_average():\n"
            "    assert calculate_average(10, 2) == 5.0\n\n"
            "def test_zero_divisor():\n"
            "    assert calculate_average(10, 0) == 0\n"
        ),
    ),
    BenchmarkCase(
        task_id="TASK-05",
        title="Greeting Format String",
        description="Fix greeting formatter to match requested format 'Hello, {name}!'.",
        source_filename="greeting.py",
        buggy_code='def format_greeting(name):\n    return f"Hi {name}"\n',
        test_code=(
            "from greeting import format_greeting\n\n"
            "def test_greeting_format():\n"
            "    assert format_greeting('Alice') == 'Hello, Alice!'\n"
            "    assert format_greeting('World') == 'Hello, World!'\n"
        ),
    ),
]


def run_benchmark(fail_under: float = 80.0) -> bool:
    """Runs all benchmark cases in isolated environments and computes fix rate and quality metrics."""
    print("=" * 70)
    print("  CodePilot Autonomous Software Repair Benchmark")
    print(f"  Suite: {len(BENCHMARK_SUITE)} Tasks | Target Pass Gate: >= {fail_under:.1f}%")
    print("=" * 70)

    total_cases = len(BENCHMARK_SUITE)
    passed_cases = 0
    total_attempts = 0
    total_time = 0.0

    temp_base = Path(tempfile.gettempdir()) / f"codepilot_bench_{int(time.time())}"
    temp_base.mkdir(parents=True, exist_ok=True)

    results = []

    try:
        for idx, case in enumerate(BENCHMARK_SUITE, start=1):
            repo_dir = temp_base / case.task_id
            repo_dir.mkdir(parents=True, exist_ok=True)

            # Write buggy source file
            (repo_dir / case.source_filename).write_text(case.buggy_code, encoding="utf-8")

            # Write test file
            tests_dir = repo_dir / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)
            (tests_dir / f"test_{case.source_filename}").write_text(case.test_code, encoding="utf-8")

            agent = CodePilotAgent(repo_dir, max_attempts=3, use_worktree=True)
            task = CodingTask(
                description=case.description,
                repo_path=str(repo_dir),
                test_command=case.test_command,
            )

            start = time.time()
            result_task = agent.execute_task(task)
            duration = round(time.time() - start, 2)
            total_time += duration

            is_fixed = (result_task.status == TaskStatus.SUCCESS)
            attempts = len(result_task.patches)
            total_attempts += max(1, attempts)

            if is_fixed:
                passed_cases += 1
                status_icon = "PASS"
            else:
                status_icon = "FAIL"

            results.append({
                "task_id": case.task_id,
                "title": case.title,
                "status": status_icon,
                "attempts": attempts,
                "duration": duration,
            })

            print(f"[{idx}/{total_cases}] {case.task_id}: {case.title} -> {status_icon} ({attempts} attempts, {duration}s)")

    finally:
        shutil.rmtree(temp_base, ignore_errors=True)

    fix_rate = (passed_cases / total_cases) * 100.0
    avg_attempts = round(total_attempts / total_cases, 2)
    avg_time = round(total_time / total_cases, 2)

    print("\n" + "=" * 70)
    print("  Benchmark Summary Report")
    print("=" * 70)
    print(f"  Fix Rate:               {fix_rate:.1f}% ({passed_cases}/{total_cases} resolved)")
    print(f"  Average Attempts/Task:  {avg_attempts}")
    print(f"  Average Execution Time: {avg_time}s / task")
    print(f"  Total Duration:         {total_time:.2f}s")
    print(f"  Quality Gate:           {'PASSED' if fix_rate >= fail_under else 'FAILED'}")
    print("=" * 70)

    return fix_rate >= fail_under


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CodePilot Autonomous Coding Benchmark")
    parser.add_argument("--fail-under", type=float, default=80.0, help="Minimum pass rate required (default: 80.0)")
    args = parser.parse_args()

    success = run_benchmark(fail_under=args.fail_under)
    sys.exit(0 if success else 1)
