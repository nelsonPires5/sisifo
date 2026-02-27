"""
taskq CLI command implementations.

This package contains individual command handlers for the taskq CLI.
Commands are organized into separate modules for maintainability.

Public API:
- TaskQCLI: Facade class for backward compatibility with tests
"""

import argparse

# Import command modules (not functions) to avoid namespace conflicts
from orchestration.cli import cmd_add as _cmd_add_module
from orchestration.cli import cmd_status as _cmd_status_module
from orchestration.cli import cmd_remove as _cmd_remove_module
from orchestration.cli import cmd_transitions as _cmd_transitions_module
from orchestration.cli import cmd_run as _cmd_run_module
from orchestration.cli import cmd_review as _cmd_review_module
from orchestration.cli import cmd_cleanup as _cmd_cleanup_module
from orchestration.cli import cmd_build_image as _cmd_build_image_module

# Handle relative imports when used as submodule
try:
    from orchestration.store import QueueStore
    from orchestration.support.paths import ensure_queue_dirs
except ImportError:
    from store import QueueStore
    from support.paths import ensure_queue_dirs


class TaskQCLI:
    """Task queue CLI interface (facade for backward compatibility).

    This class maintains the original API for tests while delegating
    to individual command modules.
    """

    def __init__(self):
        """Initialize CLI with queue store."""
        self.store = QueueStore()
        # Ensure queue directory structure exists
        ensure_queue_dirs()

    def cmd_add(self, args: argparse.Namespace) -> int:
        """Add a new task to the queue (delegates to cmd_add module)."""
        return _cmd_add_module.cmd_add(self, args)

    def cmd_status(self, args: argparse.Namespace) -> int:
        """Display task queue status (delegates to cmd_status module)."""
        return _cmd_status_module.cmd_status(self, args)

    def cmd_remove(self, args: argparse.Namespace) -> int:
        """Remove a task from the queue (delegates to cmd_remove module)."""
        return _cmd_remove_module.cmd_remove(self, args)

    def cmd_cancel(self, args: argparse.Namespace) -> int:
        """Cancel a task (delegates to cmd_transitions module)."""
        return _cmd_transitions_module.cmd_cancel(self, args)

    def cmd_retry(self, args: argparse.Namespace) -> int:
        """Retry a failed task (delegates to cmd_transitions module)."""
        return _cmd_transitions_module.cmd_retry(self, args)

    def cmd_approve(self, args: argparse.Namespace) -> int:
        """Approve a task in review (delegates to cmd_transitions module)."""
        return _cmd_transitions_module.cmd_approve(self, args)

    def cmd_run(self, args: argparse.Namespace) -> int:
        """Run task queue with concurrent workers (delegates to cmd_run module)."""
        return _cmd_run_module.cmd_run(self, args)

    def cmd_review(self, args: argparse.Namespace) -> int:
        """Launch OpenChamber review for a task (delegates to cmd_review module)."""
        return _cmd_review_module.cmd_review(self, args)

    def cmd_cleanup(self, args: argparse.Namespace) -> int:
        """Clean up runtime artifacts (delegates to cmd_cleanup module)."""
        return _cmd_cleanup_module.cmd_cleanup(self, args)

    def cmd_build_image(self, args: argparse.Namespace) -> int:
        """Build runtime image (delegates to cmd_build_image module)."""
        return _cmd_build_image_module.cmd_build_image(self, args)


__all__ = [
    "TaskQCLI",
]
