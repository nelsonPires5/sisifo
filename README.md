# Task Orchestration System

The task orchestration system manages queued tasks through a complete lifecycle: from task creation through execution, review, and approval to final completion or cancellation.

## Quickstart (uv)

From the repository root:

```bash
uv sync
uv run taskq --help
```

Typical usage from root:

```bash
uv run taskq add --id T-001 --repo sisifo --task "Implement feature X"
uv run taskq status
uv run taskq run --max-parallel 3
```

You do not need to `cd orchestration`. The queue paths default to `<repo-root>/queue/...`.

If you are outside the repo directory, point uv at this project explicitly:

```bash
uv run --project /path/to/sisifo taskq status
```

## Operator Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                      TASK LIFECYCLE                             │
└─────────────────────────────────────────────────────────────────┘

                           ┌──────────┐
                           │   ADD    │
                           │  (todo)  │
                           └────┬─────┘
                                │
                    ┌───────────┴───────────┐
                    │                       │
            ┌───────▼──────┐        ┌──────▼────────┐
            │     RUN      │        │  MANUAL TEST  │
            │ (planning &  │        │   (optional)  │
            │  building)   │        │               │
            └───────┬──────┘        └──────┬────────┘
                    │                      │
            ┌───────▼──────────────────────┘
            │
        ┌───▼────────┐
        │   REVIEW   │
        │  (review)  │
        └───┬────────┘
            │
    ┌───────┴───────┐
    │               │
┌──▼──┐        ┌───▼────┐
│RETRY│        │APPROVE │
│     │        │ (done) │
└──┬──┘        └────────┘
   │
┌──▼──────┐
│(failed) │
└─────────┘
```

## Command Reference

### taskq add
Add a new task to the queue.

```bash
taskq add [--id <ID>] [--repo <REPO>] [--base <BRANCH>] [--branch <NAME>] \
  [--worktree-path <PATH>] (--task <DESCRIPTION> | --task-file <PATH>)
```

**Parameters:**
- `--id`: Task identifier (required with `--task`; optional with `--task-file`)
- `--repo`: Repository path or short name (required with `--task`; optional with `--task-file` when frontmatter includes repo)
- `--base`: Base branch to target (default: `main`; or task-file frontmatter when provided)
- `--branch`: Branch override (default: derived `task/<id>`)
- `--worktree-path`: Worktree path override (frontmatter key: `worktree_path`)
- `--task`: Inline task description (mutually exclusive with `--task-file`)
- `--task-file`: Path to task markdown file with YAML frontmatter (mutually exclusive with `--task`)

For `--task-file`, supported frontmatter keys are: `id`, `repo`, `base`, `branch`, `worktree_path`.
If `id` is absent in frontmatter and not passed via CLI, `taskq` derives it from the filename stem.
If defaults are used (for example `id`, `base`, or `branch`), `taskq` keeps the original task file unchanged and only stores resolved values in `queue/tasks.jsonl`.

**Example:**
```bash
taskq add --id T-001 --repo sisifo --task "Implement cleanup feature"
taskq add --task-file queue/tasks/T-002.md
taskq add --task-file task.md --repo sisifo --branch feature/my-branch
```

**Task markdown example (`queue/tasks/example-task.md`):**
```markdown
---
id: T-EXAMPLE
repo: /home/USER/documents/repos/sisifo
base: main
---
Implement a small change with tests.

Acceptance criteria:
- Update the target module.
- Add or update tests.
- Keep changes scoped.
```

---

### taskq status
Display task queue status grouped by status.

```bash
taskq status [--id <ID>] [--json]
```

**Parameters:**
- `--id`: Filter by specific task ID (optional)
- `--json`: Output as JSON format (optional)

**Example:**
```bash
taskq status
taskq status --id T-001
taskq status --json
```

---

### taskq run
Execute tasks from the queue using concurrent workers.

Processes "todo" tasks through planning → building → review stages.
Uses worker pool for parallel execution.

```bash
taskq run [--id <ID>] [--max-parallel <N>] [--poll [SECONDS]] \
  [--cleanup-on-fail] [--dirty-run]
