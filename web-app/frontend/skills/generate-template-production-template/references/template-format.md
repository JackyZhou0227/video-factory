# 模板格式与运行方式

## 模板在系统中的作用

模板 JSON 是模板量产页面的可复用定义：

- `content_fields` 生成用户填写的文本、多行文本或选择字段。
- `material_requirements` 生成图片或视频上传槽，并限制每类素材数量。
- `script_generation` 定义如何把内容信息和已上传素材数量交给 LLM 生成或改写候选口播文案。
- `production` 选择服务端已有的成片流水线，以及默认画幅和批量数量。

模板不保存某次任务的字段值、素材文件、最终文案、字幕样式、背景音乐或任务状态。

## 顶层结构

```json
{
  "schema_version": 1,
  "template_version": 1,
  "id": "example-template",
  "name": "模板名称",
  "description": "模板用途",
  "content_fields": [],
  "material_requirements": [],
  "script_generation": {},
  "production": {}
}
```

系统拒绝未声明的字段。`id`、字段 `key` 和素材槽 `key` 使用小写英文字母开头，可包含小写字母、数字、连字符或下划线，并在各自列表中保持唯一。

## 内容字段

每个 `content_fields` 项支持：

- `key`、`label`：字段标识和页面标签。
- `input_type`：`text`、`textarea` 或 `select`，默认 `text`。
- `required`：是否必填，默认 `true`。
- `placeholder`、`help_text`、`default`：可选的页面辅助信息和默认值。
- `min_length`、`max_length`：可选的输入长度限制。
- `options`：仅供 `select` 使用，元素格式为 `{"value":"...","label":"..."}`；选项值必须唯一，默认值必须是其中一个选项。

最多定义 50 个内容字段。字段应表示每次量产时真正需要用户改变或确认的信息，不要把固定的创作要求伪装成输入字段。

## 素材要求

每个 `material_requirements` 项必须包含：

- `key`、`label`、`description`；
- `media_type`：`image` 或 `video`；
- `min_count` 和 `max_count`。

模板至少需要一个素材槽，最多 20 个；所有素材槽的 `max_count` 总和不能超过 20。说明应让用户知道需要上传什么内容，而不是规定与业务无关的拍摄风格。

## 文案生成

`script_generation` 包含：

- `system_prompt`：不允许使用模板占位符。
- `prompt_template`：生成候选文案的提示词。
- `rewrite_prompt_template`：可选；提供后页面才显示文案改写能力，并且必须包含 `{{original_script}}`。
- `response_format`：`plain_scripts_v1` 或 `segmented_scripts_v1`。
- `default_candidate_count`：1-10，默认 3。
- `temperature`：0-2，默认 0.75。
- `max_tokens`：1-32768，默认 2400。

生成提示词可使用：

- `{{candidate_count}}`
- `{{content_context}}`
- `{{material_context}}`
- `{{response_contract}}`

改写提示词还可使用 `{{original_script}}`。系统会安全替换这些值，并把 `response_contract` 转换为当前响应格式所需的 JSON 输出约定。不要使用其他变量、对象路径、模板语句或模板注释。

`plain_scripts_v1` 适合一般口播，LLM 返回 JSON 字符串数组。`segmented_scripts_v1` 允许每条文案包含分句，主要供需要按句组织字幕的既有流水线使用。

## 成片流水线

`production` 包含：

- `pipeline_id`：当前只能选择已注册的 `generic_concat_v1` 流水线。
- `default_ratio`：`9:16`、`16:9`、`1:1` 或 `3:4`。
- `default_batch_size`：1-50，不能超过 `max_batch_size`。
- `max_batch_size`：1-50。

### `generic_concat_v1`

一般模板默认使用。它接受自定义图片和视频素材槽，至少一个素材槽的 `min_count` 必须大于 0。运行时会标准化用户上传的素材、重新编排画面、生成配音和字幕，并按音频时长合成批量视频。

## 最终校验

数值上限、字符串长度、占位符语法、未知字段和流水线兼容性由 `scripts/validate_template.py` 统一判断。不要仅凭阅读本参考文件声明模板有效；交付前必须实际运行脚本。
