"""Unit tests for safe RepositoryReader and path traversal defenses."""

from pathlib import Path
import pytest
from app.repository.reader import RepositoryReader


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """Creates a temporary sample repository structure."""
    repo = tmp_path / "sample_project"
    repo.mkdir()

    src = repo / "src"
    src.mkdir()
    (src / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )

    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_calculator.py").write_text(
        "from src.calculator import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )

    # Excluded directory
    git_dir = repo / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("dummy git content", encoding="utf-8")

    return repo


def test_list_files_skips_excluded_dirs(sample_repo: Path):
    reader = RepositoryReader(sample_repo)
    files = reader.list_files()
    assert "src/calculator.py" in files
    assert "tests/test_calculator.py" in files
    assert not any(".git" in f for f in files)


def test_read_file_success(sample_repo: Path):
    reader = RepositoryReader(sample_repo)
    content = reader.read_file("src/calculator.py")
    assert "def add(a, b):" in content


def test_path_traversal_blocked(sample_repo: Path):
    reader = RepositoryReader(sample_repo)
    with pytest.raises(PermissionError, match="Path traversal outside repository root detected"):
        reader.resolve_safe_path("../../outside_file.txt")

    with pytest.raises(PermissionError, match="Path traversal outside repository root detected"):
        reader.resolve_safe_path("../sample_project/../../secret")


def test_read_file_size_limit(sample_repo: Path):
    reader = RepositoryReader(sample_repo)
    with pytest.raises(ValueError, match="exceeds limit"):
        reader.read_file("src/calculator.py", max_bytes=10)


def test_search_text(sample_repo: Path):
    reader = RepositoryReader(sample_repo)
    results = reader.search_text("multiply")
    assert len(results) == 1
    assert results[0]["file"] == "src/calculator.py"
    assert results[0]["line_number"] == 4
    assert "def multiply" in results[0]["line"]


def test_find_test_files(sample_repo: Path):
    reader = RepositoryReader(sample_repo)
    test_files = reader.find_test_files()
    assert "tests/test_calculator.py" in test_files
    assert "src/calculator.py" not in test_files
