# User Task Cancellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users cancel their own TTS preview tasks from the task center while preserving task history and preventing stuck `running` records.

**Architecture:** Extend the persisted task state machine with a cooperative `cancelling` state, add an ownership-checked cancel command restricted to `voice_generation`, and make `TaskExecutionManager` own cancellation signals for TTS preview tasks. Move TTS preview generation into that runtime and atomically publish its artifact with completion. Leave other producers unchanged until they can guarantee cancellation before artifact publication. Successful RunningHub submission remains local completion and is not cancellable.

**Tech Stack:** FastAPI, SQLAlchemy/PostgreSQL, asyncio, `ThreadPoolExecutor`, React/Vite, MUI, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-15-task-cancellation-design.md`

## Global Constraints

- Cancellation is a command on a supported TTS task, not deletion of the task record.
- `pending` cancellation is immediate; `running` cancellation is cooperative.
- `cancelling` counts toward quotas until a terminal state is persisted.
- Terminal state races must be resolved by an atomic database transition.
- Never terminate the whole Python process to cancel one task.
- Only runtime-managed `voice_generation` tasks are cancellable in this change.
- Other task types remain unchanged and do not show cancellation controls.
- Digital-human tasks remain unchanged; successful RunningHub submission is
  `completed` and is not cancellable.
- Do not commit `web-app/config.yaml`, generated frontend archives, secrets, or runtime output.
- Preserve existing task ownership checks and protected artifact access rules.

---

### Task 1: Establish the cancellation state contract

**Files:**
- Modify: `web-app/app/services/task_store.py`
- Modify: `web-app/app/db/models.py` only if a database constraint is added
- Modify: `web-app/tests/stores/test_task_store.py`
- Modify: `web-app/tests/api/test_tasks.py`

**Interfaces:**
- Produce `TASK_STATUSES` containing `cancelling`.
- Produce `ACTIVE_STATUSES = ("pending", "running", "cancelling")` for quota and summary logic.
- Restrict cancellation requests to `TASK_TYPE_VOICE`; other task types remain unchanged.
- Publish the TTS artifact and `completed` status through one conditional database transition.
- Produce an atomic helper with the shape:

```python
def request_task_cancellation(
    task_id: str,
    user_id: str,
) -> dict[str, Any]:
    ...
```

It returns the latest task record, changes `pending` directly to `cancelled`,
changes `running` to `cancelling`, returns an already `cancelled` task
unchanged, and rejects other terminal states with a dedicated conflict error.

- [ ] **Step 1: Write failing store tests**

Add tests covering:

```python
def test_pending_task_cancellation_is_immediate_and_finished():
    ...

def test_running_task_cancellation_enters_cancelling_without_finished_at():
    ...

def test_cancel_is_idempotent_for_cancelled_task():
    ...

def test_cancel_rejects_completed_task():
    ...

def test_cancelling_tasks_count_toward_quota_and_summary():
    ...

def test_cancel_and_complete_use_one_terminal_winner():
    ...
```

The race test should use the database update predicate
`WHERE id = :id AND status IN (...)` and assert that only one transition can
win.

- [ ] **Step 2: Run the focused tests and verify failure**

Run from `web-app/`:

```powershell
python -m pytest tests/stores/test_task_store.py tests/api/test_tasks.py -q
```

Expected: failures because `cancelling` and `request_task_cancellation` do not
exist.

- [ ] **Step 3: Implement the state and atomic transition**

Use a conditional SQLAlchemy `update()` keyed by task ID and owner:

```python
update(GenerationTask)
.where(GenerationTask.id == task_id)
.where(GenerationTask.user_id == user_id)
.where(GenerationTask.status == "pending")
.values(status="cancelled", message="任务已取消", error="用户主动取消任务", ...)
```

Use a second conditional update for `running -> cancelling`. Verify the task
type is TTS before changing state. Re-read the task after the update and map
the resulting state to idempotent success or conflict.
Include `cancelling` in quota queries and `get_task_summary()`. Keep
`mark_incomplete_tasks_failed()` treating `pending`, `running`, and
`cancelling` as unfinished on restart.

- [ ] **Step 4: Run the focused tests**

```powershell
python -m pytest tests/stores/test_task_store.py tests/api/test_tasks.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add web-app/app/services/task_store.py web-app/app/db/models.py web-app/tests/stores/test_task_store.py web-app/tests/api/test_tasks.py
git commit -m "feat: add persisted task cancellation states"
```

### Task 2: Add the authenticated cancel endpoint

**Files:**
- Modify: `web-app/app/api/tasks.py`
- Modify: `web-app/tests/api/test_tasks.py`

**Interfaces:**
- Add `POST /api/tasks/{task_id}/cancel`.
- Consume `task_store.request_task_cancellation(task_id, user["id"])`.
- Produce the same `task_payload()` shape as `GET /api/tasks/{task_id}`.

- [ ] **Step 1: Write failing API tests**

Cover:

```python
def test_user_can_cancel_owned_pending_task():
    ...

