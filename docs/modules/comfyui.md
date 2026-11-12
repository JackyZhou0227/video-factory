# ComfyUI 模块

## 作用

按工作流目录提交 ComfyUI 任务。每个工作流声明自己的输入，并可以走 RunningHub 或自定义 ComfyUI。当前有两个工作流：数字人对口型、文生图。

## 工作流

| key | 名称 | 执行环境 | 输入 |
|---|---|---|---|
| `digital-human-lipsync` | 数字人对口型 | RunningHub | 人物形象图片、对口型音频 |
| `text-to-image` | 文生图 | 自定义 ComfyUI | 提示词、清晰度、比例 |

数字人对口型的音频在 [TTS Studio](tts-studio.md) 生成后回到本模块上传。文生图的清晰度和比例是预设，对应像素由 ComfyUI 的 ResolutionSelector 按 16 的倍数算出。

## 处理流程

1. 前端读取 `GET /api/workflows`，按工作流渲染输入。
2. 提交时带上 `source`：`runninghub` 或 `selfhost`。
3. 后端保存输入并创建 `comfyui_workflow` 任务。
4. RunningHub 提交成功后任务标记为完成，产物到 RunningHub 查看，这条不能取消。自定义 ComfyUI 进入单独队列，默认同时只等 1 条（`tasks.comfyui_selfhost_limit`）。它把工作流 POST 到配置的 `/prompt`，保存返回的 `prompt_id`，完成后把图片登记为任务产物，ComfyUI 页面可以直接预览。
5. 取消本地任务时调用 ComfyUI 的 `POST /api/jobs/{prompt_id}/cancel`。旧版本没有这个接口时，改为 `POST /interrupt` 并从队列删除该编号。还没提交就取消的，不再发给 ComfyUI。

工作流定义在 `web-app/app/services/workflow_catalog.py`。RunningHub 只用 `web-app/workflows/runninghub/<key>.json` 里的 `workflow_id`。自定义 ComfyUI 使用 `web-app/workflows/selfhost/` 里的 API 格式 JSON。原稿在 [ComfyUI 工作流原稿](../comfyui-workflow/README.md)。

## 接口入口

后端路由位于 `web-app/app/api/comfyui.py`，前端组件位于 `web-app/frontend/src/components/ComfyUI.jsx`。任务状态和产物安全规则见[任务中心模块](task-center.md)。

- `GET /api/workflows`
- `POST /api/workflows/{workflow_key}/generate`
- `GET /api/task/{task_id}`

自定义 ComfyUI 的地址在 `config.yaml` 的 `comfyui.url`，默认 `http://localhost:8188`。

## 约束

- 工作流 key `digital-human-lipsync` 保持不变，已有任务和接口继续用它。
- RunningHub 工作流 ID 放在工作流 JSON 里，不由页面填写。
- 页面不负责生成音频，数字人对口型只消费 TTS Studio 导出的音频文件。
- 外部任务 ID 和链接仅保存在任务扩展信息中，不暴露服务端文件路径。
