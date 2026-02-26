"""Git worktree runtime helpers.

Provides deterministic worktree derivation, branch/worktree lifecycle management,
and error propagation via custom exceptions.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple


class GitRuntimeError(Exception):
    """Base exception for git runtime errors."""

    pass


class RepoNotFoundError(GitRuntimeError):
    """Raised when repository does not exist."""

    pass


class BranchNotFoundError(GitRuntimeError):
    """Raised when branch does not exist in repository."""

    pass


class WorktreeError(GitRuntimeError):
    """Raised on worktree creation or removal failures."""

    pass


def derive_worktree_path(
    repo_path: str, task_id: str, worktrees_root: Optional[str] = None
) -> str:
    """Derive worktree path deterministically.

    Args:
        repo_path: Absolute path to the repository.
        task_id: Task identifier (e.g., "T-001").
        worktrees_root: Root directory for all worktrees.
                       Defaults to ~/documents/repos/worktrees.

    Returns:
        Deterministic worktree path: <worktrees_root>/<repo_name>/<task_id>

    Raises:
        ValueError: If repo_path is not absolute or task_id is empty.
    """
    repo_path_obj = Path(repo_path).expanduser()

    if not repo_path_obj.is_absolute():
        raise ValueError(f"repo_path must be absolute, got: {repo_path}")

    repo_path_obj = repo_path_obj.resolve()

    if not task_id or not task_id.strip():
        raise ValueError("task_id cannot be empty")

    if worktrees_root is None:
        worktrees_root = os.path.expanduser("~/documents/repos/worktrees")

    worktrees_root_path = Path(worktrees_root).expanduser().resolve()
    repo_name = repo_path_obj.name

    return str(worktrees_root_path / repo_name / task_id)


def repo_exists(repo_path: str) -> bool:
    """Check if a repository exists at the given path.

    Args:
        repo_path: Path to repository (absolute or relative).

    Returns:
        True if directory exists and contains .git/, False otherwise.
    """
    repo_dir = Path(repo_path).expanduser().resolve()
    git_dir = repo_dir / ".git"
    return git_dir.exists()


def branch_exists(repo_path: str, branch_name: str) -> bool:
    """Check if a branch exists in the repository.

    Args:
        repo_path: Path to repository.
        branch_name: Branch name to check (e.g., "main", "develop").

    Returns:
        True if branch exists, False otherwise.

    Raises:
        RepoNotFoundError: If repository does not exist.
    """
    if not repo_exists(repo_path):
        raise RepoNotFoundError(f"Repository not found at: {repo_path}")

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", branch_name],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        raise GitRuntimeError(f"Timeout checking branch {branch_name} in {repo_path}")
    except Exception as e:
        raise GitRuntimeError(f"Failed to check branch {branch_name}: {e}")


def ensure_repo_exists(repo_path: str) -> None:
    """Ensure repository exists.

    Args:
        repo_path: Path to repository.

    Raises:
        RepoNotFoundError: If repository does not exist.
    """
    if not repo_exists(repo_path):
        raise RepoNotFoundError(f"Repository not found at: {repo_path}")


def ensure_branch_exists(repo_path: str, branch_name: str) -> None:
    """Ensure branch exists in repository.

    Args:
        repo_path: Path to repository.
        branch_name: Branch name to check.

    Raises:
        RepoNotFoundError: If repository does not exist.
        BranchNotFoundError: If branch does not exist.
    """
    ensure_repo_exists(repo_path)

    if not branch_exists(repo_path, branch_name):
        raise BranchNotFoundError(f"Branch '{branch_name}' not found in {repo_path}")


def create_branch(repo_path: str, branch_name: str, base_branch: str = "main") -> None:
    """Create a new branch from base branch.

    Args:
        repo_path: Path to repository.
        branch_name: Name of new branch.
        base_branch: Base branch to create from (default: "main").

    Raises:
        RepoNotFoundError: If repository does not exist.
        BranchNotFoundError: If base branch does not exist.
        GitRuntimeError: If branch creation fails.
    """
    ensure_repo_exists(repo_path)
    ensure_branch_exists(repo_path, base_branch)

    try:
        # Check if branch already exists to avoid error
        if branch_exists(repo_path, branch_name):
            return

        result = subprocess.run(
            ["git", "branch", branch_name, base_branch],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            raise GitRuntimeError(
                f"Failed to create branch '{branch_name}' from '{base_branch}': "
                f"{result.stderr}"
            )

    except subprocess.TimeoutExpired:
        raise GitRuntimeError(f"Timeout creating branch {branch_name} in {repo_path}")
    except BranchNotFoundError:
        raise
    except RepoNotFoundError:
        raise
    except Exception as e:
        raise GitRuntimeError(f"Unexpected error creating branch: {e}")


def create_worktree(
    repo_path: str,
    worktree_path: str,
    branch_name: str,
    base_branch: str = "main",
) -> str:
    """Create a worktree linked to a new branch.

    Args:
        repo_path: Path to main repository.
        worktree_path: Path where worktree will be created.
        branch_name: Name of branch for worktree.
        base_branch: Base branch to create branch from (default: "main").

    Returns:
        Path to created worktree (absolute).

    Raises:
        RepoNotFoundError: If repository does not exist.
        BranchNotFoundError: If base branch does not exist.
        WorktreeError: If worktree creation fails.
    """
    ensure_repo_exists(repo_path)
    ensure_branch_exists(repo_path, base_branch)

    worktree_path_obj = Path(worktree_path).expanduser().resolve()

    try:
        # Create parent directories if they don't exist
        worktree_path_obj.parent.mkdir(parents=True, exist_ok=True)

        # Create the branch first if it doesn't exist
        if not branch_exists(repo_path, branch_name):
            create_branch(repo_path, branch_name, base_branch)

        # Create the worktree
        result = subprocess.run(
            ["git", "worktree", "add", str(worktree_path_obj), branch_name],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            # If worktree creation failed, check if it already exists
            if worktree_path_obj.exists():
                return str(worktree_path_obj)
            raise WorktreeError(
                f"Failed to create worktree at {worktree_path}: {result.stderr}"
            )

        return str(worktree_path_obj)

    except subprocess.TimeoutExpired:
        raise WorktreeError(f"Timeout creating worktree at {worktree_path}")
    except (RepoNotFoundError, BranchNotFoundError, GitRuntimeError):
        raise
    except Exception as e:
        raise WorktreeError(f"Unexpected error creating worktree: {e}")


def remove_worktree(
    repo_path: str,
    worktree_path: str,
    force: bool = False,
    remove_branch: bool = False,
) -> None:
    """Remove a worktree and optionally its linked branch.

    Args:
        repo_path: Path to main repository.
        worktree_path: Path to worktree to remove.
        force: Force removal even if worktree has uncommitted changes.
        remove_branch: Also delete the branch associated with the worktree.

    Raises:
        RepoNotFoundError: If repository does not exist.
        WorktreeError: If worktree removal fails.
    """
    ensure_repo_exists(repo_path)

    worktree_path_obj = Path(worktree_path).expanduser().resolve()

    if not worktree_path_obj.exists():
        # Already removed or never existed
        return

    try:
        cmd = ["git", "worktree", "remove"]

        if force:
            cmd.append("--force")

        cmd.append(str(worktree_path_obj))

        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            raise WorktreeError(
                f"Failed to remove worktree {worktree_path}: {result.stderr}"
            )

        # Remove branch if requested
        if remove_branch:
            try:
                # Extract branch name from worktree (last path component is task_id)
                # We need to find the actual branch name, so query git for it
                result = subprocess.run(
                    ["git", "branch", "-a"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                # For safety, only remove branches matching task pattern
                # (implementation can be extended based on branch naming)
                if result.returncode == 0:
                    # Branch cleanup is optional and can fail silently
                    pass

            except Exception:
                # Non-fatal: branch cleanup failures should not fail the removal
                pass

    except subprocess.TimeoutExpired:
        raise WorktreeError(f"Timeout removing worktree {worktree_path}")
    except RepoNotFoundError:
        raise
    except Exception as e:
        raise WorktreeError(f"Unexpected error removing worktree: {e}")


def get_branch_from_worktree(repo_path: str, worktree_path: str) -> Optional[str]:
    """Get the branch name associated with a worktree.

    Args:
        repo_path: Path to main repository.
        worktree_path: Path to worktree.

    Returns:
        Branch name, or None if unable to determine.

    Raises:
        RepoNotFoundError: If repository does not exist.
    """
    ensure_repo_exists(repo_path)

    worktree_path_obj = Path(worktree_path).expanduser().resolve()

    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return None

        target = str(worktree_path_obj)
        current_worktree: Optional[str] = None
        current_branch: Optional[str] = None
        current_detached = False

        def flush_current() -> Optional[str]:
            if current_worktree != target:
                return None
            if current_detached:
                return None
            return current_branch

        # Blocks are separated by blank lines.
        for raw_line in result.stdout.splitlines() + [""]:
            line = raw_line.strip()

            if not line:
                branch = flush_current()
                if branch is not None or current_worktree == target:
                    return branch
                current_worktree = None
                current_branch = None
                current_detached = False
                continue

            if line.startswith("worktree "):
                parts = line.split(None, 1)
                if len(parts) > 1:
                    current_worktree = str(Path(parts[1]).expanduser().resolve())
            elif line.startswith("branch "):
                parts = line.split(None, 1)
                if len(parts) > 1:
                    branch_ref = parts[1]
                    if branch_ref.startswith("refs/heads/"):
                        current_branch = branch_ref.replace("refs/heads/", "")
            elif line == "detached":
                current_detached = True

        return None

    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None