def test_user_can_request_cancellation_for_owned_running_task():
    ...

def test_foreign_task_returns_404():
    ...

def test_completed_task_returns_409():
    ...

def test_repeating_cancel_is_idempotent():
    ...
```

Assert that the response includes the current status, message, `finished_at`,
and unchanged artifacts.

- [ ] **Step 2: Run tests and verify failure**

```powershell
python -m pytest tests/api/test_tasks.py -q
```

- [ ] **Step 3: Implement the endpoint and error mapping**

Map `TaskNotFoundError` to `404`, the terminal conflict exception to `409`,
and return `task_payload(updated_task)` on `200`.

- [ ] **Step 4: Run tests**

```powershell
python -m pytest tests/api/test_tasks.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add web-app/app/api/tasks.py web-app/tests/api/test_tasks.py
git commit -m "feat: expose task cancellation endpoint"
```

### Task 3: Add cooperative cancellation to the task runtime

**Files:**
- Modify: `web-app/app/services/task_runtime.py`
- Modify: `web-app/tests/services/test_task_runtime.py`

**Interfaces:**
- Extend the queued entry to carry a cancellation event/context.
- Produce:

```python
def cancel(self, task_id: str) -> bool:
    ...

def is_cancel_requested(self, task_id: str) -> bool:
    ...
```

- The runner signature may become:

```python
TaskRunner = Callable[[asyncio.Event], Awaitable[None]]
```

Keep existing zero-argument task runners compatible. Only the TTS preview
runner is cancellation-aware and eligible for cancellation.

- [ ] **Step 1: Write failing runtime tests**

Cover:

```python
async def test_cancelled_queued_task_never_starts():
    ...

async def test_running_task_receives_cancel_event():
    ...

async def test_runtime_marks_cancelled_task_terminal_after_runner_returns():
    ...

async def test_runtime_cleanup_releases_reserved_capacity():
    ...
