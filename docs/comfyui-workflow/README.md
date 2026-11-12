# ComfyUI 工作流原稿

每个工作流一个目录，放两种格式：

| 文件 | 格式 | 用途 |
|---|---|---|
| `ui.json` | ComfyUI 编辑器的 UI 格式（`nodes` / `links` / `subgraphs`） | 在 ComfyUI 里打开、继续编辑的原稿 |
| `api.json` | API 格式（节点 ID → `{class_type, inputs}`） | 提交给 `/prompt` 的格式，也是 `web-app/workflows/selfhost/` 里的实际运行文件 |

```
image_flux3_klein_t2i/   文生图（自定义 ComfyUI）
digital-human-lipsync/   数字人口播（RunningHub，仅供参考其输入参数命名）
```

## 和运行时代码的关系

- **自定义 ComfyUI** 的工作流：`api.json` 会被复制到 `web-app/workflows/selfhost/<name>.json`，
  在 `web-app/app/services/workflow_catalog.py` 的 `SELFHOST_WORKFLOW_MAPPING` 里登记，
  并在工作流定义里给每个表单字段补 `selfhost_node_id` / `selfhost_input_key`。
- **RunningHub** 的工作流：运行时只用 `workflow_id`（存在 `web-app/workflows/runninghub/`），
  `api.json` 仅用于查证参数名（如 `$videoimage.image`、`$audio.audio`）。

## 导出方式

ComfyUI 里 `Workflow → Export (API)` 得到 `api.json`，`Workflow → Save` 得到 `ui.json`。
本目录的 `api.json` 保持导出原样，不在文件里改节点——参数替换由运行时代码完成。
