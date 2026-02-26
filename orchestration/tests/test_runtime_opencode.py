"""
Unit tests for OpenCode runtime helpers.
"""

import subprocess
import pytest
from unittest.mock import Mock, patch, MagicMock

from orchestration.runtime_opencode import (
    validate_endpoint,
    run_make_plan,
    run_execute_plan,
    run_plan_sequence,
    OpenCodeException,
    EndpointError,
    PlanError,
    BuildError,
)


class TestEndpointValidation:
    """Test endpoint validation."""

    def test_validate_endpoint_basic(self):
        """Test basic endpoint validation."""
        endpoint = validate_endpoint("127.0.0.1", 8000)
        assert endpoint == "http://127.0.0.1:8000"

    def test_validate_endpoint_localhost(self):
        """Test localhost endpoint."""
        endpoint = validate_endpoint("localhost", 9000)
        assert endpoint == "http://localhost:9000"

    def test_validate_endpoint_already_has_scheme(self):
        """Test endpoint that already has http:// prefix."""
        endpoint = validate_endpoint("http://127.0.0.1", 8000)
        assert "127.0.0.1" in endpoint
        assert "8000" in endpoint

    def test_validate_endpoint_invalid_host(self):
        """Test invalid host."""
        with pytest.raises(EndpointError):
            validate_endpoint("", 8000)

    def test_validate_endpoint_invalid_port_negative(self):
        """Test invalid port (negative)."""
        with pytest.raises(EndpointError):
            validate_endpoint("127.0.0.1", -1)

    def test_validate_endpoint_invalid_port_zero(self):
        """Test invalid port (zero)."""
        with pytest.raises(EndpointError):
            validate_endpoint("127.0.0.1", 0)

    def test_validate_endpoint_invalid_port_too_high(self):
        """Test invalid port (too high)."""
        with pytest.raises(EndpointError):
            validate_endpoint("127.0.0.1", 99999)

    def test_validate_endpoint_non_string_host(self):
        """Test non-string host."""
        with pytest.raises(EndpointError):
            validate_endpoint(None, 8000)

    def test_validate_endpoint_non_int_port(self):
        """Test non-integer port."""
        with pytest.raises(EndpointError):
            validate_endpoint("127.0.0.1", "8000")


class TestMakePlan:
    """Test make-plan command execution."""

    def test_run_make_plan_success(self):
        """Test successful make-plan execution."""
        mock_output = "Plan created successfully"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=mock_output, stderr="")

            stdout, stderr = run_make_plan("http://127.0.0.1:8000", "Test task")

            assert stdout == mock_output
            assert stderr == ""
            mock_run.assert_called_once()

    def test_run_make_plan_failure(self):
        """Test make-plan failure."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=1,
                stdout="",
                stderr="Failed to create plan",
            )

            with pytest.raises(PlanError) as exc_info:
                run_make_plan("http://127.0.0.1:8000", "Test task")

            err = exc_info.value
            assert err.stage == "planning"
            assert err.exit_code == 1
            assert "Failed to create plan" in err.stderr

    def test_run_make_plan_timeout(self):
        """Test make-plan timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("opencode", 5)

            with pytest.raises(PlanError) as exc_info:
                run_make_plan("http://127.0.0.1:8000", "Test task", timeout=5)

            err = exc_info.value
            assert err.exit_code == -1
            assert "timeout" in err.stderr.lower()

    def test_run_make_plan_empty_endpoint(self):
        """Test make-plan with empty endpoint."""
        with pytest.raises(EndpointError):
            run_make_plan("", "Test task")

    def test_run_make_plan_empty_task(self):
        """Test make-plan with empty task."""
        with pytest.raises(EndpointError):
            run_make_plan("http://127.0.0.1:8000", "")

    def test_run_make_plan_none_task(self):
        """Test make-plan with None task."""
        with pytest.raises(EndpointError):
            run_make_plan("http://127.0.0.1:8000", None)


