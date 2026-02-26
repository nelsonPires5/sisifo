"""
Task file utilities for canonical task markdown handling.

Manages YAML frontmatter parsing, task file creation, and repo path resolution.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import yaml


class TaskFileError(Exception):
    """Raised when task file operations fail."""

    pass


class TaskFrontmatter:
    """Parsed frontmatter from a task markdown file."""

    REQUIRED_KEYS = {"id", "repo"}
    OPTIONAL_KEYS = {"base", "branch", "worktree_path"}

    def __init__(self, data: Dict[str, str]):
        """Initialize with frontmatter data.

        Args:
            data: Dictionary with parsed frontmatter.

        Raises:
            TaskFileError: If required keys are missing.
        """
        missing = self.REQUIRED_KEYS - set(data.keys())
        if missing:
            raise TaskFileError(f"Missing required frontmatter keys: {missing}")

        self.id = data["id"]
        self.repo = self._resolve_repo_path(data["repo"])
        self.base = data.get("base", "main")
        self.branch = data.get("branch", "")
        self.worktree_path = data.get("worktree_path", "")

    @staticmethod
    def _resolve_repo_path(repo: str) -> str:
        """Resolve repo path: absolute path used as-is, short name resolved to ~/documents/repos/<name>.

        Args:
            repo: Absolute path or short repo name.

        Returns:
            Resolved absolute path to repo.

        Raises:
            TaskFileError: If repo path doesn't exist.
        """
        if repo.startswith("/"):
            # Absolute path - use as-is
            resolved = repo
        else:
            # Short name - resolve to ~/documents/repos/<name>
            home = os.path.expanduser("~")
            resolved = os.path.join(home, "documents", "repos", repo)

        # Normalize path
        resolved = os.path.normpath(resolved)

        # Verify repo exists
        if not os.path.isdir(resolved):
            raise TaskFileError(f"Repo path does not exist: {resolved}")

        return resolved

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for YAML serialization."""
        result = {
            "id": self.id,
            "repo": self.repo,
            "base": self.base,
        }
        if self.branch:
            result["branch"] = self.branch
        if self.worktree_path:
            result["worktree_path"] = self.worktree_path
        return result


def parse_frontmatter(content: str) -> Tuple[TaskFrontmatter, str]:
    """Parse YAML frontmatter from markdown content.

    Expected format:
    ---
    id: T-001
    repo: test
    base: main
    ---
    Task body here...

    Args:
        content: Full markdown content including frontmatter.

    Returns:
        Tuple of (TaskFrontmatter, body_text).

    Raises:
        TaskFileError: If frontmatter is invalid or missing.
    """
    data, body = parse_frontmatter_optional(content)
    if not data:
        raise TaskFileError(
            "Invalid frontmatter format. Must start with --- and contain YAML between --- delimiters."
        )

    frontmatter = TaskFrontmatter(data)
    return frontmatter, body


