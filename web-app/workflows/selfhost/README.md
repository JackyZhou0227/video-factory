# Self-Host Workflows

本目录存放 **自定义 ComfyUI** 的工作流 JSON（API 格式，即 ComfyUI 导出的 "API Format"，节点 ID → `{class_type, inputs}`）。

## 工作流映射

映射写在 `app/services/workflow_catalog.py` 的 `SELFHOST_WORKFLOW_MAPPING`：

| workflow_key | selfhost 文件 | 说明 |
|---|---|---|
| `text-to-image` | `image_moss_image_t2i.json` | 文生图，需 MOSS-Image 模型（未下载时报模型缺失） |
| `image-edit` | `image_moss_image_edit.json` | 图片编辑，需 MOSS-Image 模型和编辑 LoRA（未下载时报模型缺失） |

## 参数替换

运行时按 `workflow_catalog` 里的 `selfhost_node_id` / `selfhost_input_key`
直接改节点输入，再把整份 JSON POST 到 ComfyUI `/prompt`。

原稿按功能放在 `docs/comfyui-workflow/<功能名>/`，JSON 在其中的 `json/`。
功能目录名不跟某一版模型绑定；换图时替换那里的 JSON，再改上面的文件名映射。
本目录只放从 `json/api.json` 复制来的运行文件，保持 ComfyUI 导出原样、不在文件里改节点。

当前映射（`text-to-image`）：

| 表单字段 | 节点 | 输入 |
|---|---|---|
| prompt | `18:17` | `value` |
| resolution | `19` | `megapixels`（480p / 720p / 1080p） |
| aspect_ratio | `19` | `aspect_ratio` |

负面提示词、提示词增强、增强种子和 SLG 不在表单里，节点保持工作流原稿里的值。宽高由节点 `19`（ResolutionSelector，`multiple` 为 16）按清晰度和比例算出来，再接到 `18:6`。模型、采样步数和 CFG 也留在原稿里。

当前映射（`image-edit`）：

| 表单字段 | 节点 | 输入 |
|---|---|---|
| image | `8` | `image`（先上传到 ComfyUI） |
| prompt | `39` | `prompt` |

负面提示词、采样参数和原图缩放留在工作流原稿里。

加新工作流时：

1. 把导出的 API 格式 JSON 放到本目录；
2. 在 `SELFHOST_WORKFLOW_MAPPING` 里登记 `workflow_key → 文件名`；
3. 在 `WORKFLOWS` 对应条目上给每个参数补 `selfhost_node_id` / `selfhost_input_key`。

`tests/services/test_workflow_catalog.py` 会校验这些映射指向真实存在的节点和输入键。
