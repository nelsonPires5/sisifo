"""Runtime adapters for task orchestration.

Provides modular interfaces for git, docker, opencode, and review operations.
Each adapter module can be imported independently:

- orchestration.adapters.git: Git worktree management
- orchestration.adapters.docker: Docker container lifecycle
- orchestration.adapters.opencode: OpenCode command execution
- orchestration.adapters.review: Review session launching
"""

from orchestration.adapters import protocol
from orchestration.adapters.protocol import AdapterRegistry

__all__ = [
    "protocol",
    "AdapterRegistry",
]
