"""
Tests for queue store implementation.
"""

import pytest
import tempfile
import json
from pathlib import Path
from datetime import datetime
from orchestration.store import QueueStore
from orchestration.core.models import TaskRecord


@pytest.fixture
def temp_queue_file():
    """Create a temporary queue file for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = Path(tmpdir) / "tasks.jsonl"
        yield queue_path


@pytest.fixture
def store(temp_queue_file):
    """Create a QueueStore instance with temporary file."""
    return QueueStore(str(temp_queue_file))


@pytest.fixture
def sample_record():
    """Create a sample task record."""
    return TaskRecord(
        id="task-001",
        repo="https://github.com/user/repo",
        base="main",
        task_file="tasks.md",
        status="todo",
        branch="feature/test",
        worktree_path="/tmp/worktree",
        container="container-123",
        port=8080,
        session_id="session-456",
        attempt=1,
        error_file="queue/errors/task-001.log",
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
    )


class TestTaskRecordValidation:
    """Test TaskRecord validation."""

    def test_valid_status(self, sample_record):
        """Test that valid statuses pass validation."""
        for status in TaskRecord.VALID_STATUSES:
            sample_record.status = status
            sample_record.validate()  # Should not raise

    def test_invalid_status(self, sample_record):
        """Test that invalid status raises ValueError."""
        sample_record.status = "invalid_status"
        with pytest.raises(ValueError, match="Invalid status"):
            sample_record.validate()

    def test_from_dict(self):
        """Test creating TaskRecord from dictionary."""
        data = {
            "id": "task-001",
            "repo": "https://github.com/user/repo",
            "base": "main",
            "task_file": "tasks.md",
            "status": "todo",
            "branch": "feature/test",
            "worktree_path": "/tmp/worktree",
            "container": "container-123",
            "port": 8080,
            "session_id": "session-456",
            "attempt": 1,
            "error_file": "queue/errors/task-001.log",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        record = TaskRecord.from_dict(data)
        assert record.id == "task-001"
        assert record.status == "todo"

    def test_to_dict(self, sample_record):
        """Test converting TaskRecord to dictionary."""
        data = sample_record.to_dict()
        assert data["id"] == "task-001"
        assert data["status"] == "todo"
        assert data["port"] == 8080


class TestQueueStoreInitialization:
    """Test QueueStore initialization."""

    def test_creates_file_if_missing(self):
        """Test that store creates JSONL file if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_path = Path(tmpdir) / "queue" / "tasks.jsonl"
            store = QueueStore(str(queue_path))
            assert queue_path.exists()

    def test_uses_existing_file(self, temp_queue_file):
        """Test that store uses existing file."""
        # Create file with content
        temp_queue_file.write_text('{"id": "test"}\n')
        store = QueueStore(str(temp_queue_file))
        assert temp_queue_file.exists()


class TestQueueStoreAddRecord:
    """Test adding records to queue store."""

    def test_add_single_record(self, store, sample_record):
        """Test adding a single record."""
        store.add_record(sample_record)
        retrieved = store.get_record("task-001")
        assert retrieved is not None
        assert retrieved.id == "task-001"
        assert retrieved.status == "todo"

    def test_add_multiple_records(self, store, sample_record):
        """Test adding multiple records."""
        store.add_record(sample_record)

        record2 = TaskRecord(
            id="task-002",
            repo="https://github.com/user/repo",
            base="main",
            task_file="tasks.md",
            status="planning",
            branch="feature/test2",
            worktree_path="/tmp/worktree2",
            container="container-124",
            port=8081,
            session_id="session-457",
            attempt=1,
            error_file="queue/errors/task-002.log",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )
        store.add_record(record2)

        all_records = store.get_all_records()
        assert len(all_records) == 2

    def test_add_duplicate_id_raises_error(self, store, sample_record):
        """Test that adding duplicate ID raises error."""
        store.add_record(sample_record)
        with pytest.raises(ValueError, match="already exists"):
            store.add_record(sample_record)

    def test_add_invalid_status_raises_error(self, store, sample_record):
        """Test that adding record with invalid status raises error."""
        sample_record.status = "invalid"
        with pytest.raises(ValueError, match="Invalid status"):
            store.add_record(sample_record)


