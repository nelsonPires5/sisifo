"""OpenCode command runtime helpers.

Provides wrappers for running OpenCode planning and building stage commands
(`make-plan`, `execute-plan`) against a mapped container endpoint.

Designed for worker integration - APIs accept stage, endpoint/port, task metadata,
and commands. Surfaces stdout/stderr and failures as structured exceptions.
"""

import subprocess
import json
import logging
import re
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass

try:
    from orchestration.constants import (
        DEFAULT_BUILD_AGENT,
        DEFAULT_BUILD_MODEL,
        DEFAULT_BUILD_VARIANT,
        DEFAULT_PLAN_AGENT,
        DEFAULT_PLAN_MODEL,
        DEFAULT_PLAN_VARIANT,
    )
    from orchestration.support.env import build_opencode_env
except ImportError:
    try:
        from ..constants import (
            DEFAULT_BUILD_AGENT,
            DEFAULT_BUILD_MODEL,
            DEFAULT_BUILD_VARIANT,
            DEFAULT_PLAN_AGENT,
            DEFAULT_PLAN_MODEL,
            DEFAULT_PLAN_VARIANT,
        )
        from ..support.env import build_opencode_env
    except ImportError:
        from constants import (
            DEFAULT_BUILD_AGENT,
            DEFAULT_BUILD_MODEL,
            DEFAULT_BUILD_VARIANT,
            DEFAULT_PLAN_AGENT,
            DEFAULT_PLAN_MODEL,
            DEFAULT_PLAN_VARIANT,
        )
        from support.env import build_opencode_env

logger = logging.getLogger(__name__)

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


# ============================================================================
# Exceptions
# ============================================================================


class OpenCodeException(Exception):
    """Base exception for OpenCode-related errors."""

    pass


class EndpointError(OpenCodeException):
    """Raised when endpoint is unreachable or malformed."""

    pass


class CommandError(OpenCodeException):
    """Raised when OpenCode command execution fails."""

    pass


class PlanError(CommandError):
    """Raised when `make-plan` command fails."""

    def __init__(
        self,
        stage: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        endpoint: str = "",
    ):
        self.stage = stage
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.endpoint = endpoint
        msg = f"Planning stage failed (exit code {exit_code})"
        if stderr:
            msg += f"\nStderr: {stderr[:500]}"
        super().__init__(msg)


class BuildError(CommandError):
    """Raised when `execute-plan` command fails."""

    def __init__(
        self,
        stage: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        endpoint: str = "",
    ):
        self.stage = stage
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.endpoint = endpoint
        msg = f"Building stage failed (exit code {exit_code})"
        if stderr:
            msg += f"\nStderr: {stderr[:500]}"
        super().__init__(msg)


# ============================================================================
# Endpoint management
# ============================================================================


def validate_endpoint(host: str, port: int) -> str:
    """
    Validate and normalize OpenCode endpoint URL.

    Args:
        host: Hostname or IP (e.g., "127.0.0.1" or "localhost").
        port: Port number (1-65535).

    Returns:
        Normalized endpoint URL (e.g., "http://127.0.0.1:8000").

    Raises:
        EndpointError: If endpoint is invalid.
    """
    if not host or not isinstance(host, str):
        raise EndpointError(f"Invalid host: {host}")

    if not isinstance(port, int) or port < 1 or port > 65535:
        raise EndpointError(f"Invalid port: {port}")

    # Normalize URL
    if not host.startswith(("http://", "https://")):
        endpoint = f"http://{host}:{port}"
    else:
        # Extract port if already in URL
        if "://" in host:
            endpoint = host if ":" in host.split("://")[1] else f"{host}:{port}"
        else:
            endpoint = f"{host}:{port}"

    logger.debug(f"Validated endpoint: {endpoint}")
    return endpoint


# ============================================================================
# Command execution
# ============================================================================


