"""
taskq build-image command implementation.

Builds or rebuilds the local runtime image used by task execution.
"""

import sys
import argparse
from pathlib import Path

# Handle both absolute and relative imports
try:
    from orchestration.constants import DEFAULT_DOCKER_IMAGE
    from orchestration.adapters.docker import (
        build_runtime_image,
        ContainerError,
        ImageBuildError,
    )
except ImportError:
    from constants import DEFAULT_DOCKER_IMAGE
    from adapters.docker import build_runtime_image, ContainerError, ImageBuildError


def _repo_root() -> Path:
    """Return repository root from this module location."""
    return Path(__file__).resolve().parent.parent.parent


def cmd_build_image(cli_instance, args: argparse.Namespace) -> int:
    """Build or rebuild task runtime Docker image.

    Args:
        cli_instance: Unused TaskQCLI facade parameter (kept for command parity).
        args: Parsed command-line arguments with `rebuild` and `no_pull`.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    _ = cli_instance

    try:
        repo_root = _repo_root()
        dockerfile_path = repo_root / "orchestration" / "Dockerfile"
        context_path = repo_root
        image = DEFAULT_DOCKER_IMAGE
        rebuild = bool(getattr(args, "rebuild", False))
        pull = not bool(getattr(args, "no_pull", False))

        if not dockerfile_path.exists():
            print(f"Error: Dockerfile not found: {dockerfile_path}", file=sys.stderr)
            return 1

        print(f"Building runtime image: {image}")
        print(f"  Dockerfile: {dockerfile_path}")
        print(f"  Context: {context_path}")
        print(f"  Pull base image: {'yes' if pull else 'no'}")
        print(f"  Rebuild (no cache): {'yes' if rebuild else 'no'}")

        output = build_runtime_image(
            image=image,
            dockerfile_path=str(dockerfile_path),
            context_path=str(context_path),
            rebuild=rebuild,
            pull=pull,
        )

        if output.strip():
            print(output.strip())

        print(f"Runtime image ready: {image}")
        return 0

    except (ImageBuildError, ContainerError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
