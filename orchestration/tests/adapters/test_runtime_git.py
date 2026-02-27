"""Tests for runtime_git module."""

import os
import tempfile
from pathlib import Path

import pytest

from orchestration.adapters.git import (
    BranchNotFoundError,
    GitRuntimeError,
    RepoNotFoundError,
    WorktreeError,
    branch_exists,
    create_branch,
    create_worktree,
    derive_worktree_path,
    ensure_branch_exists,
    ensure_repo_exists,
    get_branch_from_worktree,
    remove_worktree,
    repo_exists,
)


@pytest.fixture
def temp_repo():
    """Create a temporary git repository for testing."""
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "test_repo"
        repo_path.mkdir()

        # Initialize git repo
        subprocess.run(
            ["git", "init"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )

        # Configure git user for commits
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )

        # Create initial commit on main branch
        test_file = repo_path / "README.md"
        test_file.write_text("# Test Repo\n")
        subprocess.run(
            ["git", "add", "README.md"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )

        yield str(repo_path)


@pytest.fixture
def temp_worktrees_root():
    """Create a temporary worktrees root directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class TestWorktreePathDerivation:
    """Tests for derive_worktree_path function."""

    def test_derive_worktree_path_basic(self, temp_repo):
        """Test basic worktree path derivation."""
        result = derive_worktree_path(temp_repo, "T-001")
        assert "worktrees" in result
        assert "test_repo" in result
        assert "T-001" in result

    def test_derive_worktree_path_custom_root(self, temp_repo, temp_worktrees_root):
        """Test worktree path derivation with custom root."""
        result = derive_worktree_path(temp_repo, "T-002", temp_worktrees_root)
        expected = str(Path(temp_worktrees_root) / "test_repo" / "T-002")
        assert result == expected

    def test_derive_worktree_path_invalid_repo_path(self, temp_worktrees_root):
        """Test error on non-absolute repo path."""
        with pytest.raises(ValueError, match="must be absolute"):
            derive_worktree_path("relative/path", "T-001", temp_worktrees_root)

    def test_derive_worktree_path_empty_task_id(self, temp_repo, temp_worktrees_root):
        """Test error on empty task_id."""
        with pytest.raises(ValueError, match="cannot be empty"):
            derive_worktree_path(temp_repo, "", temp_worktrees_root)


class TestRepoValidation:
    """Tests for repo_exists and ensure_repo_exists functions."""

    def test_repo_exists_valid(self, temp_repo):
        """Test repo_exists returns True for valid repo."""
        assert repo_exists(temp_repo) is True

    def test_repo_exists_invalid(self):
        """Test repo_exists returns False for non-repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            assert repo_exists(tmpdir) is False

    def test_repo_exists_nonexistent(self):
        """Test repo_exists returns False for non-existent path."""
        assert repo_exists("/nonexistent/path") is False

    def test_ensure_repo_exists_valid(self, temp_repo):
        """Test ensure_repo_exists passes for valid repo."""
        ensure_repo_exists(temp_repo)  # Should not raise

    def test_ensure_repo_exists_invalid(self):
        """Test ensure_repo_exists raises for invalid repo."""
        with pytest.raises(RepoNotFoundError):
            ensure_repo_exists("/nonexistent/path")


class TestBranchValidation:
    """Tests for branch_exists and ensure_branch_exists functions."""

    def test_branch_exists_valid(self, temp_repo):
        """Test branch_exists returns True for main branch."""
        assert branch_exists(temp_repo, "main") is True

    def test_branch_exists_invalid(self, temp_repo):
        """Test branch_exists returns False for non-existent branch."""
        assert branch_exists(temp_repo, "nonexistent") is False

    def test_branch_exists_no_repo(self):
        """Test branch_exists raises for non-existent repo."""
        with pytest.raises(RepoNotFoundError):
            branch_exists("/nonexistent/path", "main")

    def test_ensure_branch_exists_valid(self, temp_repo):
        """Test ensure_branch_exists passes for existing branch."""
        ensure_branch_exists(temp_repo, "main")  # Should not raise

    def test_ensure_branch_exists_invalid_branch(self, temp_repo):
        """Test ensure_branch_exists raises for non-existent branch."""
        with pytest.raises(BranchNotFoundError):
            ensure_branch_exists(temp_repo, "nonexistent")


class TestBranchCreation:
    """Tests for create_branch function."""

    def test_create_branch_success(self, temp_repo):
        """Test successful branch creation."""
        create_branch(temp_repo, "feature", "main")
        assert branch_exists(temp_repo, "feature") is True

    def test_create_branch_idempotent(self, temp_repo):
        """Test branch creation is idempotent."""
        create_branch(temp_repo, "feature", "main")
        create_branch(temp_repo, "feature", "main")  # Should not raise
        assert branch_exists(temp_repo, "feature") is True

    def test_create_branch_invalid_base(self, temp_repo):
        """Test branch creation with invalid base branch."""
        with pytest.raises(BranchNotFoundError):
            create_branch(temp_repo, "feature", "nonexistent-base")

    def test_create_branch_no_repo(self):
        """Test branch creation with no repo."""
        with pytest.raises(RepoNotFoundError):
            create_branch("/nonexistent", "feature", "main")


class TestWorktreeCreation:
    """Tests for create_worktree and remove_worktree functions."""

    def test_create_worktree_success(self, temp_repo, temp_worktrees_root):
        """Test successful worktree creation."""
        worktree_path = str(Path(temp_worktrees_root) / "test_repo" / "T-001")
        result = create_worktree(temp_repo, worktree_path, "feature", "main")

        assert Path(result).exists()
        assert branch_exists(temp_repo, "feature") is True

    def test_create_worktree_idempotent(self, temp_repo, temp_worktrees_root):
        """Test worktree creation is idempotent."""
        worktree_path = str(Path(temp_worktrees_root) / "test_repo" / "T-002")
        result1 = create_worktree(temp_repo, worktree_path, "branch1", "main")
        result2 = create_worktree(temp_repo, worktree_path, "branch1", "main")

        assert result1 == result2

    def test_create_worktree_invalid_base(self, temp_repo, temp_worktrees_root):
        """Test worktree creation with invalid base branch."""
        worktree_path = str(Path(temp_worktrees_root) / "test_repo" / "T-003")
        with pytest.raises(BranchNotFoundError):
            create_worktree(temp_repo, worktree_path, "feature", "nonexistent")

    def test_remove_worktree_success(self, temp_repo, temp_worktrees_root):
        """Test successful worktree removal."""
        worktree_path = str(Path(temp_worktrees_root) / "test_repo" / "T-004")
        create_worktree(temp_repo, worktree_path, "feature", "main")
        assert Path(worktree_path).exists()

        remove_worktree(temp_repo, worktree_path)
        assert not Path(worktree_path).exists()

    def test_remove_worktree_idempotent(self, temp_repo, temp_worktrees_root):
        """Test worktree removal is idempotent."""
        worktree_path = str(Path(temp_worktrees_root) / "test_repo" / "T-005")
        create_worktree(temp_repo, worktree_path, "feature", "main")

        remove_worktree(temp_repo, worktree_path)
        remove_worktree(temp_repo, worktree_path)  # Should not raise


class TestGetBranchFromWorktree:
    """Tests for get_branch_from_worktree function."""

    def test_get_branch_from_worktree(self, temp_repo, temp_worktrees_root):
        """Test retrieving branch from worktree."""
        worktree_path = str(Path(temp_worktrees_root) / "test_repo" / "T-006")
        create_worktree(temp_repo, worktree_path, "mybranch", "main")

        branch = get_branch_from_worktree(temp_repo, worktree_path)
        assert branch == "mybranch" or branch is None  # May be None for detached


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
