"""Core exceptions: base worker exceptions and task processing errors."""


class WorkerError(Exception):
    """Base exception for worker pipeline errors."""

    pass


class TaskProcessingError(WorkerError):
    """Raised when task processing fails at a specific stage."""

    def __init__(
        self,
        stage: str,
        task_id: str,
        message: str,
        command: str = "",
        exit_code: int = -1,
        stdout: str = "",
        stderr: str = "",
    ):
        self.stage = stage
        self.task_id = task_id
        self.message = message
        self.command = command
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"[{stage}] {message}")
