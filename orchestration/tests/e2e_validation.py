#!/usr/bin/env python3
"""
End-to-end validation checks for task orchestration system.

Verifies:
1. Syntax validation for all Python files
2. CLI help text for all commands
3. Core imports
4. Basic command argument parsing
"""

import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
ORCHESTRATION_DIR = ROOT_DIR / "orchestration"


def run_command(cmd: list, description: str) -> bool:
    """Run a command and report results."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            print(f"[ok] {description}")
            return True
        else:
            print(f"[error] {description}")
            if result.stderr:
                print(f"  Error: {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"[error] {description} (timeout)")
        return False
    except Exception as e:
        print(f"[error] {description} ({e})")
        return False


def syntax_check(filepath: Path) -> bool:
    """Check Python file syntax."""
    return run_command(
        ["python3", "-m", "py_compile", str(filepath)],
        f"Syntax check: {filepath.name}",
    )


def cli_help_check(command: str) -> bool:
    """Check CLI help for a command."""
    import os

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT_DIR)

    cmd = [
        "python3",
        str(ORCHESTRATION_DIR / "taskq.py"),
    ]
    if command:
        cmd.append(command)
    cmd.append("--help")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        if result.returncode == 0 and (
            "usage:" in result.stdout or "positional arguments:" in result.stdout
        ):
            return run_command(cmd, f"CLI help: taskq {command or '(main)'}")
        else:
            print(f"[error] CLI help: taskq {command or '(main)'}")
            return False
    except Exception as e:
        print(f"[error] CLI help: taskq {command or '(main)'} ({e})")
        return False


def main():
    """Run all validation checks."""
    print("=" * 70)
    print("TASK ORCHESTRATION SYSTEM - END-TO-END VALIDATION")
    print("=" * 70)
    print()

    # Setup
    orchestration_dir = ORCHESTRATION_DIR
    all_passed = True

    # 1. Syntax checks
    print("SYNTAX CHECKS")
    print("-" * 70)
    python_files = [
        "taskq.py",
        "constants.py",
    ]

    for py_file in python_files:
        filepath = orchestration_dir / py_file
        if filepath.exists():
            if not syntax_check(filepath):
                all_passed = False
        else:
            print(f"[warn] {py_file} not found (skipped)")

    print()

    # 2. CLI help checks
    print("CLI HELP CHECKS")
    print("-" * 70)
    commands = [
        "",  # Main help
        "add",
        "status",
        "run",
        "review",  # NEW
        "cleanup",  # NEW
        "build-image",  # NEW
        "approve",
        "cancel",
        "retry",
        "remove",
    ]

    for cmd in commands:
        if not cli_help_check(cmd):
            all_passed = False

    print()

    # 3. Import checks
    print("IMPORT CHECKS")
    print("-" * 70)

    sys.path.insert(0, str(orchestration_dir))

    imports_to_check = [
        ("orchestration.store.repository", ["QueueStore", "TaskRecord"]),
        (
            "orchestration.support.task_files",
            ["create_canonical_task_file", "write_task_file"],
        ),
        ("orchestration.pipeline.processor", ["TaskProcessor"]),
        ("orchestration.adapters.git", ["remove_worktree"]),
        ("orchestration.adapters.docker", ["cleanup_task_containers"]),
        ("orchestration.adapters.review", ["launch_review_from_record"]),
    ]

    for module_name, items in imports_to_check:
        try:
            module = __import__(module_name, fromlist=items)
            for item in items:
                if hasattr(module, item):
                    print(f"[ok] Import: {module_name}.{item}")
                else:
                    print(f"[error] Import: {module_name}.{item} not found")
                    all_passed = False
        except ImportError as e:
            print(f"[error] Import: {module_name} failed: {e}")
            all_passed = False

    print()

    # 4. README check
    print("DOCUMENTATION CHECKS")
    print("-" * 70)
    readme_path = ROOT_DIR / "README.md"
    if readme_path.exists():
        content = readme_path.read_text()
        required_sections = [
            "Operator Workflow",
            "Command Reference",
            "taskq add",
            "taskq review",
            "taskq cleanup",
            "Status Transitions",
            "Runtime Artifacts",
        ]

        for section in required_sections:
            if section in content:
                print(f"[ok] README section: {section}")
            else:
                print(f"[error] README section: {section} not found")
                all_passed = False
    else:
        print(f"[error] README.md not found")
        all_passed = False

    print()
    print("=" * 70)
    if all_passed:
        print("[ok] ALL CHECKS PASSED")
        print("=" * 70)
        return 0
    else:
        print("[error] SOME CHECKS FAILED")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