class TestQueueStoreUpdateRecord:
    """Test updating records in queue store."""

    def test_update_status(self, store, sample_record):
        """Test updating record status."""
        store.add_record(sample_record)
        updated = store.update_record("task-001", {"status": "planning"})
        assert updated.status == "planning"
        retrieved = store.get_record("task-001")
        assert retrieved.status == "planning"

    def test_update_multiple_fields(self, store, sample_record):
        """Test updating multiple fields."""
        store.add_record(sample_record)
        updated = store.update_record(
            "task-001",
            {"status": "planning", "attempt": 2, "container": "new-container"},
        )
        assert updated.status == "planning"
        assert updated.attempt == 2
        assert updated.container == "new-container"

    def test_update_updates_timestamp(self, store, sample_record):
        """Test that update sets updated_at timestamp."""
        store.add_record(sample_record)
        original_time = store.get_record("task-001").updated_at
        updated = store.update_record("task-001", {"status": "planning"})
        assert updated.updated_at != original_time

    def test_update_nonexistent_record_raises_error(self, store):
        """Test that updating nonexistent record raises error."""
        with pytest.raises(ValueError, match="not found"):
            store.update_record("nonexistent", {"status": "planning"})

    def test_update_invalid_status_raises_error(self, store, sample_record):
        """Test that updating with invalid status raises error."""
        store.add_record(sample_record)
        with pytest.raises(ValueError, match="Invalid status"):
            store.update_record("task-001", {"status": "invalid"})


class TestQueueStoreRemoveRecord:
    """Test removing records from queue store."""

    def test_remove_record(self, store, sample_record):
        """Test removing a record."""
        store.add_record(sample_record)
        store.remove_record("task-001")
        retrieved = store.get_record("task-001")
        assert retrieved is None

    def test_remove_nonexistent_record_raises_error(self, store):
        """Test that removing nonexistent record raises error."""
        with pytest.raises(ValueError, match="not found"):
            store.remove_record("nonexistent")

    def test_remove_preserves_other_records(self, store, sample_record):
        """Test that removing one record preserves others."""
        store.add_record(sample_record)

        record2 = TaskRecord(
            id="task-002",
            repo="https://github.com/user/repo",
            base="main",
            task_file="tasks.md",
            status="planning",
            branch="feature/test2",
            worktree_path="/tmp/worktree2",
            container="container-124",
            port=8081,
            session_id="session-457",
            attempt=1,
            error_file="queue/errors/task-002.log",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )
        store.add_record(record2)

        store.remove_record("task-001")
        all_records = store.get_all_records()
        assert len(all_records) == 1
        assert all_records[0].id == "task-002"


class TestQueueStoreGetRecord:
    """Test getting records from queue store."""

    def test_get_existing_record(self, store, sample_record):
        """Test getting an existing record."""
        store.add_record(sample_record)
        retrieved = store.get_record("task-001")
        assert retrieved is not None
        assert retrieved.id == "task-001"
        assert retrieved.status == "todo"

    def test_get_nonexistent_record(self, store):
        """Test getting nonexistent record returns None."""
        retrieved = store.get_record("nonexistent")
        assert retrieved is None

    def test_get_all_records(self, store, sample_record):
        """Test getting all records."""
        store.add_record(sample_record)

        record2 = TaskRecord(
            id="task-002",
            repo="https://github.com/user/repo",
            base="main",
            task_file="tasks.md",
            status="planning",
            branch="feature/test2",
            worktree_path="/tmp/worktree2",
            container="container-124",
            port=8081,
            session_id="session-457",
            attempt=1,
            error_file="queue/errors/task-002.log",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )
        store.add_record(record2)

        all_records = store.get_all_records()
        assert len(all_records) == 2

    def test_get_records_by_status(self, store, sample_record):
        """Test getting records filtered by status."""
        store.add_record(sample_record)

        record2 = TaskRecord(
            id="task-002",
            repo="https://github.com/user/repo",
            base="main",
            task_file="tasks.md",
            status="planning",
            branch="feature/test2",
            worktree_path="/tmp/worktree2",
            container="container-124",
            port=8081,
            session_id="session-457",
            attempt=1,
            error_file="queue/errors/task-002.log",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )
        store.add_record(record2)

        todo_records = store.get_records_by_status("todo")
        assert len(todo_records) == 1
        assert todo_records[0].id == "task-001"

        planning_records = store.get_records_by_status("planning")
        assert len(planning_records) == 1
        assert planning_records[0].id == "task-002"


