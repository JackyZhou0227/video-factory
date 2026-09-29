# 智能剪辑模块

## 作用

用户输入完整文案，调用当前用户配置的 LLM 提取按出现顺序排列的素材关键词，再为每个关键词建立素材分组并批量生成混剪内容。

## 关键行为

- 关键词允许重复，重复关键词按出现位置分别建立分组。
- 文案提取由用户配置的 OpenAI 兼容 LLM 完成。
- 语音使用模块内固定的 Edge-TTS 配置，不再提供独立 Skill。
- 生成结果和失败项统一进入任务中心。

## 实现位置

后端路由为 `web-app/app/api/smart_editing.py`，核心合成为 `web-app/app/services/smart_editing.py`。前端页面入口定义在 `web-app/frontend/src/App.jsx`。
