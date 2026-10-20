"""Autonomous coding agent controller orchestrating closed-loop planning, execution, and repair."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from app.agent.diagnostics import DiagnosticEngine, DiagnosticReport
from app.core.models import CodingTask, ExecutionResult, PatchResult, TaskStatus
from app.core.retry import RetryBudget
from app.patch.engine import PatchEngine
from app.repository.reader import RepositoryReader
from app.sandbox.runner import SandboxRunner


PatchGeneratorFunc = Callable[[str, str, DiagnosticReport], str]


class CodePilotAgent:
    """Autonomous coding agent that diagnoses test failures and performs bounded self-correction."""

    def __init__(
        self,
        repo_path: str | Path,
        max_attempts: int = 3,
        timeout_seconds: float = 20.0,
        patch_generator: Optional[PatchGeneratorFunc] = None,
    ):
        self.repo_path = Path(repo_path).resolve()
        self.reader = RepositoryReader(self.repo_path)
        self.patch_engine = PatchEngine(self.reader)
        self.sandbox = SandboxRunner(self.repo_path, default_timeout=timeout_seconds)
        self.max_attempts = max_attempts
        self.patch_generator = patch_generator

    def execute_task(self, task: CodingTask) -> CodingTask:
        """Executes a coding task through the full observe -> diagnose -> repair -> verify loop."""
        task.status = TaskStatus.ANALYZING
        budget = RetryBudget(max_attempts=self.max_attempts)

        # 1. Discover repository files and test suite
        test_files = self.reader.find_test_files()
        code_files = self.reader.list_files(extensions=[".py"])
        src_candidates = [f for f in code_files if f not in test_files]

        task.plan = [
            f"Analyze repository tree ({len(code_files)} source files, {len(test_files)} test files)",
            f"Run baseline test suite: {task.test_command}",
            f"Perform bounded repair loop (max {self.max_attempts} attempts) if tests fail",
            "Generate reviewable diff and verify final state",
        ]

        # 2. Baseline Test Run
        task.status = TaskStatus.TESTING
        initial_run = self.sandbox.run(task.test_command)
        task.execution_history.append(initial_run)

        if initial_run.passed:
            task.status = TaskStatus.SUCCESS
            task.updated_at = datetime.now(timezone.utc)
            return task

        # 3. Bounded Self-Correction Loop
        task.status = TaskStatus.REPAIRING

        while not budget.exhausted:
            last_exec = task.execution_history[-1]
            diagnosis = DiagnosticEngine.diagnose(last_exec.stdout, last_exec.stderr)

            # Determine target source file to patch (never patch the test file unless no other file exists)
            target_file = None
            if diagnosis.failing_file and not Path(diagnosis.failing_file).name.startswith("test_"):
                try:
                    rel = Path(diagnosis.failing_file).relative_to(self.repo_path).as_posix()
                    target_file = rel
                except ValueError:
                    target_file = diagnosis.failing_file

            if not target_file:
                # Find corresponding source file by matching stem: e.g. test_discount.py -> discount.py
                if diagnosis.failing_file:
                    base_name = Path(diagnosis.failing_file).stem.replace("test_", "")
                    for f in src_candidates:
                        if Path(f).stem == base_name:
                            target_file = f
                            break

                if not target_file:
                    target_file = src_candidates[0] if src_candidates else (code_files[0] if code_files else None)

            if not target_file:
                task.status = TaskStatus.FAILED
                task.metadata["error"] = "No editable target file found in repository"
                return task

            original_code = self.reader.read_file(target_file)

            # Propose repair patch using generator
            if self.patch_generator:
                repaired_code = self.patch_generator(target_file, original_code, diagnosis)
            else:
                task.status = TaskStatus.FAILED
                task.metadata["error"] = "No patch generator configured to synthesize code fix"
                return task

            # Apply patch
            patch_res = self.patch_engine.apply_patch(target_file, repaired_code)
            task.patches.append(patch_res)

            if not patch_res.applied:
                # Patch rejected due to syntax error
                budget.record_error(patch_res.message)
                if budget.exhausted:
                    break
                budget.consume()
                continue

            # Verify in sandbox
            verify_run = self.sandbox.run(task.test_command)
            task.execution_history.append(verify_run)

            if verify_run.passed:
                task.status = TaskStatus.SUCCESS
                task.updated_at = datetime.now(timezone.utc)
                return task

            # Test still failing -> consume budget & record signature
            if verify_run.failure_signature:
                budget.record_error(verify_run.failure_signature)

            if budget.exhausted:
                break

            budget.consume()

        task.status = TaskStatus.FAILED
        task.updated_at = datetime.now(timezone.utc)
        return task