```

**Parameters:**
- `--id`: Run only one specific task ID once (task must be `todo`; no polling)
- `--max-parallel`: Maximum concurrent workers (default: 3)
- `--poll`: Enable polling loop; optional interval seconds (default: 5). If omitted, run is single-pass by default.
- `--cleanup-on-fail`: Remove task container/worktree when a task fails (default: preserve for inspection)
- `--dirty-run`: Reuse an existing worktree and remove stale task containers before starting setup

**Example:**
```bash
taskq run --max-parallel 4
taskq run --max-parallel 2 --poll
taskq run --max-parallel 2 --poll 10
taskq run --id T-001
taskq run --id T-001 --dirty-run
taskq run --id T-001 --cleanup-on-fail
```

**Task Execution Flow:**
1. Claims first "todo" task, transitions to "planning"
2. Reads task file and metadata
3. Creates git worktree and branch
4. Reserves port and launches Docker container
5. Runs `make-plan` command (planning stage)
6. Runs `execute-plan` command (building stage)
7. Transitions to "review" on success, or "failed" on error
8. Error reports written to `queue/errors/`

---

### taskq review
Launch OpenChamber to review a task's execution state.

Attaches to the task's running container via OpenCode endpoint.
Task must be in "review" status with port allocated.

```bash
taskq review --id <ID>
```

**Parameters:**
- `--id`: Task ID to review (required)

**Example:**
```bash
taskq review --id T-001
```

**Prerequisites:**
- Task must be in "review" status
- `openchamber` command must be available in PATH
- Task container must be running with OpenCode server

---

### taskq approve
Approve a task in review.

Transitions task from "review" to "done" status.

```bash
taskq approve --id <ID>
```

**Parameters:**
- `--id`: Task ID to approve (required)

**Example:**
```bash
taskq approve --id T-001
```

---

### taskq cancel
Cancel an active or pending task.

Legal transitions: `todo|review|failed` → `cancelled`

```bash
taskq cancel --id <ID>
```

**Parameters:**
- `--id`: Task ID to cancel (required)

**Example:**
```bash
taskq cancel --id T-001
```

---

### taskq retry
Retry a failed task.

Transitions task from "failed" to "todo".
Clears runtime handles and increments attempt counter.

```bash
taskq retry --id <ID>
```

**Parameters:**
- `--id`: Task ID to retry (required)

**Example:**
```bash
taskq retry --id T-001
```

After retrying, run `taskq run` again to process the task.

---

### taskq remove
Remove a task from the queue.

Only allows removal of tasks not in "planning" or "building" status.

```bash
taskq remove --id <ID>
```

**Parameters:**
- `--id`: Task ID to remove (required)

**Example:**
```bash
taskq remove --id T-001
```

---

### taskq cleanup
Clean up runtime artifacts for completed or cancelled tasks.

Removes Docker containers, worktrees (optionally), and error files.
Clears runtime fields in task records.

```bash
taskq cleanup [--id <ID>] [--done-only] [--cancelled-only] [--keep-worktree]
```

**Parameters:**
- `--id`: Clean specific task ID (optional, default: all done/cancelled)
- `--done-only`: Only clean tasks in "done" status (optional)
- `--cancelled-only`: Only clean tasks in "cancelled" status (optional)
- `--keep-worktree`: Remove containers but preserve worktrees (optional)

**Example:**
```bash
taskq cleanup
taskq cleanup --id T-001
taskq cleanup --done-only
taskq cleanup --keep-worktree
```

---

## Status Transitions

Valid state transitions:

```
todo
  ├→ planning (claimed by worker)
  └→ cancelled (manual cancel)

planning
  ├→ building (execution starting)
  ├→ failed (planning stage error)
  └→ cancelled (manual cancel)

building
  ├→ review (execution complete, awaiting approval)
  └→ failed (building stage error)

review
  ├→ done (approved by operator)
  └→ cancelled (manual cancel)

failed
  ├→ todo (manual retry)
  └→ cancelled (manual cancel)

done
  └─ (terminal state)

cancelled
  └─ (terminal state)
```

---

## Typical Operator Session

### 1. Add Tasks
```bash
taskq add --id T-001 --repo sisifo --task "Add feature X"
taskq add --id T-002 --repo sisifo --task "Fix bug Y"
```

### 2. View Queue
```bash
taskq status
```

### 3. Run Tasks
```bash
taskq run --max-parallel 2
```

Or run continuously:
```bash
taskq run --max-parallel 2 --poll  # Keep polling for new tasks
```

### 4. Review Completed Tasks
```bash
taskq status --json | jq '.[] | select(.status=="review")'
taskq review --id T-001
```

### 5. Approve Tasks
```bash
taskq approve --id T-001
```

### 6. Handle Failures
```bash
taskq status --json | jq '.[] | select(.status=="failed")'
taskq retry --id T-002
taskq run --max-parallel 2
```

### 7. Cleanup Completed Tasks
```bash
taskq cleanup
```

---

## Runtime Artifacts

Each task generates runtime artifacts during execution:

### Worktree
- **Location**: `~/documents/repos/worktrees/<repo>/<task-id>`
- **Created**: During planning stage
- **Contains**: Branch and working directory for task execution
- **Cleanup**: Preserved on failure by default; removed by `taskq run --cleanup-on-fail` or `taskq cleanup` (unless `--keep-worktree`)

### Container
- **Naming**: `task-<task-id>-<created-at-compact>`
- **Created**: During planning stage
- **Purpose**: Isolated execution environment with OpenCode server
- **Port**: Dynamically allocated, stored in task record
- **Cleanup**: Preserved on failure by default; removed by `taskq run --cleanup-on-fail`, `taskq run --dirty-run` (stale pre-clean), and `taskq cleanup`

### Error File
- **Location**: `queue/errors/<task-id>-<timestamp>.md`
- **Created**: When task fails
- **Contains**: Detailed error report with context and suggestions
- **Cleanup**: Removed by `taskq cleanup`

### Task File
- **Location**: `queue/tasks/<task-id>.md`
- **Created**: When task added
- **Format**: YAML frontmatter + markdown body
- **Persistence**: Kept after cleanup (historical record)

---

## Configuration

### Queue Directory
```
queue/
  ├─ tasks.jsonl          # Task records (JSONL)
  ├─ tasks/               # Task markdown files
  │  ├─ <id>.md
  │  └─ example-task.md
  └─ errors/              # Error reports
     └─ <id>-<ts>.md