class TestExecutePlan:
    """Test execute-plan command execution."""

    def test_run_execute_plan_success(self):
        """Test successful execute-plan execution."""
        mock_output = "Plan executed successfully"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=mock_output, stderr="")

            stdout, stderr = run_execute_plan("http://127.0.0.1:8000")

            assert stdout == mock_output
            assert stderr == ""
            mock_run.assert_called_once()

    def test_run_execute_plan_failure(self):
        """Test execute-plan failure."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=1,
                stdout="",
                stderr="Execution failed",
            )

            with pytest.raises(BuildError) as exc_info:
                run_execute_plan("http://127.0.0.1:8000")

            err = exc_info.value
            assert err.stage == "building"
            assert err.exit_code == 1
            assert "Execution failed" in err.stderr

    def test_run_execute_plan_timeout(self):
        """Test execute-plan timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("opencode", 600)

            with pytest.raises(BuildError) as exc_info:
                run_execute_plan("http://127.0.0.1:8000", timeout=600)

            err = exc_info.value
            assert err.exit_code == -1
            assert "timeout" in err.stderr.lower()

    def test_run_execute_plan_empty_endpoint(self):
        """Test execute-plan with empty endpoint."""
        with pytest.raises(EndpointError):
            run_execute_plan("")


class TestPlanSequence:
    """Test plan sequence execution."""

    def test_run_plan_sequence_success(self):
        """Test successful plan sequence."""
        with patch("orchestration.runtime_opencode.run_make_plan") as mock_plan:
            with patch("orchestration.runtime_opencode.run_execute_plan") as mock_build:
                mock_plan.return_value = ("Plan output", "")
                mock_build.return_value = ("Build output", "")

                result = run_plan_sequence("http://127.0.0.1:8000", "Test task")

                assert result["status"] == "success"
                assert result["plan_stdout"] == "Plan output"
                assert result["build_stdout"] == "Build output"
                assert result["error"] is None
                mock_plan.assert_called_once()
                mock_build.assert_called_once()

    def test_run_plan_sequence_plan_fails(self):
        """Test sequence when plan fails."""
        with patch("orchestration.runtime_opencode.run_make_plan") as mock_plan:
            with patch("orchestration.runtime_opencode.run_execute_plan") as mock_build:
                plan_error = PlanError(
                    stage="planning",
                    exit_code=1,
                    stdout="",
                    stderr="Plan failed",
                )
                mock_plan.side_effect = plan_error

                result = run_plan_sequence("http://127.0.0.1:8000", "Test task")

                assert result["status"] == "plan_failed"
                assert result["error"] is plan_error
                mock_build.assert_not_called()

    def test_run_plan_sequence_build_fails(self):
        """Test sequence when build fails."""
        with patch("orchestration.runtime_opencode.run_make_plan") as mock_plan:
            with patch("orchestration.runtime_opencode.run_execute_plan") as mock_build:
                mock_plan.return_value = ("Plan output", "")
                build_error = BuildError(
                    stage="building",
                    exit_code=1,
                    stdout="",
                    stderr="Build failed",
                )
                mock_build.side_effect = build_error

                result = run_plan_sequence("http://127.0.0.1:8000", "Test task")

                assert result["status"] == "build_failed"
                assert result["error"] is build_error
                assert result["plan_stdout"] == "Plan output"

    def test_run_plan_sequence_unexpected_error(self):
        """Test sequence with unexpected error."""
        with patch("orchestration.runtime_opencode.run_make_plan") as mock_plan:
            mock_plan.side_effect = RuntimeError("Unexpected error")

            result = run_plan_sequence("http://127.0.0.1:8000", "Test task")

            assert result["status"] == "plan_failed"
            assert result["error"] is not None
            assert isinstance(result["error"], PlanError)


class TestExceptionHierarchy:
    """Test exception relationships."""

    def test_plan_error_is_command_error(self):
        """Test PlanError is CommandError."""
        err = PlanError(
            stage="planning",
            exit_code=1,
            stdout="",
            stderr="Error",
        )
        from orchestration.runtime_opencode import CommandError

        assert isinstance(err, CommandError)

    def test_build_error_is_command_error(self):
        """Test BuildError is CommandError."""
        err = BuildError(
            stage="building",
            exit_code=1,
            stdout="",
            stderr="Error",
        )
        from orchestration.runtime_opencode import CommandError

        assert isinstance(err, CommandError)

    def test_command_error_is_opencode_exception(self):
        """Test CommandError is OpenCodeException."""
        err = PlanError(
            stage="planning",
            exit_code=1,
            stdout="",
            stderr="Error",
        )
        assert isinstance(err, OpenCodeException)