class TestQueueStoreClaimFirstTodo:
    """Test claiming first todo task."""

    def test_claim_first_todo(self, store, sample_record):
        """Test claiming the first todo task."""
        store.add_record(sample_record)
        claimed = store.claim_first_todo()
        assert claimed is not None
        assert claimed.id == "task-001"
        assert claimed.status == "planning"

        # Verify it's updated in store
        retrieved = store.get_record("task-001")
        assert retrieved.status == "planning"

    def test_claim_first_todo_skips_non_todo(self, store, sample_record):
        """Test that claim skips non-todo tasks."""
        sample_record.status = "planning"
        store.add_record(sample_record)

        record2 = TaskRecord(
            id="task-002",
            repo="https://github.com/user/repo",
            base="main",
            task_file="tasks.md",
            status="todo",
            branch="feature/test2",
            worktree_path="/tmp/worktree2",
            container="container-124",
            port=8081,
            session_id="session-457",
            attempt=1,
            error_file="queue/errors/task-002.log",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )
        store.add_record(record2)

        claimed = store.claim_first_todo()
        assert claimed.id == "task-002"
        assert claimed.status == "planning"

    def test_claim_first_todo_no_todos_returns_none(self, store, sample_record):
        """Test that claim returns None when no todos exist."""
        sample_record.status = "done"
        store.add_record(sample_record)
        claimed = store.claim_first_todo()
        assert claimed is None

    def test_claim_first_todo_empty_store_returns_none(self, store):
        """Test that claim returns None for empty store."""
        claimed = store.claim_first_todo()
        assert claimed is None


class TestQueueStoreClaimTodoById:
    """Test claiming specific todo tasks by ID."""

    def test_claim_todo_by_id_success(self, store, sample_record):
        """claim_todo_by_id should transition a todo task to planning."""
        store.add_record(sample_record)
        claimed = store.claim_todo_by_id("task-001")

        assert claimed is not None
        assert claimed.id == "task-001"
        assert claimed.status == "planning"

        persisted = store.get_record("task-001")
        assert persisted is not None
        assert persisted.status == "planning"

    def test_claim_todo_by_id_non_todo_returns_none(self, store, sample_record):
        """claim_todo_by_id should return None when status is not todo."""
        sample_record.status = "review"
        store.add_record(sample_record)

        claimed = store.claim_todo_by_id("task-001")
        assert claimed is None

    def test_claim_todo_by_id_missing_record_returns_none(self, store):
        """claim_todo_by_id should return None for unknown IDs."""
        claimed = store.claim_todo_by_id("missing")
        assert claimed is None


class TestQueueStoreJsonlFormat:
    """Test JSONL file format and persistence."""

    def test_jsonl_format(self, store, sample_record):
        """Test that records are stored in JSONL format."""
        store.add_record(sample_record)
        with open(store.tasks_file, "r") as f:
            lines = f.readlines()
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["id"] == "task-001"
            assert data["status"] == "todo"

    def test_persistence_across_instances(self, temp_queue_file, sample_record):
        """Test that data persists across store instances."""
        store1 = QueueStore(str(temp_queue_file))
        store1.add_record(sample_record)

        store2 = QueueStore(str(temp_queue_file))
        retrieved = store2.get_record("task-001")
        assert retrieved is not None
        assert retrieved.id == "task-001"

    def test_atomic_write_on_update(self, store, sample_record):
        """Test that updates use atomic write."""
        store.add_record(sample_record)
        store.update_record("task-001", {"status": "planning"})

        # Verify file is valid JSON
        with open(store.tasks_file, "r") as f:
            lines = f.readlines()
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["status"] == "planning"


