#!/usr/bin/env python3
"""Create a simple manual E2E task file in the test repository."""

from pathlib import Path


TASK_ID = "T-TEST-HELLO-20260226"
TEST_REPO = Path.home() / "documents" / "repos" / "test"
TASK_FILE = TEST_REPO / "test.md"


def build_task_markdown(task_id: str, repo_path: Path) -> str:
    """Return canonical task markdown content."""
    return "\n".join(
        [
            "---",
            f"id: {task_id}",
            f"repo: {repo_path}",
            "base: main",
            "---",
            "Create a minimal Python hello world change in this repository.",
            "",
            "Requirements:",
            "- Add a new file named hello.py that prints exactly: Hello, world!",
            "- Do not add tests.",
            "- Keep the change minimal and self-contained.",
            "",
            "Verification:",
            "- The repository has at least one modified or new file after execution.",
        ]
    )


def main() -> int:
    if not TEST_REPO.exists():
        raise FileNotFoundError(f"Test repo not found: {TEST_REPO}")

    content = build_task_markdown(TASK_ID, TEST_REPO)
    TASK_FILE.write_text(content + "\n", encoding="utf-8")

    print(f"Task markdown written: {TASK_FILE}")
    print(f"Task ID: {TASK_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
