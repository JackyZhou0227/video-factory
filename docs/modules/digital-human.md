# 数字人模块

## 作用

上传人物图片和已生成的口播音频，提交 RunningHub 数字人工作流生成视频。音频在 [TTS Studio](tts-studio.md) 中生成后回到本模块上传。

## 处理流程

1. 上传人物图片。
2. 上传口播音频。
3. 后端保存用户输入素材并创建 `digital_human` 视频任务。
4. 提交固定 RunningHub 工作流。
5. RunningHub 接收成功后任务标记为 `completed`，产物通过任务中心访问。

## 接口入口

后端路由位于 `web-app/app/api/digital_human.py`，前端组件位于 `web-app/frontend/src/components/DigitalHuman.jsx`。任务状态和产物安全规则见[任务中心模块](task-center.md)。

## 约束

- RunningHub 工作流 ID 是服务端固定值，不由用户配置。
- 页面不负责生成音频，只消费 TTS Studio 导出的音频文件。
- 外部任务 ID 和链接仅保存在任务扩展信息中，不暴露服务端文件路径。
