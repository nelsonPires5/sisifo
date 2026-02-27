"""
Queue store for task runtime records with JSONL persistence, file locking, and atomic updates.
"""

import json
import os
import fcntl
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

try:
    from orchestration.core.models import TaskRecord
except ImportError:
    from core.models import TaskRecord


class QueueStore:
    """Thread-safe JSONL queue store with file locking and atomic writes."""

    def __init__(self, tasks_file: Optional[str] = None):
        """
        Initialize queue store.

        Args:
            tasks_file: Path to JSONL file for task records (created if missing).
                If omitted, defaults to <repo-root>/queue/tasks.jsonl.
        """
        if tasks_file is None:
            repo_root = Path(__file__).resolve().parent.parent.parent
            self.tasks_file = repo_root / "queue" / "tasks.jsonl"
        else:
            self.tasks_file = Path(tasks_file)
        self._lock = threading.RLock()
        self._file_lock_handle = None

        # Ensure directory exists
        self.tasks_file.parent.mkdir(parents=True, exist_ok=True)

        # Create empty file if missing
        if not self.tasks_file.exists():
            self.tasks_file.touch()

    def _acquire_file_lock(self) -> None:
        """Acquire exclusive file lock."""
        if self._file_lock_handle is not None:
            return  # Already locked

        self._file_lock_handle = open(self.tasks_file, "a+")
        fcntl.flock(self._file_lock_handle.fileno(), fcntl.LOCK_EX)

    def _release_file_lock(self) -> None:
        """Release file lock."""
        if self._file_lock_handle is not None:
            fcntl.flock(self._file_lock_handle.fileno(), fcntl.LOCK_UN)
            self._file_lock_handle.close()
            self._file_lock_handle = None

    def _read_all_records(self) -> List[TaskRecord]:
        """Read all records from JSONL file (must be called within lock context)."""
        records = []
        if not self.tasks_file.exists() or self.tasks_file.stat().st_size == 0:
            return records

        try:
            with open(self.tasks_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        records.append(TaskRecord.from_dict(data))
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Error reading JSONL file: {e}")

        return records

    def _write_all_records(self, records: List[TaskRecord]) -> None:
        """Write all records to JSONL file atomically (must be called within lock context)."""
        # Validate all records before writing
        for record in records:
            record.validate()

        # Write to temporary file first, then atomically rename
        temp_file = self.tasks_file.with_suffix(".jsonl.tmp")
        try:
            with open(temp_file, "w") as f:
                for record in records:
                    line = json.dumps(record.to_dict(), default=str)
                    f.write(line + "\n")
            # Atomic rename
            temp_file.replace(self.tasks_file)
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise e

    def add_record(self, record: TaskRecord) -> None:
        """
        Add a new task record.

        Args:
            record: TaskRecord to add

        Raises:
            ValueError: If status is invalid or record ID already exists
        """
        record.validate()

        with self._lock:
            self._acquire_file_lock()
            try:
                records = self._read_all_records()

                # Check if ID already exists
                if any(r.id == record.id for r in records):
                    raise ValueError(f"Record with id '{record.id}' already exists")

                records.append(record)
                self._write_all_records(records)
            finally:
                self._release_file_lock()

    def update_record(self, record_id: str, updates: Dict[str, Any]) -> TaskRecord:
        """
        Update an existing task record.

        Args:
            record_id: ID of record to update
            updates: Dictionary of fields to update

        Returns:
            Updated TaskRecord

        Raises:
            ValueError: If record not found, status is invalid, or transition is illegal
        """
        with self._lock:
            self._acquire_file_lock()
            try:
                records = self._read_all_records()
                record_idx = None

                for idx, r in enumerate(records):
                    if r.id == record_id:
                        record_idx = idx
                        break

                if record_idx is None:
                    raise ValueError(f"Record with id '{record_id}' not found")

                # Apply updates
                record_dict = records[record_idx].to_dict()
                old_status = record_dict["status"]
                record_dict.update(updates)

                # Validate status transition if status is being changed
                if "status" in updates:
                    new_status = updates["status"]
                    if new_status != old_status and not TaskRecord.is_valid_transition(
                        old_status, new_status
                    ):
                        raise ValueError(
                            f"Invalid status transition: {old_status} -> {new_status}"
                        )

                record_dict["updated_at"] = datetime.utcnow().isoformat()

                updated_record = TaskRecord.from_dict(record_dict)
                updated_record.validate()

                records[record_idx] = updated_record
                self._write_all_records(records)

                return updated_record
            finally:
                self._release_file_lock()

    def remove_record(self, record_id: str) -> None:
        """
        Remove a task record.

        Args:
            record_id: ID of record to remove

        Raises:
            ValueError: If record not found
        """
        with self._lock:
            self._acquire_file_lock()
            try:
                records = self._read_all_records()
                original_count = len(records)
                records = [r for r in records if r.id != record_id]

                if len(records) == original_count:
                    raise ValueError(f"Record with id '{record_id}' not found")

                self._write_all_records(records)
            finally:
                self._release_file_lock()

    def get_record(self, record_id: str) -> Optional[TaskRecord]:
        """
        Get a task record by ID.

        Args:
            record_id: ID of record to retrieve

        Returns:
            TaskRecord if found, None otherwise
        """
        with self._lock:
            self._acquire_file_lock()
            try:
                records = self._read_all_records()
                for r in records:
                    if r.id == record_id:
                        return r
                return None
            finally:
                self._release_file_lock()

    def get_all_records(self) -> List[TaskRecord]:
        """
        Get all task records.

        Returns:
            List of all TaskRecords
        """
        with self._lock:
            self._acquire_file_lock()
            try:
                return self._read_all_records()
            finally:
                self._release_file_lock()

    def get_records_by_status(self, status: str) -> List[TaskRecord]:
        """
        Get all records with a specific status.

        Args:
            status: Status to filter by

        Returns:
            List of TaskRecords with matching status
        """
        with self._lock:
            self._acquire_file_lock()
            try:
                records = self._read_all_records()
                return [r for r in records if r.status == status]
            finally:
                self._release_file_lock()

    def claim_first_todo(self) -> Optional[TaskRecord]:
        """
        Atomically claim the first 'todo' task and mark it as 'planning'.

        Returns:
            Claimed TaskRecord if available, None if no todo tasks

        Raises:
            ValueError: If status transition is invalid
        """
        with self._lock:
            self._acquire_file_lock()
            try:
                records = self._read_all_records()
                for idx, r in enumerate(records):
                    if r.status == "todo":
                        # Transition to planning
                        record_dict = r.to_dict()
                        record_dict["status"] = "planning"
                        record_dict["updated_at"] = datetime.utcnow().isoformat()

                        updated_record = TaskRecord.from_dict(record_dict)
                        updated_record.validate()

                        records[idx] = updated_record
                        self._write_all_records(records)
                        return updated_record

                return None
            finally:
                self._release_file_lock()

    def claim_todo_by_id(self, record_id: str) -> Optional[TaskRecord]:
        """Atomically claim a specific 'todo' task and mark it as 'planning'.

        Args:
            record_id: Task ID to claim.

        Returns:
            Updated TaskRecord if task exists in 'todo', otherwise None.
        """
        with self._lock:
            self._acquire_file_lock()
            try:
                records = self._read_all_records()
                for idx, r in enumerate(records):
                    if r.id != record_id:
                        continue

                    if r.status != "todo":
                        return None

                    record_dict = r.to_dict()
                    record_dict["status"] = "planning"
                    record_dict["updated_at"] = datetime.utcnow().isoformat()

                    updated_record = TaskRecord.from_dict(record_dict)
                    updated_record.validate()

                    records[idx] = updated_record
                    self._write_all_records(records)
                    return updated_record

                return None
            finally:
                self._release_file_lock()

    def clear(self) -> None:
        """Clear all records (useful for testing)."""
        with self._lock:
            self._acquire_file_lock()
            try:
                self._write_all_records([])
            finally:
                self._release_file_lock()