def run_make_plan(
    endpoint: str,
    task_body: str,
    timeout: int = 300,
    workdir: Optional[str] = None,
    agent: str = DEFAULT_PLAN_AGENT,
    model: str = DEFAULT_PLAN_MODEL,
    variant: str = DEFAULT_PLAN_VARIANT,
) -> Tuple[str, str]:
    """
    Execute `make-plan` command against OpenCode server.

    Runs the planning stage command and returns captured output.

    Args:
        endpoint: OpenCode server endpoint URL (e.g., "http://127.0.0.1:8000").
        task_body: Task description/prompt to send to planner.
        timeout: Command timeout in seconds (default 300).
        workdir: Optional working directory to pass to OpenCode with --dir flag.

    Returns:
        Tuple of (stdout, stderr) from command.

    Raises:
        EndpointError: If endpoint is invalid.
        PlanError: If command fails.
    """
    if not endpoint:
        raise EndpointError("Endpoint cannot be empty")

    if not task_body or not isinstance(task_body, str):
        raise EndpointError("task_body must be non-empty string")

    logger.info(f"Running make-plan on endpoint {endpoint}")

    try:
        # Run make-plan inside the container to use its config/auth context.
        container_id = _container_id_from_endpoint(endpoint)
        cmd = ["docker", "exec"]
        if workdir:
            cmd.extend(["-w", workdir])
        cmd.append(container_id)
        cmd.extend(
            [
                "opencode",
                "run",
                "--model",
                model,
                "--variant",
                variant,
                "--agent",
                agent,
                "--command",
                "make-plan-sisifo",
                task_body,
            ]
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=build_opencode_env(),
        )

        if result.returncode != 0 or __stderr_has_failure(result.stderr):
            raise PlanError(
                stage="planning",
                exit_code=result.returncode if result.returncode != 0 else -1,
                stdout=result.stdout,
                stderr=result.stderr,
                endpoint=endpoint,
            )

        logger.info(f"make-plan succeeded on {endpoint}")
        return result.stdout, result.stderr

    except subprocess.TimeoutExpired:
        raise PlanError(
            stage="planning",
            exit_code=-1,
            stdout="",
            stderr=f"Command timeout after {timeout}s",
            endpoint=endpoint,
        )
    except PlanError:
        raise
    except Exception as e:
        raise PlanError(
            stage="planning",
            exit_code=-1,
            stdout="",
            stderr=str(e),
            endpoint=endpoint,
        )


def run_execute_plan(
    endpoint: str,
    timeout: int = 600,
    workdir: Optional[str] = None,
    agent: str = DEFAULT_BUILD_AGENT,
    model: str = DEFAULT_BUILD_MODEL,
    variant: str = DEFAULT_BUILD_VARIANT,
) -> Tuple[str, str]:
    """
    Execute `execute-plan` command against OpenCode server.

    Runs the building stage command.

    Args:
        endpoint: OpenCode server endpoint URL.
        timeout: Command timeout in seconds (default 600).
        workdir: Optional working directory to pass to OpenCode with --dir flag.

    Returns:
        Tuple of (stdout, stderr) from command.

    Raises:
        EndpointError: If endpoint is invalid.
        BuildError: If command fails.
    """
    if not endpoint:
        raise EndpointError("Endpoint cannot be empty")

    logger.info(f"Running execute-plan on endpoint {endpoint}")

    try:
        # Run execute-plan inside the container to use its config/auth context.
        container_id = _container_id_from_endpoint(endpoint)
        cmd = ["docker", "exec"]
        if workdir:
            cmd.extend(["-w", workdir])
        cmd.append(container_id)
        cmd.extend(
            [
                "opencode",
                "run",
                "--model",
                model,
                "--variant",
                variant,
                "--agent",
                agent,
                "--command",
                "execute-plan-sisifo",
            ]
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=build_opencode_env(),
        )

        if result.returncode != 0 or __stderr_has_failure(result.stderr):
            raise BuildError(
                stage="building",
                exit_code=result.returncode if result.returncode != 0 else -1,
                stdout=result.stdout,
                stderr=result.stderr,
                endpoint=endpoint,
            )

        logger.info(f"execute-plan succeeded on {endpoint}")
        return result.stdout, result.stderr

    except subprocess.TimeoutExpired:
        raise BuildError(
            stage="building",
            exit_code=-1,
            stdout="",
            stderr=f"Command timeout after {timeout}s",
            endpoint=endpoint,
        )
    except BuildError:
        raise
    except Exception as e:
        raise BuildError(
            stage="building",
            exit_code=-1,
            stdout="",
            stderr=str(e),
            endpoint=endpoint,
        )


