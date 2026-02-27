"""Core domain model: TaskRecord and status transition logic."""

from dataclasses import dataclass, asdict
from typing import Dict, Any


@dataclass
class TaskRecord:
    """Single source of truth for task runtime record schema."""

    id: str
    repo: str
    base: str
    task_file: str
    status: str  # Validated at write-time
    branch: str
    worktree_path: str
    container: str
    port: int
    session_id: str
    attempt: int
    error_file: str
    created_at: str
    updated_at: str
    opencode_attempt_dir: str = ""
    opencode_config_dir: str = ""
    opencode_data_dir: str = ""

    # Valid status values
    VALID_STATUSES = {
        "todo",
        "planning",
        "building",
        "review",
        "done",
        "failed",
        "cancelled",
    }

    def validate(self) -> None:
        """Validate status value at write-time."""
        if self.status not in self.VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{self.status}'. Must be one of: {', '.join(self.VALID_STATUSES)}"
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRecord":
        """Create TaskRecord from dictionary."""
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert TaskRecord to dictionary."""
        return asdict(self)

    @staticmethod
    def is_valid_transition(from_status: str, to_status: str) -> bool:
        """
        Check if a status transition is legal.

        Status machine:
        - todo -> planning -> building -> review -> done
        - planning|building -> failed
        - todo|review|failed -> cancelled
        - failed -> todo (retry)

        Args:
            from_status: Current status
            to_status: Target status

        Returns:
            True if transition is valid, False otherwise
        """
        # Transition map: from_status -> set of valid target statuses
        transitions = {
            "todo": {"planning", "cancelled"},
            "planning": {"building", "failed", "cancelled"},
            "building": {"review", "failed"},
            "review": {"done", "cancelled"},
            "failed": {"todo", "cancelled"},
            "done": set(),  # Terminal state
            "cancelled": set(),  # Terminal state
        }

        return to_status in transitions.get(from_status, set())
