# AGENTS.md

Repository guide for agentic coding tools working in `sisifo`.

## Scope and Intent

- This repo is a Python 3.11 task orchestration CLI (`taskq`).
- Main package: `orchestration/`.
- Queue state lives under `queue/` (`tasks.jsonl`, `tasks/`, `errors/`).
- Default worker image is `ghcr.io/anomalyco/opencode:latest`.
- Runtime container naming is `task-<task-id>-<created-at-compact>`.
- Use this file as the default runbook for edits, tests, and reviews.

## CLI Behavior (Current)

- `taskq add`:
  - With `--task`: require `--id` and `--repo`.
  - With `--task-file`: `--id`/`--repo` are optional when available from frontmatter.
  - If task-file lacks `id`, derive ID from normalized filename stem.
  - Supported task-file frontmatter keys: `id`, `repo`, `base`, `branch`, `worktree_path`.
  - Do not rewrite task-file content to inject defaults; resolve defaults into `tasks.jsonl` only.
  - `worktree_path` can be set by frontmatter or `--worktree-path`.
- `taskq run`:
  - Default mode is single-pass (no polling loop).
  - Use `--poll [SECONDS]` to enable polling (`5` seconds when no value passed).
  - Use `--id <ID>` to run one specific `todo` task once.
  - Use `--cleanup-on-fail` to remove task container/worktree when a run fails.
  - By default failures preserve worktree/container for inspection.
  - Use `--dirty-run` to reuse an existing worktree and clear stale task containers before launch.
  - `--id` cannot be combined with `--poll`.
  - Removed flags: `--once`, `--poll-interval-sec`, `--worktrees-root`.
- Worker setup expects `worktree_path` to be present in each task record.

## Environment and Setup

- Work from repo root: `/home/np/documents/repos/sisifo`.
- Sync deps first: `uv sync`.
- Confirm CLI entrypoint: `uv run taskq --help`.

## Build, Lint, and Test Commands

### Build
- Build source/wheel artifacts: `uv build`.
- Expected outputs:
  - `dist/sisifo_taskq-<version>.tar.gz`
  - `dist/sisifo_taskq-<version>-py3-none-any.whl`

### Lint / Static Validation
- No dedicated Ruff/Flake8/Mypy config is committed today.
- Canonical lightweight check:
  - `uv run python -m py_compile orchestration/taskq.py orchestration/queue_store.py orchestration/worker.py orchestration/runtime_git.py orchestration/runtime_docker.py orchestration/runtime_opencode.py orchestration/runtime_review.py orchestration/task_files.py`
- Optional broad compile check:
  - `uv run python -m py_compile orchestration/*.py`

### Tests
- Full suite: `uv run pytest orchestration/tests -q`
- Verbose run: `uv run pytest orchestration/tests -v`
- Single file: `uv run pytest orchestration/tests/test_taskq.py -q`
- Single class: `uv run pytest orchestration/tests/test_taskq.py::TestTaskQCLIRun -q`
- Single test (preferred pattern):
  - `uv run pytest orchestration/tests/test_queue_store.py::TestQueueStoreAddRecord::test_add_single_record -q`
- Filter by expression: `uv run pytest orchestration/tests -k "cleanup and not smoke" -q`
- Stop early on failure: `uv run pytest orchestration/tests -x -q`

### Supplemental Validation
- Smoke checks: `uv run python orchestration/tests/smoke_tests.py`
- End-to-end validation script: `uv run python orchestration/tests/e2e_validation.py`

## High-Value Paths

- CLI entrypoint: `orchestration/taskq.py`
- Queue persistence/state machine: `orchestration/queue_store.py`
- Worker pipeline orchestration: `orchestration/worker.py`
- Task markdown/frontmatter helpers: `orchestration/task_files.py`
- Runtime adapters: `orchestration/runtime_git.py`, `orchestration/runtime_docker.py`, `orchestration/runtime_opencode.py`, `orchestration/runtime_review.py`
- Tests: `orchestration/tests/`

## Code Style and Conventions

### Python and Formatting
- Target Python version: `>=3.11`.
- Use 4-space indentation.
- Prefer double quotes for strings.
- Keep concise module/class/function docstrings.
- Preserve existing section-divider style where present (`# ====...====`).

