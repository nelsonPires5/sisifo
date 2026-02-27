# AGENTS.md

Repository guide for agentic coding tools working in `sisifo`.

## Scope and Intent

- This repo is a Python 3.11 task orchestration CLI (`taskq`).
- Main package: `orchestration/`.
- Queue state lives under `queue/` (`tasks.jsonl`, `tasks/`, `errors/`, `opencode/`).
- Default worker image is `sisifo/opencode:latest`.
- Runtime container naming is `task-<task-id>-<created-at-compact>`.
- Use this file as the default runbook for edits, tests, and reviews.

## Current Architecture (Layered)

Canonical package layout:

```text
orchestration/
  __init__.py
  constants.py
  core/
    models.py
    naming.py
    exceptions.py
  store/
    repository.py
    error_store.py
  support/
    paths.py
    task_files.py
    env.py
  adapters/
    git.py
    docker.py
    opencode.py
    review.py
    protocol.py
  pipeline/
    processor.py
    stages.py
    error_reporting.py
  cli/
    cmd_add.py
    cmd_status.py
    cmd_remove.py
    cmd_transitions.py
    cmd_run.py
    cmd_review.py
    cmd_cleanup.py
    cmd_build_image.py
  taskq.py
```

Legacy flat modules were removed. Do not reintroduce:

- `orchestration/queue_store.py`
- `orchestration/task_files.py`
- `orchestration/worker.py`
- `orchestration/runtime_git.py`
- `orchestration/runtime_docker.py`
- `orchestration/runtime_opencode.py`
- `orchestration/runtime_review.py`
- `orchestration/queue_helpers.py`

### Dependency Rules (Must Hold)

- `core`: domain-only; no dependency on higher layers.
- `store`: depends on `core`.
- `support`: helpers/utilities, independent of pipeline/cli.
- `adapters`: runtime integrations; may use `core` and `support`.
- `pipeline`: orchestrates execution using `core` + `store` + `adapters` + `support`.
- `cli`: command handlers; may depend on all lower layers.
- `taskq.py`: thin parser + dispatch entrypoint only.

## CLI Behavior (Current)

- `taskq add`:
  - With `--task`: require `--id` and `--repo`.
  - With `--task-file`: `--id` and `--repo` optional when available from frontmatter.
  - If task-file lacks `id`, derive ID from normalized filename stem.
  - Supported task-file frontmatter keys: `id`, `repo`, `base`, `branch`, `worktree_path`.
  - Do not rewrite task-file content to inject defaults; resolve defaults into `tasks.jsonl` only.
  - `worktree_path` can be set by frontmatter or `--worktree-path`.
- `taskq run`:
  - Default mode is single-pass (no polling loop).
  - Use `--poll [SECONDS]` to enable polling (`5` seconds when no value passed).
  - Use `--id <ID>` to run one specific `todo` task once.
  - Use `--cleanup-on-fail` to remove task container/worktree on failure.
  - By default failures preserve worktree/container for inspection.
  - Use `--dirty-run` to reuse an existing worktree and clear stale task containers before launch.
  - Use `--follow` to stream worker/runtime logs during execution.
  - `--id` cannot be combined with `--poll`.
- `taskq review`:
  - Task must be `review` and have `port > 0`.
  - Requires `opencode_config_dir` and `opencode_data_dir` to exist.
- `taskq cleanup`:
  - Cleans `done` + `cancelled` by default.
  - Supports `--done-only`, `--cancelled-only`, `--id`, `--keep-worktree`.
- `taskq build-image`:
  - Builds image tag from `DEFAULT_DOCKER_IMAGE` in `orchestration/constants.py`.
  - Uses Dockerfile at `orchestration/Dockerfile` (context: repo root).
  - Supports `--rebuild` (no-cache) and `--no-pull` (skip base-image refresh).
- Worker/pipeline setup expects `worktree_path` in each task record.

## Environment and Setup

- Work from repo root: `/home/np/documents/repos/sisifo`.
- Sync deps first: `uv sync`.
- Confirm entrypoint: `uv run taskq --help`.

## Build, Lint, and Test Commands

### Build

- Build source/wheel artifacts: `uv build`.
- Expected outputs:
  - `dist/sisifo_taskq-<version>.tar.gz`
  - `dist/sisifo_taskq-<version>-py3-none-any.whl`

### Lint / Static Validation

- No dedicated Ruff/Flake8/Mypy config is committed today.
- Canonical compile check:
  - `uv run python -m py_compile orchestration/taskq.py orchestration/constants.py orchestration/core/*.py orchestration/store/*.py orchestration/support/*.py orchestration/adapters/*.py orchestration/pipeline/*.py orchestration/cli/*.py`

### Tests

- Full suite: `uv run pytest orchestration/tests -q`
- Verbose run: `uv run pytest orchestration/tests -v`
- Layer-focused runs:
  - `uv run pytest orchestration/tests/store -q`
  - `uv run pytest orchestration/tests/support -q`
  - `uv run pytest orchestration/tests/adapters -q`
  - `uv run pytest orchestration/tests/pipeline -q`
  - `uv run pytest orchestration/tests/cli -q`
- Single file:
  - `uv run pytest orchestration/tests/cli/test_taskq.py -q`
- Single class:
  - `uv run pytest orchestration/tests/pipeline/test_worker.py::TestTaskProcessorPipeline -q`
- Single test (preferred pattern):
  - `uv run pytest orchestration/tests/store/test_queue_store.py::TestQueueStoreAddRecord::test_add_single_record -q`
- Filter by expression:
  - `uv run pytest orchestration/tests -k "cleanup and not smoke" -q`
- Stop early on failure:
  - `uv run pytest orchestration/tests -x -q`

