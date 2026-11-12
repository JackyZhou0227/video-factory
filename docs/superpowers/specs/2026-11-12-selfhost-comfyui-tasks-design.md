# 本地 ComfyUI 任务独立执行

## 意图

RunningHub 的工作流是提交后就结束，取消没有意义。本地 ComfyUI 会在本机等到出图，而且 ComfyUI 自己能按 `prompt_id` 取消。这两条不该再共用「一律不能取消」和「只认视频产物」的路径。

## 目标

- `source=selfhost` 的任务在自己的队列里跑，不占用海报、模板、剪辑那条执行队列。
- 排队中或执行中可以取消。已提交到 ComfyUI 的，调用它的取消接口。
- 完成后的图片在 ComfyUI 页面能预览和下载。
- RunningHub 仍是提交成功即结束，不能取消，页面仍跳到 RunningHub。

## 非目标

- 不新增任务类型。仍是 `comfyui_workflow`，用 `extra_info.source` 区分。
- 不恢复进程重启后还在跑的 ComfyUI 作业。重启时未完成任务继续标为失败。
- 不把上传文件接到 ComfyUI 节点。文生图现在没有文件输入。
- 不下载视频或音频输出。当前只收 `images`。

## 约束

- 取消正在跑的作业用 `POST /api/jobs/{prompt_id}/cancel`。该接口对排队中的作业出队，对正在跑的作业中断；已结束或未知编号返回 200 且 `cancelled` 为 false。
- 旧版 ComfyUI 没有这个路径时，再退回 `POST /interrupt`（正文带 `prompt_id`）和 `POST /queue`（正文 `{"delete": ["<prompt_id>"]}`）。
- 本机默认同时只等 1 条本地 ComfyUI 任务，和单卡排队一致。配置项 `tasks.comfyui_selfhost_limit`，默认 `1`。

## 方案

1. 新任务类型 `comfyui_selfhost`。取消规则干净，但任务中心、统计和已有记录都要分叉。
2. 仍用 `comfyui_workflow`，按 `extra_info.source` 分叉。任务列表不用改类型，RunningHub 和本地图在同一栏。采用这个。
3. 照 Qwen 再开一组线程池。Qwen 的线程池是为了挡住 CPU/GPU 推理，不占视频合成线程。本地 ComfyUI 的重活在另一个进程，本进程只发 HTTP，线程池帮不上。

## 行为

- 提交后把 ComfyUI 返回的 `prompt_id` 写入 `extra_info.comfyui_prompt_id`。
- 还没提交到 ComfyUI 就取消：不再 `POST /prompt`，任务改为 `cancelled`。
- 已经拿到 `prompt_id` 再取消：先调取消接口，轮询停止，任务改为 `cancelled`。若这时历史里已经是完成，则按成功收图，不改成取消。
- 页面轮询在 `source=selfhost` 且完成后返回图片产物地址，不再只找视频。
- 任务中心只给 `source=selfhost` 且状态为 `pending` 或 `running` 的任务显示取消。RunningHub 仍返回 409。
