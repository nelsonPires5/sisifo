"""
Unit tests for task_files module.
"""

import os
import tempfile
from pathlib import Path
import pytest

from orchestration.task_files import (
    TaskFileError,
    TaskFrontmatter,
    parse_frontmatter,
    create_canonical_task_file,
    write_task_file,
    read_task_file,
    normalize_task_from_file,
    ensure_queue_dirs,
)
from orchestration import task_files as task_files_module


class TestTaskFrontmatter:
    """Test TaskFrontmatter parsing and validation."""

    EXISTING_REPO = str(Path(__file__).resolve().parents[2])

    def test_valid_frontmatter(self):
        """Test creating valid frontmatter with required keys."""
        data = {"id": "T-001", "repo": self.EXISTING_REPO}
        fm = TaskFrontmatter(data)
        assert fm.id == "T-001"
        assert fm.base == "main"  # default

    def test_missing_required_key(self):
        """Test that missing required keys raise error."""
        data = {"id": "T-001"}  # missing 'repo'
        with pytest.raises(TaskFileError, match="Missing required frontmatter keys"):
            TaskFrontmatter(data)

    def test_optional_base_key(self):
        """Test custom base branch."""
        data = {
            "id": "T-001",
            "repo": self.EXISTING_REPO,
            "base": "develop",
        }
        fm = TaskFrontmatter(data)
        assert fm.base == "develop"

    def test_optional_branch_key(self):
        """Test custom branch frontmatter value."""
        data = {
            "id": "T-001",
            "repo": self.EXISTING_REPO,
            "base": "develop",
            "branch": "feature/demo",
        }
        fm = TaskFrontmatter(data)
        assert fm.branch == "feature/demo"

    def test_optional_worktree_path_key(self):
        """Test custom worktree_path frontmatter value."""
        data = {
            "id": "T-001",
            "repo": self.EXISTING_REPO,
            "worktree_path": "/tmp/custom-worktree",
        }
        fm = TaskFrontmatter(data)
        assert fm.worktree_path == "/tmp/custom-worktree"

    def test_repo_path_resolution_absolute(self):
        """Test that absolute paths are used as-is."""
        # Create a temp directory to use as repo
        with tempfile.TemporaryDirectory() as tmpdir:
            data = {"id": "T-001", "repo": tmpdir}
            fm = TaskFrontmatter(data)
            assert fm.repo == os.path.normpath(tmpdir)

    def test_repo_path_resolution_short_name(self):
        """Test that short names are resolved to ~/documents/repos/<name>."""
        # Create the expected directory
        home = os.path.expanduser("~")
        repo_dir = os.path.join(home, "documents", "repos", "test")
        existed_before = os.path.isdir(repo_dir)
        Path(repo_dir).mkdir(parents=True, exist_ok=True)

        try:
            data = {"id": "T-001", "repo": "test"}
            fm = TaskFrontmatter(data)
            assert fm.repo == repo_dir
        finally:
            # Clean up only if this test created the directory
            if not existed_before and os.path.isdir(repo_dir):
                os.rmdir(repo_dir)

    def test_repo_path_nonexistent(self):
        """Test that nonexistent repo paths raise error."""
        data = {"id": "T-001", "repo": "/nonexistent/repo/path"}
        with pytest.raises(TaskFileError, match="Repo path does not exist"):
            TaskFrontmatter(data)

    def test_to_dict(self):
        """Test converting frontmatter back to dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data = {"id": "T-001", "repo": tmpdir, "base": "develop"}
            fm = TaskFrontmatter(data)
            result = fm.to_dict()
            assert result["id"] == "T-001"
            assert result["repo"] == os.path.normpath(tmpdir)
            assert result["base"] == "develop"


class TestParseFrontmatter:
    """Test frontmatter parsing from markdown."""

    def test_valid_frontmatter_parsing(self, tmp_path):
        """Test parsing valid frontmatter from markdown."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        content = f"""---
id: T-001
repo: {repo_dir}
base: main
---
This is the task body.
It can span multiple lines."""

        fm, body = parse_frontmatter(content)
        assert fm.id == "T-001"
        assert fm.base == "main"
        assert "This is the task body" in body
        assert "multiple lines" in body

    def test_missing_frontmatter(self):
        """Test that missing frontmatter raises error."""
        content = "Just plain text without frontmatter."
        with pytest.raises(TaskFileError, match="Invalid frontmatter format"):
            parse_frontmatter(content)

    def test_invalid_yaml(self, tmp_path):
        """Test that invalid YAML raises error."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        content = f"""---
