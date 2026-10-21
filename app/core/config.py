"""Application configuration and environment settings for CodePilot."""

import os
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for CodePilot autonomous coding platform."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ENVIRONMENT: str = "development"
    API_KEY: Optional[str] = None  # If set, enforced on /tasks and /approve

    # Agent execution limits
    MAX_RETRY_ATTEMPTS: int = 3
    DEFAULT_EXECUTION_TIMEOUT: float = 30.0
    MAX_OUTPUT_BYTES: int = 150_000

    # Model inference settings
    MODEL_PROVIDER: str = "mock"  # "ollama", "openai", "anthropic", "mock"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    MODEL_NAME: str = "qwen2.5-coder:7b"
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    # Security: Registered repository paths allowed for modification
    # Empty list means any path within current workspace or subdirectories of workspace
    REGISTERED_REPO_ROOTS: List[str] = []

    # Command allowlist for sandbox execution
    COMMAND_ALLOWLIST: List[str] = [
        "pytest",
        "python -m pytest",
        "python -m unittest",
    ]

    # Persistent task storage path (SQLite)
    TASK_DB_PATH: str = "codepilot_tasks.db"

    # Container isolation settings
    DOCKER_SANDBOX_ENABLED: bool = False
    DOCKER_IMAGE: str = "python:3.11-slim"

    @property
    def allowed_repo_roots(self) -> List[Path]:
        """Resolves configured allowed repository root paths."""
        if not self.REGISTERED_REPO_ROOTS:
            # Default to workspace root
            return [Path.cwd().resolve()]
        return [Path(p).resolve() for p in self.REGISTERED_REPO_ROOTS]

    def is_repo_allowed(self, target_path: str | Path) -> bool:
        """Verifies target repo path is contained within registered roots."""
        resolved = Path(target_path).resolve()
        for root in self.allowed_repo_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
            if resolved == root:
                return True
        return False


settings = Settings()
