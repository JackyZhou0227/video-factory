# Self-Host Workflows

本目录存放 **自定义 ComfyUI** 的工作流 JSON（API 格式，即 ComfyUI 导出的 "API Format"，节点 ID → `{class_type, inputs}`）。

## 工作流映射

映射写在 `app/services/workflow_catalog.py` 的 `SELFHOST_WORKFLOW_MAPPING`：

| workflow_key | selfhost 文件 | 说明 |
|---|---|---|
| `text-to-image` | `image_flux3_klein_t2i.json` | 文生图，需 Flux3 系列模型（未下载时报模型缺失） |

## 参数替换

运行时按 `workflow_catalog` 里的 `selfhost_node_id` / `selfhost_input_key`
直接改节点输入，再把整份 JSON POST 到 ComfyUI `/prompt`。

原稿（UI 格式 + API 格式）统一放在仓库根目录 `docs/comfyui-workflow/<name>/`，
本目录只放从那里复制来的 `api.json`，保持 ComfyUI 导出原样、不在文件里改节点。

当前映射（`text-to-image`）：

| 表单字段 | 节点 | 输入 |
|---|---|---|
| prompt | `18:17` | `value` |
| negative_prompt | `18:5` | `text` |
| width | `18:6` | `width` |
| height | `18:6` | `height` |

加新工作流时：

1. 把导出的 API 格式 JSON 放到本目录；
2. 在 `SELFHOST_WORKFLOW_MAPPING` 里登记 `workflow_key → 文件名`；
3. 在 `WORKFLOWS` 对应条目上给每个参数补 `selfhost_node_id` / `selfhost_input_key`。

`tests/services/test_workflow_catalog.py` 会校验这些映射指向真实存在的节点和输入键。
