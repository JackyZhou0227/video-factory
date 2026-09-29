# 任务中心模块

## 作用

统一记录各生成模块的请求、进度、错误和产物，按当前登录用户隔离。

## 任务类型

`digital_human`、`voice_generation`、`poster_video`、`template_production`、`smart_editing`。语音调速结果追加到原语音任务，不创建新任务；模板内部的文案生成和改写也不单独建任务。

## 数据模型

表为 `generation_tasks`，保存请求/成功/失败数量、状态、进度、创建人快照、UTC 时间、`extra_info_json` 和 `artifacts_json`。敏感 API Key 不写入扩展字段。

## 产物目录

```text
web-app/output/tasks/YYYY/MM/DD/{task_type}/{task_id}/
```

服务端路径只保存在后端，接口返回产物 ID 和 URL。手动删除文件不会删除任务记录，详情会标记 `missing`，下载返回 `404`。

## API

- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/artifacts/{artifact_id}/preview`
- `GET /api/tasks/{task_id}/artifacts/{artifact_id}/download`
- `GET /api/tasks/{task_id}/download`

所有接口校验当前用户的任务归属，并执行目录边界检查。
