# 模板量产模块

## 作用

按固定业务模板组织素材与文案，调用 Edge-TTS 和 FFmpeg 批量生成短视频；模板定义与具体任务数据分离。

## 模板定义

模板存储在 PostgreSQL `templates.definition` JSONB 字段中，全站共享。定义包括内容字段、素材槽、文案提示词和服务端流水线绑定，不包括上传文件、生成文案或任务状态。

- 管理员导入模板，登录用户查看、导出和使用。
- 导入文件上限 128 KiB，模板 ID 全局唯一。
- 只允许绑定已注册流水线，不执行模板中的 Python 表达式或任意函数。

## 处理流程

1. 选择或导入模板。
2. 填写模板字段并上传素材。
3. 生成/改写文案并合成语音。
4. 通过 FFmpeg 合成批量视频。
5. 将批量结果写入一个 `template_production` 任务。

## API 与实现

路由和流水线位于 `web-app/app/api/template_production.py`、`web-app/app/services/template_production.py`，接口统一使用 `/api/template-production/` 前缀。背景音乐曲库由同一模块管理。
