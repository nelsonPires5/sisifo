"""
taskq add command implementation.

Handles adding new tasks to the queue from inline task or task files.
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Handle both absolute and relative imports
try:
    from orchestration.core.naming import derive_branch_name
    from orchestration.constants import DEFAULT_BASE_BRANCH
    from orchestration.support.task_files import (
        create_canonical_task_file,
        write_task_file,
        read_task_file,
        parse_frontmatter_optional,
        normalize_task_id_from_filename,
        TaskFrontmatter,
        TaskFileError,
    )
    from orchestration.core.models import TaskRecord
except ImportError:
    from core.naming import derive_branch_name
    from constants import DEFAULT_BASE_BRANCH
    from support.task_files import (
        create_canonical_task_file,
        write_task_file,
        read_task_file,
        parse_frontmatter_optional,
        normalize_task_id_from_filename,
        TaskFrontmatter,
        TaskFileError,
    )
    from core.models import TaskRecord


def _derive_branch_name(task_id: str) -> str:
    """Derive default branch name from task ID."""
    return derive_branch_name(task_id)


def _format_task_file_path(task_file_path: Path) -> str:
    """Store task file path relative to repo root when possible."""
    resolved = task_file_path.expanduser().resolve()
    repo_root = Path(__file__).resolve().parent.parent.parent
    try:
        return str(resolved.relative_to(repo_root))
    except ValueError:
        return str(resolved)


def _resolve_worktree_path(worktree_path: str) -> str:
    """Resolve worktree path override to absolute path."""
    path = Path(worktree_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return str(path)


def cmd_add(cli_instance, args: argparse.Namespace) -> int:
    """Add a new task to the queue.

    Args:
        cli_instance: TaskQCLI instance with store
        args: Parsed command-line arguments with: id, repo, base, task, task_file

    Returns:
        Exit code (0 on success, 1 on error)
    """
    try:
        task_id_arg = (getattr(args, "id", "") or "").strip()
        repo_arg = (getattr(args, "repo", "") or "").strip()
        base_arg = (getattr(args, "base", "") or "").strip()
        branch_override = (getattr(args, "branch", "") or "").strip()
        worktree_override = (getattr(args, "worktree_path", "") or "").strip()

        if args.task_file:
            source_path = Path(args.task_file).expanduser()
            if not source_path.is_absolute():
                source_path = (Path.cwd() / source_path).resolve()

            if not source_path.exists():
                print(
                    f"Error: Failed to process task file: Source file not found: {source_path}",
                    file=sys.stderr,
                )
                return 1

            try:
                source_content = source_path.read_text(encoding="utf-8")
                frontmatter_data, _ = parse_frontmatter_optional(source_content)
            except (TaskFileError, OSError) as e:
                print(f"Error: Failed to process task file: {e}", file=sys.stderr)
                return 1

            fm_id = str(frontmatter_data.get("id", "") or "").strip()
            fm_repo = str(frontmatter_data.get("repo", "") or "").strip()
            fm_base = str(frontmatter_data.get("base", "") or "").strip()
            fm_branch = str(frontmatter_data.get("branch", "") or "").strip()
            fm_worktree = str(frontmatter_data.get("worktree_path", "") or "").strip()

            task_id = (
                task_id_arg or fm_id or normalize_task_id_from_filename(source_path)
            )
            repo_value = repo_arg or fm_repo

            if cli_instance.store.get_record(task_id) is not None:
                print(
                    f"Error: Record with id '{task_id}' already exists",
                    file=sys.stderr,
                )
                return 1

            if not repo_value:
                print(
                    "Error: Failed to process task file: missing repo (provide --repo or frontmatter repo)",
                    file=sys.stderr,
                )
                return 1

            try:
                resolved_repo = TaskFrontmatter._resolve_repo_path(repo_value)
            except TaskFileError as e:
                print(f"Error: Failed to process task file: {e}", file=sys.stderr)
                return 1

            from orchestration.adapters.git import derive_worktree_path

            base = base_arg or fm_base or DEFAULT_BASE_BRANCH
            branch_name = branch_override or fm_branch or _derive_branch_name(task_id)
            worktree_path = (
                _resolve_worktree_path(worktree_override)
                if worktree_override
                else _resolve_worktree_path(fm_worktree)
                if fm_worktree
                else derive_worktree_path(resolved_repo, task_id)
            )
            task_file_value = _format_task_file_path(source_path)
            print(f"Task file registered: {task_file_value}")

        else:
            if not task_id_arg:
                print("Error: --id is required when using --task", file=sys.stderr)
                return 1
            if not repo_arg:
                print("Error: --repo is required when using --task", file=sys.stderr)
                return 1

            task_id = task_id_arg
            base = base_arg or DEFAULT_BASE_BRANCH

            if cli_instance.store.get_record(task_id) is not None:
                print(
                    f"Error: Record with id '{task_id}' already exists",
                    file=sys.stderr,
                )
                return 1

            try:
                content = create_canonical_task_file(
                    task_id,
                    repo_arg,
                    args.task,
                    base,
                    branch=branch_override or None,
                    worktree_path=worktree_override or None,
                )
                canonical_path = write_task_file(task_id, content)
                frontmatter, _ = read_task_file(task_id)
            except TaskFileError as e:
                print(f"Error: Failed to create task file: {e}", file=sys.stderr)
                return 1

            from orchestration.adapters.git import derive_worktree_path

            resolved_repo = frontmatter.repo
            base = frontmatter.base
            branch_name = (
                branch_override or frontmatter.branch or _derive_branch_name(task_id)
            )
            worktree_path = (
                _resolve_worktree_path(worktree_override)
                if worktree_override
                else _resolve_worktree_path(frontmatter.worktree_path)
                if frontmatter.worktree_path
                else derive_worktree_path(resolved_repo, task_id)
            )
            task_file_value = str(Path("queue") / "tasks" / f"{task_id}.md")
            print(f"Task file created: {canonical_path}")

        now = datetime.now(timezone.utc).isoformat()

        record = TaskRecord(
            id=task_id,
            repo=resolved_repo,
            base=base,
            task_file=task_file_value,
            status="todo",
            branch=branch_name,
            worktree_path=worktree_path,
            container="",
            port=0,
            session_id="",
            attempt=0,
            error_file="",
            created_at=now,
            updated_at=now,
        )

        try:
            cli_instance.store.add_record(record)
            print(f"Task added to queue: {task_id}")
            return 0
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
