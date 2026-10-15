# Task Cancellation Design

**Date:** 2026-10-15

## Goal

Allow an authenticated user to cancel their own locally generated TTS preview
tasks from the task center, with explicit state transitions and without
terminating the whole application process.

## Product Semantics

- Cancellation is a user command, not deletion of the task record.
- A pending task is cancelled immediately and releases admission capacity.
- A running TTS preview enters `cancelling` while its provider call completes
  or reaches a safe checkpoint; its result is discarded if cancellation wins.
- A task that has already reached a terminal state cannot be cancelled.
- Cancellation is idempotent: repeating the command for an already cancelled
  task returns the current task state.
- Completion and cancellation race through an atomic database transition. The
  first terminal transition wins.
- The UI must distinguish "cancellation requested" from "cancelled".
- Cancellation is available only for `voice_generation` tasks created by the
  TTS preview endpoints. Other task types are not exposed as cancellable until
  their producers can guarantee that they stop before publishing more results.
- Digital-human tasks keep their current execution semantics. Successful
  submission to RunningHub is local task completion, so a submitted
  digital-human task is `completed` and cannot be cancelled.

## State Model

Existing terminal states remain unchanged:

```text
pending -> cancelled
pending -> running -> completed
                  -> failed
                  -> cancelling -> cancelled
                                  -> completed
```

`cancelling` is an active state and counts toward task quotas until a TTS task
reaches a terminal state. It is only valid for runtime-managed TTS preview
work.

## API Contract

Add:

```http
POST /api/tasks/{task_id}/cancel
```

The endpoint authenticates ownership, verifies that the task is a runtime-
managed TTS preview, atomically records the cancellation request, signals its
runtime entry, and returns the latest public task payload. It returns `404`
for a missing or foreign task, `409` for unsupported or already-terminal
tasks other than idempotent `cancelled`, and `200` for an already cancelled
TTS task.

## Execution Boundary

TTS preview generation must be submitted through the application-owned task
runtime. The runtime owns its cancellation signal. It must not kill the
Python process or terminate an unrelated user's work. Poster-video,
template-production, smart-editing, and digital-human task cancellation are
out of scope for this implementation because their producers do not yet
provide the same cancellation and artifact-publication guarantees.

Qwen GPU inference is not guaranteed to stop mid-call. The implementation must
check cancellation before queue admission, before inference, after inference,
and atomically while publishing the artifact and transitioning to
`completed`. If cancellation wins during an uncancellable inference call, the
result must not be published as a completed user artifact; the task should
converge to `cancelled` after the call returns.

## Scope Exclusions

- No force-kill endpoint.
- No cancellation controls for non-TTS task types in this implementation.
- No changes to digital-human submission or RunningHub task semantics.
- No deletion of task history when a task is cancelled.
