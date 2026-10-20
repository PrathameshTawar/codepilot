"""Diagnostic engine for parsing pytest failures and extracting targeted error evidence."""

import re
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
    """Parses raw execution and pytest output to produce concise, actionable repair context."""

    @staticmethod
    def diagnose(stdout: str, stderr: str) -> DiagnosticReport:
        combined = f"{stdout}\n{stderr}"
        report = DiagnosticReport()

        # Find failing test names: e.g. "FAILED tests/test_calc.py::test_add - AssertionError"
        failing_tests = re.findall(r"FAILED\s+([^\s:]+::\w+)", combined)
        if not failing_tests:
            # Alternate pytest format: "FAILED tests/test_calc.py"
            failing_tests = re.findall(r"FAILED\s+([^\s]+)", combined)
        report.failing_tests = list(dict.fromkeys(failing_tests))

        # Find explicit exception: e.g. "AssertionError: assert 10 == 20" or "ZeroDivisionError: division by zero"
        exc_match = re.search(r"((?:[A-Za-z]+Error|Exception):\s*[^\r\n]*)", combined)
        if exc_match:
            report.primary_error = exc_match.group(1).strip()

        # Find assertion detail lines (e.g., E       assert -1900 == 80)
        assert_lines = re.findall(r"(E\s{3,}.*)", combined)
        if assert_lines:
            report.assertion_details = "\n".join(line.strip() for line in assert_lines[:5])
            # If pytest formatted without explicit "AssertionError:" word, infer from "assert ..."
            if not report.primary_error:
                first_assert = re.sub(r"^E\s+", "", assert_lines[0]).strip()
                report.primary_error = f"AssertionError: {first_assert}"

        # Find file and line from traceback: e.g. File "...", line 12, in ...
        tb_match = re.search(r'File\s+"([^"]+)",\s+line\s+(\d+)', combined)
        if tb_match:
            report.failing_file = tb_match.group(1)
            report.line_number = int(tb_match.group(2))
        elif report.failing_tests:
            # Infer test file from test identifier: e.g. tests/test_discount.py::test_percentage_discount
            first_test_file = report.failing_tests[0].split("::")[0]
            report.failing_file = first_test_file

        # Generate a concise summary
        if report.failing_tests or report.primary_error:
            test_str = ", ".join(report.failing_tests) if report.failing_tests else "Unknown test"
            err_str = report.primary_error or "Test execution failed"
            report.summary = f"Failure in [{test_str}]: {err_str}"
            if report.assertion_details:
                report.summary += f"\nEvidence:\n{report.assertion_details}"
        else:
            report.summary = "No explicit test assertion failure detected; possible environment or syntax issue."

        return report
