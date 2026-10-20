"""Unit tests for PatchEngine AST validation, diffing, and rollback."""

from pathlib import Path
import pytest
from app.patch.engine import PatchEngine
from app.repository.reader import RepositoryReader


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "patch_repo"
    repo.mkdir()
    (repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    return repo


def test_create_diff(temp_repo: Path):
    reader = RepositoryReader(temp_repo)
    engine = PatchEngine(reader)
    orig = "def add(a, b):\n    return a + b\n"
    mod = "def add(a, b):\n    return a + b + 1\n"
    diff = engine.create_diff("calculator.py", orig, mod)
    assert "--- a/calculator.py" in diff
    assert "+++ b/calculator.py" in diff
    assert "+    return a + b + 1" in diff


def test_syntax_validation_rejects_broken_python(temp_repo: Path):
    reader = RepositoryReader(temp_repo)
    engine = PatchEngine(reader)
    is_valid, err = engine.validate_syntax("def broken_func(:", "test.py")
    assert is_valid is False
    assert err is not None
    assert "SyntaxError" in err


def test_apply_patch_rejects_syntax_error(temp_repo: Path):
    reader = RepositoryReader(temp_repo)
    engine = PatchEngine(reader)
    broken_code = "def add(a, b):\n    return a + "
    result = engine.apply_patch("calculator.py", broken_code)
    assert result.applied is False
    assert "Rejected: invalid syntax" in result.message

    # Ensure original file was NOT overwritten
    current = reader.read_file("calculator.py")
    assert "return a + b" in current


def test_apply_patch_success_and_rollback(temp_repo: Path):
    reader = RepositoryReader(temp_repo)
    engine = PatchEngine(reader)
    original_code = reader.read_file("calculator.py")
    new_code = "def add(a, b):\n    return (a + b) * 2\n"

    result = engine.apply_patch("calculator.py", new_code)
    assert result.applied is True
    assert "Patch applied and verified cleanly" in result.message
    assert reader.read_file("calculator.py") == new_code

    # Rollback to original
    engine.rollback("calculator.py", original_code)
    assert reader.read_file("calculator.py") == original_code


def test_patch_path_traversal_blocked(temp_repo: Path):
    reader = RepositoryReader(temp_repo)
    engine = PatchEngine(reader)
    with pytest.raises(PermissionError):
        engine.apply_patch("../../escaped.py", "x = 1")
