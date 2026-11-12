# 本地 ComfyUI 独立任务 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `source=selfhost` 的 ComfyUI 任务走单独队列，能调用 ComfyUI 原生取消，并在页面上预览图片产物。

**Architecture:** 任务类型仍是 `comfyui_workflow`。`TaskExecutionManager` 增加一条只给本地 ComfyUI 用的 asyncio 队列，默认 1 个工人。执行器保存 `prompt_id`，取消时优先 `POST /api/jobs/{id}/cancel`，404 再退回 `/interrupt` 加 `/queue` 删除。RunningHub 的提交和「不能取消」保持不变。

**Tech Stack:** FastAPI、httpx、现有 `task_store` / `task_runtime`、React 任务中心与 `ComfyUI.jsx`。

**Spec:** `docs/superpowers/specs/2026-11-12-selfhost-comfyui-tasks-design.md`

## Global Constraints

- 取消正在跑或排队中的 ComfyUI 作业：`POST /api/jobs/{prompt_id}/cancel`。
- 该路径 404 时：`POST /interrupt`，JSON `{"prompt_id": "<id>"}`；再 `POST /queue`，JSON `{"delete": ["<id>"]}`。
- `tasks.comfyui_selfhost_limit` 默认 `1`。
- 任务类型保持 `comfyui_workflow`。`extra_info.source` 为 `selfhost` 或 `runninghub`。`prompt_id` 存在 `extra_info.comfyui_prompt_id`。
- RunningHub 取消仍是 409，文案保持「ComfyUI 工作流任务暂不支持取消」不适用本地任务；本地允许取消，RunningHub 的 409 文案改为「RunningHub 工作流任务暂不支持取消」。
- 重启时未完成任务仍由 `mark_incomplete_tasks_failed` 标失败，不恢复轮询。

## Review Focus

- 取消发生在 `POST /prompt` 返回之前：不得再把工作流提交出去。
- 取消和完成撞在一起：历史已是 `completed` 时收图并标完成，不标取消。
- 新版取消接口 404：退回 `/interrupt` 与 `/queue`，两条都发出。
- RunningHub 任务调用取消：仍是 409，状态不变。
- 本地队列已满：新任务不进 RunningHub 那条队列，返回 429。

---

### Task 1: 按来源决定能不能取消

**Files:**
- Modify: `web-app/app/services/task_store.py` (`request_task_cancellation`)
- Modify: `web-app/app/api/tasks.py` (`cancel_task`)
- Test: `web-app/tests/stores/test_task_store.py`
- Test: `web-app/tests/api/test_tasks.py`

**Interfaces:**
- Consumes: `task["extra_info"]["source"]`
- Produces: `request_task_cancellation` 对 `source=selfhost` 且 `pending` 直接改为 `cancelled`；`running` 改为 `cancelling`。`source` 不是 `selfhost` 的 `comfyui_workflow` 抛 `TaskCancellationConflictError`，文案「RunningHub 工作流任务暂不支持取消」。

- [ ] **Step 1: 改失败测试**

把 `test_comfyui_workflow_task_cannot_be_cancelled` 拆成两条：无 `source` 或 `source=runninghub` 的 running 任务仍抛 `TaskCancellationConflictError`；`extra_info={"source": "selfhost"}` 的 running 任务变为 `cancelling`，pending 任务变为 `cancelled`。

API 测试：`POST /api/tasks/{id}/cancel` 对 runninghub 返回 409；对 selfhost 的 pending 返回 200 且 `status=cancelled`。

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m pytest web-app/tests/stores/test_task_store.py::TaskStoreTests::test_runninghub_comfyui_workflow_cannot_be_cancelled web-app/tests/stores/test_task_store.py::TaskStoreTests::test_selfhost_comfyui_workflow_can_be_cancelled -q`

Expected: FAIL

- [ ] **Step 3: 实现来源判断**

`request_task_cancellation` 和 `tasks.cancel_task` 只拒绝 `task_type == comfyui_workflow` 且 `extra_info.source != "selfhost"` 的任务。selfhost 走现有的 pending→cancelled、running→cancelling。

- [ ] **Step 4: 跑测试，确认通过**

Run: `python -m pytest web-app/tests/stores/test_task_store.py web-app/tests/api/test_tasks.py -q`

Expected: PASS

### Task 2: 本地 ComfyUI 单独队列

**Files:**
- Modify: `web-app/app/services/task_runtime.py`
- Modify: `web-app/app/main.py`（构造 `TaskExecutionManager`）
- Modify: `web-app/config.example.yaml`
- Test: `web-app/tests/services/test_task_runtime.py`

**Interfaces:**
- Consumes: `tasks.comfyui_selfhost_limit`，缺省 `1`
- Produces: `TaskExecutionManager.submit(task_id, runner, *, lane="default")`。`lane="comfyui"` 进入独立队列，工人数等于 `comfyui_selfhost_limit`。`cancel` / `can_cancel` 两条队列都能找到该任务。`snapshot()` 增加 `"comfyui": {"active", "queued", "limit"}`。

- [ ] **Step 1: 写失败测试**

`comfyui_selfhost_limit=1` 时，第二条 `lane="comfyui"` 的任务在第一条完成前不会开始。`lane="default"` 的任务不受这条限制。两条都超过各自容量时 `submit` 抛 `TaskRuntimeCapacityError`。

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m pytest web-app/tests/services/test_task_runtime.py -q`

