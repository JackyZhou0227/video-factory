# ComfyUI 工作流原稿

每个功能一个中文目录。目录名是产品里的工作流，不跟某一版模型或图绑在一起。换一套效果更好的图时，替换该目录 `json/` 里的文件，目录名保持不变。

```
文生图/
  README.md    功能介绍，以及当前用的是哪套图
  json/        ui.json、api.json
数字人对口型/
  README.md
  json/
```

| 文件 | 格式 | 用途 |
|---|---|---|
| `json/ui.json` | ComfyUI 编辑器的 UI 格式（`nodes` / `links` / `subgraphs`） | 在 ComfyUI 里打开、继续编辑的原稿 |
| `json/api.json` | API 格式（节点 ID → `{class_type, inputs}`） | 提交给 `/prompt` 的格式 |

## 和运行时代码的关系

- **自定义 ComfyUI**：把 `json/api.json` 复制到 `web-app/workflows/selfhost/`，文件名可以按这版图来取。在 `workflow_catalog.py` 的 `SELFHOST_WORKFLOW_MAPPING` 里把功能 key 指到这个文件，并给表单字段补 `selfhost_node_id` / `selfhost_input_key`。换图时改映射和字段绑定，不改功能目录名。
- **RunningHub**：运行时只用 `workflow_id`（存在 `web-app/workflows/runninghub/`）。这里的 `api.json` 用来查参数名，例如 `$videoimage.image`、`$audio.audio`。

## 导出方式

ComfyUI 里 `Workflow → Export (API)` 得到 `api.json`，`Workflow → Save` 得到 `ui.json`。`json/` 里保持导出原样，不在文件里改节点。参数替换由运行时代码完成。
