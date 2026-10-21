"""Isolated workspace and worktree manager for sandboxed patch evaluation and zero-side-effect repairs."""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional
from app.core.models import PatchResult


class IsolatedWorkspace:
    """Manages an isolated copy of a repository for experimentation, testing, and atomic merge on approval."""

    EXCLUDED_PATTERNS = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "artifacts",
        "dist",
        "build",
    }

    def __init__(self, target_repo_path: str | Path, workspace_id: str):
        self.target_repo_path = Path(target_repo_path).resolve()
        self.workspace_id = workspace_id
        self.temp_root = Path(tempfile.gettempdir()) / "codepilot_workspaces" / workspace_id
        self.temp_root.mkdir(parents=True, exist_ok=True)

        self._baseline_snapshots: Dict[str, str] = {}
        self._initialize_copy()

    def _initialize_copy(self) -> None:
        """Copies non-ignored repository contents into the isolated temporary directory."""
        for root, dirs, files in os.walk(self.target_repo_path):
            dirs[:] = [d for d in dirs if d not in self.EXCLUDED_PATTERNS and not d.startswith(".")]
            rel_dir = Path(root).relative_to(self.target_repo_path)
            dest_dir = self.temp_root / rel_dir
            dest_dir.mkdir(parents=True, exist_ok=True)

            for file in files:
                src_file = Path(root) / file
                dest_file = dest_dir / file
                shutil.copy2(src_file, dest_file)

                # Record baseline text snapshot for Python and config files
                if file.endswith((".py", ".json", ".yaml", ".yml", ".toml", ".txt", ".md")):
                    try:
                        rel_path = (rel_dir / file).as_posix()
                        self._baseline_snapshots[rel_path] = dest_file.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        pass

    def reset_file_to_baseline(self, relative_path: str) -> None:
        """Resets a modified file back to its pristine baseline state to prevent failed patches from piling up."""
        clean_rel = relative_path.replace("\\", "/").lstrip("/")
        if clean_rel in self._baseline_snapshots:
            target_path = self.temp_root / clean_rel
            target_path.write_text(self._baseline_snapshots[clean_rel], encoding="utf-8")

    def apply_patch_to_target_repo(self, patch: PatchResult) -> bool:
        """Merges a human-approved patch from the isolated workspace into the real target repository."""
        clean_rel = patch.file_path.replace("\\", "/").lstrip("/")
        isolated_file = self.temp_root / clean_rel
        real_file = self.target_repo_path / clean_rel

        if not isolated_file.exists():
            return False

        real_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(isolated_file, real_file)
        return True

    def cleanup(self) -> None:
        """Removes the isolated temporary workspace directory."""
        if self.temp_root.exists():
            try:
                shutil.rmtree(self.temp_root, ignore_errors=True)
            except Exception:
                pass