```

### Worktrees
Default location: `~/documents/repos/worktrees`
- Per-repository structure: `<root>/<repo>/<id>`
- Set per task via `worktree_path` (frontmatter) or `--worktree-path` on `taskq add`

### Container Configuration
- **Image**: `ghcr.io/anomalyco/opencode:latest` (default)
- **Port Allocation**: Automatic (reserved pool)
- **Host**: `127.0.0.1` (local container)

---

## Error Handling

### Task Failures
1. Worker captures error during planning or building
2. Generates detailed error report (saved to `queue/errors/`)
3. Transitions task to "failed" status
4. Preserves worktree/container for inspection by default
5. Operator decides: retry, cancel, or investigate manually

### Resource Cleanup on Failure
- Worker preserves container and worktree by default for inspection
- Use `taskq run --cleanup-on-fail` to restore auto-cleanup behavior
- `taskq run --dirty-run` removes stale task containers before launching a new run
- Cleanup errors don't prevent error reporting
- Operator can later use `taskq cleanup --id <ID>` for manual cleanup

### Port Conflicts
- `taskq run` reserves ports dynamically
- If port allocation fails, task transitions to "failed"
- Error report indicates port issue

---

## Integration Points

### Task Files
- **Location**: `orchestration/task_files.py`
- **Handles**: YAML frontmatter parsing, canonical file creation
- **Required Frontmatter**: `id`, `repo`, `base` (optional)

### Git Runtime
- **Location**: `orchestration/runtime_git.py`
- **Functions**: Worktree creation/removal, branch management

### Docker Runtime
- **Location**: `orchestration/runtime_docker.py`
- **Functions**: Container launch, port allocation, cleanup

### OpenCode Runtime
- **Location**: `orchestration/runtime_opencode.py`
- **Functions**: `make-plan`, `execute-plan` execution

### Review Launcher
- **Location**: `orchestration/runtime_review.py`
- **Functions**: OpenChamber launch for review sessions

---

## Testing

Run unit tests:
```bash
uv run pytest orchestration/tests/test_taskq.py -v
uv run pytest orchestration/tests/test_queue_store.py -v
uv run pytest orchestration/tests/test_worker.py -v
```

Syntax check:
```bash
uv run python -m py_compile orchestration/taskq.py
```

CLI smoke tests:
```bash
uv run taskq --help
uv run taskq status --help
uv run taskq run --help
```

---

## Troubleshooting

### Task stuck in "planning"
- Check worker is running: `taskq run`
- Check Docker: `docker ps | grep task-`
- Check worktree: `ls -la ~/documents/repos/worktrees/`

### Review fails with port error
- Check port is allocated: `taskq status --id <ID> --json | jq '.port'`
- Check container is running: `docker ps | grep task-<ID>`
- Try cleanup and retry

### Worktree removal fails
- Worktree may have uncommitted changes
- `taskq cleanup --keep-worktree` preserves for manual inspection
- Manual removal: `git worktree remove --force ~/documents/repos/worktrees/<repo>/<id>`

### Container cleanup fails
- Container may not exist (already removed)
- Manual cleanup: `docker rm -f task-<ID>`
- `taskq cleanup` is idempotent and safe to re-run

---

## Design Notes

### Atomicity
- Queue store uses file locking (fcntl) for atomic operations
- Status transitions validated at write-time
- `claim_first_todo()` is atomic: reads all, transitions one, writes all

### Concurrency
- Multiple workers can run simultaneously
- Each worker gets unique session ID
- File locking ensures no data corruption
- Thread-safe within single process (RLock)

### Error Recovery
- Failed tasks preserved in "failed" status
- Error reports provide context for manual investigation
- `taskq retry` allows unlimited retries
- `taskq cancel` halts task lifecycle

### Resource Cleanup
- Each task has deterministic worktree path (no collisions)
- Container names include task ID (deterministic cleanup)
- Manual cleanup via `taskq cleanup` is safe (idempotent)
- Error files kept for history (can be archived/deleted manually)
