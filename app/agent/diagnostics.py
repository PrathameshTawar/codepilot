"""Diagnostic engine for parsing pytest and test failures to extract structured error evidence."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DiagnosticReport(BaseModel):
    """Structured failure diagnosis extracted from test output."""

    failing_tests: List[str] = Field(default_factory=list)
    primary_error: Optional[str] = None
    failing_file: Optional[str] = None
    line_number: Optional[int] = None
    assertion_details: Optional[str] = None
    summary: str = ""


class DiagnosticEngine:
    """Parses execution and pytest outputs into structured, actionable repair context."""

    @staticmethod
    def diagnose(stdout: str, stderr: str) -> DiagnosticReport:
        combined = f"{stdout}\n{stderr}"
        report = DiagnosticReport()

        # 1. Extract failing test identifiers (e.g. FAILED tests/test_calc.py::test_add - AssertionError)
        failing_tests = re.findall(r"FAILED\s+([^\s:]+::[^\s\-]+)", combined)
        if not failing_tests:
            # Fallback for plain filename or module format
            failing_tests = re.findall(r"FAILED\s+([^\s:]+(?:::[\w]+)?)", combined)
        report.failing_tests = list(dict.fromkeys(failing_tests))

        # 2. Extract primary exception name and message
        # Format A: Pytest summary line "FAILED tests/test_foo.py::test_bar - AssertionError: assert 1 == 2"
        summary_exc = re.search(r"FAILED\s+[^\r\n]*-\s+([A-Z][a-zA-Z0-9]+(?:Error|Exception):\s*[^\r\n]*)", combined)
        if summary_exc:
            report.primary_error = summary_exc.group(1).strip()

        # Format B: Explicit 'E   ' prefixed lines in pytest failure sections
        if not report.primary_error:
            e_exc = re.search(r"^E\s+([A-Z][a-zA-Z0-9]+(?:Error|Exception):\s*[^\r\n]*)", combined, re.MULTILINE)
            if e_exc:
                report.primary_error = e_exc.group(1).strip()

        # Format C: Standard Python exception line: e.g. "AssertionError: 1 != 2"
        if not report.primary_error:
            std_exc = re.search(r"\b([A-Z][a-zA-Z0-9]+(?:Error|Exception):\s*[^\r\n]*)", combined)
            if std_exc:
                report.primary_error = std_exc.group(1).strip()

        # 3. Extract assertion detail lines
        assert_lines = re.findall(r"^E\s+(.*)", combined, re.MULTILINE)
        if assert_lines:
            report.assertion_details = "\n".join(line.strip() for line in assert_lines[:5])
            if not report.primary_error:
                first_assert = assert_lines[0].strip()
                if first_assert.startswith("assert "):
                    report.primary_error = f"AssertionError: {first_assert}"
                else:
                    report.primary_error = f"AssertionError: {first_assert}"

        # 4. Extract failing file and line number
        # Look for pytest style: "path/to/file.py:42: in func" or "path/to/file.py:42: AssertionError"
        py_tracebacks = re.findall(r"([a-zA-Z0-9_\-\.\/\\]+\.py):(\d+):(?:\s+in\s+[a-zA-Z0-9_]+|\s+[A-Z]\w*Error|\s*AssertionError)?", combined)
        # Look for standard style: File "...", line 42, in func
        std_tracebacks = re.findall(r'File\s+"([^"]+\.py)",\s+line\s+(\d+)', combined)

        candidates = py_tracebacks + std_tracebacks

        target_file = None
        target_line = None

        if candidates:
            # Prioritize non-test source files (where the code bug actually is)
            source_candidates = [
                (f, int(line)) for f, line in candidates
                if not Path(f).name.startswith("test_") and not Path(f).name.endswith("_test.py")
            ]
            if source_candidates:
                target_file, target_line = source_candidates[-1]
            else:
                target_file, target_line = candidates[0][0], int(candidates[0][1])

        if target_file:
            report.failing_file = target_file
            report.line_number = target_line
        elif report.failing_tests:
            first_test_file = report.failing_tests[0].split("::")[0]
            report.failing_file = first_test_file

        # 5. Format concise summary
        if report.failing_tests or report.primary_error:
            test_str = ", ".join(report.failing_tests) if report.failing_tests else "Unknown test"
            err_str = report.primary_error or "Test execution failed"
            report.summary = f"Failure in [{test_str}]: {err_str}"
            if report.assertion_details:
                report.summary += f"\nEvidence:\n{report.assertion_details}"
        else:
            report.summary = "No explicit test assertion failure detected; possible environment or syntax issue."

        return report
