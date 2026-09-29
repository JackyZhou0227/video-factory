# TTS Studio 模块

## 作用

独立生成语音，支持 Edge-TTS 在线音色和 Qwen3-TTS Base 本地音色克隆。生成结果可试听、下载，并作为数字人模块的输入。

## Provider

- `edge_tts`：在线预设音色，状态接口静态返回可用，生成时才访问网络。
- `qwen3_tts_base`：本地模型，需要参考音频和参考文本；启动期只做轻量检查，首次克隆时加载完整权重。

本模块的本地模型开关、模型路径和设备由 `config.yaml` 的 `tts.qwen3_tts_base` 配置控制。

## 音色档案

个人档案保存在 PostgreSQL `voice_profiles`，参考音频保存在 `<server.output_dir>/voice_profiles/<user_id>/<profile_id>/`。每个用户最多 20 个档案，所有读写按当前登录用户隔离。

## API

路由位于 `web-app/app/api/tts_studio.py`，包括 provider 状态、语言、Edge-TTS 音色、语音生成、音频下载和个人音色档案操作。路径统一以 `/api/tts-studio/` 开头。

## 失败处理

TTS 任务统一写入任务中心；provider 不可用时返回明确原因，不加载已关闭的本地模型。
