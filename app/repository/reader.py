"""Safe repository reader with path traversal prevention and bounded file inspection."""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class RepositoryReader:
    """Safely inspects files, lists directories, and searches code within an isolated repository root."""

    EXCLUDED_DIRS = {
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        "node_modules",
        "artifacts",
        "dist",
        "build",
        ".ruff_cache",
    }

    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir).resolve()
        if not self.root_dir.exists() or not self.root_dir.is_dir():
            raise ValueError(f"Repository root directory does not exist or is not a directory: {self.root_dir}")

    def resolve_safe_path(self, relative_path: str | Path) -> Path:
        """Resolves relative path and verifies it strictly resides inside the repository root.

        Raises:
            PermissionError: If path traversal outside the repository root is attempted.
        """
        # Normalize and strip leading slashes to prevent escape
        clean_rel = str(relative_path).lstrip("/\\")
        candidate = (self.root_dir / clean_rel).resolve()

        try:
            candidate.relative_to(self.root_dir)
        except ValueError as err:
            raise PermissionError(f"Access denied: Path traversal outside repository root detected: {relative_path}") from err

        return candidate

    def list_files(self, extensions: Optional[List[str]] = None, max_files: int = 200) -> List[str]:
        """Lists files in the repository, skipping excluded directories."""
        files_found: List[str] = []
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in self.EXCLUDED_DIRS and not d.startswith(".")]
            for file in files:
                if len(files_found) >= max_files:
                    return files_found
                file_path = Path(root) / file
                rel_path = file_path.relative_to(self.root_dir).as_posix()
                if extensions:
                    if any(file.endswith(ext) for ext in extensions):
                        files_found.append(rel_path)
                else:
                    files_found.append(rel_path)
        return files_found

    def read_file(self, relative_path: str, max_bytes: int = 150_000) -> str:
        """Reads text content of a repository file with strict size bounds."""
        target_path = self.resolve_safe_path(relative_path)
        if not target_path.exists():
            raise FileNotFoundError(f"File not found in repository: {relative_path}")
        if target_path.is_dir():
            raise IsADirectoryError(f"Target path is a directory, not a file: {relative_path}")

        file_size = target_path.stat().st_size
        if file_size > max_bytes:
            raise ValueError(f"File size ({file_size} bytes) exceeds limit ({max_bytes} bytes): {relative_path}")

        return target_path.read_text(encoding="utf-8", errors="replace")

    def search_text(self, pattern: str, case_sensitive: bool = False, max_matches: int = 30) -> List[Dict[str, Any]]:
        """Searches files in the repository for a regex or string pattern."""
        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)
        matches: List[Dict[str, Any]] = []

        for rel_path in self.list_files(extensions=[".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml"]):
            try:
                content = self.read_file(rel_path)
            except Exception:
                continue

            for line_no, line in enumerate(content.splitlines(), start=1):
                if regex.search(line):
                    matches.append(
                        {
                            "file": rel_path,
                            "line_number": line_no,
                            "line": line.strip(),
                        }
                    )
                    if len(matches) >= max_matches:
                        return matches
        return matches

    def find_test_files(self) -> List[str]:
        """Finds Python test files in the repository."""
        all_py = self.list_files(extensions=[".py"])
        return [f for f in all_py if Path(f).name.startswith("test_") or Path(f).name.endswith("_test.py")]
