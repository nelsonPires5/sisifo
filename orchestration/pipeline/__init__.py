"""
Task processing pipeline for executing claimed tasks through planning, building, and review stages.

Orchestrates git worktrees, docker containers, and OpenCode commands to execute tasks
from claim through completion or failure. Handles error reporting and state persistence.

Main exports:
- TaskProcessor: Main orchestrator for task execution
- TaskProcessingError: Exception for pipeline failures
"""

try:
    from orchestration.pipeline.processor import TaskProcessor, TaskProcessingError
except ImportError:
    from pipeline.processor import TaskProcessor, TaskProcessingError

__all__ = [
    "TaskProcessor",
    "TaskProcessingError",
]
