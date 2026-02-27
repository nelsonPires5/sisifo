"""Unit tests for taskq build-image command."""

import argparse
from pathlib import Path

from unittest.mock import patch

from orchestration.constants import DEFAULT_DOCKER_IMAGE
from orchestration.adapters.docker import ContainerError
from orchestration.cli import cmd_build_image as cmd_build_image_module


def _args(rebuild: bool = False, no_pull: bool = False) -> argparse.Namespace:
    """Construct argparse namespace for build-image command."""
    return argparse.Namespace(rebuild=rebuild, no_pull=no_pull)


def test_build_image_success_uses_default_constant(tmp_path, monkeypatch):
    """build-image should tag with DEFAULT_DOCKER_IMAGE by default."""
    dockerfile_path = tmp_path / "orchestration" / "Dockerfile"
    dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
    dockerfile_path.write_text("FROM scratch\n", encoding="utf-8")

    monkeypatch.setattr(cmd_build_image_module, "_repo_root", lambda: tmp_path)

    with patch(
        "orchestration.cli.cmd_build_image.build_runtime_image",
        return_value="build ok",
    ) as mock_build:
        result = cmd_build_image_module.cmd_build_image(None, _args())

    assert result == 0
    assert mock_build.call_count == 1
    kwargs = mock_build.call_args.kwargs
    assert kwargs["image"] == DEFAULT_DOCKER_IMAGE
    assert kwargs["dockerfile_path"] == str(dockerfile_path)
    assert kwargs["context_path"] == str(tmp_path)
    assert kwargs["rebuild"] is False
    assert kwargs["pull"] is True


def test_build_image_rebuild_and_no_pull_flags(tmp_path, monkeypatch):
    """build-image flags should map to rebuild/pull options."""
    dockerfile_path = tmp_path / "orchestration" / "Dockerfile"
    dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
    dockerfile_path.write_text("FROM scratch\n", encoding="utf-8")

    monkeypatch.setattr(cmd_build_image_module, "_repo_root", lambda: tmp_path)

    with patch(
        "orchestration.cli.cmd_build_image.build_runtime_image",
        return_value="build ok",
    ) as mock_build:
        result = cmd_build_image_module.cmd_build_image(
            None,
            _args(rebuild=True, no_pull=True),
        )

    assert result == 0
    kwargs = mock_build.call_args.kwargs
    assert kwargs["rebuild"] is True
    assert kwargs["pull"] is False


def test_build_image_fails_when_dockerfile_missing(tmp_path, monkeypatch):
    """build-image should fail fast when Dockerfile path is missing."""
    monkeypatch.setattr(cmd_build_image_module, "_repo_root", lambda: tmp_path)

    result = cmd_build_image_module.cmd_build_image(None, _args())
    assert result == 1


def test_build_image_adapter_error_returns_failure(tmp_path, monkeypatch):
    """Adapter errors should map to non-zero exit code."""
    dockerfile_path = tmp_path / "orchestration" / "Dockerfile"
    dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
    dockerfile_path.write_text("FROM scratch\n", encoding="utf-8")

    monkeypatch.setattr(cmd_build_image_module, "_repo_root", lambda: tmp_path)

    with patch(
        "orchestration.cli.cmd_build_image.build_runtime_image",
        side_effect=ContainerError("boom"),
    ):
        result = cmd_build_image_module.cmd_build_image(None, _args())

    assert result == 1


def test_runtime_dockerfile_has_required_opencode_env_defaults():
    """Runtime Dockerfile should define required OpenCode env defaults."""
    repo_root = Path(__file__).resolve().parents[3]
    dockerfile = repo_root / "orchestration" / "Dockerfile"
    contents = dockerfile.read_text(encoding="utf-8")

    assert "ENV OPENCODE_DISABLE_AUTOUPDATE=false" in contents
    assert 'ENV OPENCODE_PERMISSION=\'{"*":"allow"}\'' in contents