### Supplemental Validation

- Smoke checks: `uv run python orchestration/tests/smoke_tests.py`
- End-to-end validation script: `uv run python orchestration/tests/e2e_validation.py`

## High-Value Paths

- CLI entrypoint (thin): `orchestration/taskq.py`
- CLI command dispatch: `orchestration/cli/`
- Domain model and transitions: `orchestration/core/models.py`
- Naming helpers: `orchestration/core/naming.py`
- Queue persistence/state machine enforcement: `orchestration/store/repository.py`
- Error report persistence: `orchestration/store/error_store.py`
- Pipeline orchestrator: `orchestration/pipeline/processor.py`
- Pipeline stages: `orchestration/pipeline/stages.py`
- Runtime adapters: `orchestration/adapters/*.py`
- Runtime image build command: `orchestration/cli/cmd_build_image.py`
- Runtime image definition: `orchestration/Dockerfile`
- Task/frontmatter and path helpers: `orchestration/support/task_files.py`, `orchestration/support/paths.py`
- Environment filtering helpers: `orchestration/support/env.py`
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
- Preserve dual-import fallback pattern used by package modules:
  - `try: from orchestration...`
  - `except ImportError: from ...`
- Remove unused imports when editing nearby code.
- Do not add imports from removed legacy module paths.

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
- On task failure, cleanup all containers matching the task ID (not just a single container handle).

### Logging and Output

- Use module-level logger pattern: `logger = logging.getLogger(__name__)`.
- `debug` for noisy internals, `info` for stage transitions, `warning/error` for failures.
- Keep log messages actionable and tied to task ID/stage when possible.

### Paths, Files, and IO

- Prefer `pathlib.Path` for path handling.
- Keep queue paths deterministic and repo-root relative where expected.
- Ensure directories exist before writes: `mkdir(parents=True, exist_ok=True)`.
- Ensure queue bootstrap creates `queue/tasks.jsonl`, `queue/tasks/`, `queue/errors/`, `queue/opencode/` when missing.
- Write text files with explicit encoding (`utf-8`).

### Timestamps and Timezones

- Existing code still uses `datetime.utcnow().isoformat()` in many paths.
- For new code, prefer timezone-aware UTC when practical:
  - `datetime.now(timezone.utc).isoformat()`
- Do not mix timestamp formats within one logical flow.

## Testing Practices for Changes

- Add or update tests under the matching layer directory:
  - `tests/store/`, `tests/support/`, `tests/adapters/`, `tests/pipeline/`, `tests/cli/`
- Prefer pytest fixtures with `tmp_path` or `TemporaryDirectory` for isolation.
- Mock subprocess/docker/external tool boundaries in unit tests.
- Keep tests deterministic; avoid host-global mutable state.
- For fixes, run the smallest relevant test first, then broaden scope.
- If moving symbols across modules, update patch targets in tests to the new canonical path.

## Agent Workflow Expectations

- Keep changes focused; avoid unrelated refactors.
- Preserve task status state-machine constraints.
- Keep cleanup/retry paths idempotent.
- Keep `orchestration/taskq.py` thin; put command logic in `orchestration/cli/*`.
- Keep `pipeline` stage behavior stable when refactoring internals.
- Update docs if CLI behavior or operator flow changes.
- Before handoff, run at least one targeted test and report it.

### Operator Flow: Review and Cleanup with Attempt Directories

**Review phase:**

- Task transitions to `review` after successful pipeline setup/execute/success stages.
- Task record stores `opencode_attempt_dir`, `opencode_config_dir`, and `opencode_data_dir`.
- Operator runs `taskq review --id <ID>`, which validates strict-local directories.
- OpenChamber (via `orchestration.adapters.review`) receives attempt-specific config/data via env.
- Container mounts strict-local directories, not host-global OpenCode dirs.

**Cleanup phase:**

- For terminal tasks (`done`/`cancelled`), `taskq cleanup` removes:
  - Docker container(s) for task ID
  - Git worktree (unless `--keep-worktree`)
  - `queue/opencode/<task-id>/` (all attempts)
  - Error file (if present)
  - Runtime fields in task record (`opencode_*`, `port`, `container`, etc.)
- Cleanup is idempotent and safe to rerun.
- Canonical task markdown in `queue/tasks/<task-id>.md` is preserved.

**Retry with attempt increment:**

- On `taskq retry --id <ID>` from `failed`:
  - Status transitions `failed -> todo`
  - Attempt counter increments
  - Runtime handles are cleared (`port`, `container`, `opencode_*`)
  - Next `taskq run` creates fresh attempt dirs and re-bootstraps config/data
- Each attempt has isolated state; no cross-attempt pollution.

## Legacy Import Guardrails

When checking cutover integrity, these patterns should not appear in code:

- `from orchestration.runtime_`
- `from orchestration.queue_store`
- `from orchestration.task_files`
- `from orchestration.worker`
- `from orchestration.queue_helpers`

Exception: historical docs/plans may still contain these strings.

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
- Run one task with dirty rerun: `uv run taskq run --id T-001 --dirty-run`
- Run one task with failure auto-cleanup: `uv run taskq run --id T-001 --cleanup-on-fail`
- Run one task with streamed logs: `uv run taskq run --id T-001 --follow`
- Build runtime image: `uv run taskq build-image`
- Rebuild runtime image (no cache): `uv run taskq build-image --rebuild`
- Compile check: `uv run python -m py_compile orchestration/taskq.py orchestration/constants.py orchestration/core/*.py orchestration/store/*.py orchestration/support/*.py orchestration/adapters/*.py orchestration/pipeline/*.py orchestration/cli/*.py`
- Build package: `uv build`
