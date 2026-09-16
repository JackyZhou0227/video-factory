export const FINAL_TASK_STATUSES = new Set(["completed", "partial_failed", "failed"]);

export function shouldRestoreTask(task) {
  return Boolean(task && !FINAL_TASK_STATUSES.has(task.status));
}