id: T-001
repo: {repo_dir}
invalid yaml: [unclosed
---
Body"""

        with pytest.raises(TaskFileError, match="Invalid YAML"):
            parse_frontmatter(content)


class TestCreateCanonicalTaskFile:
    """Test creating canonical task files."""

    def test_create_with_absolute_repo(self, tmp_path):
        """Test creating canonical file with absolute repo path."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        content = create_canonical_task_file(
            "T-001", str(repo_dir), "Implement feature X", "main"
        )

        assert "id: T-001" in content
        assert "---" in content
        assert "Implement feature X" in content

    def test_create_with_custom_base(self, tmp_path):
        """Test creating with custom base branch."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        content = create_canonical_task_file(
            "T-001", str(repo_dir), "Task body", "develop"
        )

        fm, _ = parse_frontmatter(content)
        assert fm.base == "develop"

    def test_create_with_custom_branch(self, tmp_path):
        """Test creating canonical file with branch key."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        content = create_canonical_task_file(
            "T-010",
            str(repo_dir),
            "Task body",
            "main",
            branch="feature/custom",
        )

        fm, _ = parse_frontmatter(content)
        assert fm.branch == "feature/custom"

    def test_create_with_custom_worktree_path(self, tmp_path):
        """Test creating canonical file with worktree_path key."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        content = create_canonical_task_file(
            "T-020",
            str(repo_dir),
            "Task body",
            "main",
            worktree_path="/tmp/custom-worktree",
        )

        fm, _ = parse_frontmatter(content)
        assert fm.worktree_path == "/tmp/custom-worktree"


class TestWriteTaskFile:
    """Test writing task files to canonical location."""

    def test_write_task_file(self, tmp_path):
        """Test writing a task file."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        content = create_canonical_task_file(
            "T-001", str(repo_dir), "Task body", "main"
        )

        path = write_task_file("T-001", content, str(tasks_dir))

        assert path.exists()
        assert path.name == "T-001.md"
        assert "Task body" in path.read_text()

    def test_write_task_id_mismatch(self, tmp_path):
        """Test that ID mismatch raises error."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        content = create_canonical_task_file("T-001", str(repo_dir), "Body", "main")

        with pytest.raises(TaskFileError, match="Task ID mismatch"):
            write_task_file("T-002", content, str(tasks_dir))


class TestReadTaskFile:
    """Test reading task files."""

    def test_read_task_file(self, tmp_path):
        """Test reading an existing task file."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        # Create and write a task file
        content = create_canonical_task_file(
            "T-001", str(repo_dir), "Test task body", "main"
        )
        write_task_file("T-001", content, str(tasks_dir))

        # Read it back
        fm, body = read_task_file("T-001", str(tasks_dir))
        assert fm.id == "T-001"
        assert "Test task body" in body

    def test_read_nonexistent_file(self, tmp_path):
        """Test that reading nonexistent file raises error."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        with pytest.raises(TaskFileError, match="Task file not found"):
            read_task_file("T-999", str(tasks_dir))


class TestNormalizeTaskFromFile:
    """Test normalizing tasks from source files."""

    def test_normalize_with_frontmatter(self, tmp_path):
        """Test normalizing a source file that has frontmatter."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        # Create source file with frontmatter
        source_content = f"""---
id: T-001
repo: {repo_dir}
base: feature
---
Original task body."""

        source_file = source_dir / "task.md"
        source_file.write_text(source_content)

        # Normalize it
        result_path = normalize_task_from_file(
            str(source_file), "T-001", str(repo_dir), "main", str(tasks_dir)
        )

        assert result_path.exists()
        fm, body = read_task_file("T-001", str(tasks_dir))
        assert "Original task body" in body

    def test_normalize_without_frontmatter(self, tmp_path):
        """Test normalizing a source file without frontmatter."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        # Create source file without frontmatter
        source_content = "Just a plain task description without frontmatter."
        source_file = source_dir / "task.md"
        source_file.write_text(source_content)

        # Normalize it
        result_path = normalize_task_from_file(
            str(source_file), "T-002", str(repo_dir), "develop", str(tasks_dir)
        )

        assert result_path.exists()
        fm, body = read_task_file("T-002", str(tasks_dir))
        assert fm.base == "develop"
        assert "plain task description" in body

    def test_normalize_without_frontmatter_derives_id_from_filename(self, tmp_path):
        """Test ID derivation from filename when --id is omitted."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        source_file = source_dir / "hello world task.md"
        source_file.write_text("Task body without frontmatter")

        result_path = normalize_task_from_file(
            str(source_file),
            "",
            str(repo_dir),
            "main",
            str(tasks_dir),
        )

        assert result_path.exists()
        assert result_path.name == "T-HELLO-WORLD-TASK.md"

    def test_normalize_missing_file(self, tmp_path):
        """Test that missing source file raises error."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        with pytest.raises(TaskFileError, match="Source file not found"):
            normalize_task_from_file(
                "/nonexistent/file.md", "T-001", "/some/repo", "main", str(tasks_dir)
            )


class TestEnsureQueueDirs:
    """Test queue bootstrap directory creation."""

    def test_ensure_queue_dirs_creates_expected_structure(self, tmp_path, monkeypatch):
        """Ensure queue directories and tasks.jsonl are created."""
        fake_module_dir = tmp_path / "orchestration"
        fake_module_dir.mkdir(parents=True, exist_ok=True)
        fake_module_file = fake_module_dir / "task_files.py"
        fake_module_file.write_text("# test", encoding="utf-8")

        monkeypatch.setattr(task_files_module, "__file__", str(fake_module_file))

        ensure_queue_dirs()

        queue_dir = tmp_path / "queue"
        assert (queue_dir / "tasks").is_dir()
        assert (queue_dir / "errors").is_dir()
        assert (queue_dir / "tasks" / ".gitkeep").exists()
        assert (queue_dir / "errors" / ".gitkeep").exists()
        assert (queue_dir / "tasks.jsonl").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