```

Use `asyncio.Event` gates so the tests do not depend on sleeps.

- [ ] **Step 2: Run tests and verify failure**

```powershell
python -m pytest tests/services/test_task_runtime.py -q
```

- [ ] **Step 3: Implement cancellation bookkeeping**

Maintain a task-ID map of cancellation events. When `cancel(task_id)` is
called, set the event and let the worker decide whether a queued task can be
marked `cancelled` immediately or a running task must remain `cancelling`.
Always remove the event in `finally`, decrement `_reserved`, and call
`queue.task_done()`.

The worker must handle `asyncio.CancelledError` separately from user-requested
cancellation: service shutdown should produce the existing
`服务停止时任务已取消` message, while a user request should produce
`任务已取消`.

- [ ] **Step 4: Run tests**

```powershell
python -m pytest tests/services/test_task_runtime.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add web-app/app/services/task_runtime.py web-app/tests/services/test_task_runtime.py
git commit -m "feat: add cooperative task runtime cancellation"
```

### Task 4: Connect the cancel endpoint to the runtime

**Files:**
- Modify: `web-app/app/api/tasks.py`
- Modify: `web-app/app/services/task_runtime.py`
- Modify: `web-app/tests/api/test_tasks.py`

**Interfaces:**
- The endpoint must call the runtime cancellation hook after the persisted
  transition:

```python
runtime = get_task_runtime()
runtime.cancel(task_id)
```

- If the task transitions `pending -> cancelled`, the runtime hook is a
  no-op or removes a queued entry.
- If it transitions `running -> cancelling`, the runtime event is set.
- If the runtime is unavailable during a lightweight router test, the
  persisted transition still succeeds and the endpoint must not crash.

- [ ] **Step 1: Add integration tests**

Test a queued task, a running task, and a runtime-unavailable request. Assert
that persisted state and in-memory cancellation signal agree.

- [ ] **Step 2: Implement the integration**

Keep the database transition authoritative. Do not let a missing runtime
reverse a successful persisted cancellation.

- [ ] **Step 3: Run tests**

```powershell
python -m pytest tests/api/test_tasks.py tests/services/test_task_runtime.py -q
```

- [ ] **Step 4: Commit**

```powershell
git add web-app/app/api/tasks.py web-app/app/services/task_runtime.py web-app/tests/api/test_tasks.py
git commit -m "feat: connect persisted cancellation to runtime"
```

### Task 5: Move TTS preview generation into the managed runtime

**Files:**
- Modify: `web-app/app/api/tts_studio.py`
- Modify: `web-app/app/services/tts_qwen.py`
- Modify: `web-app/app/services/tts/providers/qwen3_tts.py` only if provider-level cancellation checks are needed
- Modify: `web-app/frontend/src/components/TTSStudio.jsx`
- Modify: `web-app/tests/api/test_tts_studio.py`
- Modify: `web-app/tests/services/tts/test_tts_service.py`

**Interfaces:**
- `POST /api/tts-studio/edge-tts/preview` and
  `POST /api/tts-studio/voice-clone/preview` return `{ "task_id": ... }`
  immediately after creating and scheduling a task.
- Add a shared async task runner that owns upload persistence, TTS synthesis,
  artifact publication, and terminal status updates.
- The runner receives `cancel_event` and checks it:
  1. before provider invocation;
  2. after provider invocation;
  3. before adding the artifact;
  4. before marking `completed`.

- [ ] **Step 1: Add failing API tests for asynchronous TTS**

Update tests to assert that the POST returns without waiting for synthesis,
the task starts as `pending` or `running`, and a mocked runner eventually
produces the same audio artifact and response metadata currently returned by
the synchronous endpoint.

Add a test where cancellation arrives after mocked synthesis returns but before
artifact publication; assert no completed artifact is exposed and final status
is `cancelled`.

- [ ] **Step 2: Run focused tests and verify failure**

```powershell
python -m pytest tests/api/test_tts_studio.py tests/services/tts/test_tts_service.py -q
```

- [ ] **Step 3: Implement the background TTS runner**

Create the task and save any uploaded reference audio before scheduling. Move
the existing synthesis and `_complete_voice_task` / `_fail_voice_task` logic
into a runner submitted through `common.schedule_task`. Return only the task
ID from the POST. Preserve the existing task artifact URL contract; the
frontend obtains the artifact URL from task polling.

Do not call `task_store.update_task(status="running")` from the request handler
after scheduling; the runtime owns that transition.

- [ ] **Step 4: Add cancellation checkpoints**

Use a helper that raises an internal cancellation exception when the event is
set. Catch it separately and persist `cancelled`, not `failed`. Ensure partial
files are removed or recorded as non-result artifacts and never published as a
completed primary artifact.

- [ ] **Step 5: Update the TTS frontend flow**

Store the returned `task_id`, poll `GET /api/tasks/{task_id}`, show
`pending`, `running`, `cancelling`, `completed`, `failed`, and `cancelled`,
and derive the audio preview URL from the completed primary artifact. Add a
cancel action while the task is active.

- [ ] **Step 6: Run backend and frontend checks**

```powershell
python -m pytest tests/api/test_tts_studio.py tests/services/tts/test_tts_service.py -q
cd frontend
npm run build
```

- [ ] **Step 7: Commit**

```powershell
git add web-app/app/api/tts_studio.py web-app/app/services/tts_qwen.py web-app/app/services/tts/providers/qwen3_tts.py web-app/frontend/src/components/TTSStudio.jsx web-app/tests/api/test_tts_studio.py web-app/tests/services/tts/test_tts_service.py
git commit -m "feat: run TTS previews as cancellable tasks"
```

### Task 6: Add cancellation controls to the task center

**Files:**
- Modify: `web-app/frontend/src/components/TaskCenter.jsx`
- Modify: `web-app/frontend/src/theme.js` if a `cancelling` color is not already defined
- Add or modify: `web-app/frontend/src/lib/taskCancellation.js` if a small API helper is useful
- Add or modify: `web-app/frontend/src/lib/taskCancellation.test.js`

**Interfaces:**
- Active TTS task rows show a cancel icon button with a tooltip. Other task
  types do not show cancellation controls.
- Clicking it opens a confirmation dialog for `running` tasks and immediately
  cancels `pending` tasks after the same command path.
- The button is disabled during the request and while status is `cancelling`.
- Polling continues after a `202`/`cancelling` response and stops only on a
  terminal state.

- [ ] **Step 1: Write frontend tests**

Cover:

```javascript
test("cancel action posts to the task endpoint and refreshes the row", ...);
test("terminal tasks do not render a cancel action", ...);
test("cancelling tasks keep polling and disable the action", ...);
test("cancel errors leave the task row active and show the error", ...);
```

- [ ] **Step 2: Run frontend tests and verify failure**

Run the repository's configured frontend test command if available; otherwise
run the targeted Vitest command used by the existing frontend test setup.

- [ ] **Step 3: Implement the task-center control**

Use the existing MUI button/icon patterns. Keep text concise:
`取消任务`, `正在取消`, `任务已取消`. Do not expose a force-kill action.
Use the existing `apiJson` and task polling conventions.

- [ ] **Step 4: Run frontend verification**

```powershell
cd web-app/frontend
npm run build
```

- [ ] **Step 5: Commit**

```powershell
git add web-app/frontend/src/components/TaskCenter.jsx web-app/frontend/src/theme.js web-app/frontend/src/lib/taskCancellation.js web-app/frontend/src/lib/taskCancellation.test.js
git commit -m "feat: add task center cancellation control"
```

### Task 7: Verify restart recovery without changing digital-human semantics

**Files:**
- Modify: `web-app/app/services/task_store.py` only if restart recovery needs
  the active-state constant from Task 1
- Modify: `web-app/tests/stores/test_task_store.py`

**Interfaces:**
- Restart recovery marks `pending`, `running`, and `cancelling` local tasks
  failed with an explicit restart message, unless a future durable executor
  provides resumability.
- Digital-human tasks submitted successfully to RunningHub remain `completed`
  and are not included in cancellation changes.

- [ ] **Step 1: Add tests**

Assert that all active local states are recovered on restart and that an
already-completed digital-human task remains completed and has no cancellation
path.

- [ ] **Step 2: Confirm unchanged digital-human behavior**

Do not add a new digital-human cancellation field or alter the existing
RunningHub submission payload. The task center hides the cancel action for its
`completed` state; add only a regression assertion if the current tests do not
already cover that behavior.

- [ ] **Step 3: Run tests**

```powershell
python -m pytest tests/api/test_tasks.py tests/api/test_digital_human.py tests/stores/test_task_store.py -q
```

- [ ] **Step 4: Commit**

```powershell
git add web-app/app/services/task_store.py web-app/tests/stores/test_task_store.py web-app/tests/api/test_tasks.py web-app/tests/api/test_digital_human.py
git commit -m "test: preserve completed digital human task semantics"
```

### Task 8: Full verification and operational rollout

**Files:**
- Modify: `web-app/config.example.yaml` only if a cancellation timeout or
  polling setting is introduced.
- Modify: `docs/operations/` with operator notes if deployment behavior changes.

**Interfaces:**
- No new secret or production-only setting is required for the first version.
- Existing failed-task cleanup retains cancelled task directories according to
  the documented retention policy.

- [ ] **Step 1: Run the full backend suite**

```powershell
cd web-app
python -m pytest -q
```

- [ ] **Step 2: Build the frontend**

```powershell
cd web-app/frontend
npm run build
```

- [ ] **Step 3: Perform a manual smoke test**

1. Create a TTS task with a long input.
2. Cancel it while pending and verify it becomes `cancelled`.
3. Start another TTS task, cancel during inference, and verify it becomes
   `cancelling` before converging to `cancelled`.
4. Refresh the task center and verify task history remains visible.
5. Verify active non-TTS tasks show no cancellation action.
6. Submit a RunningHub digital-human task and verify successful submission
   remains `completed` with no cancel action.

- [ ] **Step 4: Inspect the diff and runtime output**

```powershell
git diff --check
git status --short
```

Confirm no secrets, generated archives, local output, or `config.yaml` are
included.

- [ ] **Step 5: Commit documentation and final verification**

```powershell
git add docs/superpowers/specs/2026-10-15-task-cancellation-design.md docs/superpowers/plans/2026-10-15-task-cancellation.md docs/operations
git commit -m "docs: add task cancellation rollout plan"
```