def parse_frontmatter_optional(content: str) -> Tuple[Dict[str, Any], str]:
    """Parse optional YAML frontmatter from markdown content.

    Returns an empty metadata dict when frontmatter is absent.

    Args:
        content: Full markdown content.

    Returns:
        Tuple of (metadata_dict, body_text).

    Raises:
        TaskFileError: If frontmatter delimiters exist but YAML is invalid.
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
    if not match:
        return {}, content

    yaml_text = match.group(1)
    body = match.group(2)

    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as e:
        raise TaskFileError(f"Invalid YAML in frontmatter: {e}")

    if not isinstance(data, dict):
        raise TaskFileError("Frontmatter must be a YAML dictionary.")

    return data, body


def create_canonical_task_file(
    task_id: str,
    repo: str,
    body: str,
    base: str = "main",
    branch: Optional[str] = None,
    worktree_path: Optional[str] = None,
) -> str:
    """Create canonical task markdown with frontmatter.

    Args:
        task_id: Task identifier (e.g., "T-001").
        repo: Repository path or short name.
        body: Task body/description text.
        base: Base branch name (default: "main").

    Returns:
        Full markdown content with frontmatter.

    Raises:
        TaskFileError: If repo cannot be resolved.
    """
    # Validate and resolve repo
    resolved_repo = TaskFrontmatter._resolve_repo_path(repo)

    # Build frontmatter
    frontmatter_data = {
        "id": task_id,
        "repo": resolved_repo,
        "base": base,
    }
    if branch:
        frontmatter_data["branch"] = branch
    if worktree_path:
        frontmatter_data["worktree_path"] = worktree_path

    yaml_content = yaml.dump(
        frontmatter_data, default_flow_style=False, sort_keys=False
    )

    # Build full content
    content = f"---\n{yaml_content}---\n{body}"

    return content


def write_task_file(
    task_id: str, content: str, tasks_dir: Optional[str] = None
) -> Path:
    """Write a task markdown file to the canonical location.

    Args:
        task_id: Task identifier (must match frontmatter id).
        content: Full markdown content with frontmatter.
        tasks_dir: Directory to write task file to (default: queue/tasks).

    Returns:
        Path to written file.

    Raises:
        TaskFileError: If task_id doesn't match frontmatter or write fails.
    """
    if tasks_dir is None:
        tasks_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "queue", "tasks"
        )

    # Ensure directory exists
    Path(tasks_dir).mkdir(parents=True, exist_ok=True)

    # Validate frontmatter matches task_id
    try:
        frontmatter, _ = parse_frontmatter(content)
    except TaskFileError as e:
        raise TaskFileError(f"Invalid content: {e}")

    if frontmatter.id != task_id:
        raise TaskFileError(
            f"Task ID mismatch: argument '{task_id}' vs frontmatter '{frontmatter.id}'"
        )

    # Write file
    file_path = Path(tasks_dir) / f"{task_id}.md"

    try:
        file_path.write_text(content, encoding="utf-8")
    except IOError as e:
        raise TaskFileError(f"Failed to write task file: {e}")

    return file_path


def read_task_file(
    task_id: str, tasks_dir: Optional[str] = None
) -> Tuple[TaskFrontmatter, str]:
    """Read and parse a canonical task markdown file.

    Args:
        task_id: Task identifier (e.g., "T-001").
        tasks_dir: Directory containing task files (default: queue/tasks).

    Returns:
        Tuple of (TaskFrontmatter, body_text).

    Raises:
        TaskFileError: If file not found or invalid.
    """
    if tasks_dir is None:
        tasks_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "queue", "tasks"
        )

    file_path = Path(tasks_dir) / f"{task_id}.md"

    if not file_path.exists():
        raise TaskFileError(f"Task file not found: {file_path}")

    try:
        content = file_path.read_text(encoding="utf-8")
    except IOError as e:
        raise TaskFileError(f"Failed to read task file: {e}")

    return parse_frontmatter(content)


def normalize_task_from_file(
    source_file: str,
    task_id: str,
    repo: str,
    base: str = "main",
    tasks_dir: Optional[str] = None,
    branch: str = "",
    worktree_path: str = "",
) -> Path:
    """Load a task from source markdown file and write to canonical location.

    Reads source file, extracts/validates frontmatter or uses provided metadata,
    and writes to queue/tasks/<task_id>.md.

    Args:
        source_file: Path to source markdown file.
        task_id: Task identifier (overrides source file if present).
        repo: Repository path or short name (overrides source file if present).
        base: Base branch name (default: "main").
        tasks_dir: Directory to write task file to (default: queue/tasks).

    Returns:
        Path to canonical task file.

    Raises:
        TaskFileError: If source file is invalid or write fails.
    """
    # Read source file
    source_path = Path(source_file)
    if not source_path.exists():
        raise TaskFileError(f"Source file not found: {source_file}")

    try:
        source_content = source_path.read_text(encoding="utf-8")
    except IOError as e:
        raise TaskFileError(f"Failed to read source file: {e}")

    # Try to parse frontmatter from source
    try:
        source_frontmatter, body = parse_frontmatter(source_content)
        # Use source values if not overridden
        final_id = task_id or source_frontmatter.id
        final_repo = repo or source_frontmatter.repo
        final_base = base if base != "main" else source_frontmatter.base
        final_branch = branch or source_frontmatter.branch
        final_worktree_path = worktree_path or source_frontmatter.worktree_path
    except TaskFileError:
        # No frontmatter in source - use body as-is
        if not repo:
            raise TaskFileError("Source file has no frontmatter; must provide --repo")
        body = source_content
        final_id = task_id or normalize_task_id_from_filename(source_path)
        final_repo = repo
        final_base = base
        final_branch = branch
        final_worktree_path = worktree_path

    # Create canonical content
    canonical_content = create_canonical_task_file(
        final_id,
        final_repo,
        body,
        final_base,
        branch=final_branch,
        worktree_path=final_worktree_path,
    )

    # Write to canonical location
    return write_task_file(final_id, canonical_content, tasks_dir)


def normalize_task_id_from_filename(source_path: Path) -> str:
    """Derive a task ID from source filename when ID is omitted."""
    stem = source_path.stem.strip()
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-")

    if not normalized:
        raise TaskFileError(f"Cannot derive task ID from filename: {source_path.name}")

    if not normalized.upper().startswith("T-"):
        normalized = f"T-{normalized}"

    return normalized.upper()


def _normalize_task_id_from_filename(source_path: Path) -> str:
    """Backward-compatible alias for internal usage."""
    return normalize_task_id_from_filename(source_path)


def ensure_queue_dirs() -> None:
    """Ensure queue directories and tasks.jsonl exist."""
    repo_root = Path(__file__).resolve().parent.parent
    queue_dir = repo_root / "queue"
    tasks_dir = queue_dir / "tasks"
    errors_dir = queue_dir / "errors"

    queue_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    errors_dir.mkdir(parents=True, exist_ok=True)

    (tasks_dir / ".gitkeep").touch(exist_ok=True)
    (errors_dir / ".gitkeep").touch(exist_ok=True)
    (queue_dir / "tasks.jsonl").touch(exist_ok=True)
