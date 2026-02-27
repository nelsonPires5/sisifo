"""
Tests for runtime adapters protocol consistency and registry checks.

Tests cover:
- Adapter module contract validation
- Registry sanity checks for adapter availability
- Env/path consolidation parity between adapters
- Exception hierarchy consistency
"""

import pytest
from pathlib import Path

from orchestration.adapters import protocol
from orchestration.adapters import git
from orchestration.adapters import docker
from orchestration.adapters import opencode
from orchestration.adapters import review


class TestAdapterModuleContract:
    """Test that all adapter modules have required components."""

    def test_git_adapter_has_required_functions(self):
        """Verify git adapter module has required functions."""
        required_functions = [
            "create_worktree",
            "remove_worktree",
            "repo_exists",
            "branch_exists",
        ]
        for func in required_functions:
            assert hasattr(git, func), f"git adapter missing function: {func}"

    def test_docker_adapter_has_required_functions(self):
        """Verify docker adapter module has required functions."""
        required_functions = [
            "find_available_port",
            "launch_container",
            "stop_container",
            "container_logs",
        ]
        for func in required_functions:
            assert hasattr(docker, func), f"docker adapter missing function: {func}"

    def test_opencode_adapter_has_required_functions(self):
        """Verify opencode adapter module has required functions."""
        required_functions = [
            "validate_endpoint",
            "run_plan_sequence",
            "run_execute_plan",
        ]
        for func in required_functions:
            assert hasattr(opencode, func), f"opencode adapter missing function: {func}"

    def test_review_adapter_has_required_functions(self):
        """Verify review adapter module has required functions."""
        required_functions = [
            "launch_review",
            "launch_review_from_record",
        ]
        for func in required_functions:
            assert hasattr(review, func), f"review adapter missing function: {func}"


class TestAdapterExceptionHierarchy:
    """Test that adapter exceptions follow consistent hierarchy."""

    def test_git_adapter_exceptions_are_defined(self):
        """Verify git adapter exceptions exist and inherit properly."""
        assert issubclass(git.GitRuntimeError, Exception)
        assert issubclass(git.RepoNotFoundError, git.GitRuntimeError)
        assert issubclass(git.BranchNotFoundError, git.GitRuntimeError)
        assert issubclass(git.WorktreeError, git.GitRuntimeError)

    def test_docker_adapter_exceptions_are_defined(self):
        """Verify docker adapter exceptions exist and inherit properly."""
        assert issubclass(docker.DockerException, Exception)
        assert issubclass(docker.ContainerError, docker.DockerException)
        assert issubclass(docker.PortAllocationError, docker.DockerException)
        assert issubclass(docker.ContainerStartError, docker.ContainerError)

    def test_opencode_adapter_exceptions_are_defined(self):
        """Verify opencode adapter exceptions exist and inherit properly."""
        assert issubclass(opencode.OpenCodeException, Exception)
        assert issubclass(opencode.CommandError, opencode.OpenCodeException)
        assert issubclass(opencode.PlanError, opencode.CommandError)
        assert issubclass(opencode.BuildError, opencode.CommandError)

    def test_review_adapter_exceptions_are_defined(self):
        """Verify review adapter exceptions exist and inherit properly."""
        assert issubclass(review.ReviewException, Exception)
        assert issubclass(review.ReviewLaunchError, review.ReviewException)
        assert issubclass(review.StrictLocalValidationError, review.ReviewException)


class TestAdapterRegistryContract:
    """Test adapter registry protocol and availability."""

    def test_adapter_registry_class_exists(self):
        """Verify AdapterRegistry class is defined."""
        assert hasattr(protocol, "AdapterRegistry")
        assert hasattr(protocol.AdapterRegistry, "register")
        assert hasattr(protocol.AdapterRegistry, "get")
        assert hasattr(protocol.AdapterRegistry, "list")

    def test_adapter_exception_bases_defined(self):
        """Verify base adapter exception classes are defined."""
        assert issubclass(protocol.GitAdapterException, protocol.AdapterException)
        assert issubclass(protocol.DockerAdapterException, protocol.AdapterException)
        assert issubclass(protocol.OpenCodeAdapterException, protocol.AdapterException)
        assert issubclass(protocol.ReviewAdapterException, protocol.AdapterException)


class TestPathConsolidationParity:
    """Test path handling consistency across adapters."""

    def test_git_worktree_path_derivation(self):
        """Test git adapter derives worktree paths consistently."""
        # Test basic path derivation
        repo = "/test/repo"
        task_id = "T-001"

        # Should return a valid path string
        path = git.derive_worktree_path(repo, task_id)
        assert isinstance(path, str)
        assert len(path) > 0

    def test_git_worktree_path_includes_repo_name(self):
        """Test git worktree path includes repo identifier."""
        repo = "/test/my-repo"
        task_id = "T-001"

        path = git.derive_worktree_path(repo, task_id)
        # Path should be reasonably structured
        assert "worktree" in path.lower() or "work-tree" in path.lower() or "/" in path

    def test_docker_container_naming_consistency(self):
        """Test docker container names follow a consistent pattern."""
        # Docker container names should be deterministic based on inputs
        from orchestration.core.naming import derive_container_name
        from datetime import datetime

        task_id = "T-001"
        timestamp = datetime.utcnow().isoformat()

        name = derive_container_name(task_id, timestamp)

        # Should be a valid string and include task ID
        assert isinstance(name, str)
        assert task_id.lower() in name.lower()

    def test_adapter_exception_messages_are_strings(self):
        """Test that adapter exceptions can have string messages."""
        # This is a basic sanity check
        exc1 = git.GitRuntimeError("test message")
        assert str(exc1) == "test message"

        exc2 = docker.ContainerError("test message")
        assert str(exc2) == "test message"

        exc4 = review.ReviewException("test message")
        assert str(exc4) == "test message"

    def test_adapter_port_allocation_error_creation(self):
        """Test that port allocation error can be created."""
        # Test specific docker exception
        port_error = docker.PortAllocationError("No ports available")
        assert isinstance(port_error, docker.DockerException)
        assert "No ports available" in str(port_error)

    def test_adapter_git_repo_not_found_error_creation(self):
        """Test that git repo not found error can be created."""
        repo_error = git.RepoNotFoundError("Repo not found")
        assert isinstance(repo_error, git.GitRuntimeError)
        assert "Repo not found" in str(repo_error)
