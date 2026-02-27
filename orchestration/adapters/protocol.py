"""Adapter protocol and contracts for runtime modules.

Defines the shared contract/interface for runtime adapters (git, docker, opencode, review).
Each adapter module implements specialized functionality while adhering to these base contracts.
"""

from typing import Protocol, Any, Dict, Optional, Tuple


# ============================================================================
# Base Exception Protocols
# ============================================================================


class AdapterException(Exception):
    """Base exception for all adapter errors."""

    pass


class GitAdapterException(AdapterException):
    """Base for git adapter errors."""

    pass


class DockerAdapterException(AdapterException):
    """Base for docker adapter errors."""

    pass


class OpenCodeAdapterException(AdapterException):
    """Base for opencode adapter errors."""

    pass


class ReviewAdapterException(AdapterException):
    """Base for review adapter errors."""

    pass


# ============================================================================
# Adapter Registry
# ============================================================================


class AdapterRegistry:
    """Registry for discovering and loading runtime adapters."""

    _adapters: Dict[str, Any] = {}

    @classmethod
    def register(cls, name: str, module: Any) -> None:
        """Register an adapter module by name.

        Args:
            name: Adapter name (e.g., 'git', 'docker', 'opencode', 'review').
            module: The adapter module object.
        """
        cls._adapters[name] = module

    @classmethod
    def get(cls, name: str) -> Optional[Any]:
        """Retrieve a registered adapter by name.

        Args:
            name: Adapter name.

        Returns:
            The adapter module, or None if not registered.
        """
        return cls._adapters.get(name)

    @classmethod
    def list(cls) -> list[str]:
        """List all registered adapter names.

        Returns:
            List of registered adapter names.
        """
        return list(cls._adapters.keys())
