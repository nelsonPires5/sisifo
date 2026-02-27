"""
Environment variable helpers for subprocess management.

Provides safe environment builders for OpenCode and OpenChamber runtimes
with argumentized filtering for X11 support and other specialized needs.
"""

import os
from typing import Dict, List, Optional


def build_safe_env(
    include_x11_keys: bool = False,
    extra_keys: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Build safe environment variables for subprocess execution.

    Filters environment to safe/essential keys while optionally including
    X11-related variables and arbitrary extra keys.

    Args:
        include_x11_keys: If True, include DISPLAY and XAUTHORITY for X11.
        extra_keys: Additional environment keys to include if present.

    Returns:
        Dictionary of safe environment variables suitable for subprocess.run().
    """
    # Core safe keys always included
    safe_keys = [
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "PWD",
        "TMPDIR",
    ]

    # Optionally add X11 keys (for interactive sessions like OpenChamber review)
    if include_x11_keys:
        safe_keys.extend(["DISPLAY", "XAUTHORITY"])

    # Add any additional requested keys
    if extra_keys:
        safe_keys.extend(extra_keys)

    # Build environment, only including keys that exist
    return {k: os.environ.get(k, "") for k in safe_keys if k in os.environ}


def build_opencode_env(
    extra_keys: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Build environment for OpenCode command execution.

    OpenCode subprocess (make-plan, execute-plan) do not need X11 keys.

    Args:
        extra_keys: Additional environment keys to include if present.

    Returns:
        Dictionary of safe environment variables.
    """
    return build_safe_env(include_x11_keys=False, extra_keys=extra_keys)


def build_review_env(
    endpoint: str,
    skip_start: bool = True,
    opencode_config_dir: Optional[str] = None,
    opencode_data_dir: Optional[str] = None,
) -> Dict[str, str]:
    """Build environment for openchamber review subprocess.

    Includes X11 keys for interactive session and OpenCode-specific variables
    for strict-local directory configuration.

    Args:
        endpoint: OpenCode server endpoint URL (e.g., "http://127.0.0.1:8000").
        skip_start: If True, set OPENCODE_SKIP_START=true.
        opencode_config_dir: Optional strict-local config directory path.
        opencode_data_dir: Optional strict-local data directory path.

    Returns:
        Dictionary of environment variables suitable for subprocess.run().
    """
    # Start with safe base environment including X11 keys for interactive session
    env = build_safe_env(include_x11_keys=True)

    # Add OpenCode-specific variables
    env["OPENCODE_HOST"] = endpoint
    if skip_start:
        env["OPENCODE_SKIP_START"] = "true"

    # Set strict-local directories if provided
    if opencode_config_dir:
        env["OPENCODE_CONFIG_DIR"] = opencode_config_dir
    if opencode_data_dir:
        env["OPENCODE_DATA_DIR"] = opencode_data_dir

    return env
