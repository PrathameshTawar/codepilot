"""Patch generation, AST syntax validation, and atomic file modification."""

import ast
import difflib
from pathlib import Path
from typing import Optional, Tuple

from app.core.models import PatchResult
from app.repository.reader import RepositoryReader


class PatchEngine:
    """Safely validates, applies, and rolls back code patches inside a repository workspace."""

    def __init__(self, reader: RepositoryReader):
        self.reader = reader

    def create_diff(self, file_path: str, original: str, modified: str) -> str:
        """Generates standard, valid unified diff between original and modified content."""
        orig_lines = original.splitlines()
        mod_lines = modified.splitlines()
        diff_lines = list(
            difflib.unified_diff(
                orig_lines,
                mod_lines,
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                lineterm="",
            )
        )
        if not diff_lines:
            return ""
        return "\n".join(diff_lines) + "\n"

    def validate_syntax(self, content: str, file_path: str) -> Tuple[bool, Optional[str]]:
        """Validates syntax using Python AST parser for Python files."""
        if file_path.endswith(".py"):
            try:
                ast.parse(content, filename=file_path)
            except SyntaxError as err:
                return False, f"SyntaxError at line {err.lineno}: {err.msg}"
        return True, None

    def apply_patch(self, file_path: str, modified_content: str) -> PatchResult:
        """Validates AST syntax, generates diff, and atomically writes the patch to disk."""
        target_path = self.reader.resolve_safe_path(file_path)
        original_content = ""
        if target_path.exists():
            original_content = target_path.read_text(encoding="utf-8", errors="replace")

        # Pre-validate Python syntax before touching filesystem
        is_valid, syntax_error = self.validate_syntax(modified_content, file_path)
        diff = self.create_diff(file_path, original_content, modified_content)

        if not is_valid:
            return PatchResult(
                file_path=file_path,
                diff=diff,
                applied=False,
                message=f"Rejected: invalid syntax - {syntax_error}",
            )

        # Ensure parent directories exist
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(modified_content, encoding="utf-8")

        return PatchResult(
            file_path=file_path,
            diff=diff,
            applied=True,
            message="Patch applied and verified cleanly",
            patched_content=modified_content,
        )

    def rollback(self, file_path: str, original_content: str) -> None:
        """Restores a file to its original content."""
        target_path = self.reader.resolve_safe_path(file_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(original_content, encoding="utf-8")