# ============================================================================
# Utilities
# ============================================================================


def __stderr_has_failure(stderr: str) -> bool:
    """Return True when stderr content indicates command failure."""
    if not stderr:
        return False

    normalized = ANSI_ESCAPE_RE.sub("", stderr).strip().lower()
    if not normalized:
        return False

    failure_markers = (
        "error:",
        "failed to change directory",
        "unknown command",
        "not found",
        "unrecognized",
    )
    return any(marker in normalized for marker in failure_markers)


def _container_id_from_endpoint(endpoint: str) -> str:
    if not endpoint:
        raise EndpointError("Endpoint cannot be empty")

    if not endpoint.startswith("http://"):
        raise EndpointError(f"Unsupported endpoint format: {endpoint}")

    try:
        port_str = endpoint.rsplit(":", 1)[-1]
        port = int(port_str)
    except ValueError as e:
        raise EndpointError(f"Invalid endpoint port in {endpoint}") from e

    return _container_id_from_port(port)


def _container_id_from_port(port: int) -> str:
    try:
        result = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"publish={port}",
                "--format",
                "{{.ID}}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired as e:
        raise EndpointError("Timeout resolving container for endpoint") from e
    except Exception as e:
        raise EndpointError(f"Failed to resolve container for port {port}: {e}") from e

    if result.returncode != 0:
        raise EndpointError(
            f"Failed to resolve container for port {port}: {result.stderr}"
        )

    container_id = result.stdout.strip().splitlines()
    if not container_id or not container_id[0]:
        raise EndpointError(f"No running container found for port {port}")

    return container_id[0]


def run_plan_sequence(
    endpoint: str,
    task_body: str,
    plan_timeout: int = 300,
    build_timeout: int = 600,
    workdir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute full planning + building sequence against endpoint.

    Runs `make-plan` followed by `execute-plan`, with error propagation
    indicating which stage failed.

    Args:
        endpoint: OpenCode server endpoint URL.
        task_body: Task description for planning stage.
        plan_timeout: Timeout for make-plan in seconds (default 300).
        build_timeout: Timeout for execute-plan in seconds (default 600).
        workdir: Optional working directory to pass to OpenCode with --dir flag.

    Returns:
        Dictionary with keys:
        - 'plan_stdout', 'plan_stderr': Output from make-plan
        - 'build_stdout', 'build_stderr': Output from execute-plan
        - 'status': 'success' | 'plan_failed' | 'build_failed'
        - 'error': Exception if failed (PlanError or BuildError)

    Example:
        result = run_plan_sequence("http://127.0.0.1:8000", "Implement X feature")
        if result['status'] == 'success':
            print("Planning and building completed")
        elif result['status'] == 'plan_failed':
            print(f"Planning failed: {result['error'].stderr}")
    """
    result = {
        "plan_stdout": "",
        "plan_stderr": "",
        "build_stdout": "",
        "build_stderr": "",
        "status": "success",
        "error": None,
    }

    try:
        logger.info(f"Starting plan sequence on {endpoint}")
        result["plan_stdout"], result["plan_stderr"] = run_make_plan(
            endpoint,
            task_body,
            timeout=plan_timeout,
            workdir=workdir,
        )
        logger.info("Planning stage completed successfully")

        result["build_stdout"], result["build_stderr"] = run_execute_plan(
            endpoint,
            timeout=build_timeout,
            workdir=workdir,
        )
        logger.info("Building stage completed successfully")
        result["status"] = "success"

    except PlanError as e:
        logger.error(f"Planning stage failed: {e}")
        result["status"] = "plan_failed"
        result["error"] = e
        result["plan_stdout"] = e.stdout
        result["plan_stderr"] = e.stderr

    except BuildError as e:
        logger.error(f"Building stage failed: {e}")
        result["status"] = "build_failed"
        result["error"] = e
        # plan_stdout/stderr already set from previous stage
        result["build_stdout"] = e.stdout
        result["build_stderr"] = e.stderr

    except Exception as e:
        logger.error(f"Unexpected error in plan sequence: {e}")
        result["status"] = "plan_failed"
        result["error"] = PlanError(
            stage="planning",
            exit_code=-1,
            stdout="",
            stderr=str(e),
        )

    return result