### Imports
- Group imports as: standard library, third-party, local package.
- Keep import style consistent within any file you touch.
- Preserve dual-import fallback pattern used by CLI/runtime modules:
  - `try: from orchestration...`
  - `except ImportError: from ...`
- Remove unused imports when editing nearby code.

### Types and Data Modeling
- Add type hints to new/modified signatures.
- Prefer explicit return types for public functions.
- Use dataclasses for structured payloads (`TaskRecord`, `ContainerConfig`).
- Keep serialized record shape aligned with `TaskRecord`.
- Use `Dict[str, Any]` only when stricter typing is impractical.

### Naming
- Functions/variables: `snake_case`.
- Classes/exceptions: `PascalCase`.
- Constants: `UPPER_SNAKE_CASE`.
- Tests: `test_*.py` files and `test_*` functions.
- Treat task IDs as external identifiers (`T-001` style).

### Error Handling and Exceptions
- Validate inputs early; fail with explicit messages.
- Prefer domain exceptions over generic `Exception`.
- When wrapping subprocess/runtime failures, include stage, exit code, stdout, and stderr when available.
- Keep CLI command behavior: return `0` on success, `1` on failure.
- Print user-facing CLI failures to `stderr`.
- On task failure, cleanup all containers matching the task ID (not just the latest container handle).

### Logging and Output
- Use module-level logger pattern: `logger = logging.getLogger(__name__)`.
- `debug` for noisy internals, `info` for stage transitions, `warning/error` for failures.
- Keep log messages actionable and tied to task ID/stage where possible.

### Paths, Files, and IO
- Prefer `pathlib.Path` for path handling.
- Keep queue paths deterministic and repo-root relative where expected.
- Ensure directories exist before writes: `mkdir(parents=True, exist_ok=True)`.
- Ensure queue bootstrap creates `queue/tasks.jsonl`, `queue/tasks/`, and `queue/errors/` when missing.
- Write text files with explicit encoding (`utf-8`).

### Timestamps and Timezones
- Existing code often uses `datetime.utcnow().isoformat()`.
- For new code, prefer timezone-aware UTC when practical:
  - `datetime.now(timezone.utc).isoformat()`
- Do not mix timestamp formats within one logical flow.

## Testing Practices for Changes

- Add or update tests in `orchestration/tests/` alongside behavior changes.
- Prefer pytest fixtures with `tmp_path` or `TemporaryDirectory` for isolation.
- Mock subprocess/docker/external tool boundaries in unit tests.
- Keep tests deterministic; avoid host-global mutable state.
- For fixes, run the smallest relevant test first, then broaden scope.

## Agent Workflow Expectations

- Keep changes focused; avoid unrelated refactors.
- Preserve task status state-machine constraints.
- Keep cleanup/retry paths idempotent.
- Update docs if CLI behavior or operator flow changes.
- Before handoff, run at least one targeted test and report it.

## Cursor and Copilot Rules

- Checked locations:
  - `.cursor/rules/`
  - `.cursorrules`
  - `.github/copilot-instructions.md`
- Current status: no Cursor or Copilot rule files found in this repo.
- If these files appear later, treat them as additional authoritative instructions.

## Quick Command Cheatsheet

- Sync deps: `uv sync`
- CLI help: `uv run taskq --help`
- Add inline task: `uv run taskq add --id T-001 --repo /abs/repo --task "Do X"`
- Add from file: `uv run taskq add --task-file queue/tasks/T-001.md`
- Full tests: `uv run pytest orchestration/tests -q`
- Single test: `uv run pytest path/to/test_file.py::TestClass::test_name -q`
- Run single pass: `uv run taskq run --max-parallel 3`
- Run polling loop: `uv run taskq run --max-parallel 3 --poll 5`
- Run one task by ID: `uv run taskq run --id T-001`
- Run one task with preserved dirty rerun: `uv run taskq run --id T-001 --dirty-run`
- Run one task with failure auto-cleanup: `uv run taskq run --id T-001 --cleanup-on-fail`
- Syntax check: `uv run python -m py_compile orchestration/*.py`
- Build package: `uv build`