Expected: FAIL，`submit` 不接受 `lane`

- [ ] **Step 3: 加独立队列**

`main.py` 读取 `tasks.comfyui_selfhost_limit`，默认 1。`config.example.yaml` 加上该键和一句注释：本地 ComfyUI 同时等待的任务数。不要把本地任务放进 Qwen 线程池。

- [ ] **Step 4: 跑测试，确认通过**

Run: `python -m pytest web-app/tests/services/test_task_runtime.py -q`

Expected: PASS

### Task 3: 执行器保存 prompt_id 并响应取消

**Files:**
- Modify: `web-app/app/api/comfyui.py`（`_create_selfhost_task`、`_run_selfhost_workflow`）
- Modify: `web-app/app/api/common.py` 只在调用处传入 lane，不改公共签名以外的行为
- Test: `web-app/tests/api/test_comfyui.py`

**Interfaces:**
- Consumes: `lane="comfyui"`，`cancel_event: asyncio.Event`，`common.finalize_cancellation`
- Produces: `cancel_selfhost_prompt(base_url: str, prompt_id: str) -> None`。先 `POST {base_url}/api/jobs/{prompt_id}/cancel`。404 时再 `POST {base_url}/interrupt` 与 `POST {base_url}/queue`。其它 HTTP 错误抛给上层，任务记 `failed`。

- [ ] **Step 1: 写失败测试**

用 `httpx.MockTransport` 或现有 mock 方式覆盖四条：

- 提交成功后 `extra_info.comfyui_prompt_id` 等于 `/prompt` 响应里的 `prompt_id`。
- `cancel_event` 在 `/prompt` 之前置位：没有 `/prompt` 请求，任务 `cancelled`。
- `/prompt` 之后、历史完成之前置位：发出 `/api/jobs/{id}/cancel`，任务 `cancelled`，不登记产物。
- `/api/jobs/{id}/cancel` 返回 404：接着请求 `/interrupt` 且正文 `prompt_id` 正确，以及 `/queue` 且 `delete` 含该 id。
- 取消请求发出时 `/history` 已是 `completed` 且带一张图：任务 `completed`，产物 `kind=image`。

`_create_selfhost_task` 里 `schedule_task` 改走 `lane="comfyui"`。执行器签名接受 `cancel_event`。

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m pytest web-app/tests/api/test_comfyui.py -q -k selfhost`

Expected: FAIL

- [ ] **Step 3: 实现取消与收图**

轮询循环每次醒来先看 `cancel_event`。拿到 `prompt_id` 后立刻写入 `extra_info`。完成路径保持只下载 `outputs.*.images`。取消且未完成时调用 `finalize_cancellation`，不留下半张已登记产物。

- [ ] **Step 4: 跑测试，确认通过**

Run: `python -m pytest web-app/tests/api/test_comfyui.py web-app/tests/services/test_task_runtime.py -q`

Expected: PASS

### Task 4: 页面只给本地任务取消，并显示图片

**Files:**
- Modify: `web-app/app/api/comfyui.py`（`_task_payload`）
- Modify: `web-app/frontend/src/components/ComfyUI.jsx`
- Modify: `web-app/frontend/src/components/TaskCenter.jsx`（`canCancelTask`）
- Test: `web-app/tests/api/test_comfyui.py`

**Interfaces:**
- Consumes: 任务 `extra_info.source`、`artifacts`
- Produces: `GET /api/task/{id}` 增加 `image_urls: string[]`，来自 `kind=image` 且 `status=completed` 的产物，顺序与产物列表一致。`video_url` 行为不变。

- [ ] **Step 1: 写失败测试**

已完成且有一张 image 产物的 selfhost 任务，`GET /api/task/{id}` 的 `image_urls` 长度为 1，且是该产物的预览地址。只有视频产物时 `image_urls` 为空。

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m pytest web-app/tests/api/test_comfyui.py -q -k image_urls`

Expected: FAIL

- [ ] **Step 3: 接上页面**

`_task_payload` 填 `image_urls`。`ComfyUI.jsx` 在 `source=selfhost` 且完成后用 `ProtectedMedia kind="image"` 显示第一张，并提供下载。RunningHub 的「已提交 / 去 RunningHub 查看」不改。

selfhost 处于 `pending` 或 `running` 时，页面和任务中心都显示取消，调用现有 `POST /api/tasks/{id}/cancel`。RunningHub 任务中心不显示取消。

- [ ] **Step 4: 跑测试并构建前端**

Run: `python -m pytest web-app/tests/api/test_comfyui.py web-app/tests/api/test_tasks.py -q`

Run: `npm run build`（工作目录 `web-app/frontend`）

Expected: 测试 PASS，构建成功

### Task 5: 文档

**Files:**
- Modify: `docs/modules/comfyui.md`
- Modify: `web-app/config.example.yaml`（若 Task 2 已写注释，这里只核对）

- [ ] **Step 1: 改模块说明**

写明本地任务单独队列、默认同等 1 条、取消会调用 ComfyUI 的 `/api/jobs/{id}/cancel`，RunningHub 不能取消。图片产物在本页预览，也出现在任务中心。

- [ ] **Step 2: 不提交**

计划评审通过之前不提交。评审通过后的提交粒度按任务拆开。
