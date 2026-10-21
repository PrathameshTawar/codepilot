"""Autonomous coding agent controller orchestrating closed-loop planning, isolated execution, and repair."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from app.agent.diagnostics import DiagnosticEngine, DiagnosticReport
from app.agent.model_client import ModelClient
from app.core.config import settings
from app.core.models import CodingTask, ExecutionResult, PatchResult, TaskStatus
from app.core.retry import RetryBudget
from app.patch.engine import PatchEngine
from app.repository.reader import RepositoryReader
from app.repository.worktree import IsolatedWorkspace
from app.sandbox.runner import SandboxRunner


PatchGeneratorFunc = Callable[[str, str, DiagnosticReport], str]


class CodePilotAgent:
    """Autonomous coding agent that diagnoses test failures and performs bounded self-correction in isolated workspaces."""

    def __init__(
        self,
        repo_path: str | Path,
        max_attempts: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        patch_generator: Optional[PatchGeneratorFunc] = None,
        use_worktree: bool = True,
    ):
        self.repo_path = Path(repo_path).resolve()
        self.max_attempts = max_attempts or settings.MAX_RETRY_ATTEMPTS
        self.timeout_seconds = timeout_seconds or settings.DEFAULT_EXECUTION_TIMEOUT
        self.use_worktree = use_worktree

        # Default model client if no custom generator is injected
        if patch_generator:
            self.patch_generator = patch_generator
        else:
            model_client = ModelClient()
            self.patch_generator = lambda f, c, d: model_client.generate_repair(f, c, d)

    def execute_task(self, task: CodingTask) -> CodingTask:
        """Executes a coding task through the full observe -> diagnose -> repair -> verify loop inside an isolated workspace."""
        task.status = TaskStatus.ANALYZING
        budget = RetryBudget(max_attempts=self.max_attempts)

        # 1. Initialize isolated execution workspace to avoid touching target repo directly
        workspace = None
        if self.use_worktree:
            workspace = IsolatedWorkspace(self.repo_path, task.task_id)
            active_path = workspace.temp_root
            task.metadata["workspace_id"] = task.task_id
        else:
            active_path = self.repo_path

        reader = RepositoryReader(active_path)
        patch_engine = PatchEngine(reader)
        sandbox = SandboxRunner(active_path, default_timeout=self.timeout_seconds)

        # Discover repository files
        test_files = reader.find_test_files()
        code_files = reader.list_files(extensions=[".py"])
        src_candidates = [f for f in code_files if f not in test_files]

        task.plan = [
            f"Analyze repository tree ({len(code_files)} source files, {len(test_files)} test files)",
            f"Run baseline test suite in isolated workspace: {task.test_command}",
            f"Perform bounded repair loop (max {self.max_attempts} attempts) if tests fail",
            "Generate reviewable diff and verify final state",
        ]

        # 2. Baseline Test Run
        task.status = TaskStatus.TESTING
        initial_run = sandbox.run(task.test_command)
        task.execution_history.append(initial_run)

        if initial_run.passed:
            task.status = TaskStatus.SUCCESS
            task.updated_at = datetime.now(timezone.utc)
            if workspace and not self.use_worktree:
                workspace.cleanup()
            return task

        # 3. Bounded Self-Correction Loop
        task.status = TaskStatus.REPAIRING

        while not budget.exhausted:
            last_exec = task.execution_history[-1]
            diagnosis = DiagnosticEngine.diagnose(last_exec.stdout, last_exec.stderr)

            # Determine target source file to patch
            target_file = None
            if diagnosis.failing_file and not Path(diagnosis.failing_file).name.startswith("test_"):
                try:
                    rel = Path(diagnosis.failing_file).relative_to(active_path).as_posix()
                    target_file = rel
                except ValueError:
                    target_file = diagnosis.failing_file

            if not target_file and diagnosis.failing_file:
                # Find corresponding source file by matching stem: e.g. test_discount.py -> discount.py
                base_name = Path(diagnosis.failing_file).stem.replace("test_", "").replace("_test", "")
                for f in src_candidates:
                    if Path(f).stem == base_name:
                        target_file = f
                        break

            # If only a single source candidate exists, infer it
            if not target_file and len(src_candidates) == 1:
                target_file = src_candidates[0]

            # Fail cleanly rather than guessing random files (Problem 6 fix)
            if not target_file:
                task.status = TaskStatus.FAILED
                task.metadata["error"] = "Cannot determine target source file with confidence; aborting to prevent unsafe edits"
                task.updated_at = datetime.now(timezone.utc)
                return task

            # Reset file to clean baseline before attempting patch (prevents patch pileup, Problem 9 fix)
            if workspace:
                workspace.reset_file_to_baseline(target_file)

            original_code = reader.read_file(target_file)

            # Propose repair patch using generator
            try:
                repaired_code = self.patch_generator(target_file, original_code, diagnosis)
            except Exception as gen_err:
                task.status = TaskStatus.FAILED
                task.metadata["error"] = f"Patch synthesis error: {gen_err}"
                return task

            # Apply patch to isolated workspace
            patch_res = patch_engine.apply_patch(target_file, repaired_code)
            task.patches.append(patch_res)

            if not patch_res.applied:
                # Syntax error
                budget.record_error(patch_res.message)
                if budget.exhausted:
                    break
                budget.consume()
                continue

            # Verify in sandbox
            verify_run = sandbox.run(task.test_command)
            task.execution_history.append(verify_run)

            if verify_run.passed:
                # Success in isolated workspace! Ready for human approval / merge
                task.status = TaskStatus.SUCCESS
                task.metadata["verified_in_worktree"] = True
                task.updated_at = datetime.now(timezone.utc)
                return task

            # Test still failing -> record signature and consume budget
            if verify_run.failure_signature:
                budget.record_error(verify_run.failure_signature)

            if budget.exhausted:
                break

            budget.consume()

        # If loop exhausts without success, ensure target repo is completely clean
        task.status = TaskStatus.FAILED
        task.updated_at = datetime.now(timezone.utc)
        return task