class TestTaskRecordOpenCodeFields:
    """Test new OpenCode metadata fields in TaskRecord."""

    def test_opencode_fields_have_defaults(self, sample_record):
        """Test that OpenCode fields default to empty strings."""
        assert sample_record.opencode_attempt_dir == ""
        assert sample_record.opencode_config_dir == ""
        assert sample_record.opencode_data_dir == ""

    def test_opencode_fields_can_be_set(self, sample_record):
        """Test that OpenCode fields can be set."""
        sample_record.opencode_attempt_dir = "/path/to/attempt"
        sample_record.opencode_config_dir = "/path/to/config"
        sample_record.opencode_data_dir = "/path/to/data"

        assert sample_record.opencode_attempt_dir == "/path/to/attempt"
        assert sample_record.opencode_config_dir == "/path/to/config"
        assert sample_record.opencode_data_dir == "/path/to/data"

    def test_opencode_fields_in_dict_conversion(self, sample_record):
        """Test that OpenCode fields are included in dict conversion."""
        sample_record.opencode_attempt_dir = "/attempt"
        sample_record.opencode_config_dir = "/config"
        sample_record.opencode_data_dir = "/data"

        data = sample_record.to_dict()
        assert "opencode_attempt_dir" in data
        assert "opencode_config_dir" in data
        assert "opencode_data_dir" in data
        assert data["opencode_attempt_dir"] == "/attempt"
        assert data["opencode_config_dir"] == "/config"
        assert data["opencode_data_dir"] == "/data"

    def test_backward_compatibility_missing_fields(self):
        """Test that old records without OpenCode fields deserialize correctly."""
        old_data = {
            "id": "task-001",
            "repo": "https://github.com/user/repo",
            "base": "main",
            "task_file": "tasks.md",
            "status": "todo",
            "branch": "feature/test",
            "worktree_path": "/tmp/worktree",
            "container": "container-123",
            "port": 8080,
            "session_id": "session-456",
            "attempt": 1,
            "error_file": "queue/errors/task-001.log",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            # No OpenCode fields
        }
        record = TaskRecord.from_dict(old_data)
        assert record.id == "task-001"
        assert record.opencode_attempt_dir == ""
        assert record.opencode_config_dir == ""
        assert record.opencode_data_dir == ""

    def test_opencode_fields_persist_in_store(self, store, sample_record):
        """Test that OpenCode fields persist through add/update/get cycle."""
        sample_record.opencode_attempt_dir = "/attempt/path"
        sample_record.opencode_config_dir = "/config/path"
        sample_record.opencode_data_dir = "/data/path"

        store.add_record(sample_record)
        retrieved = store.get_record("task-001")

        assert retrieved.opencode_attempt_dir == "/attempt/path"
        assert retrieved.opencode_config_dir == "/config/path"
        assert retrieved.opencode_data_dir == "/data/path"

    def test_opencode_fields_persist_after_update(self, store, sample_record):
        """Test that OpenCode fields persist after updates."""
        sample_record.opencode_attempt_dir = "/attempt/path"
        sample_record.opencode_config_dir = "/config/path"
        sample_record.opencode_data_dir = "/data/path"

        store.add_record(sample_record)
        store.update_record("task-001", {"status": "planning"})
        retrieved = store.get_record("task-001")

        assert retrieved.opencode_attempt_dir == "/attempt/path"
        assert retrieved.opencode_config_dir == "/config/path"
        assert retrieved.opencode_data_dir == "/data/path"
        assert retrieved.status == "planning"

    def test_opencode_fields_update_separately(self, store, sample_record):
        """Test that OpenCode fields can be updated independently."""
        store.add_record(sample_record)
        updated = store.update_record(
            "task-001", {"opencode_attempt_dir": "/new/attempt"}
        )

        assert updated.opencode_attempt_dir == "/new/attempt"
        assert updated.opencode_config_dir == ""
        assert updated.opencode_data_dir == ""


class TestQueueStoreClear:
    """Test clearing store."""

    def test_clear_removes_all_records(self, store, sample_record):
        """Test that clear removes all records."""
        store.add_record(sample_record)
        assert len(store.get_all_records()) == 1

        store.clear()
        assert len(store.get_all_records()) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
