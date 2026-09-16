import assert from "node:assert/strict";
import test from "node:test";
import { shouldRestoreTask } from "./taskRecovery.js";

test("only active generation tasks are restored after a refresh", () => {
  for (const status of ["pending", "running"]) {
    assert.equal(shouldRestoreTask({ status }), true, status);
  }
  for (const status of ["completed", "partial_failed", "failed"]) {
    assert.equal(shouldRestoreTask({ status }), false, status);
  }
  assert.equal(shouldRestoreTask(null), false);
});
